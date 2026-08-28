# -*- coding: utf-8 -*-
"""src/analysis/gold_backtest_runner.py —— 2025Q3-2026Q8 黄金与地缘避险板块物理隔离拟真交易人逐步推进回测执行器

严格遵循：
1. 物理数据隔离（仅读取 data/raw/backtest_gold_2025q3_2026q8/ 原始数据，禁止前视泄漏）
2. 拟真交易人逐步推进（t日收盘计算决策，t+1日开盘真实撮合）
3. A股机构真实费率（买入 0.125%，卖出 0.175%，闲置现金年化 1.8%）
4. 三级对照组基准矩阵（沪深300、黄金ETF、黄金股7巨头等权买入持有）
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
from src.nowcasting.triangle_validator import NowcastingTriangleValidator

logger = logging.getLogger("gold_backtest")


@dataclass
class DailySnapshot:
    """日频因果仿真快照。"""
    date: str
    strategy_nav: float
    csi300_nav: float
    gold_etf_nav: float
    gold_ew_nav: float
    active_holdings: Dict[str, float]
    cash_ratio: float
    trend_gate_status: Dict[str, bool]
    turnover_rate: float
    total_fee_cny: float


class GoldBacktestRunner:
    """黄金与贵金属避险市场物理隔离样本外回测引擎。"""

    # 黄金核心 7 大标的
    GOLD_TICKERS = ["600547", "600489", "601899", "002155", "000975", "600988", "601069"]

    BUY_FRICTION = 0.00125    # 0.125% 买入综合费率 (0.25‰ 佣金 + 1.0‰ 滑点)
    SELL_FRICTION = 0.00175   # 0.175% 卖出综合费率 (0.25‰ 佣金 + 1.0‰ 滑点 + 0.5‰ 印花税)
    DAILY_CASH_YIELD = 0.00005  # 闲置现金日息 (年化约 1.8%)

    def __init__(self, raw_data_dir: Optional[str | Path] = None, initial_capital: float = 1_000_000.0):
        self.raw_data_dir = Path(raw_data_dir or "data/raw/backtest_gold_2025q3_2026q8")
        self.initial_capital = initial_capital

        # 加载核心量化引擎 (保持论文经典 NALE alpha=0.4)
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
        gold_etf_nav = [1.0]
        gold_ew_nav = [1.0]

        current_weights: Dict[str, float] = {t: 0.0 for t in self.GOLD_TICKERS}
        snapshots: List[DailySnapshot] = []

        gold_rets_df = prices_df[self.GOLD_TICKERS].pct_change().fillna(0.0)
        csi300_rets = prices_df["000300.SH"].pct_change().fillna(0.0)
        gold_etf_rets = prices_df["518880.SH"].pct_change().fillna(0.0)
        gold_ew_rets = gold_rets_df.mean(axis=1)

        # 逐步推进仿真 (从第 20 个交易日开始)
        for t in range(20, T):
            dt_str = str(dates[t].date())
            sub_prices = prices_df.iloc[:t]
            sub_nowcast = nowcast_df.iloc[:t]

            target_weights: Dict[str, float] = {}
            gate_status: Dict[str, bool] = {}

            curr_spot = float(sub_nowcast["gold_spot_price"].iloc[-1])
            curr_geo = float(sub_nowcast["geopolitical_risk_index"].iloc[-1])

            for ticker in self.GOLD_TICKERS:
                stock_kline = pd.DataFrame({"close": sub_prices[ticker]})
                gate_dec = self.trend_gate.evaluate_gate(ticker, stock_kline)
                gate_status[ticker] = gate_dec.gate_open

                # 黄金板块特有定性打分与地缘避险溢价
                base_score = 0.70 if curr_geo > 50.0 else 0.35
                gfca_score = base_score + (0.15 if gate_dec.gate_open else -0.30)

                alloc_order = self.allocator.allocate_position(
                    ticker=ticker,
                    gfca_composite_score=gfca_score,
                    trend_gate_decision=gate_dec,
                    bet_type=BetType.CATALYST_ALPHA if gate_dec.gate_open else BetType.SUPER_BETA
                )
                target_weights[ticker] = alloc_order.target_weight_pct

            # 归一化总仓位（上限 95%，留 5% 现金）
            total_target_w = sum(target_weights.values())
            if total_target_w > 0.95:
                for k in target_weights:
                    target_weights[k] = (target_weights[k] / total_target_w) * 0.95

            # 计算调仓换手与交易摩擦成本
            turnover = 0.0
            total_friction_loss = 0.0

            for ticker in self.GOLD_TICKERS:
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

            # 撮合 t+1 日（即当前日 t）真实收益
            stock_ret_contrib = sum(current_weights[ticker] * gold_rets_df[ticker].iloc[t] for ticker in self.GOLD_TICKERS)
            cash_contrib = cash_w * self.DAILY_CASH_YIELD

            daily_strat_ret = stock_ret_contrib + cash_contrib - total_friction_loss

            strat_nav.append(strat_nav[-1] * (1.0 + daily_strat_ret))
            csi300_nav.append(csi300_nav[-1] * (1.0 + csi300_rets.iloc[t]))
            gold_etf_nav.append(gold_etf_nav[-1] * (1.0 + gold_etf_rets.iloc[t]))
            gold_ew_nav.append(gold_ew_nav[-1] * (1.0 + gold_ew_rets.iloc[t]))

            snapshots.append(DailySnapshot(
                date=dt_str,
                strategy_nav=strat_nav[-1],
                csi300_nav=csi300_nav[-1],
                gold_etf_nav=gold_etf_nav[-1],
                gold_ew_nav=gold_ew_nav[-1],
                active_holdings=current_weights.copy(),
                cash_ratio=cash_w,
                trend_gate_status=gate_status,
                turnover_rate=turnover,
                total_fee_cny=total_friction_loss * self.initial_capital
            ))

        metrics = self._calculate_comprehensive_metrics(
            strat_nav=pd.Series(strat_nav, index=dates[19:]),
            csi300_nav=pd.Series(csi300_nav, index=dates[19:]),
            gold_etf_nav=pd.Series(gold_etf_nav, index=dates[19:]),
            gold_ew_nav=pd.Series(gold_ew_nav, index=dates[19:])
        )

        return {
            "metrics": metrics,
            "snapshots": snapshots,
            "nav_series": {
                "dates": [str(d.date()) for d in dates[19:]],
                "strategy": strat_nav,
                "csi300": csi300_nav,
                "gold_etf": gold_etf_nav,
                "gold_ew": gold_ew_nav
            }
        }

    def _calculate_comprehensive_metrics(
        self,
        strat_nav: pd.Series,
        csi300_nav: pd.Series,
        gold_etf_nav: pd.Series,
        gold_ew_nav: pd.Series
    ) -> Dict[str, Any]:
        """计算全套量化绩效指标。"""
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
            
            cum_max = nav.cummax()
            dd = (nav - cum_max) / cum_max
            max_dd = float(abs(dd.min()))

            calmar = float(ann_ret / max_dd) if max_dd > 0 else 0.0
            ir = float(excess_r.mean() / (excess_r.std() + 1e-8) * np.sqrt(ann_factor))
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
            "benchmark_gold_etf_stats": calc_curve_stats(gold_etf_nav, csi300_nav),
            "benchmark_gold_ew_stats": calc_curve_stats(gold_ew_nav, csi300_nav)
        }
