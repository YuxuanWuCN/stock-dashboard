"""Automated 3-criterion acceptance gate evaluation (FR-006, US3).

Implements the strictly pre-committed criteria:
1. c1: At least 3 of 4 historical bear market windows have shallower MaxDD than baseline A0.
2. c2: Full sample MaxDD improves by >= 2.0 percentage points, and parameter median remains superior.
3. c3: Annualized return drag under 30 bps round-trip friction does not exceed 1.0 percentage point.

Final status: 'improved' iff (c1 and c2 and c3) else 'no_significant_improvement'.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def judge_method_results(
    results_df: pd.DataFrame,
    baseline_method: str = "A0",
) -> pd.DataFrame:
    """Evaluate candidate portfolio methods against baseline across the 3 pre-committed criteria.

    Parameters:
        results_df: DataFrame containing columns: ['method', 'param_id', 'window', 'max_dd_pct', 'ann_ret_pct', 'cost_drag_pct']
        baseline_method: Method identifier for benchmark (default: 'A0').

    Returns:
        DataFrame summarizing criteria evaluation and final verdict for each candidate.
    """
    # Extract baseline
    base_rows = results_df[results_df["method"] == baseline_method]
    if base_rows.empty:
        raise ValueError(f"Baseline method '{baseline_method}' not found in results_df")

    base_by_window = base_rows.set_index("window")
    bear_window_names = [w for w in ["Bear2015", "Bear2018", "Bear2022", "Bear2026"] if w in base_by_window.index]
    base_full = base_by_window.loc["FullSample"] if "FullSample" in base_by_window.index else base_rows.iloc[0]

    candidates = [m for m in results_df["method"].unique() if m != baseline_method]
    verdict_rows: list[dict[str, Any]] = []

    for cand in candidates:
        cand_rows = results_df[results_df["method"] == cand]
        cand_by_window = cand_rows.set_index("window")

        # Criterion 1: Bear market windows comparison
        windows_better = 0
        for w in bear_window_names:
            if w in cand_by_window.index:
                cand_dd = cand_by_window.loc[w, "max_dd_pct"]
                base_dd = base_by_window.loc[w, "max_dd_pct"]
                # Shallower drawdown: -10% is better than -15%
                if cand_dd > base_dd:
                    windows_better += 1

        c1_pass = bool(windows_better >= 3)

        # Criterion 2: Full sample MaxDD gain >= 2.0 pp
        cand_full = cand_by_window.loc["FullSample"] if "FullSample" in cand_by_window.index else cand_rows.iloc[0]
        cand_full_dd = float(cand_full["max_dd_pct"])
        base_full_dd = float(base_full["max_dd_pct"])
        # Gain is candidate DD minus baseline DD (e.g. -18.0 - (-20.0) = +2.0 pp)
        dd_gain_pp = round(cand_full_dd - base_full_dd, 2)
        # Check median if multiple param_ids exist
        median_cand_dd = float(cand_rows[cand_rows["window"] == "FullSample"]["max_dd_pct"].median())
        median_better = bool(median_cand_dd > base_full_dd)
        c2_pass = bool((dd_gain_pp >= 2.0) and median_better)

        # Criterion 3: Return drag under friction <= 1.0 pp
        cand_ret = float(cand_full["ann_ret_pct"])
        base_ret = float(base_full["ann_ret_pct"])
        ret_drag_pp = round(base_ret - cand_ret, 2)
        c3_pass = bool(ret_drag_pp <= 1.0)

        is_improved = bool(c1_pass and c2_pass and c3_pass)
        verdict_str = "improved" if is_improved else "no_significant_improvement"

        verdict_rows.append({
            "method": cand,
            "c1_windows_better": int(windows_better),
            "c1_total_windows": int(len(bear_window_names)),
            "c1_pass": bool(c1_pass),
            "c2_full_dd_gain_pp": float(dd_gain_pp),
            "c2_median_better": bool(median_better),
            "c2_pass": bool(c2_pass),
            "c3_ret_drag_pp": float(ret_drag_pp),
            "c3_pass": bool(c3_pass),
            "verdict": verdict_str,
        })

    return pd.DataFrame(verdict_rows)
