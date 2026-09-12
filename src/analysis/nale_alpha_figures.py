"""Render provenance-labeled, high-resolution NALE comparison figures."""

from __future__ import annotations

from io import BytesIO
import math

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import pandas as pd


VERSION_ORDER = ("B0", "B1", "V1", "V2", "V3", "V4", "V5")
FIGURE_DPI = 220


def render_rank_ic_figure(comparison: pd.DataFrame, *, fixture: bool) -> bytes:
    """Plot every planned version without turning missing results into zero IC."""
    required = {"version", "phase", "status", "rank_ic_mean"}
    if not required.issubset(comparison.columns):
        raise ValueError("rank IC figure needs version/phase/status/rank_ic_mean")
    if comparison["version"].duplicated().any() or set(comparison["version"]) != set(VERSION_ORDER):
        raise ValueError("rank IC figure needs each planned version once")
    phases = comparison["phase"].drop_duplicates().tolist()
    if len(phases) != 1 or phases[0] not in ("validation", "test"):
        raise ValueError("rank IC figure needs one declared validation or test phase")
    phase = phases[0]

    rows = comparison.set_index("version").loc[list(VERSION_ORDER)]
    heights: list[float] = []
    available: list[bool] = []
    for row in rows.itertuples():
        if row.status == "available":
            try:
                value = float(row.rank_ic_mean)
            except (TypeError, ValueError) as exc:
                raise ValueError("available rank IC must be finite") from exc
            if not math.isfinite(value) or abs(value) > 1:
                raise ValueError("available rank IC must be finite and within [-1, 1]")
            heights.append(value)
            available.append(True)
        elif row.status == "not_evaluable":
            if pd.notna(row.rank_ic_mean):
                raise ValueError("unavailable version cannot have rank IC")
            heights.append(0.0)
            available.append(False)
        else:
            raise ValueError("invalid rank IC figure status")

    span = min(1.0, max(0.05, max(abs(value) for value in heights) * 1.35))
    fig = Figure(figsize=(9, 4.5), dpi=FIGURE_DPI, facecolor="white")
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    colors = ["#243b53" if version == "B0" else "#7994a3" if version == "B1"
              else "#087e8b" for version in VERSION_ORDER]
    bars = ax.bar(range(len(VERSION_ORDER)), heights, color=colors, width=0.65)
    for index, (bar, value, is_available) in enumerate(zip(bars, heights, available)):
        if is_available:
            offset = span * 0.055 * (1 if value >= 0 else -1)
            ax.text(index, value + offset, f"{value:+.3f}", ha="center",
                    va="bottom" if value >= 0 else "top", fontsize=9)
        else:
            bar.set_hatch("//")
            bar.set_edgecolor("#7994a3")
            ax.text(index, span * 0.05, "N/A", ha="center", va="bottom",
                    color="#657987", fontsize=9)
    ax.axhline(0, color="#243b53", linewidth=0.8)
    ax.set_xticks(range(len(VERSION_ORDER)), VERSION_ORDER)
    ax.set_ylim(-span, span)
    ax.set_xlabel("Model version")
    ax.set_ylabel("Mean daily Spearman Rank IC (unitless)")
    ax.set_title(f"NALE Week1: {phase} Rank IC by version", loc="left")
    ax.grid(axis="y", alpha=0.18)
    ax.set_axisbelow(True)
    note = ("ENGINEERING FIXTURE - NOT MARKET EVIDENCE" if fixture
            else "Observed candidate - not approved for release")
    fig.text(0.5, 0.035, note, ha="center", va="center", fontsize=10,
             color="#a84729" if fixture else "#53616b", weight="bold")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    output = BytesIO()
    fig.savefig(output, format="png", dpi=FIGURE_DPI,
                metadata={"Description": note})
    return output.getvalue()
