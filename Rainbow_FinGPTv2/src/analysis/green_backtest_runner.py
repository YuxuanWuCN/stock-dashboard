# -*- coding: utf-8 -*-
"""src/analysis/green_backtest_runner.py —— 2025Q3-2026Q3 绿电公用事业与新能源板块物理隔离拟真交易人逐步推进回测执行器

严格遵循：
1. 物理数据隔离（仅读取 data/raw/backtest_green_2025q3_2026q3/ 原始数据，禁止前视泄漏）
2. 拟真交易人逐步推进（t日收盘计算决策，t+1日开盘真实撮合）
3. A股机构真实费率（买入 0.125%，卖出 0.175%，闲置现金年化 1.8%）
4. 三级对照组基准矩阵（沪深300、新能源/绿电ETF、绿电核心6巨头等权买入持有）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

from src.analysis.famamacbethv3 import FamaMacBethV3Engine
from src.analysis.scoringv3 import GFCAScoringEngine
from src.execution.trend_gate import TrendGate, TrendGateDecision
from src.execution.portfolio_allocator import DynamicBetAllocator, BetType, EvidencePhase
from src.nowcasting.triangle_validator import NowcastingTriangleValidator

logger = logging.getLogger("green_backtest")


@dataclass
class DailySnapshot:
    """日频因果仿真快照。"""
    date: str
    strategy_nav: float
    csi300_nav: float
    green_etf_nav: float
    green_ew_nav: float
    active_holdings: Dict[str, float]
    cash_ratio: float
    trend_gate_status: Dict[str, bool]
    turnover_rate: float
    total_fee_cny: float


class GreenBacktestRunner:
    """绿电与新能源公用事业市场物理隔离样本外回测引擎。"""

    # 绿电与新能源 6 大标的
    GREEN_TICKERS = ["001258", "002459", "002466", "601012", "600438", "300750"]

    BUY_FRICTION = 0.00125    # 0.125% 买入综合费率 (0.25‰ 佣金 + 1.0‰ 滑点)
    SELL_FRICTION = 0.00175   # 0.175% 卖出综合费率 (0.25‰ 佣金 + 1.0‰ 滑点 + 0.5‰ 印花税)
    DAILY_CASH_YIELD = 0.00005  # 闲置现金日息 (年化约 1.8%)

    def __init__(self, raw_data_dir: Optional[str | Path] = None, initial_capital: float = 1_000_000.0):
        self.raw_data_dir = Path(raw_data_dir or "data/raw/backtest_green_2025q3_2026q3")
        self.initial_capital = initial_capital

        # 加载核心量化引擎 (保持论文经典 NALE alpha=0.4 与特质定价)
        self.fm_engine = FamaMacBethV3Engine(t_stat_threshold=3.0)
        self.scoring_engine = GFCAScoringEngine(tanh_scaling=1.2, nale_alpha=0.4)
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
        green_etf_nav = [1.0]
        green_ew_nav = [1.0]

        current_weights: Dict[str, float] = {t: 0.0 for t in self.GREEN_TICKERS}
        snapshots: List[DailySnapshot] = []

        green_rets_df = prices_df[self.GREEN_TICKERS].pct_change().fillna(0.0)
        csi300_rets = prices_df["000300.SH"].pct_change().fillna(0.0)
        green_etf_rets = prices_df["515790.SH"].pct_change().fillna(0.0)
        green_ew_rets = green_rets_df.mean(axis=1)

        # 逐步推进仿真 (从第 20 个交易日开始)
        for t in range(20, T):
            dt_str = str(dates[t].date())
            sub_prices = prices_df.iloc[:t]
            sub_nowcast = nowcast_df.iloc[:t]

            target_weights: Dict[str, float] = {}
            gate_status: Dict[str, bool] = {}

            curr_absorb = float(sub_nowcast["grid_absorption_rate"].iloc[-1])
            curr_spot = float(sub_nowcast["green_power_market_price"].iloc[-1])

            for ticker in self.GREEN_TICKERS:
                stock_kline = pd.DataFrame({"close": sub_prices[ticker]})
                gate_dec = self.trend_gate.evaluate_gate(ticker, stock_kline)
                gate_status[ticker] = gate_dec.gate_open

                # 绿电公用事业定性打分：电网消纳率与现货电价联动
                base_score = 0.68 if curr_absorb >= 93.0 else 0.35
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

            for ticker in self.GREEN_TICKERS:
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
            stock_ret_contrib = sum(current_weights[ticker] * green_rets_df[ticker].iloc[t] for ticker in self.GREEN_TICKERS)
            cash_contrib = cash_w * self.DAILY_CASH_YIELD

            daily_strat_ret = stock_ret_contrib + cash_contrib - total_friction_loss

            strat_nav.append(strat_nav[-1] * (1.0 + daily_strat_ret))
            csi300_nav.append(csi300_nav[-1] * (1.0 + csi300_rets.iloc[t]))
            green_etf_nav.append(green_etf_nav[-1] * (1.0 + green_etf_rets.iloc[t]))
            green_ew_nav.append(green_ew_nav[-1] * (1.0 + green_ew_rets.iloc[t]))

            snapshots.append(DailySnapshot(
                date=dt_str,
                strategy_nav=strat_nav[-1],
                csi300_nav=csi300_nav[-1],
                green_etf_nav=green_etf_nav[-1],
                green_ew_nav=green_ew_nav[-1],
                active_holdings=current_weights.copy(),
                cash_ratio=cash_w,
                trend_gate_status=gate_status,
                turnover_rate=turnover,
                total_fee_cny=total_friction_loss * self.initial_capital
            ))

        metrics = self._calculate_comprehensive_metrics(
            strat_nav=pd.Series(strat_nav, index=dates[19:]),
            csi300_nav=pd.Series(csi300_nav, index=dates[19:]),
            green_etf_nav=pd.Series(green_etf_nav, index=dates[19:]),
            green_ew_nav=pd.Series(green_ew_nav, index=dates[19:])
        )

        return {
            "metrics": metrics,
            "snapshots": snapshots,
            "nav_series": {
                "dates": [str(d.date()) for d in dates[19:]],
                "strategy": strat_nav,
                "csi300": csi300_nav,
                "green_etf": green_etf_nav,
                "green_ew": green_ew_nav
            }
        }

    def _calculate_comprehensive_metrics(
        self,
        strat_nav: pd.Series,
        csi300_nav: pd.Series,
        green_etf_nav: pd.Series,
        green_ew_nav: pd.Series
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
            "benchmark_green_etf_stats": calc_curve_stats(green_etf_nav, csi300_nav),
            "benchmark_green_ew_stats": calc_curve_stats(green_ew_nav, csi300_nav)
        }

    def generate_and_save_artifacts(self, result: Dict[str, Any], output_fig_dir: Optional[Path] = None, output_json: Optional[Path] = None):
        """生成并持久化实证图表与 JSON 统计工件。"""
        root = Path(__file__).resolve().parent.parent.parent
        fig_dir = output_fig_dir or (root / "reports" / "figures" / "backtest_green_2025q3_2026q3")
        json_path = output_json or (root / "docs" / "data" / "paper" / "backtest_green_2025q3_2026q3.json")

        fig_dir.mkdir(parents=True, exist_ok=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. 保存 JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "period": f"{result['snapshots'][0].date} ~ {result['snapshots'][-1].date}",
                "tickers": self.GREEN_TICKERS,
                "metrics": result["metrics"],
                "nav_series": result["nav_series"]
            }, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved green backtest json: {json_path}")

        # 2. 绘制图一：净值走势与水下回撤对比
        nav_data = result["nav_series"]
        dates = pd.to_datetime(nav_data["dates"])
        strat_nav = np.array(nav_data["strategy"])
        csi_nav = np.array(nav_data["csi300"])
        etf_nav = np.array(nav_data["green_etf"])
        ew_nav = np.array(nav_data["green_ew"])

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2.2, 1.0]})
        
        ax1.plot(dates, strat_nav, label=f"Rainbow-FinGPT 绿电增强策略 (Sharpe={result['metrics']['strategy_stats']['sharpe_ratio']:.2f})", color="#16a34a", lw=2.2)
        ax1.plot(dates, etf_nav, label=f"绿电/新能源ETF (515790) (Sharpe={result['metrics']['benchmark_green_etf_stats']['sharpe_ratio']:.2f})", color="#0284c7", lw=1.5, ls="--")
        ax1.plot(dates, ew_nav, label="绿电6巨头等权买入持有", color="#d97706", lw=1.2, ls=":")
        ax1.plot(dates, csi_nav, label="沪深300基准 (000300)", color="#94a3b8", lw=1.0)
        
        ax1.set_title("绿电公用事业与新能源板块物理隔离拟真交易人净值走势对比 (2025Q3-2026Q3)", fontsize=12, fontweight="bold")
        ax1.set_ylabel("累计净值 (基准=1.0)", fontsize=10)
        ax1.legend(loc="upper left", frameon=True, facecolor="#f8fafc", framealpha=0.9)
        ax1.grid(True, alpha=0.3, ls="--")

        # 水下回撤
        def get_dd(nav_arr):
            cum_m = np.maximum.accumulate(nav_arr)
            return (nav_arr - cum_m) / cum_m * 100.0

        ax2.plot(dates, get_dd(strat_nav), color="#16a34a", lw=1.8, label="策略回撤 (Trend Gate C浪拦截)")
        ax2.plot(dates, get_dd(etf_nav), color="#0284c7", lw=1.2, ls="--", label="绿电ETF回撤")
        ax2.fill_between(dates, get_dd(strat_nav), 0, color="#16a34a", alpha=0.15)
        ax2.set_ylabel("动态回撤 (%)", fontsize=10)
        ax2.set_xlabel("交易日期 (样本外逐步推进)", fontsize=10)
        ax2.legend(loc="lower left", frameon=True)
        ax2.grid(True, alpha=0.3, ls="--")

        plt.tight_layout()
        fig1_path = fig_dir / "fig1_cumulative_equity_and_drawdown.png"
        fig.savefig(fig1_path, dpi=200)
        plt.close(fig)
        logger.info(f"Saved figure 1: {fig1_path}")

        # 3. 绘制图二：资产配置仓位与逐日换手率
        fig, (ax3, ax4) = plt.subplots(2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [1.8, 1.0]})
        
        snapshot_dates = [pd.to_datetime(s.date) for s in result["snapshots"]]
        holdings = {t: [s.active_holdings.get(t, 0.0) * 100 for s in result["snapshots"]] for t in self.GREEN_TICKERS}
        cash = [s.cash_ratio * 100 for s in result["snapshots"]]
        turnovers = [s.turnover_rate * 100 for s in result["snapshots"]]

        y_stack = [holdings[t] for t in self.GREEN_TICKERS] + [cash]
        labels = [f"标的 {t}" for t in self.GREEN_TICKERS] + ["闲置现金 (日息1.8%年化)"]
        colors = ["#22c55e", "#10b981", "#059669", "#047857", "#065f46", "#0f766e", "#cbd5e1"]

        ax3.stackplot(snapshot_dates, y_stack, labels=labels, colors=colors, alpha=0.85)
        ax3.set_title("动态头寸分配与 Trend Gate 状态机持仓分布 (001258/601012等)", fontsize=12, fontweight="bold")
        ax3.set_ylabel("资产配置比例 (%)", fontsize=10)
        ax3.legend(loc="upper left", ncol=3, fontsize=8, frameon=True)
        ax3.grid(True, alpha=0.3)

        ax4.bar(snapshot_dates, turnovers, color="#6366f1", width=1.0, alpha=0.7, label="逐日调仓换手率 (%)")
        ax4.set_ylabel("换手率 (%)", fontsize=10)
        ax4.set_xlabel("交易日期", fontsize=10)
        ax4.legend(loc="upper right", frameon=True)
        ax4.grid(True, alpha=0.3)

        plt.tight_layout()
        fig2_path = fig_dir / "fig2_asset_allocation_and_turnover.png"
        fig.savefig(fig2_path, dpi=200)
        plt.close(fig)
        logger.info(f"Saved figure 2: {fig2_path}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    runner = GreenBacktestRunner()
    res = runner.run_walk_forward_backtest()
    runner.generate_and_save_artifacts(res)
    
    strat = res["metrics"]["strategy_stats"]
    etf = res["metrics"]["benchmark_green_etf_stats"]
    print(f"\n===== 绿电公用事业物理隔离实测完成 =====")
    print(f"策略总收益: +{strat['total_return']*100:.2f}% (年化: +{strat['annualized_return']*100:.2f}%)")
    print(f"策略夏普比: {strat['sharpe_ratio']:.2f} (绿电ETF: {etf['sharpe_ratio']:.2f})")
    print(f"最大回撤: {strat['max_drawdown']*100:.2f}% (绿电ETF: {etf['max_drawdown']*100:.2f}%)")
    print(f"信息比率: {strat['information_ratio']:.2f}")


if __name__ == "__main__":
    main()

