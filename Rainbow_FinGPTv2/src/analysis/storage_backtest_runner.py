# -*- coding: utf-8 -*-
"""src/analysis/storage_backtest_runner.py —— 2025Q2-2026Q7 存储市场物理隔离拟真交易人逐步推进回测执行器

严格遵循：
1. 物理数据隔离（仅读取 data/raw/backtest_storage_2025q2_2026q7/ 原始数据，禁止前视泄漏）
2. 拟真交易人逐步推进（t日收盘计算决策，t+1日开盘真实撮合）
3. A股机构真实费率（买入 0.125%，卖出 0.175%，闲置现金年化 1.8%）
4. 三级对照组基准矩阵（沪深300、芯片ETF、存储5巨头等权买入持有）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.analysis.famamacbethv3 import FamaMacBethV3Engine
from src.analysis.scoringv3 import GFCAScoringEngine
from src.execution.trend_gate import TrendGate, TrendGateDecision
from src.execution.portfolio_allocator import DynamicBetAllocator, BetType, EvidencePhase
from src.graph.supply_chain_graph import SupplyChainGraph
from src.nowcasting.triangle_validator import NowcastingTriangleValidator

logger = logging.getLogger("storage_backtest")


@dataclass
class DailySnapshot:
    """日频因果仿真快照。"""
    date: str
    strategy_nav: float
    csi300_nav: float
    chip_etf_nav: float
    storage_ew_nav: float
    active_holdings: Dict[str, float]
    cash_ratio: float
    trend_gate_status: Dict[str, bool]
    turnover_rate: float
    total_fee_cny: float


class StorageBacktestRunner:
    """存储市场物理隔离样本外回测引擎。"""

    STORAGE_TICKERS = ["001309", "300475", "301308", "688525", "688008"]

    BUY_FRICTION = 0.00125    # 0.125% 买入综合费率 (0.25‰ 佣金 + 1.0‰ 滑点)
    SELL_FRICTION = 0.00175   # 0.175% 卖出综合费率 (0.25‰ 佣金 + 1.0‰ 滑点 + 0.5‰ 印花税)
    DAILY_CASH_YIELD = 0.00005  # 闲置现金日息 (年化约 1.8%)

    def __init__(self, raw_data_dir: Optional[str | Path] = None, initial_capital: float = 1_000_000.0):
        self.raw_data_dir = Path(raw_data_dir or "data/raw/backtest_storage_2025q2_2026q7")
        self.initial_capital = initial_capital

        # 加载核心量化引擎
        self.fm_engine = FamaMacBethV3Engine(t_stat_threshold=3.0)
        self.scoring_engine = GFCAScoringEngine(tanh_scaling=1.5, nale_alpha=0.4)
        self.trend_gate = TrendGate(ma_period=20)
        self.allocator = DynamicBetAllocator(total_portfolio_capital=initial_capital)
        self.nowcast_validator = NowcastingTriangleValidator(penalty_lambda=0.5)

    def load_isolated_raw_data(self) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """读取物理隔离目录中的原始数据。"""
        prices_df = pd.read_csv(self.raw_data_dir / "market_prices.csv", index_col=0, parse_dates=True)
        nowcast_df = pd.read_csv(self.raw_data_dir / "nowcasting_spot.csv", index_col=0, parse_dates=True)
        factors_df = pd.read_csv(self.raw_data_dir / "factors.csv", index_col=0, parse_dates=True)
        return prices_df, nowcast_df, factors_df

    def run_walk_forward_backtest(self) -> Dict[str, Any]:
        """执行日频拟真交易人全流程样本外回测。"""
        prices_df, nowcast_df, factors_df = self.load_isolated_raw_data()
        dates = prices_df.index
        T = len(dates)

        # 组合状态与净值初始化
        strat_nav = [1.0]
        csi300_nav = [1.0]
        chip_etf_nav = [1.0]
        storage_ew_nav = [1.0]

        # 初始持仓权重 (标的代码 -> 权重 [0.0, 1.0])
        current_weights: Dict[str, float] = {t: 0.0 for t in self.STORAGE_TICKERS}
        snapshots: List[DailySnapshot] = []

        # 存储 5 巨头日收益矩阵
        storage_rets_df = prices_df[self.STORAGE_TICKERS].pct_change().fillna(0.0)
        csi300_rets = prices_df["000300.SH"].pct_change().fillna(0.0)
        chip_etf_rets = prices_df["512760.SH"].pct_change().fillna(0.0)
        storage_ew_rets = storage_rets_df.mean(axis=1)

        # 逐步推进仿真 (从第 20 个交易日开始计算指标)
        for t in range(20, T):
            dt_str = str(dates[t].date())
            sub_prices = prices_df.iloc[:t]
            sub_nowcast = nowcast_df.iloc[:t]
            sub_factors = factors_df.iloc[:t]

            # 1. 拟真交易人时点 t 决策：严格仅使用 <= t 的历史切片
            target_weights: Dict[str, float] = {}
            gate_status: Dict[str, bool] = {}

            # 当前现货与海关高频数据
            curr_spot = float(sub_nowcast["dxi_spot_price"].iloc[-1])
            curr_korea_yoy = float(sub_nowcast["korea_customs_yoy"].iloc[-1])

            # 对存储标的依次评估 GFCA、Nowcasting 减值惩罚与 Trend Gate 状态
            for ticker in self.STORAGE_TICKERS:
                stock_kline = pd.DataFrame({"close": sub_prices[ticker]})
                gate_dec = self.trend_gate.evaluate_gate(ticker, stock_kline)
                gate_status[ticker] = gate_dec.gate_open

                # 提取锁价成本（若无则默认为 100）
                cost_col = f"lockin_cost_{ticker}"
                prepay_cost = float(sub_nowcast[cost_col].iloc[-1]) if cost_col in sub_nowcast.columns else 100.0

                nowcast_sig = self.nowcast_validator.evaluate_asset_nowcasting(
                    ticker=ticker,
                    korea_customs_export_yoy=curr_korea_yoy,
                    spot_dxi_price=curr_spot,
                    lockin_prepay_cost=prepay_cost
                )

                # 动态评估行业景气度评分：
                # 1. 现货价与海关出口持续高增时赋予高景气度 (0.75~0.85)
                # 2. 若现货价跌破锁价成本或海关出口转负，触发 Nowcasting 减值惩罚
                # 3. 结合 Trend Gate 趋势通道赋予顺势 Alpha
                if curr_spot >= prepay_cost and curr_korea_yoy > 0:
                    base_score = 0.80 if gate_dec.gate_open else 0.40
                else:
                    base_score = 0.35 if gate_dec.gate_open else -0.30

                gfca_score = base_score + nowcast_sig.impairment_penalty_drift

                # 动态分配头寸：
                # 1. 均线金叉多头 + 现货高景气：稳健重仓 (15% 单票，总仓 75%)
                # 2. 均线死叉或现货见顶：启动风控机制保护，仓位降至 0%~2%
                # 3. 既保证了主升浪收益，又避免了过高杠杆带来的深幅回撤
                if gate_dec.gate_open and curr_spot >= prepay_cost:
                    target_w = 0.15
                elif gate_dec.gate_open:
                    target_w = 0.06
                elif curr_spot >= prepay_cost:
                    target_w = 0.02
                else:
                    target_w = 0.00

                target_weights[ticker] = target_w

            # 归一化总仓位（若多标的被允许，上限 95%，留 5% 现金）
            total_target_w = sum(target_weights.values())
            if total_target_w > 0.95:
                for k in target_weights:
                    target_weights[k] = (target_weights[k] / total_target_w) * 0.95
            
            # 2. 计算调仓换手与交易摩擦成本
            turnover = 0.0
            total_friction_loss = 0.0

            for ticker in self.STORAGE_TICKERS:
                w_curr = current_weights.get(ticker, 0.0)
                w_tgt = target_weights.get(ticker, 0.0)
                delta_w = w_tgt - w_curr
                turnover += abs(delta_w)

                if delta_w > 0:  # 买入
                    total_friction_loss += delta_w * self.BUY_FRICTION
                elif delta_w < 0:  # 卖出
                    total_friction_loss += abs(delta_w) * self.SELL_FRICTION

            current_weights = target_weights.copy()
            cash_w = max(0.0, 1.0 - sum(current_weights.values()))

            # 3. 撮合 t+1 日（即当前日 t）真实收益
            stock_ret_contrib = sum(current_weights[ticker] * storage_rets_df[ticker].iloc[t] for ticker in self.STORAGE_TICKERS)
            cash_contrib = cash_w * self.DAILY_CASH_YIELD

            daily_strat_ret = stock_ret_contrib + cash_contrib - total_friction_loss

            strat_nav.append(strat_nav[-1] * (1.0 + daily_strat_ret))
            csi300_nav.append(csi300_nav[-1] * (1.0 + csi300_rets.iloc[t]))
            chip_etf_nav.append(chip_etf_nav[-1] * (1.0 + chip_etf_rets.iloc[t]))
            storage_ew_nav.append(storage_ew_nav[-1] * (1.0 + storage_ew_rets.iloc[t]))

            snapshots.append(DailySnapshot(
                date=dt_str,
                strategy_nav=strat_nav[-1],
                csi300_nav=csi300_nav[-1],
                chip_etf_nav=chip_etf_nav[-1],
                storage_ew_nav=storage_ew_nav[-1],
                active_holdings=current_weights.copy(),
                cash_ratio=cash_w,
                trend_gate_status=gate_status,
                turnover_rate=turnover,
                total_fee_cny=total_friction_loss * self.initial_capital
            ))

        # 4. 计算学术量化实证指标
        metrics = self._calculate_comprehensive_metrics(
            strat_nav=pd.Series(strat_nav, index=dates[19:]),
            csi300_nav=pd.Series(csi300_nav, index=dates[19:]),
            chip_etf_nav=pd.Series(chip_etf_nav, index=dates[19:]),
            storage_ew_nav=pd.Series(storage_ew_nav, index=dates[19:])
        )

        return {
            "metrics": metrics,
            "snapshots": snapshots,
            "nav_series": {
                "dates": [str(d.date()) for d in dates[19:]],
                "strategy": strat_nav,
                "csi300": csi300_nav,
                "chip_etf": chip_etf_nav,
                "storage_ew": storage_ew_nav
            }
        }

    def _calculate_comprehensive_metrics(
        self,
        strat_nav: pd.Series,
        csi300_nav: pd.Series,
        chip_etf_nav: pd.Series,
        storage_ew_nav: pd.Series
    ) -> Dict[str, Any]:
        """计算全套量化绩效指标（年化收益率、Sharpe、Calmar、MaxDD、IR、Harvey t-stat）。"""
        N = len(strat_nav)
        ann_factor = 250.0

        def calc_curve_stats(nav: pd.Series, bench: pd.Series) -> Dict[str, float]:
            tot_ret = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
            ann_ret = float((1.0 + tot_ret) ** (ann_factor / N) - 1.0)
            
            daily_r = nav.pct_change().dropna()
            bench_r = bench.pct_change().dropna()
            excess_r = daily_r - bench_r

            ann_vol = float(daily_r.std() * np.sqrt(ann_factor))
            sharpe = float((daily_r.mean() - 0.00006) / (daily_r.std() + 1e-8) * np.sqrt(ann_factor))
            
            # 最大回撤
            cum_max = nav.cummax()
            dd = (nav - cum_max) / cum_max
            max_dd = float(abs(dd.min()))

            calmar = float(ann_ret / max_dd) if max_dd > 0 else 0.0
            ir = float(excess_r.mean() / (excess_r.std() + 1e-8) * np.sqrt(ann_factor))
            
            # Harvey et al. 2016 因子特异性 Alpha t 统计量
            alpha_t = float(excess_r.mean() / (excess_r.std() / np.sqrt(len(excess_r)) + 1e-8))

            return {
                "total_return": tot_ret,
                "annualized_return": ann_ret,
                "annualized_volatility": ann_vol,
                "sharpe_ratio": sharpe,
                "max_drawdown": max_dd,
                "calmar_ratio": calmar,
                "information_ratio": ir,
                "harvey_alpha_t_stat": alpha_t
            }

        return {
            "strategy_stats": calc_curve_stats(strat_nav, csi300_nav),
            "benchmark_csi300_stats": calc_curve_stats(csi300_nav, csi300_nav),
            "benchmark_chip_etf_stats": calc_curve_stats(chip_etf_nav, csi300_nav),
            "benchmark_storage_ew_stats": calc_curve_stats(storage_ew_nav, csi300_nav)
        }
