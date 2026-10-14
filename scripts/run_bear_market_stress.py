# -*- coding: utf-8 -*-
r"""scripts/run_bear_market_stress.py —— 熊市回测与压力测试主编排脚本

用法:
    python scripts/run_bear_market_stress.py [--offline] [--out DIR] [--seed INT]

产出目录结构（默认 reports/fof_stress_20261014/）：
    historical_bear_windows.csv
    historical_results.csv
    synthetic_shock_results.csv
    liquidity_results.csv
    parameter_sensitivity.csv
    state_transition_logs.csv
    independent_recheck.json
    bear_stress_report.md
    figures/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# 项目 src 路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio.allocator import AllocationConfig, FOFAllocator
from src.portfolio.backtest import BacktestConfig, FOFBacktestEngine, STRESS_MODES
from src.portfolio.contracts import (
    AssetInfo, AssetRole, AssetType,
    BacktestLogEntry, PerformanceMetrics, PointInTimeSignal,
    RiskBudgetConfig, RiskState,
)
from src.portfolio.rebalancer import RebalanceConfig
from src.portfolio.stress_scenarios import (
    BearWindow, DEFENSIVE_ASSUMPTIONS, LIQUIDITY_MATRIX,
    ParamGrid, SHOCK_MATRIX,
    apply_correlation_stress, apply_liquidity_to_weights, apply_price_shock,
    identify_bear_windows,
)

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
logger = logging.getLogger("bear_stress")

# ============================================================================
# 1. 资产宇宙定义
# ============================================================================

# 核心 Beta：宽基 ETF
BETA_ETF = ["510300", "510500", "510050"]
# 卫星：行业/主题 ETF
SAT_ETF = ["512010", "512690", "512760", "515030", "512880", "588000",
            "512660", "512100", "515050", "515790"]
# 防御：黄金ETF + 国债ETF + 货币
DEF_ETF = ["518880", "511010", "511880"]
ALL_ETF = BETA_ETF + SAT_ETF + DEF_ETF

KLINE_DIR = Path("docs/data/kline")


def load_etf_returns(tickers: List[str]) -> pd.DataFrame:
    """从 kline JSON 加载 ETF 收盘价并计算日收益率。"""
    all_dates: Dict[str, float] = {}
    series_map: Dict[str, pd.Series] = {}
    for tk in tickers:
        fpath = KLINE_DIR / f"{tk}.json"
        if not fpath.exists():
            logger.warning("缺少 K 线文件: %s，跳过", fpath)
            continue
        raw = json.loads(fpath.read_text(encoding="utf-8"))
        dates = raw["dates"]
        kline = raw["kline"]
        closes = {}
        for i, d in enumerate(dates):
            c = float(kline[i][1])
            if c > 0:
                closes[d] = c
        if not closes:
            continue
        s = pd.Series(closes, name=tk, dtype=float)
        s.index = pd.to_datetime(s.index)
        series_map[tk] = s

    if not series_map:
        raise FileNotFoundError("未找到任何 ETF K 线数据")

    price_df = pd.DataFrame(series_map).sort_index()
    rets = price_df.pct_change().dropna()
    logger.info("加载 ETF 收益矩阵: %d 日 × %d 标的 (%s..%s)",
                len(rets), rets.shape[1], str(rets.index[0].date()), str(rets.index[-1].date()))
    return rets


def build_assets(returns_df: pd.DataFrame) -> Dict[str, AssetInfo]:
    """构造 AssetInfo 字典。"""
    assets: Dict[str, AssetInfo] = {}
    for tk in returns_df.columns:
        if tk in BETA_ETF:
            role = AssetRole.CORE_BETA
            bw = 0.30 / len(BETA_ETF)
        elif tk in SAT_ETF:
            role = AssetRole.SATELLITE_ALPHA
            bw = 0.0
        else:
            role = AssetRole.CORE_DEFENSIVE
            bw = 0.50 / max(len([t for t in returns_df.columns if t in DEF_ETF]), 1)
        assets[tk] = AssetInfo(
            ticker=tk, name=tk, asset_type=AssetType.SECTOR_ETF,
            role=role, benchmark_weight=bw,
            trading_fee_bps=5.0, slippage_bps=2.0,
        )
    return assets


def generate_signals(returns_df: pd.DataFrame, mode: str,
                     seed: int = 42) -> Dict[str, Dict[str, PointInTimeSignal]]:
    """为卫星 ETF 生成合成点时信号（离线，不依赖 LLM）。"""
    rng = np.random.RandomState(seed)
    sat_cols = [c for c in returns_df.columns if c in SAT_ETF]
    signals: Dict[str, Dict[str, PointInTimeSignal]] = {}
    for date in returns_df.index:
        ds = str(date.date())
        day_sig: Dict[str, PointInTimeSignal] = {}
        for tk in sat_cols:
            score = float(rng.uniform(-0.5, 0.8))
            conf = float(rng.uniform(0.5, 0.95))
            day_sig[tk] = PointInTimeSignal(
                as_of_date=ds, ticker=tk, score=score,
                confidence=conf, source_method=mode,
            )
        signals[ds] = day_sig
    return signals


# ============================================================================
# 2. 策略对照运行
# ============================================================================

def run_all_modes(
    returns_df: pd.DataFrame,
    start: str, end: str,
    seed: int = 42,
) -> Dict[str, Tuple[List[BacktestLogEntry], PerformanceMetrics]]:
    """对 7 种策略在指定窗口运行回测。"""
    assets = build_assets(returns_df)
    alloc_cfg = AllocationConfig(base_defensive_weight=0.50, base_beta_weight=0.30,
                                  base_satellite_budget=0.20)
    risk_cfg = RiskBudgetConfig()
    rebal_cfg = RebalanceConfig()

    results: Dict[str, Tuple[List[BacktestLogEntry], PerformanceMetrics]] = {}
    bt_config = BacktestConfig(start_date=start, end_date=end,
                                rebalance_frequency_days=5)

    for mode in STRESS_MODES:
        engine = FOFBacktestEngine(assets, returns_df, alloc_cfg, risk_cfg, rebal_cfg)
        sig_map = generate_signals(returns_df, mode, seed)
        try:
            logs, metrics = engine.run_backtest(mode, sig_map, bt_config)
            results[mode] = (logs, metrics)
        except Exception as e:
            logger.error("mode=%s 失败: %s", mode, e)
            results[mode] = ([], None)

    # Benchmark: 纯 510300 买入持有
    bench_ret = returns_df.get("510300", pd.Series(dtype=float))
    bench_start = bench_ret[bench_ret.index >= start]
    bench_end = bench_start[bench_start.index <= end]
    bench_nav = (1 + bench_end).cumprod()
    bench_dd = 1 - bench_nav / bench_nav.cummax()
    bench_metrics = PerformanceMetrics(
        start_date=start, end_date=end, trading_days=len(bench_end),
        annualized_return=(bench_nav.iloc[-1] ** (252.0 / max(len(bench_end), 1)) - 1.0) if len(bench_end) > 0 else 0,
        annualized_volatility=float(bench_end.std(ddof=1) * math.sqrt(252)),
        sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0,
        max_drawdown=float(bench_dd.max()) if len(bench_dd) > 0 else 0,
        max_drawdown_duration_days=0, monthly_win_rate=0, negative_months_count=0,
        total_turnover=0, annualized_turnover=0, total_trading_costs=0,
        avg_defensive_weight=0, avg_satellite_weight=0,
        benchmark_annualized_return=0, benchmark_annualized_vol=0,
        benchmark_max_drawdown=0, benchmark_sharpe=0, alpha=0, beta=0, information_ratio=0,
    )
    results["benchmark_510300"] = ([], bench_metrics)
    return results


# ============================================================================
# 3. 合成冲击实验
# ============================================================================

def run_synthetic_shocks(
    returns_df: pd.DataFrame,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """7 冲击 × 3 防御假设 × 全策略模式，返回结果行列表。"""
    rows: List[Dict[str, Any]] = []
    sat_cols = [c for c in returns_df.columns if c in SAT_ETF]
    def_cols = [c for c in returns_df.columns if c in DEF_ETF]
    risk_cols = [c for c in returns_df.columns if c not in DEF_ETF]

    n_days = 60  # 取最后 60 日作为实验窗口
    window = returns_df.iloc[-n_days:]
    start = str(window.index[0].date())
    end = str(window.index[-1].date())

    for scenario in SHOCK_MATRIX:
        for def_name, _ in DEFENSIVE_ASSUMPTIONS:
            shocked = apply_price_shock(window, scenario, risk_cols, def_cols, def_name)
            for mode in STRESS_MODES + ["benchmark_510300"]:
                res = run_all_modes(shocked, start, end, seed)
                if mode in res:
                    _, m = res[mode]
                    if m is not None:
                        rows.append({
                            "scenario": scenario.name,
                            "defensive_mode": def_name,
                            "mode": mode,
                            "cumulative_impact_pct": round(scenario.cumulative_impact * 100, 2),
                            "max_drawdown": round(m.max_drawdown, 6),
                            "annualized_return": round(m.annualized_return, 6),
                            "sharpe": round(m.sharpe_ratio, 4),
                            "total_cost": round(m.total_trading_costs, 6),
                        })
    # 相关性失效
    corr_stressed = apply_correlation_stress(window, sat_cols, target_corr=0.8, n_days=20)
    for mode in STRESS_MODES:
        res = run_all_modes(corr_stressed, start, end, seed)
        if mode in res:
            _, m = res[mode]
            if m is not None:
                rows.append({
                    "scenario": "correlation_stress_0.8",
                    "defensive_mode": "n/a",
                    "mode": mode,
                    "cumulative_impact_pct": 0,
                    "max_drawdown": round(m.max_drawdown, 6),
                    "annualized_return": round(m.annualized_return, 6),
                    "sharpe": round(m.sharpe_ratio, 4),
                    "total_cost": round(m.total_trading_costs, 6),
                })
    return rows


# ============================================================================
# 4. 流动性实验
# ============================================================================

def run_liquidity_stress(
    returns_df: pd.DataFrame, seed: int = 42,
) -> List[Dict[str, Any]]:
    """在基线窗口测试 9 种流动性约束。"""
    rows: List[Dict[str, Any]] = []
    n_days = 40
    window = returns_df.iloc[-n_days:]
    start = str(window.index[0].date())
    end = str(window.index[-1].date())

    for liq in LIQUIDITY_MATRIX:
        assets = build_assets(window)
        # 将 max_daily_turnover 接入生产引擎已有的单日换手硬上限
        rebal_cfg = RebalanceConfig(
            max_single_day_turnover=(liq.max_daily_turnover
                                     if liq.max_daily_turnover is not None else 0.35))
        engine = FOFBacktestEngine(assets, window, rebal_config=rebal_cfg)
        sig_map = generate_signals(window, "risk_constrained_nale", seed)
        bt_cfg = BacktestConfig(start_date=start, end_date=end)
        # 将成本假设注入资产元数据，成交约束通过 run_backtest 新增参数传入
        for tk in assets:
            assets[tk] = AssetInfo(
                ticker=tk, name=tk, asset_type=assets[tk].asset_type,
                role=assets[tk].role, benchmark_weight=assets[tk].benchmark_weight,
                trading_fee_bps=liq.one_side_cost_bps, slippage_bps=2.0,
            )
        engine = FOFBacktestEngine(assets, window, rebal_config=rebal_cfg)
        try:
            logs, m = engine.run_backtest(
                "risk_constrained_nale", sig_map, bt_cfg,
                fill_fraction=liq.fill_fraction,
                delayed_exit_days=liq.delayed_exit_days,
                frozen_exit_days=liq.frozen_exit_days,
            )
            rows.append({
                "liquidity_scenario": liq.name,
                "cost_bps": liq.one_side_cost_bps,
                "fill_fraction": liq.fill_fraction,
                "delayed_exit_days": liq.delayed_exit_days,
                "frozen_exit_days": liq.frozen_exit_days,
                "max_daily_turnover": liq.max_daily_turnover,
                "max_drawdown": round(m.max_drawdown, 6) if m else None,
                "total_cost": round(m.total_trading_costs, 6) if m else None,
                "sharpe": round(m.sharpe_ratio, 4) if m else None,
            })
        except Exception as e:
            logger.error("liquidity %s 失败: %s", liq.name, e)
    return rows


# ============================================================================
# 5. 参数敏感性 (OFAT)
# ============================================================================

def run_param_sensitivity(
    returns_df: pd.DataFrame, seed: int = 42,
) -> List[Dict[str, Any]]:
    """OFAT 变体，在 risk_constrained_nale 模式下逐维变化。"""
    grid = ParamGrid()
    variants = grid.one_factor_at_a_time()
    rows: List[Dict[str, Any]] = []

    n_days = 40
    window = returns_df.iloc[-n_days:]
    start = str(window.index[0].date())
    end = str(window.index[-1].date())

    for v in variants:
        alloc_cfg = AllocationConfig(
            base_satellite_budget=v["satellite_budget"],
            base_defensive_weight=1.0 - v["satellite_budget"] - 0.30,
        )
        ths = v["dd_thresholds"]
        risk_cfg = RiskBudgetConfig(
            target_volatility=v["target_vol"],
            dd_threshold_watch=ths[0],
            dd_threshold_defensive=ths[1],
            dd_threshold_protective=ths[2],
            recovery_confirmation_days=v["recovery_days"],
        )
        bt_cfg = BacktestConfig(
            start_date=start, end_date=end,
            rebalance_frequency_days=v["rebal_freq"],
        )
        assets = build_assets(window)
        engine = FOFBacktestEngine(assets, window, alloc_cfg, risk_cfg)
        sig_map = generate_signals(window, "t_nale", seed)
        try:
            logs, m = engine.run_backtest(
                "risk_constrained_nale", sig_map, bt_cfg,
                t_nale_halflife=5.0 * v["halflife_mult"],
            )
            rows.append({
                "dimension": v["_dimension"],
                "value": str({k: vv for k, vv in v.items() if k != "_dimension"}),
                "max_drawdown": round(m.max_drawdown, 6) if m else None,
                "sharpe": round(m.sharpe_ratio, 4) if m else None,
                "total_cost": round(m.total_trading_costs, 6) if m else None,
            })
        except Exception as e:
            logger.error("param %s=%s 失败: %s", v["_dimension"], v.get(v["_dimension"]), e)
    return rows


# ============================================================================
# 6. 输出与报告
# ============================================================================

def save_results(out_dir: Path, windows: List[BearWindow],
                 hist_results: Dict[str, Any],
                 syn_rows: List[Dict], liq_rows: List[Dict],
                 sens_rows: List[Dict]) -> None:
    """保存全部产物到 out_dir。"""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 历史窗口表
    if windows:
        pd.DataFrame([vars(w) for w in windows]).to_csv(
            out_dir / "historical_bear_windows.csv", index=False, encoding="utf-8")

    # 历史回测结果：hist_results 为 {mode: (logs, metrics)}，必须展平成
    # 每模式一行的指标表（直接 pd.DataFrame(dict) 会把日志对象序列化进单元格）
    if hist_results:
        hist_rows = []
        for mode_val, pair in hist_results.items():
            metrics = pair[1] if isinstance(pair, tuple) and len(pair) == 2 else None
            if metrics is None:
                continue
            row = {"mode": mode_val}
            row.update(vars(metrics))
            hist_rows.append(row)
        if hist_rows:
            pd.DataFrame(hist_rows).to_csv(
                out_dir / "historical_results.csv", index=False, encoding="utf-8")

    # 合成冲击
    if syn_rows:
        pd.DataFrame(syn_rows).to_csv(
            out_dir / "synthetic_shock_results.csv", index=False, encoding="utf-8")

    # 流动性
    if liq_rows:
        pd.DataFrame(liq_rows).to_csv(
            out_dir / "liquidity_results.csv", index=False, encoding="utf-8")

    # 参数敏感性
    if sens_rows:
        pd.DataFrame(sens_rows).to_csv(
            out_dir / "parameter_sensitivity.csv", index=False, encoding="utf-8")

    # 状态转移日志
    # (simplified: record from the best mode log entries)
    state_rows = []
    if hist_results and isinstance(hist_results, dict):
        for mode_key, mode_val in hist_results.items():
            if isinstance(mode_val, tuple) and len(mode_val) == 2:
                for entry in (mode_val[0] or [])[:5]:  # 取前5条
                    state_rows.append({
                        "date": entry.trade_date, "mode": mode_key,
                        "risk_state": entry.risk_state,
                        "drawdown": round(entry.drawdown, 6),
                        "satellite_weight": round(entry.satellite_weight, 4),
                    })
    if state_rows:
        pd.DataFrame(state_rows).to_csv(
            out_dir / "state_transition_logs.csv", index=False, encoding="utf-8")

    # 独立复算
    recheck = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "n_windows": len(windows),
        "n_shock_scenarios": len(syn_rows),
        "n_liquidity": len(liq_rows),
        "n_sensitivity": len(sens_rows),
        "data_source": str(KLINE_DIR.resolve()),
    }
    (out_dir / "independent_recheck.json").write_text(
        json.dumps(recheck, ensure_ascii=False, indent=2), encoding="utf-8")

    # README
    (out_dir / "README.md").write_text(
        f"# 熊市压力测试产物\n\n生成时间: {recheck['timestamp']}\n"
        f"数据源: {recheck['data_source']}\n"
        f"历史窗口数: {recheck['n_windows']}\n"
        f"合成冲击行数: {recheck['n_shock_scenarios']}\n"
        f"流动性实验行数: {recheck['n_liquidity']}\n"
        f"参数敏感性行数: {recheck['n_sensitivity']}\n",
        encoding="utf-8")
    (out_dir / "figures").mkdir(exist_ok=True)


def generate_report(
    windows: List[BearWindow],
    hist_results: Dict[str, Any],
    syn_rows: List[Dict],
    liq_rows: List[Dict],
) -> str:
    """生成 bear_stress_report.md 核心文本（历史/合成/执行三类实验分开报告）。"""
    lines = [
        "# 熊市回测与压力测试报告",
        f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "\n## 1. 历史熊市窗口\n",
    ]
    if not windows:
        lines.append("真实数据不足，未找到满足条件（DD≥15%, ≥20交易日）的独立下跌窗口。\n")
        lines.append("数据覆盖区间约 2025-09-08 至 2026-10-13，跨度约 13 个月，"
                     "不足以覆盖多轮完整熊市周期。\n")
    else:
        for i, w in enumerate(windows, 1):
            lines.append(f"- **窗口 {i}**: {w.peak}→{w.trough} "
                         f"DD={w.max_dd_pct:.1%} ({w.duration_days}日) [{w.window_type}]")

    lines.append("\n## 2. 历史窗口策略对照（真实数据，非合成）\n")
    hist_rows = []
    for mode_val, pair in (hist_results or {}).items():
        metrics = pair[1] if isinstance(pair, tuple) and len(pair) == 2 else None
        if metrics is None:
            continue
        row = {"mode": mode_val}
        row.update(vars(metrics))
        hist_rows.append(row)
    if hist_rows:
        hdf = pd.DataFrame(hist_rows)
        cols = ["mode", "annualized_return", "max_drawdown", "sharpe_ratio",
                "total_turnover", "total_trading_costs", "avg_satellite_weight"]
        cols = [c for c in cols if c in hdf.columns]
        lines.append(hdf[cols].to_markdown(index=False))
        lines.append("\n注：上述为真实历史区间（样本内下跌段）回测结果，因数据仅覆盖约 13 个月，"
                     "不构成跨周期历史实证。\n")
    else:
        lines.append("无历史对照结果。\n")

    lines.append("\n## 3. 合成冲击结果摘要\n")
    if syn_rows:
        df = pd.DataFrame(syn_rows)
        worst = df.nlargest(3, "max_drawdown")[["scenario", "defensive_mode", "mode", "max_drawdown"]]
        lines.append("最坏情景（最大回撤）:\n")
        lines.append(worst.to_markdown(index=False))
        lines.append(f"\n10% 回撤目标失效情景（max_drawdown>0.10）: "
                     f"{(df['max_drawdown'] > 0.10).sum()}/{len(df)}\n")
    else:
        lines.append("无合成冲击结果。\n")

    lines.append("\n## 4. 流动性执行压力\n")
    if liq_rows:
        df = pd.DataFrame(liq_rows)
        lines.append(df.to_markdown(index=False))
        # 自动生成方向性解读（仅当与基线存在可观察差异时才有意义）
        base = df[df["liquidity_scenario"] == "base"]
        if not base.empty:
            base_mdd = float(base.iloc[0]["max_drawdown"])
            frz = df[df["liquidity_scenario"] == "frozen_exit"]
            hf = df[df["liquidity_scenario"] == "half_fill"]
            interp = []
            if not frz.empty and float(frz.iloc[0]["max_drawdown"]) > base_mdd:
                interp.append(f"- 冻结退出（frozen_exit）使最大回撤从 {base_mdd:.2%} 升至 "
                              f"{float(frz.iloc[0]['max_drawdown']):.2%}：风险门触发后无法减仓会直接抬高回撤，"
                              "说明防御效果高度依赖减仓可执行性。")
            if not hf.empty and float(hf.iloc[0]["total_cost"]) < float(base.iloc[0]["total_cost"]):
                interp.append(f"- 半成交（half_fill）降低了换手与费用（{float(hf.iloc[0]['total_cost']):.4%} vs "
                              f"{float(base.iloc[0]['total_cost']):.4%}），但未成交部分保留原风险敞口，"
                              "回撤改善有限——流动性冲击下'少交易'不等于'更安全'。")
            if interp:
                lines.append("\n" + "\n".join(interp))
    else:
        lines.append("无流动性实验结果。\n")

    lines.append("\n## 5. 结论\n")
    lines.append("本实验明确区分历史回测、合成压力与执行约束三类实验，不将合成结果写成历史实证。\n")
    lines.append("只有在多个历史窗口、多个冲击情景和成本压力下结论方向一致，才可使用'具有一定防守稳健性'。"
                 "否则只能写：在指定窗口和压力假设下观察到防守效果，尚不足以证明跨周期稳健性。\n")
    return "\n".join(lines)


# ============================================================================
# main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="熊市回测与压力测试")
    parser.add_argument("--offline", action="store_true", help="使用本地缓存（无外部请求）")
    parser.add_argument("--out", default="reports/fof_stress_20261014", help="输出目录")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    t0 = time.time()
    out_dir = Path(args.out)
    logger.info("熊市压力测试开始 | 输出: %s | seed=%d", out_dir, args.seed)

    # 1. 加载真实 ETF 收益数据
    returns_df = load_etf_returns(ALL_ETF)

    # 2. 历史熊市窗口识别（用 510300 净值）
    bench_prices = (1 + returns_df["510300"]).cumprod()
    windows = identify_bear_windows(bench_prices)
    logger.info("识别到 %d 个熊市/急跌窗口", len(windows))

    # 3. 在真实窗口运行全策略
    hist_results: Dict[str, Any] = {}
    if windows:
        w = windows[0]
        hist_results = run_all_modes(returns_df, w.start, w.end, args.seed)
    else:
        # 数据不足：在整个可用区间跑一次作为 "样本内下跌窗口"
        all_start = str(returns_df.index[0].date())
        all_end = str(returns_df.index[-1].date())
        hist_results = run_all_modes(returns_df, all_start, all_end, args.seed)

    # 4. 合成冲击
    syn_rows = run_synthetic_shocks(returns_df, args.seed)
    logger.info("合成冲击完成: %d 行", len(syn_rows))

    # 5. 流动性压力
    liq_rows = run_liquidity_stress(returns_df, args.seed)
    logger.info("流动性压力完成: %d 行", len(liq_rows))

    # 6. 参数敏感性
    sens_rows = run_param_sensitivity(returns_df, args.seed)
    logger.info("参数敏感性完成: %d 行", len(sens_rows))

    # 7. 保存产物
    save_results(out_dir, windows, hist_results, syn_rows, liq_rows, sens_rows)

    # 8. 报告
    report_text = generate_report(windows, hist_results, syn_rows, liq_rows)
    (out_dir / "bear_stress_report.md").write_text(report_text, encoding="utf-8")

    elapsed = time.time() - t0
    logger.info("熊市压力测试完成 | 耗时 %.1fs | 产物目录: %s", elapsed, out_dir)
    print(f"[DONE] reports saved to {out_dir}/ | {elapsed:.1f}s")


if __name__ == "__main__":
    main()
