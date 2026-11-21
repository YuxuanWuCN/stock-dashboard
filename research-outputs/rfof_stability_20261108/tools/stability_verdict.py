
"""Apply the pre-committed three-criterion defense-layer comparison.

The input is measured net of the 30 bps friction assumption for criterion 3.
Pass only with three better bear windows, a 2 pp full-sample drawdown gain
and a superior median parameter, and at most 1 pp of annualized return drag.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

import pandas as pd

BEAR_NAMES = ("Bear2015", "Bear2018", "Bear2022", "Bear2026")


def _primary(rows: pd.DataFrame, params: Mapping[str, str]) -> pd.DataFrame:
    method = rows["method"].iat[0]
    if method in params:
        rows = rows.loc[rows["param_id"].eq(params[method])]
        if rows.empty:
            raise ValueError(f"No rows for {method} parameter {params[method]!r}")
    elif "param_id" in rows and rows["param_id"].nunique() > 1:
        raise ValueError(f"Choose a primary param_id for {method}")
    return rows.set_index("window", verify_integrity=True)


def judge_method_results(
    results_df: pd.DataFrame,
    baseline_method: str = "A0",
    *,
    primary_params: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Compare primary settings against A0 and test the full parameter median."""
    params = primary_params or {}
    base_rows = results_df.loc[results_df["method"].eq(baseline_method)]
    if base_rows.empty:
        raise ValueError(f"Baseline method '{baseline_method}' not found in results_df")
    base = _primary(base_rows, params)
    if "FullSample" not in base.index:
        raise ValueError("Baseline requires FullSample")
    base_full = base.loc["FullSample"]
    bear_windows = [w for w in BEAR_NAMES if w in base.index and isfinite(base.at[w, "max_dd_pct"])]

    records = []
    for method, rows in results_df.groupby("method", sort=False):
        if method == baseline_method:
            continue
        candidate = _primary(rows, params)
        if "FullSample" not in candidate.index:
            raise ValueError(f"{method} requires FullSample")
        full = candidate.loc["FullSample"]
        wins = sum(
            bool(candidate.at[window, "max_dd_pct"] > base.at[window, "max_dd_pct"])
            for window in bear_windows if window in candidate.index
        )
        dd_gain = float(full["max_dd_pct"] - base_full["max_dd_pct"])
        median_dd = rows.loc[rows["window"].eq("FullSample"), "max_dd_pct"].median()
        median_better = bool(median_dd > base_full["max_dd_pct"])
        drag = float(base_full["ann_ret_pct"] - full["ann_ret_pct"])
        c1 = wins >= 3
        c2 = dd_gain >= 2.0 and median_better
        c3 = drag <= 1.0
        records.append({
            "method": method,
            "c1_windows_better": wins,
            "c1_total_windows": len(bear_windows),
            "c1_pass": c1,
            "c2_full_dd_gain_pp": dd_gain,
            "c2_median_better": median_better,
            "c2_pass": c2,
            "c3_ret_drag_pp": drag,
            "c3_pass": c3,
            "verdict": "improved" if c1 and c2 and c3 else "no_significant_improvement",
        })
    return pd.DataFrame(records)
