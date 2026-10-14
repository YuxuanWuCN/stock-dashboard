# -*- coding: utf-8 -*-
"""src/portfolio/backtest.py —— FOF 组合点时回测引擎与四组对照基准

依据《FOF 组合配置改造意见》§6 & §7：
实现必须对照的四组组合：
1. Baseline-FOF：纯战略基准权重（如 70% 纯债/防御 + 30% 沪深300ETF），定期再平衡，不使用 NALE；
2. NALE-FOF：使用 NALE/T-NALE 主动偏离，但暂不启用组合风险缩放与回撤状态机；
3. Risk-Constrained NALE-FOF：全功能版本，启用波动率目标缩放、集中度与分层回撤状态机；
4. Sentiment-only：仅使用原生事实/情绪打分，不使用拓扑网络传导与时效衰减，用于验证 NALE 边际贡献。

支持严格的 T+1 决策与执行时序、交易费用核算、详细日志输出与标准量化指标计算。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.portfolio.allocator import AllocationConfig, FOFAllocator
from src.portfolio.contracts import (
    AssetInfo,
    AssetRole,
    BacktestLogEntry,
    BacktestTrade,
    PerformanceMetrics,
    PointInTimeSignal,
    PortfolioWeights,
    RiskBudgetConfig,
    RiskState,
)
from src.portfolio.rebalancer import RebalanceConfig, RebalanceManager
from src.portfolio.risk_budget import RiskBudgetManager

logger = logging.getLogger("portfolio.backtest")


@dataclass(frozen=True)
class BacktestConfig:
    """回测参数契约。"""
    start_date: str
    end_date: str
    initial_nav: float = 1.0
    rebalance_frequency_days: int = 5     # 调仓频率 (如每周 5 个交易日评估)
    benchmark_ticker: str = "510300"      # 基准资产代码 (如 沪深300ETF)
    risk_free_rate: float = 0.02          # 无风险利率 (年化 2.0%)


STRESS_MODES = [
    "baseline", "nale", "risk_constrained_nale", "sentiment_only",
    "t_nale", "defensive_only",
]


class FOFBacktestEngine:
    """FOF 组合点时回测执行引擎。"""

    def __init__(
        self,
        assets: Dict[str, AssetInfo],
        returns_df: pd.DataFrame,          # 行: 日期 (升序), 列: 各 ticker 日收益率
        alloc_config: Optional[AllocationConfig] = None,
        risk_config: Optional[RiskBudgetConfig] = None,
        rebal_config: Optional[RebalanceConfig] = None,
    ):
        self.assets = assets
        self.returns_df = returns_df.copy().sort_index()
        self.alloc_config = alloc_config or AllocationConfig()
        self.risk_config = risk_config or RiskBudgetConfig()
        self.rebal_config = rebal_config or RebalanceConfig()

        self.allocator = FOFAllocator(assets, self.alloc_config, self.risk_config)
        self.rebalancer = RebalanceManager(assets, self.rebal_config)
        self.risk_manager = RiskBudgetManager(self.risk_config)

    def run_backtest(
        self,
        mode: str,
        signals_by_date: Dict[str, Dict[str, PointInTimeSignal]],
        config: BacktestConfig,
        t_nale_halflife: float | Dict[str, float] = 5.0,
        t_nale_age_map: Optional[Dict[str, int]] = None,
        fill_fraction: float = 1.0,
        delayed_exit_days: int = 0,
        frozen_exit_days: int = 0,
    ) -> Tuple[List[BacktestLogEntry], PerformanceMetrics]:
        """运行单组回测策略。

        Args:
            mode: 策略模式 (baseline/nale/risk_constrained_nale/sentiment_only/t_nale/defensive_only)
            signals_by_date: 点时信号字典
            config: 回测配置
            t_nale_halflife: T-NALE 异质半衰期基值（交易日）
            t_nale_age_map: 节点年龄映射 {ticker: signal_age_days}
            fill_fraction: 每次调仓的实际成交比例（<1.0 模拟流动性冲击下的部分成交，
                未成交部分保留原仓位，用于熊市压力测试）
            delayed_exit_days: 风险门（进入 DEFENSIVE/PROTECTIVE）触发后，强制减仓动作
                延迟多少个交易日执行（0=不启用该压力情景）
            frozen_exit_days: 风险门触发后连续多少个交易日内无法减仓（0=不启用）
        """
        # 1. 过滤日期区间
        # 兼容性修复：returns_df.index 既可能是纯日期字符串（如 test_portfolio_fof.py），
        # 也可能是 pandas Timestamp（如 scripts/run_bear_market_stress.py 用 pct_change()
        # 后的默认索引）。统一归一化为 "YYYY-MM-DD" 后再与 config 以及
        # signals_by_date 的 key 进行匹配，避免 Timestamp 带时间部分导致信号永远
        # 查不到（历史隐藏 bug：导致所有依赖卫星信号的模式静默退化为无信号运行）。
        def _norm_date(val) -> str:
            s = str(val)
            return s[:10] if " " in s else s

        dates = [
            d for d in self.returns_df.index
            if config.start_date <= _norm_date(d) <= config.end_date
        ]
        if len(dates) < 5:
            raise ValueError(f"回测区间 [{config.start_date}, {config.end_date}] 内有效交易日不足 ({len(dates)} 天)")

        self.risk_manager.reset(initial_nav=config.initial_nav)

        # 初始持仓：战略基准
        current_weights: Dict[str, float] = {}
        for t, a in self.assets.items():
            current_weights[t] = a.benchmark_weight
        # 校验并归一化初始权重
        total_init = sum(current_weights.values())
        if abs(total_init - 1.0) > 1e-4:
            primary_def = self.allocator.defensive_tickers[0]
            current_weights[primary_def] += (1.0 - total_init)

        nav = config.initial_nav
        benchmark_nav = config.initial_nav
        historical_returns: List[float] = []
        logs: List[BacktestLogEntry] = []
        all_trades: List[BacktestTrade] = []

        days_since_last_rebalance = config.rebalance_frequency_days  # 首日立即调仓

        # 流动性/执行压力跟踪变量（默认全 0/1.0 时不改变既有行为）
        _SEVERITY = {"normal": 0, "watch": 1, "defensive": 2, "protective": 3}
        risk_tickers = set(self.allocator.beta_tickers) | set(self.allocator.satellite_tickers)
        prev_severity = 0
        frozen_until_idx = -1
        forced_exit_due_idx: Optional[int] = None
        forced_exit_state: Optional[RiskState] = None

        for i, dt_val in enumerate(dates):
            date_str = _norm_date(dt_val)
            day_returns = self.returns_df.loc[dt_val].to_dict()

            # 基准当日收益
            bench_ret = float(day_returns.get(config.benchmark_ticker, 0.0))
            if math.isnan(bench_ret) or math.isinf(bench_ret):
                bench_ret = 0.0

            # 判定当日是否进行调仓
            should_rebalance = (days_since_last_rebalance >= config.rebalance_frequency_days)
            daily_turnover = 0.0
            daily_fee = 0.0
            in_frozen_window = i <= frozen_until_idx

            if should_rebalance or (forced_exit_due_idx is not None and i >= forced_exit_due_idx):
                # 获取点时信号
                date_signals = signals_by_date.get(date_str, {})

                # 依据模式决定风险状态与主动信号
                if mode == "baseline":
                    target_pw = self.allocator.allocate(
                        trade_date=date_str,
                        signals={},  # 无主动信号
                        current_risk_state=RiskState.NORMAL,
                        effective_satellite_budget=0.0,
                        volatility_scale=1.0,
                    )
                elif mode == "nale":
                    # 不启用风险缩放与回撤状态机
                    target_pw = self.allocator.allocate(
                        trade_date=date_str,
                        signals=date_signals,
                        current_risk_state=RiskState.NORMAL,
                        effective_satellite_budget=self.alloc_config.base_satellite_budget,
                        volatility_scale=1.0,
                    )
                elif mode == "risk_constrained_nale":
                    # 全功能：波动率缩放 + 回撤状态机
                    vol_scale = self.risk_manager.compute_volatility_scale(historical_returns)
                    current_risk_state, _, _ = self.risk_manager.update_risk_state(nav)
                    target_pw = self.allocator.allocate(
                        trade_date=date_str,
                        signals=date_signals,
                        current_risk_state=current_risk_state,
                        volatility_scale=vol_scale,
                    )
                elif mode == "defensive_only":
                    # 100% 防御底仓，无信号
                    target_pw = self.allocator.allocate(
                        trade_date=date_str,
                        signals={},
                        current_risk_state=RiskState.PROTECTIVE,
                        effective_satellite_budget=0.0,
                        volatility_scale=0.0,
                    )
                elif mode == "t_nale":
                    # T-NALE: 信号按节点年龄指数衰减
                    date_signals = self._apply_t_nale_decay(
                        date_signals, t_nale_halflife, t_nale_age_map)
                    vol_scale = self.risk_manager.compute_volatility_scale(historical_returns)
                    current_risk_state, _, _ = self.risk_manager.update_risk_state(nav)
                    target_pw = self.allocator.allocate(
                        trade_date=date_str,
                        signals=date_signals,
                        current_risk_state=current_risk_state,
                        volatility_scale=vol_scale,
                    )
                elif mode == "sentiment_only":
                    # 仅情绪，无网络传导
                    target_pw = self.allocator.allocate(
                        trade_date=date_str,
                        signals=date_signals,
                        current_risk_state=RiskState.NORMAL,
                        effective_satellite_budget=self.alloc_config.base_satellite_budget,
                        volatility_scale=1.0,
                    )
                else:
                    raise ValueError(f"未知回测模式: {mode}")

                # 风险门强制减仓（delayed_exit_days 压力情景）：到点时以触发状态覆盖目标权重
                forced_this_bar = (forced_exit_due_idx is not None and i >= forced_exit_due_idx)
                if forced_this_bar:
                    forced_pw = self.allocator.allocate(
                        trade_date=date_str,
                        signals={},
                        current_risk_state=forced_exit_state or RiskState.DEFENSIVE,
                        effective_satellite_budget=0.0,
                        volatility_scale=0.0,
                    )
                    tgt_risk_w = sum(target_pw.weights.get(t, 0.0) for t in risk_tickers)
                    forced_risk_w = sum(forced_pw.weights.get(t, 0.0) for t in risk_tickers)
                    if forced_risk_w < tgt_risk_w - 1e-9:
                        target_pw = forced_pw

                # 执行死区与调仓
                executed_weights, daily_turnover, daily_fee, day_trades = (
                    self.rebalancer.apply_deadband_and_execute(
                        trade_date=date_str,
                        current_weights=current_weights,
                        target_weights=target_pw,
                        fill_fraction=fill_fraction,
                    )
                )

                # 冻结期（frozen_exit_days 压力情景）：禁止风险资产净减仓，未成交仓位保留原状
                if in_frozen_window:
                    cur_risk_w = sum(current_weights.get(t, 0.0) for t in risk_tickers)
                    new_risk_w = sum(executed_weights.get(t, 0.0) for t in risk_tickers)
                    if new_risk_w < cur_risk_w - 1e-9:
                        executed_weights = dict(current_weights)
                        daily_turnover = 0.0
                        daily_fee = 0.0
                        day_trades = []

                current_weights = executed_weights
                all_trades.extend(day_trades)
                days_since_last_rebalance = 0
                if forced_this_bar:
                    forced_exit_due_idx = None
                    forced_exit_state = None
            else:
                days_since_last_rebalance += 1

            # 计算当日资产加权总回报
            gross_return = 0.0
            for t, w in current_weights.items():
                r_asset = float(day_returns.get(t, 0.0))
                if math.isnan(r_asset) or math.isinf(r_asset):
                    r_asset = 0.0
                gross_return += w * r_asset

            # 扣除当日交易费用
            net_return = gross_return - daily_fee
            nav = nav * (1.0 + net_return)
            benchmark_nav = benchmark_nav * (1.0 + bench_ret)
            historical_returns.append(net_return)

            # 更新回撤状态跟踪
            curr_state, dd, peak = self.risk_manager.update_risk_state(nav)

            # 风险门触发检测：严重度升高至 DEFENSIVE/PROTECTIVE 时，登记冻结窗口与延迟减仓
            curr_sev = _SEVERITY.get(curr_state.value, 0)
            if curr_sev >= 2 and curr_sev > prev_severity:
                if frozen_exit_days > 0:
                    frozen_until_idx = i + frozen_exit_days
                if delayed_exit_days > 0:
                    forced_exit_due_idx = i + delayed_exit_days + 1
                    forced_exit_state = curr_state
            prev_severity = curr_sev

            # 统计各角色权重
            sat_w = sum(current_weights.get(t, 0.0) for t in self.allocator.satellite_tickers)
            def_w = sum(current_weights.get(t, 0.0) for t in self.allocator.defensive_tickers)
            beta_w = sum(current_weights.get(t, 0.0) for t in self.allocator.beta_tickers)

            active_sig_scores = {
                t: sig.score
                for t, sig in signals_by_date.get(date_str, {}).items()
                if sig.is_valid
            }

            logs.append(
                BacktestLogEntry(
                    trade_date=date_str,
                    nav=nav,
                    daily_return=net_return,
                    benchmark_nav=benchmark_nav,
                    benchmark_daily_return=bench_ret,
                    drawdown=dd,
                    peak_nav=peak,
                    risk_state=curr_state.value,
                    satellite_weight=sat_w,
                    defensive_weight=def_w,
                    core_beta_weight=beta_w,
                    weights=current_weights.copy(),
                    turnover=daily_turnover,
                    total_fee=daily_fee,
                    active_signals=active_sig_scores,
                )
            )

            # 经历一天资产价格变动后的仓位浮动
            if (1.0 + gross_return) > 1e-6:
                drifted_weights = {}
                for t, w in current_weights.items():
                    r_asset = float(day_returns.get(t, 0.0))
                    drifted_weights[t] = w * (1.0 + r_asset) / (1.0 + gross_return)
                current_weights = drifted_weights

        # 2. 计算综合业绩指标
        metrics = self._calculate_metrics(logs, config)
        return logs, metrics

    def _apply_t_nale_decay(
        self,
        signals: Dict[str, PointInTimeSignal],
        halflife: float | Dict[str, float] = 5.0,
        age_map: Optional[Dict[str, int]] = None,
    ) -> Dict[str, PointInTimeSignal]:
        """T-NALE 异质半衰期衰减：score_decayed = score * 0.5^(age/halflife)。

        支持：
        1. 异质半衰期字典映射 {ticker: halflife_days} 或标量半衰期（倍率）；
        2. 显式年龄映射 age_map 或从信号 details["node_age"] 中自动提取点时动态年龄；
        3. 若信号 details 中已标记 is_t_nale_decayed=True 且未显式指定覆盖参数，则保持现有衰减避免二次衰减。
        """
        import copy
        decayed: Dict[str, PointInTimeSignal] = {}
        amap = age_map or {}
        for ticker, sig in signals.items():
            # 若信号在生成层已按异质半衰期衰减过，且调用者未提供显式 age_map 覆盖且 halflife 为基准 5.0，则透传
            if sig.details.get("is_t_nale_decayed") and not amap and (isinstance(halflife, (int, float)) and halflife == 5.0):
                decayed[ticker] = sig
                continue

            if ticker in amap:
                age = float(amap[ticker])
            else:
                age = float(sig.details.get("node_age", sig.details.get("t_nale_age", 1.0)))

            if isinstance(halflife, dict):
                h = float(halflife.get(ticker, 5.0))
            elif isinstance(halflife, (int, float)):
                base_h = sig.details.get("sector_half_life")
                if base_h is not None:
                    mult = float(halflife) / 5.0
                    h = float(base_h) * mult
                else:
                    h = float(halflife)
            else:
                h = 5.0

            factor = math.pow(0.5, age / max(h, 0.1))
            new_sig = copy.copy(sig)
            new_sig.score = sig.score * factor
            new_sig.details = {
                **sig.details,
                "t_nale_age": age,
                "t_nale_factor": factor,
                "t_nale_halflife": h,
                "is_t_nale_decayed": True,
            }
            decayed[ticker] = new_sig
        return decayed

    # ------------------------------------------------------------------

    def _calculate_metrics(
        self,
        logs: List[BacktestLogEntry],
        config: BacktestConfig,
    ) -> PerformanceMetrics:
        """计算标准量化投资指标。"""
        n_days = len(logs)
        if n_days == 0:
            raise ValueError("回测日志为空")

        df = pd.DataFrame([
            {
                "date": x.trade_date,
                "nav": x.nav,
                "daily_return": x.daily_return,
                "benchmark_nav": x.benchmark_nav,
                "bench_return": x.benchmark_daily_return,
                "drawdown": x.drawdown,
                "turnover": x.turnover,
                "fee": x.total_fee,
                "defensive": x.defensive_weight,
                "satellite": x.satellite_weight,
            }
            for x in logs
        ])
        df["date"] = pd.to_datetime(df["date"])

        total_return = df["nav"].iloc[-1] / df["nav"].iloc[0] - 1.0
        annualized_return = (1.0 + total_return) ** (252.0 / n_days) - 1.0

        daily_std = float(df["daily_return"].std(ddof=1))
        annualized_vol = daily_std * math.sqrt(252.0)

        rf = config.risk_free_rate
        sharpe = (annualized_return - rf) / (annualized_vol + 1e-9)

        # Sortino Ratio (下行波动)
        downside_returns = df.loc[df["daily_return"] < 0, "daily_return"]
        downside_std = float(downside_returns.std(ddof=1)) * math.sqrt(252.0) if len(downside_returns) > 1 else 1e-4
        sortino = (annualized_return - rf) / (downside_std + 1e-9)

        # 最大回撤与持续期
        max_dd = float(df["drawdown"].max())
        calmar = annualized_return / (max_dd + 1e-9)

        # 回撤持续最长交易日数
        max_dd_duration = 0
        current_dd_len = 0
        for dd_val in df["drawdown"]:
            if dd_val > 1e-4:
                current_dd_len += 1
                if current_dd_len > max_dd_duration:
                    max_dd_duration = current_dd_len
            else:
                current_dd_len = 0

        # 月度胜率与亏损月份数
        df["month"] = df["date"].dt.to_period("M")
        monthly_grouped = df.groupby("month").apply(
            lambda g: (g["nav"].iloc[-1] / g["nav"].iloc[0] - 1.0),
            include_groups=False,
        )
        total_months = len(monthly_grouped)
        win_months = int((monthly_grouped > 0).sum())
        loss_months = total_months - win_months
        monthly_win_rate = (win_months / total_months) if total_months > 0 else 0.0

        total_turnover = float(df["turnover"].sum())
        annualized_turnover = total_turnover * (252.0 / n_days)
        total_fees = float(df["fee"].sum())

        avg_def = float(df["defensive"].mean())
        avg_sat = float(df["satellite"].mean())

        # 基准指标
        bench_total_return = df["benchmark_nav"].iloc[-1] / df["benchmark_nav"].iloc[0] - 1.0
        bench_ann_return = (1.0 + bench_total_return) ** (252.0 / n_days) - 1.0
        bench_daily_std = float(df["bench_return"].std(ddof=1))
        bench_ann_vol = bench_daily_std * math.sqrt(252.0)
        bench_peak = df["benchmark_nav"].cummax()
        bench_dd = (bench_peak - df["benchmark_nav"]) / bench_peak
        bench_max_dd = float(bench_dd.max())
        bench_sharpe = (bench_ann_return - rf) / (bench_ann_vol + 1e-9)

        # Alpha, Beta, IR
        cov_matrix = np.cov(df["daily_return"], df["bench_return"])
        beta = float(cov_matrix[0, 1] / (cov_matrix[1, 1] + 1e-9))
        alpha = float((annualized_return - rf) - beta * (bench_ann_return - rf))

        excess_returns = df["daily_return"] - df["bench_return"]
        tracking_error = float(excess_returns.std(ddof=1)) * math.sqrt(252.0)
        info_ratio = (annualized_return - bench_ann_return) / (tracking_error + 1e-9)

        return PerformanceMetrics(
            start_date=config.start_date,
            end_date=config.end_date,
            trading_days=n_days,
            annualized_return=annualized_return,
            annualized_volatility=annualized_vol,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            max_drawdown=max_dd,
            max_drawdown_duration_days=max_dd_duration,
            monthly_win_rate=monthly_win_rate,
            negative_months_count=loss_months,
            total_turnover=total_turnover,
            annualized_turnover=annualized_turnover,
            total_trading_costs=total_fees,
            avg_defensive_weight=avg_def,
            avg_satellite_weight=avg_sat,
            benchmark_annualized_return=bench_ann_return,
            benchmark_annualized_vol=bench_ann_vol,
            benchmark_max_drawdown=bench_max_dd,
            benchmark_sharpe=bench_sharpe,
            alpha=alpha,
            beta=beta,
            information_ratio=info_ratio,
        )
