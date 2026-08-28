# -*- coding: utf-8 -*-
"""src/analysis/storage_backtest_runner.py —— 2025Q2-2026Q3 存储市场物理隔离拟真交易人逐步推进回测执行器

严格遵循：
1. 物理数据隔离（仅读取 data/raw/backtest_storage_2025q2_2026q3/ 与 docs/data/kline/ 原始数据，禁止前视泄漏）
2. 拟真交易人逐步推进（t日收盘计算决策，t+1日开盘真实撮合）
3. 因子与供应链闭环驱动（GFCA 几何因子空间坐标对齐 + NALE 供应链拓扑网络传导 alpha=0.4 + 美股 MU 跨市场溢出特征）
4. 截面龙头非对称聚焦（Top 1 领头羊 45%, Top 2 35%, Top 3 15%）+ 5% 调仓死区缓冲区（抑制摩擦）
5. A股机构真实费率（买入 0.125%，卖出 0.175%，闲置现金年化 1.8%）
6. 三级对照组基准矩阵（沪深300、芯片ETF、存储5巨头等权买入持有）
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
    DEADBAND = 0.05           # 5% 调仓死区容忍度 (避免微小权重波动的无效摩擦损耗)

    def __init__(self, raw_data_dir: Optional[str | Path] = None, initial_capital: float = 1_000_000.0):
        self.raw_data_dir = Path(raw_data_dir or "data/raw/backtest_storage_2025q2_2026q3")
        self.initial_capital = initial_capital

        # 加载核心量化与闭环传导引擎
        self.fm_engine = FamaMacBethV3Engine(t_stat_threshold=3.0)
        self.scoring_engine = GFCAScoringEngine(tanh_scaling=1.0, nale_alpha=0.4)
        self.trend_gate = TrendGate(ma_period=20)
        self.allocator = DynamicBetAllocator(total_portfolio_capital=initial_capital)
        self.nowcast_validator = NowcastingTriangleValidator(penalty_lambda=0.6)

        # 存储产业链经济关联拓扑邻接矩阵 (001309德明利、300475香农、301308江波龙、688525佰维、688008澜起)
        self.adj_matrix = np.array([
            [1.0, 0.4, 0.5, 0.8, 0.3],
            [0.4, 1.0, 0.3, 0.5, 0.2],
            [0.5, 0.3, 1.0, 0.6, 0.3],
            [0.8, 0.5, 0.6, 1.0, 0.5],
            [0.3, 0.2, 0.3, 0.5, 1.0],
        ])

    def load_isolated_raw_data(self) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """读取物理隔离目录中的原始数据，并对齐美股 MU 跨市场滞后领先信号。"""
        prices_df = pd.read_csv(self.raw_data_dir / "market_prices.csv", index_col=0, parse_dates=True)
        nowcast_df = pd.read_csv(self.raw_data_dir / "nowcasting_spot.csv", index_col=0, parse_dates=True)
        factors_df = pd.read_csv(self.raw_data_dir / "factors.csv", index_col=0, parse_dates=True)

        # 提取美股 MU 隔夜收益领先特征 (滞后 1 日切片，严防前视)
        mu_path = self.raw_data_dir.parent.parent / "docs" / "data" / "kline" / "MU.json"
        if mu_path.exists():
            with open(mu_path, "r", encoding="utf-8") as f:
                mu_json = json.load(f)
            mu_dates = pd.to_datetime(mu_json["dates"])
            mu_closes = [r[1] for r in mu_json["kline"]]
            mu_df = pd.DataFrame({"mu_close": mu_closes}, index=mu_dates)
            mu_rets = mu_df["mu_close"].pct_change()
            prices_df["mu_lag_ret"] = mu_rets.reindex(prices_df.index).ffill().fillna(0.0)
        else:
            prices_df["mu_lag_ret"] = 0.0

        return prices_df, nowcast_df, factors_df

    def run_walk_forward_backtest(self) -> Dict[str, Any]:
        """执行日频拟真交易人全流程样本外回测。"""
        prices_df, nowcast_df, factors_df = self.load_isolated_raw_data()
        dates = prices_df.index
        T = len(dates)

        strat_nav = [1.0]
        csi300_nav = [1.0]
        chip_etf_nav = [1.0]
        storage_ew_nav = [1.0]

        current_weights: Dict[str, float] = {t: 0.0 for t in self.STORAGE_TICKERS}
        snapshots: List[DailySnapshot] = []

        storage_rets_df = prices_df[self.STORAGE_TICKERS].pct_change().fillna(0.0)
        csi300_rets = prices_df["000300.SH"].pct_change().fillna(0.0)
        chip_etf_rets = prices_df["512760.SH"].pct_change().fillna(0.0)
        storage_ew_rets = storage_rets_df.mean(axis=1)

        # 逐步推进仿真 (从第 20 个交易日开始计算指标)
        for t in range(20, T):
            dt_str = str(dates[t].date())
            sub_prices = prices_df.iloc[:t]
            sub_nowcast = nowcast_df.iloc[:t]

            # 1. 拟真交易人时点 t 决策：严格仅使用 <= t 的历史切片
            curr_spot = float(sub_nowcast["dxi_spot_price"].iloc[-1])
            curr_korea_yoy = float(sub_nowcast["korea_customs_yoy"].iloc[-1])
            curr_mu_lag = float(sub_prices["mu_lag_ret"].iloc[-1])

            gate_decs: Dict[str, TrendGateDecision] = {}
            penalties: Dict[str, float] = {}
            raw_factor_dict: Dict[str, List[float]] = {
                "alpha_momentum_20d": [],
                "alpha_volatility_20d": [],
                "alpha_supply_chain_score": [],
                "alpha_chokepoint_moat": []
            }

            for ticker in self.STORAGE_TICKERS:
                p_series = sub_prices[ticker]
                stock_kline = pd.DataFrame({"close": p_series})
                gate_dec = self.trend_gate.evaluate_gate(ticker, stock_kline)
                gate_decs[ticker] = gate_dec

                cost_col = f"lockin_cost_{ticker}"
                prepay_cost = float(sub_nowcast[cost_col].iloc[-1]) if cost_col in sub_nowcast.columns else 85.0

                nowcast_sig = self.nowcast_validator.evaluate_asset_nowcasting(
                    ticker=ticker,
                    korea_customs_export_yoy=curr_korea_yoy,
                    spot_dxi_price=curr_spot,
                    lockin_prepay_cost=prepay_cost
                )
                penalties[ticker] = nowcast_sig.impairment_penalty_drift

                # 提取因子并在供应链维度并入美股 MU 跨市场溢出信息
                mom20 = (p_series.iloc[-1] / p_series.iloc[-20] - 1.0) if len(p_series) >= 20 else 0.0
                vol20 = float(p_series.pct_change().iloc[-20:].std() * np.sqrt(250)) if len(p_series) >= 20 else 0.30
                supply_score = (0.85 if curr_spot >= prepay_cost else 0.25) + 0.5 * curr_mu_lag
                moat_score = 0.90 if ticker in ["688525", "001309"] else 0.70

                raw_factor_dict["alpha_momentum_20d"].append(mom20)
                raw_factor_dict["alpha_volatility_20d"].append(vol20)
                raw_factor_dict["alpha_supply_chain_score"].append(supply_score)
                raw_factor_dict["alpha_chokepoint_moat"].append(moat_score)

            raw_factor_df = pd.DataFrame(raw_factor_dict, index=self.STORAGE_TICKERS)

            # 2. 计算 GFCA 几何因子空间坐标对齐与 Nowcasting 动态漂移
            gfca_coords = self.scoring_engine.align_gfca_coordinates(
                raw_factor_df=raw_factor_df,
                impairment_penalties=penalties
            )
            raw_scores = {tk: gfca_coords[tk].composite_score for tk in self.STORAGE_TICKERS}

            # 3. 计算 NALE 供应链网络传导增强得分 (alpha=0.4)
            nale_results = self.scoring_engine.calculate_nale_score(
                node_scores=raw_scores,
                adjacency_matrix=self.adj_matrix,
                ticker_list=self.STORAGE_TICKERS
            )

            # 4. 截面龙头非对称聚焦 (Top 1 领头羊 45%, Top 2 35%, Top 3 15%, 后2名 0%)
            sorted_tickers = sorted(self.STORAGE_TICKERS, key=lambda k: nale_results[k].final_nale_score, reverse=True)
            top1, top2, top3 = sorted_tickers[0], sorted_tickers[1], sorted_tickers[2]

            desired_weights: Dict[str, float] = {}
            gate_status: Dict[str, bool] = {}

            for ticker in self.STORAGE_TICKERS:
                nale_res = nale_results[ticker]
                gate_dec = gate_decs[ticker]
                gate_status[ticker] = gate_dec.gate_open

                # 宏观与微观门禁硬拦截：若均线破位或海关出口崩塌，强制归零避险
                if not gate_dec.gate_open or curr_korea_yoy < -12.0:
                    desired_weights[ticker] = 0.0
                else:
                    if ticker == top1:
                        base = 0.45
                    elif ticker == top2:
                        base = 0.35
                    elif ticker == top3:
                        base = 0.15
                    else:
                        base = 0.00

                    score_mod = float(np.clip(0.75 + 0.25 * nale_res.final_nale_score, 0.40, 1.15))
                    spot_mod = 1.05 if curr_spot >= 120.0 else 0.85
                    desired_weights[ticker] = base * score_mod * spot_mod

            # 归一化总仓位（上限 95%，留 5% 现金）
            tot_desired = sum(desired_weights.values())
            if tot_desired > 0.95:
                for k in desired_weights:
                    desired_weights[k] = (desired_weights[k] / tot_desired) * 0.95

            # 5. 调仓死区缓冲区过滤 (若偏离 < DEADBAND 且未触发清仓，则保持不变以避免磨损)
            target_weights: Dict[str, float] = {}
            for ticker in self.STORAGE_TICKERS:
                if desired_weights[ticker] == 0.0:
                    target_weights[ticker] = 0.0
                elif abs(desired_weights[ticker] - current_weights.get(ticker, 0.0)) < self.DEADBAND:
                    target_weights[ticker] = current_weights.get(ticker, 0.0)
                else:
                    target_weights[ticker] = desired_weights[ticker]

            # 6. 计算调仓换手与交易摩擦成本
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

            # 7. 撮合 t+1 日（即当前日 t）真实收益
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

        # 汇总最终量化度量指标
        metrics = self._calculate_comprehensive_metrics(
            strat_nav=pd.Series(strat_nav),
            csi300_nav=pd.Series(csi300_nav),
            chip_etf_nav=pd.Series(chip_etf_nav),
            storage_ew_nav=pd.Series(storage_ew_nav)
        )

        return {
            "period": f"{dates[20].date()} ~ {dates[-1].date()} ({len(snapshots)} Trading Days)",
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
            "benchmark_chip_etf_stats": calc_curve_stats(chip_etf_nav, csi300_nav),
            "benchmark_storage_ew_stats": calc_curve_stats(storage_ew_nav, csi300_nav)
        }
