# -*- coding: utf-8 -*-
"""tests/verify_challenger_empirical.py —— Challenger M1-4-1 Empirical Data Extractor

Runs all verification checks and prints formatted tables and stats for analysis.md.
"""

import math
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from src.pricing.pca_backtest import (
    compute_alpha_composite_nale,
    compute_performance_metrics,
    decompose_annual_alpha_beta,
    load_and_align_datasets,
    run_weekly_long_short_backtest,
)

def run_empirical_checks():
    print("=== 1. LOADING DATA ===")
    factors_df, csmar_panel, latest_mv = load_and_align_datasets()
    print(f"Factors DF shape: {factors_df.shape}")
    print(f"CSMAR panel shape: {csmar_panel.shape}")
    print(f"Latest MV shape: {latest_mv.shape}")

    print("\n=== 2. FACTOR SCORE DISTRIBUTION ===")
    alpha_series, returns_matrix = compute_alpha_composite_nale(factors_df, csmar_panel)
    valid_count = int(alpha_series.notna().sum())
    mean_val = float(alpha_series.mean())
    std_val = float(alpha_series.std(ddof=1))
    min_val = float(alpha_series.min())
    max_val = float(alpha_series.max())
    skew_val = float(stats.skew(alpha_series.values))
    kurt_val = float(stats.kurtosis(alpha_series.values))
    nan_count = int(alpha_series.isna().sum())
    inf_count = int(np.isinf(alpha_series.values).sum())

    print(f"Valid stocks: {valid_count} (>= 290 check: {valid_count >= 290})")
    print(f"Mean: {mean_val:.10e} (abs < 0.1: {abs(mean_val) < 0.1})")
    print(f"Std: {std_val:.6f} (abs(std-1) < 0.1: {abs(std_val - 1.0) < 0.1})")
    print(f"Min: {min_val:.4f}, Max: {max_val:.4f}")
    print(f"Skewness: {skew_val:.4f}, Excess Kurtosis: {kurt_val:.4f}")
    print(f"NaN count: {nan_count}, Inf count: {inf_count}")

    # Neutralization check
    merged = pd.DataFrame({
        "alpha": alpha_series,
        "sector": factors_df.loc[alpha_series.index, "sector"],
        "log_mv": np.log(latest_mv.loc[alpha_series.index]),
    }).dropna()
    ind_dummies = pd.get_dummies(merged["sector"], drop_first=True, dtype=float)
    X = sm.add_constant(pd.concat([ind_dummies, merged[["log_mv"]]], axis=1))
    ols = sm.OLS(merged["alpha"], X).fit()
    print(f"Neutralization residual check R²: {ols.rsquared:.10e} (Expected: ~0)")

    print("\n=== 3. PORTFOLIO LEG SIZING ON EVERY REBALANCE DATE ===")
    volume_matrix = csmar_panel.pivot(
        index="trade_date", columns="stock_code", values="volume"
    ).fillna(0.0)

    universes = ["full", "student_A", "student_B", "student_C"]
    sizing_stats = []
    backtest_results = {}

    for u in universes:
        res = run_weekly_long_short_backtest(
            alpha_series=alpha_series,
            returns_df=returns_matrix,
            stock_metadata=factors_df,
            cohort=u,
            volume_df=volume_matrix,
        )
        backtest_results[u] = res
        reb_dates = res.rebalance_dates
        long_lens = [len(res.long_holdings[d]) for d in reb_dates]
        short_lens = [len(res.short_holdings[d]) for d in reb_dates]
        min_l, max_l, mean_l = min(long_lens), max(long_lens), np.mean(long_lens)
        min_s, max_s, mean_s = min(short_lens), max(short_lens), np.mean(short_lens)
        sizing_ok = (min_l >= 10 and min_s >= 10)
        sizing_stats.append({
            "Universe": u,
            "Rebalances": len(reb_dates),
            "Min_Long": min_l,
            "Max_Long": max_l,
            "Mean_Long": round(mean_l, 2),
            "Min_Short": min_s,
            "Max_Short": max_s,
            "Mean_Short": round(mean_s, 2),
            "Sizing_Pass": sizing_ok,
        })
        print(f"Universe: {u} | Rebalances: {len(reb_dates)} | Long leg: min={min_l}, max={max_l}, mean={mean_l:.2f} | Short leg: min={min_s}, max={max_s}, mean={mean_s:.2f} | Sizing >= 10: {sizing_ok}")

    sizing_df = pd.DataFrame(sizing_stats)

    print("\n=== 4. DAILY RETURNS & LEAKAGE VERIFICATION ===")
    return_checks = []
    for u in universes:
        res = backtest_results[u]
        rets = res.daily_returns
        cum_ret = res.cumulative_returns
        cum_log = res.cumulative_log_returns

        nan_in_ret = int(rets.isna().sum())
        inf_in_ret = int(np.isinf(rets.values).sum())
        nan_in_cum = int(cum_ret.isna().sum())
        nan_in_log = int(cum_log.isna().sum())
        min_r = float(rets.min())
        max_r = float(rets.max())

        # Independent manual check of 0.5 * Long - 0.5 * Short
        cur_l, cur_s = None, None
        reb_set = set(res.rebalance_dates)
        indep_rets = []
        for d in sorted(returns_matrix.index):
            if d in reb_set:
                cur_l = res.long_holdings[d]
                cur_s = res.short_holdings[d]
            rl = float(returns_matrix.loc[d, cur_l].dropna().mean()) if cur_l else 0.0
            rs = float(returns_matrix.loc[d, cur_s].dropna().mean()) if cur_s else 0.0
            rp = 0.5 * rl - 0.5 * rs
            indep_rets.append(rp)
        indep_s = pd.Series(indep_rets, index=sorted(returns_matrix.index))
        max_diff = float(np.abs(rets - indep_s).max())

        return_checks.append({
            "Universe": u,
            "Days": len(rets),
            "NaN_Rets": nan_in_ret,
            "Inf_Rets": inf_in_ret,
            "Min_Daily_Ret": f"{min_r:.6f}",
            "Max_Daily_Ret": f"{max_r:.6f}",
            "Max_Discrepancy_vs_Oracle": f"{max_diff:.2e}",
            "NaN_CumRet": nan_in_cum,
            "NaN_CumLog": nan_in_log,
        })
        print(f"Universe: {u} | Days: {len(rets)} | NaN count: {nan_in_ret} | Max discrepancy: {max_diff:.2e} | Min: {min_r:.4f}, Max: {max_r:.4f}")

    ret_df = pd.DataFrame(return_checks)

    print("\n=== 5. TURNOVER CONSTRAINTS & BREAKDOWN ===")
    turnover_stats = []
    for u in universes:
        res = backtest_results[u]
        to = res.turnover_series
        m = compute_performance_metrics(res)
        ann_to = m["annualized_turnover"]
        in_bounds = (0.0 <= ann_to <= 10.0)
        turnover_stats.append({
            "Universe": u,
            "Turnover_Steps": len(to),
            "Min_Step_TO": float(to.min()),
            "Max_Step_TO": float(to.max()),
            "Mean_Step_TO": float(to.mean()),
            "Annualized_Turnover": float(ann_to),
            "Within_[0,10]_Bound": in_bounds,
        })
        print(f"Universe: {u} | Mean step TO: {to.mean():.4f} | Max step TO: {to.max():.4f} | Annualized TO: {ann_to:.6f} | Bound [0, 10]: {in_bounds}")

    to_df = pd.DataFrame(turnover_stats)

    print("\n=== 6. SUMMARY METRICS COMPARISON ===")
    summary_path = Path("reports/tables/ashare_pca_backtest/backtest_summary.csv")
    if summary_path.exists():
        saved_summary = pd.read_csv(summary_path)
        print(saved_summary.to_string(index=False))

    print("\n=== 7. ANNUAL ALPHA / BETA REGRESSION CHECK ===")
    for u in universes:
        csv_path = Path(f"reports/tables/ashare_pca_backtest/annual_alpha_{u.lower()}.csv")
        if csv_path.exists():
            df_a = pd.read_csv(csv_path)
            print(f"\nAnnual Alpha/Beta: {u}")
            print(df_a.to_string(index=False))

if __name__ == "__main__":
    run_empirical_checks()
