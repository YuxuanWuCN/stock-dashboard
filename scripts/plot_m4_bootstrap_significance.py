# -*- coding: utf-8 -*-
"""scripts/plot_m4_bootstrap_significance.py —— M4 走步评测学术级 Bootstrap 显著性图集。

只读消费某个 ``run_id`` 的评测产物（``reports/tables/pca_nale_integration/<run_id>/``），
用与评测器**完全相同**的区块 bootstrap 算法与种子重放抽样（逐次复算均值分布），
产出成套出版级图形（300 dpi PNG + 同名 PDF）：

  fig1_ic_forest          主变体均值 IC 的区块 bootstrap 95% CI 森林图（10/40 交易日块）
  fig2_bootstrap_dist     主变体 bootstrap 均值抽样分布直方图 + CI 边界（块长 10 与 40）
  fig3_ic_timeseries      逐信号日累计 IC（时序稳定性诊断）
  fig4_portfolio_ci       多空组合每期净收益（主成本档）的 95% CI 森林图
  fig5_holm_heatmap       Holm 校正后 p 值热图（网络 × 变体，逐视界）

纪律：
1. 图内任何轴标签/标题/图例**不得出现年化字样**（复用评测器的守卫词表）；
2. 抽样分布由 ``ic_series.csv`` 确定性重放（同一 seed、同一 rng 消耗顺序），并以
   ``bootstrap.csv`` 中的 point_mean/ci_low/ci_high 做逐项一致性断言——重放与评测器
   不一致即拒绝出图（防止"图上的分布"与"表里的区间"脱节）；
3. 不修任何评测数字：图是表的视觉化，冲突时以表为准并报错；
4. 图形为确定性重放视图，可重复生成（不占用评测器 run_id 目录的"拒绝覆盖"语义）。

用法::

    python scripts/plot_m4_bootstrap_significance.py --run-id m4-full-run-C-20260919
    python scripts/plot_m4_bootstrap_significance.py --run-id ... --variants W-corr|alpha_0.75,...
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_pca_nale_integration import (  # noqa: E402
    DEFAULT_BOOTSTRAP_REPS,
    DEFAULT_SEED,
    FORBIDDEN_FIELD_TOKENS,
    trading_days_to_signal_blocks,
)

TABLE_ROOT = ROOT / "reports/tables/pca_nale_integration"
FIGURE_ROOT = ROOT / "reports/figures/pca_nale_integration"

#: 图集默认重点展示的变体（其余变体仍在数据表中，不因图省略而"消失"）。
DEFAULT_FOCUS_VARIANTS: tuple[str, ...] = (
    "alpha_0.00", "b0_alpha_0.40", "alpha_0.05", "alpha_0.20", "alpha_0.60", "alpha_0.75",
    "gate_V1", "gate_V2", "gate_V3", "placebo_node_permutation",
)

#: 全图统一风格（出版级、色盲友好）。
STYLE = {
    "colors": {
        "alpha_0.00": "#7f7f7f",
        "b0_alpha_0.40": "#1f77b4",
        "alpha_0.05": "#8c564b",
        "alpha_0.20": "#9467bd",
        "alpha_0.60": "#2ca02c",
        "alpha_0.75": "#d62728",
        "gate_V1": "#ff7f0e",
        "gate_V2": "#e377c2",
        "gate_V3": "#17becf",
        "placebo_node_permutation": "#bcbd22",
    },
    "grid_alpha": 0.35,
    "dpi": 300,
}


class PlotError(ValueError):
    """图集输入或一致性断言失败（fail-closed）。"""


# ---------------------------------------------------------------------------
# 与评测器逐位一致的 bootstrap 重放
# ---------------------------------------------------------------------------

def replay_block_bootstrap_means(
    values: Sequence[float],
    *,
    block_length: int,
    reps: int = DEFAULT_BOOTSTRAP_REPS,
    seed: int = DEFAULT_SEED,
) -> np.ndarray:
    """按评测器 ``block_bootstrap_interval`` 的同一算法与 rng 消耗顺序重放抽样，
    返回每次重采样的均值数组（可与评测器写出的 ci_low/ci_high 逐位核对）。"""
    series = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if series.size == 0:
        raise PlotError("重放输入为空")
    block = min(int(block_length), series.size)
    n_blocks = int(np.ceil(series.size / block))
    rng = np.random.default_rng(int(seed))
    starts = rng.integers(0, series.size, size=(int(reps), n_blocks))
    offsets = np.arange(block)[None, :]
    sample = np.empty((int(reps), n_blocks * block), dtype=float)
    for column in range(n_blocks):
        indices = (starts[:, column][:, None] + offsets) % series.size
        sample[:, column * block : (column + 1) * block] = series[indices]
    return sample.mean(axis=1)


def _assert_consistent(
    means: np.ndarray,
    raw_series: np.ndarray,
    reference: pd.Series,
    *,
    label: str,
) -> None:
    """重放分布与评测器 bootstrap.csv 的区间/点估计必须一致，否则拒绝出图。

    逐位恒等式（不是统计近似）：
    * ``reference["point_mean"]`` == 原始有限值序列均值（评测器定义即如此）；
    * 重放 means 的 2.5%/97.5% 分位数 == ``ci_low``/``ci_high``（同算法同种子 ⇒ 同抽样）。
    """
    series_mean = float(np.asarray(raw_series, dtype=float).mean())
    if not np.isclose(series_mean, float(reference["point_mean"]), rtol=1e-12, atol=0.0):
        raise PlotError(
            f"{label}: 序列均值 {series_mean:.17g} ≠ 表内 point_mean {reference['point_mean']:.17g}"
        )
    low, high = np.quantile(means, 0.025), np.quantile(means, 0.975)
    for name, replayed, declared in (
        ("ci_low", low, reference["ci_low"]),
        ("ci_high", high, reference["ci_high"]),
    ):
        if not np.isclose(float(replayed), float(declared), rtol=1e-12, atol=1e-15):
            raise PlotError(f"{label}: 重放 {name}={replayed:.17g} ≠ 表内 {declared:.17g}（图与表脱节，拒绝出图）")


def _guard_text(text: str) -> str:
    for token in FORBIDDEN_FIELD_TOKENS:
        if token in str(text).lower():
            raise PlotError(f"图形文本含年化字样：{text!r}")
    return text


# ---------------------------------------------------------------------------
# 载入
# ---------------------------------------------------------------------------

def load_run_tables(run_id: str) -> dict[str, object]:
    base = TABLE_ROOT / run_id
    required = ["bootstrap.csv", "ic_series.csv", "metrics_by_variant.csv", "portfolio.csv", "manifest.json"]
    missing = [name for name in required if not (base / name).exists()]
    if missing:
        raise PlotError(f"{base} 缺少产物：{missing}")
    return {
        "bootstrap": pd.read_csv(base / "bootstrap.csv"),
        "ic_series": pd.read_csv(base / "ic_series.csv"),
        "metrics": pd.read_csv(base / "metrics_by_variant.csv"),
        "portfolio": pd.read_csv(base / "portfolio.csv"),
        "manifest": json.loads((base / "manifest.json").read_text(encoding="utf-8")),
        "base": base,
    }


def _variant_label(network: str, variant: str) -> str:
    return f"{network}|{variant}"


def _import_pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


# ---------------------------------------------------------------------------
# 图 1：IC 森林图
# ---------------------------------------------------------------------------

def plot_ic_forest(bootstrap: pd.DataFrame, focus: Sequence[str], out: Path) -> list[Path]:
    plt = _import_pyplot()
    outputs: list[Path] = []
    for horizon in sorted(bootstrap["horizon"].unique()):
        subset = bootstrap[
            (bootstrap["horizon"] == horizon)
            & (bootstrap["metric"] == "pearson_ic")
            & (~bootstrap["is_sensitivity"])
            & (bootstrap["block_trading_days"] == 10)
            & (bootstrap["variant"].isin(focus))
        ]
        if subset.empty:
            continue
        fig, ax = plt.subplots(figsize=(8.4, 0.42 * len(subset) + 1.6))
        y, yticks, ylabels = 0, [], []
        for network in sorted(subset["network"].unique()):
            block = subset[subset["network"] == network].sort_values("point_mean")
            for _, row in block.iterrows():
                color = STYLE["colors"].get(row["variant"], "#4c72b0")
                ax.hlines(y, row["ci_low"], row["ci_high"], color=color, linewidth=2.4, alpha=0.9)
                ax.plot(row["point_mean"], y, "o", color=color, markersize=4.2)
                yticks.append(y)
                ylabels.append(_variant_label(network, row["variant"]))
                y += 1
            y += 0.6
        ax.set_yticks(yticks)
        ax.set_yticklabels(ylabels, fontsize=7)
        ax.axvline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.8)
        ax.set_xlabel(_guard_text("cross-sectional mean IC, block-bootstrap 95% CI (per holding period)"))
        ax.set_title(_guard_text(
            f"M4 walk-forward IC significance — horizon {horizon}d "
            f"(seed {DEFAULT_SEED}, {DEFAULT_BOOTSTRAP_REPS} reps, 10-trading-day blocks)"
        ))
        ax.grid(alpha=STYLE["grid_alpha"], axis="x")
        fig.tight_layout()
        for suffix in ("png", "pdf"):
            path = out / f"fig1_ic_forest_h{horizon}.{suffix}"
            fig.savefig(path, dpi=STYLE["dpi"])
            outputs.append(path)
        plt.close(fig)
    return outputs


# ---------------------------------------------------------------------------
# 图 2：bootstrap 抽样分布
# ---------------------------------------------------------------------------

def plot_bootstrap_distributions(tables: Mapping[str, object], focus: Sequence[str], out: Path) -> list[Path]:
    plt = _import_pyplot()
    bootstrap: pd.DataFrame = tables["bootstrap"]  # type: ignore[assignment]
    ic_series: pd.DataFrame = tables["ic_series"]  # type: ignore[assignment]
    manifest: dict = tables["manifest"]  # type: ignore[assignment]
    outputs: list[Path] = []

    for horizon in sorted(bootstrap["horizon"].unique()):
        selected = bootstrap[
            (bootstrap["horizon"] == horizon)
            & (bootstrap["metric"] == "pearson_ic")
            & (~bootstrap["is_sensitivity"])
            & (bootstrap["variant"].isin(focus))
        ]
        if selected.empty:
            continue
        networks = sorted(selected["network"].unique())
        block_lengths = sorted(selected["block_trading_days"].unique())
        fig, axes = plt.subplots(
            len(networks), len(block_lengths),
            figsize=(4.4 * len(block_lengths), 3.0 * len(networks)), squeeze=False,
        )
        for row_index, network in enumerate(networks):
            for col_index, block_days in enumerate(block_lengths):
                ax = axes[row_index][col_index]
                rows = selected[(selected["network"] == network) & (selected["block_trading_days"] == block_days)]
                blocks = trading_days_to_signal_blocks(block_days, int(manifest["config"]["signal_step"]))
                for _, row in rows.sort_values("point_mean").iterrows():
                    values = ic_series[
                        (ic_series["network"] == row["network"])
                        & (ic_series["variant"] == row["variant"])
                        & (ic_series["horizon"] == horizon)
                    ]["pearson_ic"].to_numpy(dtype=float)
                    finite = values[np.isfinite(values)]
                    if finite.size == 0:
                        continue
                    means = replay_block_bootstrap_means(finite.tolist(), block_length=blocks)
                    _assert_consistent(means, finite, row,
                                       label=f"{network}|{row['variant']}|h{horizon}|block{block_days}")
                    color = STYLE["colors"].get(row["variant"], "#4c72b0")
                    ax.hist(means, bins=60, alpha=0.45, color=color, density=True)
                    ax.axvline(row["ci_low"], color=color, linestyle=":", linewidth=1.0)
                    ax.axvline(row["ci_high"], color=color, linestyle=":", linewidth=1.0)
                ax.axvline(0.0, color="black", linewidth=0.9)
                ax.set_title(_guard_text(f"{network} — {block_days}-trading-day blocks"), fontsize=10)
                ax.grid(alpha=STYLE["grid_alpha"])
                if row_index == len(networks) - 1:
                    ax.set_xlabel(_guard_text("bootstrap mean IC (per holding period)"))
        handles = [
            plt.Line2D([0], [0], color=STYLE["colors"].get(variant, "#4c72b0"), lw=4, label=variant)
            for variant in focus
        ]
        fig.legend(handles=handles, loc="upper center", ncol=min(4, len(handles)), fontsize=8,
                   bbox_to_anchor=(0.5, 1.02))
        fig.suptitle(_guard_text(f"Block-bootstrap sampling distribution of mean IC — horizon {horizon}d"),
                     fontsize=12)
        fig.tight_layout()
        for suffix in ("png", "pdf"):
            path = out / f"fig2_bootstrap_dist_h{horizon}.{suffix}"
            fig.savefig(path, dpi=STYLE["dpi"], bbox_inches="tight")
            outputs.append(path)
        plt.close(fig)
    return outputs


# ---------------------------------------------------------------------------
# 图 3：累计 IC 时序
# ---------------------------------------------------------------------------

def plot_ic_timeseries(ic_series: pd.DataFrame, focus: Sequence[str], out: Path) -> list[Path]:
    plt = _import_pyplot()
    outputs: list[Path] = []
    for horizon in sorted(ic_series["horizon"].unique()):
        subset = ic_series[(ic_series["horizon"] == horizon) & (ic_series["variant"].isin(focus))]
        if subset.empty:
            continue
        networks = sorted(subset["network"].unique())
        fig, axes = plt.subplots(1, len(networks), figsize=(6.0 * len(networks), 3.8), squeeze=False)
        for index, network in enumerate(networks):
            ax = axes[0][index]
            block = subset[subset["network"] == network]
            for variant, group in block.groupby("variant"):
                ordered = group.sort_values("signal_date")
                dates = pd.to_datetime(ordered["signal_date"])
                values = ordered["pearson_ic"].astype(float)
                ax.plot(dates, values.cumsum(), label=variant, linewidth=1.4,
                        color=STYLE["colors"].get(variant))
            ax.axhline(0.0, color="black", linewidth=0.8)
            ax.set_title(_guard_text(f"{network} — cumulative daily IC (h={horizon}d)"), fontsize=10)
            ax.set_ylabel("cumulative IC (per holding period)")
            ax.grid(alpha=STYLE["grid_alpha"])
            ax.tick_params(axis="x", rotation=30, labelsize=7)
        handles, labels = axes[0][0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="upper center", ncol=min(4, max(1, len(labels))), fontsize=8,
                   bbox_to_anchor=(0.5, 1.02))
        fig.suptitle(_guard_text(f"Daily IC time series — horizon {horizon}d"), fontsize=12)
        fig.tight_layout()
        for suffix in ("png", "pdf"):
            path = out / f"fig3_ic_timeseries_h{horizon}.{suffix}"
            fig.savefig(path, dpi=STYLE["dpi"], bbox_inches="tight")
            outputs.append(path)
        plt.close(fig)
    return outputs


# ---------------------------------------------------------------------------
# 图 4：组合每期净收益 CI 森林图
# ---------------------------------------------------------------------------

def plot_portfolio_ci(tables: Mapping[str, object], focus: Sequence[str], out: Path) -> list[Path]:
    plt = _import_pyplot()
    portfolio: pd.DataFrame = tables["portfolio"]  # type: ignore[assignment]
    manifest: dict = tables["manifest"]  # type: ignore[assignment]
    cost = float(manifest["config"]["cost_bps"])
    outputs: list[Path] = []
    for horizon in sorted(portfolio["horizon"].unique()):
        selected = portfolio[
            (portfolio["horizon"] == horizon)
            & (portfolio["metric"] == "net_return")
            & (portfolio["cost_bps"] == cost)
            & (portfolio["variant"].isin(focus))
        ]
        if selected.empty:
            continue
        fig, ax = plt.subplots(figsize=(8.4, 0.40 * len(selected) + 1.6))
        y, yticks, ylabels = 0, [], []
        for network in sorted(selected["network"].unique()):
            block = selected[selected["network"] == network].sort_values("point_mean")
            for _, row in block.iterrows():
                color = STYLE["colors"].get(row["variant"], "#4c72b0")
                ax.hlines(y, row["ci_low"], row["ci_high"], color=color, linewidth=2.4, alpha=0.9)
                ax.plot(row["point_mean"], y, "o", color=color, markersize=4.2)
                yticks.append(y)
                ylabels.append(_variant_label(network, row["variant"]))
                y += 1
            y += 0.6
        ax.set_yticks(yticks)
        ax.set_yticklabels(ylabels, fontsize=7)
        ax.axvline(0.0, color="black", linewidth=0.8, linestyle="--")
        ax.set_xlabel(_guard_text(
            f"net per-period long-short return (block-bootstrap 95% CI, {cost:.0f} bps two-sided)"
        ))
        ax.set_title(_guard_text(f"Long-short portfolio significance — horizon {horizon}d holding"))
        ax.grid(alpha=STYLE["grid_alpha"], axis="x")
        fig.tight_layout()
        for suffix in ("png", "pdf"):
            path = out / f"fig4_portfolio_ci_h{horizon}.{suffix}"
            fig.savefig(path, dpi=STYLE["dpi"])
            outputs.append(path)
        plt.close(fig)
    return outputs


# ---------------------------------------------------------------------------
# 图 5：Holm 校正后 p 值热图
# ---------------------------------------------------------------------------

def plot_holm_heatmap(metrics: pd.DataFrame, out: Path) -> list[Path]:
    plt = _import_pyplot()
    outputs: list[Path] = []
    for horizon in sorted(metrics["horizon"].unique()):
        subset = metrics[metrics["horizon"] == horizon]
        networks = sorted(subset["network"].unique())
        variants = sorted(subset["variant"].unique(), key=lambda v: (v != "b0_alpha_0.40", v))
        matrix = np.full((len(variants), len(networks)), np.nan)
        for i, variant in enumerate(variants):
            for j, network in enumerate(networks):
                row = subset[(subset["variant"] == variant) & (subset["network"] == network)]
                if not row.empty:
                    matrix[i, j] = float(row["holm_adjusted_p"].iloc[0])
        fig, ax = plt.subplots(figsize=(1.9 * len(networks) + 2.4, 0.30 * len(variants) + 2.0))
        image = ax.imshow(matrix, cmap="RdYlGn_r", vmin=0.0, vmax=1.0, aspect="auto")
        ax.set_xticks(range(len(networks)), networks)
        ax.set_yticks(range(len(variants)), variants, fontsize=7)
        for i in range(len(variants)):
            for j in range(len(networks)):
                if np.isfinite(matrix[i, j]):
                    ax.text(j, i, f"{matrix[i, j]:.3f}", ha="center", va="center", fontsize=6)
        ax.set_title(_guard_text(f"Holm-adjusted p (two-sided, daily cross-sectional IC) — h={horizon}d"))
        fig.colorbar(image, ax=ax, shrink=0.8)
        fig.tight_layout()
        for suffix in ("png", "pdf"):
            path = out / f"fig5_holm_heatmap_h{horizon}.{suffix}"
            fig.savefig(path, dpi=STYLE["dpi"])
            outputs.append(path)
        plt.close(fig)
    return outputs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4 评测 Bootstrap 显著性图集（只读评测产物）")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--variants", default=",".join(DEFAULT_FOCUS_VARIANTS),
                        help="重点展示的变体（逗号分隔；全部变体仍以数据表为准）")
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.run_id):
        raise PlotError(f"非法 run_id：{args.run_id!r}")
    focus = [part.strip() for part in args.variants.split(",") if part.strip()]
    tables = load_run_tables(args.run_id)
    out_dir = FIGURE_ROOT / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    outputs += plot_ic_forest(tables["bootstrap"], focus, out_dir)  # type: ignore[arg-type]
    outputs += plot_bootstrap_distributions(tables, focus, out_dir)
    outputs += plot_ic_timeseries(tables["ic_series"], focus, out_dir)  # type: ignore[arg-type]
    outputs += plot_portfolio_ci(tables, focus, out_dir)
    outputs += plot_holm_heatmap(tables["metrics"], out_dir)  # type: ignore[arg-type]
    if not outputs:
        raise PlotError("没有产出任何图形（检查变体名与视界）")
    print(json.dumps({"run_id": args.run_id, "figures": [str(path) for path in outputs]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
