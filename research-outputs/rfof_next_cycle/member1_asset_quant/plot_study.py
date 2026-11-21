
"""Publication figures for the verified offline study."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
from matplotlib import font_manager
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtest import drawdown

BLUE = "#174d78"
OCHRE = "#a0491c"
TEAL = "#257771"
GREY = "#616a73"
PURPLE = "#6a5688"
COLORS = [GREY, TEAL, PURPLE, BLUE, OCHRE]
FONTS = ("Noto Sans CJK SC", "Microsoft YaHei", "SimHei", "PingFang SC", "WenQuanYi Zen Hei")


def _export(fig, directory, name):
    fig.savefig(directory / f"{name}.png", dpi=300, facecolor="white")
    plt.close(fig)


def _calendar(ax, year=2):
    ax.xaxis.set_major_locator(mdates.YearLocator(year))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def create_figures(
    directory: Path, defense: pd.DataFrame, tdf_long: pd.DataFrame, tdf_recent: pd.DataFrame,
    tax: pd.DataFrame, age: pd.DataFrame,
) -> None:
    fonts = {entry.name for entry in font_manager.fontManager.ttflist}
    chinese = next((name for name in FONTS if name in fonts), None)
    if not chinese:
        raise RuntimeError("Install a Chinese font from plot_study.FONTS to export figures")
    directory.mkdir(parents=True)
    style = {
        "font.family": chinese, "font.size": 10, "axes.titlesize": 12,
        "axes.labelcolor": "#233442", "axes.titlecolor": "#192b39", "axes.unicode_minus": False,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
        "axes.axisbelow": True, "grid.alpha": .30, "grid.linestyle": ":",
        "legend.frameon": False, "lines.linewidth": 1.5,
    }
    with plt.rc_context(style):
        fig, axes = plt.subplots(2, 1, figsize=(10, 6.6), sharex=True, layout="constrained")
        for i, (method, daily) in enumerate(defense.items()):
            line = ["--", ":", "-.", "-", "-"][i]
            axes[0].plot((1 + daily).cumprod(), label=method, color=COLORS[i], linestyle=line)
            axes[1].plot(100 * drawdown(daily), color=COLORS[i], linestyle=line)
        axes[0].set(title="防守层走步回测（双边摩擦 30 bps）", ylabel="累计净值（初始 1）")
        axes[1].set(xlabel="交易日", ylabel="回撤（%）")
        axes[0].legend(ncols=5, loc="upper left")
        _calendar(axes[1])
        _export(fig, directory, "defense_nav_drawdown")

        fig, axes = plt.subplots(2, 1, figsize=(10, 7.5), layout="constrained")
        for ax, frame, title, strategies in (
            (axes[0], tdf_long, "防守层与 Y 份额的完整重合段", ("A0", "A3", "A4")),
            (axes[1], tdf_recent, "含真实股票腿的生命周期账本与 Y 份额", ("RFOF_A0_B2", "RFOF_A3_B2", "RFOF_A4_B2")),
        ):
            names = {"017247": "华夏 2040Y", "017258": "建信 2040Y", "017377": "南方 2040Y"}
            for name, color, marker in zip(names, (GREY, TEAL, PURPLE), (":", "--", "-.")):
                ax.plot((1 + frame[name]).cumprod(), label=names[name], color=color, linestyle=marker)
            for name, color, line in zip(strategies, ("#17242d", BLUE, OCHRE), ("--", "-", "-")):
                ax.plot((1 + frame[name]).cumprod(), label=name.replace("RFOF_", "R-FOF ").replace("_", "+"),
                        color=color, linestyle=line)
            ax.set(title=title, ylabel="累计净值（初始 1）")
            ax.legend(ncols=3, loc="best")
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        axes[1].set_xlabel("交易日（各面板内同区间）")
        _export(fig, directory, "tdf_matched_nav")

        demo = tax.loc[tax["net_nominal_return_assumption_pct"].eq(3)]
        fig, ax = plt.subplots(figsize=(7.2, 4.2), layout="constrained")
        position = np.arange(len(demo))
        ax.bar(position - .17, demo["outside_net_replacement_pct"], .34, color=GREY, label="普通账户")
        ax.bar(position + .17, demo["eet_net_replacement_pct"], .34, color=BLUE, label="个人养老金账户")
        ax.set_xticks(position, [f"{rate}%" for rate in demo["marginal_tax_pct"]])
        ax.set(title="同等工作期净支出下的首年净替代率", xlabel="缴费期边际税率", ylabel="净替代率（%）")
        ax.legend()
        _export(fig, directory, "eet_replacement")

        fig, axes = plt.subplots(2, 1, figsize=(8.4, 6.1), sharex=True, layout="constrained")
        for ax, scenario, title in (
            (axes[0], "63d_blocks", "历史收益块情景"),
            (axes[1], "lower_drift_3pct", "收益漂移下调至年化 3% 的压力情景"),
        ):
            rows = age.loc[age["scenario"].eq(scenario)]
            for policy, name, color, line in (
                ("fixed_4_8", "固定 4.8% 支取", GREY, "--"),
                ("dynamic_guardrail", "动态护栏", BLUE, "-"),
            ):
                subset = rows.loc[rows["policy"].eq(policy)]
                ax.plot(subset["age"], subset["ruin_by_age_pct"], label=name, color=color, linestyle=line)
            ax.axvline(78, color=OCHRE, linestyle=":", label="78 岁设医疗专户")
            ax.set(title=title, ylabel="累计耗尽率（%）", ylim=(-2, 102))
        axes[0].legend(ncols=3, loc="upper left")
        axes[1].set(xlabel="年龄（岁）", xticks=[60, 65, 70, 75, 78, 80, 85])
        _export(fig, directory, "retirement_ruin_by_age")
