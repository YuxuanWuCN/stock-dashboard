"""End-to-end driver for the R-FOF Stability & Futures Realism Study (2026-11).

Executes:
1. Load clean 10-ETF qualified universe (2012-2026).
2. Walk-forward backtests for A0, A1 (Ledoit-Wolf), A2 (HRP), A3 (VolTarget).
3. Friction sensitivity (0, 15, 30 bps) & 4 historical bear market stress windows.
4. Futures Crisis-Alpha sleeve realism & sensitivity grid (B0-B4).
5. Automated 3-criterion acceptance verdict.
6. Publication-grade figures (>= 200 DPI) & CSV result exports.
7. Executive summary markdown report.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Set Chinese font fallback for Windows publication charts
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from stability_futures import compute_futures_sensitivity_grid, compute_futures_variant
from stability_universe import QUALIFIED_CODES, load_universe
from stability_verdict import judge_method_results
from stability_walkforward import (
    BEAR_WINDOWS,
    compute_drawdown_series,
    compute_metrics,
    compute_window_metrics,
    run_walkforward,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = PROJECT_ROOT / "reports" / "stability_20261108"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run R-FOF Stability & Futures Study")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory to save report and artifacts",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite outputs if output directory already exists",
    )
    return parser.parse_args()


def plot_charts(
    walkforward_dict: dict[str, dict[str, Any]],
    stress_results_df: pd.DataFrame,
    futures_df: pd.DataFrame,
    fig_dir: Path,
) -> list[Path]:
    """Generate publication-ready 300 DPI comparative charts."""
    fig_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    # Chart 1: Cumulative Net Value & Underwater Drawdown (A0 vs A1 vs A2 vs A3)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True, gridspec_kw={"height_ratios": [2.2, 1.2]})

    colors = {
        "A0": "#7F8C8D",  # Gray (Static Baseline)
        "A1": "#C0392B",  # Crimson (Ledoit-Wolf MinVar)
        "A2": "#2980B9",  # Strong Blue (HRP)
        "A3": "#27AE60",  # Green (VolTarget 8%)
    }
    labels_zh = {
        "A0": "A0: 既有固定规则基准 (36%纯债+40%红利+24%沪深300)",
        "A1": "A1: Ledoit-Wolf 协方差收缩最小方差 (Cap 40%)",
        "A2": "A2: 层次风险平价 HRP (López de Prado 2016)",
        "A3": "A3: 无杠杆波动率目标动态缩放 (目标年化 8%)",
    }

    for m_id, res in walkforward_dict.items():
        nav = res["nav"]
        dd = compute_drawdown_series(res["daily_net_ret"])
        c = colors.get(m_id, "#333333")
        lbl = labels_zh.get(m_id, m_id)

        ax1.plot(nav.index, nav.values, label=lbl, color=c, lw=1.6)
        ax2.plot(dd.index, dd.values, label=m_id, color=c, lw=1.2)

    ax1.set_title("R-FOF 防守层长周期滚动前向回测对比 (2015-2026 样本外，15bps换手摩擦)", fontsize=13, pad=10, fontweight="bold")
    ax1.set_ylabel("累计净值 (基准=1.0)", fontsize=11)
    ax1.grid(True, linestyle="--", alpha=0.4)
    ax1.legend(loc="upper left", frameon=True, fontsize=9.5)

    ax2.set_title("水下最大回撤分布 (Underwater Drawdown %)", fontsize=11, pad=6)
    ax2.set_ylabel("回撤百分比 (%)", fontsize=10)
    ax2.set_xlabel("交易日期", fontsize=11)
    ax2.grid(True, linestyle="--", alpha=0.4)

    plt.tight_layout()
    chart1_path = fig_dir / "fig_defense_nav_and_drawdown.png"
    plt.savefig(chart1_path, dpi=300)
    plt.close(fig)
    generated.append(chart1_path)

    # Chart 2: 4 Historical Bear Market Stress Windows Comparison (Bar Chart)
    bear_names = ["Bear2015", "Bear2018", "Bear2022", "Bear2026"]
    bear_labels = ["2015 杠杆崩塌\n(2015.06-2016.02)", "2018 贸易紧缩\n(2018.01-2018.12)", "2022 核心阴跌\n(2021.12-2022.10)", "2026 真实深调\n(2025.09-2026.10)"]

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(bear_names))
    width = 0.20

    m_list = ["A0", "A1", "A2", "A3"]
    for i, m_id in enumerate(m_list):
        sub = stress_results_df[(stress_results_df["method"] == m_id) & (stress_results_df["param_id"] == "cost_15bps")]
        sub_by_w = sub.set_index("window")
        dds = [abs(float(sub_by_w.loc[w, "max_dd_pct"])) if w in sub_by_w.index else 0.0 for w in bear_names]
        ax.bar(x + (i - 1.5) * width, dds, width, label=m_id, color=colors[m_id], alpha=0.9)

    ax.set_title("4 大极端历史熊市窗口各配置方案最大回撤对比 (柱高越低越抗跌)", fontsize=12, pad=10, fontweight="bold")
    ax.set_ylabel("最大回撤深度绝对值 (|MaxDD| %)", fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels(bear_labels, fontsize=9.5)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend(frameon=True, fontsize=10)

    plt.tight_layout()
    chart2_path = fig_dir / "fig_bear_windows_maxdd.png"
    plt.savefig(chart2_path, dpi=300)
    plt.close(fig)
    generated.append(chart2_path)

    # Chart 3: Futures Sleeve Sensitivity Grid
    fig, ax = plt.subplots(figsize=(9, 4.5))
    fut_vars = futures_df["variant"].values
    fut_rets = futures_df["ann_ret_pct"].values
    fut_dds = futures_df["max_dd_pct"].values

    x = np.arange(len(fut_vars))
    ax.plot(x, fut_rets, marker="o", color="#C0392B", lw=1.6, label="年化收益率 (CAGR %)")
    ax.plot(x, fut_dds, marker="s", color="#2980B9", lw=1.4, linestyle="--", label="最大回撤 (MaxDD %)")
    ax.set_title("进攻核期货对冲腿在不同展期成本与现实性假设下的抗风险表现", fontsize=11, pad=10, fontweight="bold")
    ax.set_ylabel("百分比 (%)", fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels(fut_vars, rotation=35, ha="right", fontsize=8.5)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(frameon=True, fontsize=9.5)

    plt.tight_layout()
    chart3_path = fig_dir / "fig_futures_cost_sensitivity.png"
    plt.savefig(chart3_path, dpi=300)
    plt.close(fig)
    generated.append(chart3_path)

    return generated


def main() -> None:
    args = parse_args()
    out_dir = args.out
    tables_dir = out_dir / "tables"
    fig_dir = out_dir / "figures"

    tables_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print(">>> 启动 R-FOF 防守层长周期稳定性与期货现实性实证流水线")
    print("=" * 70)

    # 1. Load clean qualified universe
    print("[1/5] 加载 10 只合格长历史 ETF 面板数据 (2012-2026)...")
    prices = load_universe(QUALIFIED_CODES)
    print(f"      合格面板覆盖: {prices.index[0].date()} 至 {prices.index[-1].date()}, 共 {len(prices)} 个真实交易日")

    # 2. Run walkforward backtests
    print("[2/5] 滚动前向回测 (3年训练窗，季度再平衡，无前视隔离)...")
    methods = ["A0", "A1", "A2", "A3"]
    friction_levels = [0.0, 15.0, 30.0]

    all_method_results: list[dict[str, Any]] = []
    canonical_walkforward: dict[str, dict[str, Any]] = {}

    for m in methods:
        for cost in friction_levels:
            cost_tag = f"cost_{int(cost)}bps"
            wf = run_walkforward(prices, method=m, train_days=756, cost_bps=cost)

            if cost == 15.0:
                canonical_walkforward[m] = wf

            # Extract full sample and bear windows metrics
            w_df = compute_window_metrics(wf["daily_net_ret"], BEAR_WINDOWS)
            for w_name, row in w_df.iterrows():
                all_method_results.append({
                    "method": m,
                    "param_id": cost_tag,
                    "window": w_name,
                    "n_days": int(row["n_days"]),
                    "ann_ret_pct": float(row["ann_ret_pct"]),
                    "ann_vol_pct": float(row["ann_vol_pct"]),
                    "max_dd_pct": float(row["max_dd_pct"]),
                    "sharpe": float(row["sharpe"]),
                    "calmar": float(row["calmar"]),
                    "turnover": float(wf["turnover"]),
                    "cost_drag_pct": float(wf["cost_drag_pct"]),
                })

    method_results_df = pd.DataFrame(all_method_results)
    out_method_csv = tables_dir / "defense_method_results.csv"
    method_results_df.to_csv(out_method_csv, index=False, encoding="utf-8-sig")
    print(f"      [OK] 防守层回测全量指标已写入: {out_method_csv.name}")

    # 3. Futures sensitivity grid
    print("[3/5] 计算期货 Crisis-Alpha 对冲腿现实性与摩擦敏感性网格...")
    futures_df = compute_futures_sensitivity_grid()
    out_futures_csv = tables_dir / "futures_sensitivity.csv"
    futures_df.to_csv(out_futures_csv, index=False, encoding="utf-8-sig")
    print(f"      [OK] 期货敏感性全景表已写入: {out_futures_csv.name}")

    # 4. Automated 3-criterion verdict evaluation
    print("[4/5] 执行预承诺的三原语自动化及格门禁裁决...")
    # Evaluate at standard 15bps cost
    std_15bps_df = method_results_df[method_results_df["param_id"] == "cost_15bps"]
    verdict_df = judge_method_results(std_15bps_df, baseline_method="A0")
    out_verdict_csv = tables_dir / "verdict.csv"
    verdict_df.to_csv(out_verdict_csv, index=False, encoding="utf-8-sig")
    print(f"      [OK] 自动化裁决表已写入: {out_verdict_csv.name}")

    # 5. Publication-ready charts
    print("[5/5] 渲染出版级 300 DPI 净值、回撤与敏感性图表...")
    gen_figs = plot_charts(canonical_walkforward, method_results_df, futures_df, fig_dir)
    for p in gen_figs:
        print(f"      [OK] 渲染完成: {p.name}")

    print("\n" + "=" * 70)
    print(">>> 自动化裁决摘要汇总 (Automated Gate Verdict Summary):")
    print("=" * 70)
    print(verdict_df[["method", "c1_windows_better", "c1_pass", "c2_full_dd_gain_pp", "c2_pass", "c3_ret_drag_pp", "c3_pass", "verdict"]].to_string(index=False))
    print("=" * 70)


if __name__ == "__main__":
    main()
