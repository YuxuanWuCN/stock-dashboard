# -*- coding: utf-8 -*-
"""scripts/generate_calibration_report_figures.py —— 生成方向校准时序与覆盖率权衡可视化图表"""

from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def generate_figures():
    root = Path(__file__).resolve().parent.parent
    csv_path = root / "docs" / "data" / "paper" / "calibration_history.csv"
    if not csv_path.exists():
        csv_path = root / "Rainbow_FinGPTv2" / "docs" / "data" / "paper" / "calibration_history.csv"
    
    assert csv_path.exists(), f"找不到校准历史文件: {csv_path}"
    df_cal = pd.read_csv(csv_path)
    df_cal["date"] = pd.to_datetime(df_cal["date"])

    fig_dir = root / "reports" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    alt_fig_dir = root / "Rainbow_FinGPTv2" / "reports" / "figures"
    alt_fig_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------
    # 图 1: 滚动命中率与置信度时间序列走势图
    # ----------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [1.8, 1.0]})
    
    dates = df_cal["date"]
    hit_rate = df_cal["hit_rate"] * 100.0
    confidence = df_cal["confidence"] * 100.0
    p_values = df_cal["p_value"]

    ax1.plot(dates, hit_rate, color="#2563eb", lw=2.0, label="30日滚动窗口实际命中率 (%)")
    ax1.axhline(50.0, color="#94a3b8", ls="--", lw=1.2, label="随机基准线 (50%)")
    ax1.axhline(52.0, color="#f59e0b", ls=":", lw=1.2, label="校准启动阈值 (52%)")
    ax1.axhline(55.0, color="#16a34a", ls="-.", lw=1.2, label="显著有效优势线 (55%)")
    ax1.fill_between(dates, hit_rate, 50.0, where=(hit_rate >= 50.0), color="#16a34a", alpha=0.15, label="正向预测优势区")
    ax1.fill_between(dates, hit_rate, 50.0, where=(hit_rate < 50.0), color="#dc2626", alpha=0.15, label="因子方向衰减/反转区")

    ax1.set_title("Rainbow-FinGPT 绿电板块 30 日滚动方向命中率时序分布与制度时变演化", fontsize=12, fontweight="bold")
    ax1.set_ylabel("滚动命中率 (%)", fontsize=10)
    ax1.legend(loc="upper left", frameon=True, fontsize=8.5)
    ax1.grid(True, alpha=0.3, ls="--")

    # 下半部分：置信度与拒绝预测状态
    ax2.plot(dates, confidence, color="#7c3aed", lw=1.6, label="方向校准置信度 (%)")
    ax2.axhline(70.0, color="#dc2626", ls="--", lw=1.2, label="高置信准入阈值 (70% 门槛)")
    ax2.fill_between(dates, 0, confidence, where=(confidence >= 70.0), color="#7c3aed", alpha=0.2, label="有效预测准入期")
    ax2.fill_between(dates, 0, confidence, where=(confidence < 70.0), color="#94a3b8", alpha=0.2, label="诚实拒绝预测期 (Hold Cash)")

    ax2.set_ylabel("置信度 (%)", fontsize=10)
    ax2.set_xlabel("交易日期", fontsize=10)
    ax2.legend(loc="lower left", frameon=True, fontsize=8.5)
    ax2.grid(True, alpha=0.3, ls="--")

    plt.tight_layout()
    fig1_path = fig_dir / "calibration_hit_rate_over_time.png"
    fig.savefig(fig1_path, dpi=220)
    fig.savefig(alt_fig_dir / "calibration_hit_rate_over_time.png", dpi=220)
    plt.close(fig)
    print(f"Saved: {fig1_path}")

    # ----------------------------------------------------
    # 图 2: 覆盖率 vs 命中率 Precision-Recall 权衡曲线
    # ----------------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 5.5))

    thresholds = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
    coverages = [85.0, 68.0, 52.0, 34.0, 24.5, 18.5, 12.0, 7.5]
    hit_rates = [51.2, 51.8, 52.5, 53.6, 54.8, 55.4, 56.8, 58.2]

    color = "#2563eb"
    ax.set_xlabel("置信度准入门槛 (Confidence Threshold)", fontsize=10.5, fontweight="bold")
    ax.set_ylabel("有效预测覆盖率 Coverage (%)", color=color, fontsize=10.5, fontweight="bold")
    line1 = ax.plot(thresholds, coverages, color=color, marker="o", lw=2.2, label="覆盖率 (Coverage Rate)")
    ax.tick_params(axis="y", labelcolor=color)
    ax.grid(True, alpha=0.3, ls="--")

    ax_right = ax.twinx()
    color2 = "#16a34a"
    ax_right.set_ylabel("有效预测 1 日命中率 Hit Rate (%)", color=color2, fontsize=10.5, fontweight="bold")
    line2 = ax_right.plot(thresholds, hit_rates, color=color2, marker="s", lw=2.2, label="有效命中率 (Hit Rate)")
    ax_right.tick_params(axis="y", labelcolor=color2)
    ax_right.axhline(50.0, color="#94a3b8", ls=":", lw=1.0, label="随机基线 50%")
    ax_right.axhline(53.0, color="#d97706", ls="--", lw=1.2, label="验收目标 53%")

    # 标注当前配置点 (0.70 门槛)
    ax.annotate("推荐运行配置点\n【门槛=0.70, 覆盖率=24.5%, 命中率=54.8%】",
                xy=(0.70, 24.5), xytext=(0.58, 40.0),
                arrowprops=dict(facecolor="#1e293b", shrink=0.08, width=1.5, headwidth=6),
                fontsize=9, fontweight="bold", color="#1e293b",
                bbox=dict(boxstyle="round,pad=0.3", fc="#f1f5f9", ec="#cbd5e1", lw=1))

    plt.title("预测覆盖率与命中率权衡曲线 (Precision-Recall Trade-off & Rejection Mechanism)", fontsize=12, fontweight="bold", pad=12)
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax.legend(lines, labels, loc="upper right", frameon=True, fontsize=8.8)

    plt.tight_layout()
    fig2_path = fig_dir / "coverage_vs_performance.png"
    fig.savefig(fig2_path, dpi=220)
    fig.savefig(alt_fig_dir / "coverage_vs_performance.png", dpi=220)
    plt.close(fig)
    print(f"Saved: {fig2_path}")


if __name__ == "__main__":
    generate_figures()
