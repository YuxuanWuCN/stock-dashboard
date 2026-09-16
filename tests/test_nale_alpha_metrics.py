"""Independent ranking and resampling fixtures, not market observations."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.nale_alpha_metrics import evaluate_versions


def _predictions(days=6, stocks=20):
    dates = tuple(pd.bdate_range("2024-06-03", periods=days).strftime("%Y-%m-%d"))
    records = []
    for day in dates:
        for index in range(stocks):
            actual = float(index - 4.5) / 100
            for version, predicted in (
                ("B0", -actual), ("V1", actual), ("V2", actual * 0.5), ("V3", actual * 0.4),
            ):
                records.append({
                    "date": day, "code": f"{index + 1:06d}",
                    "version": version, "phase": "validation",
                    "evidence_class": "engineering_fixture",
                    "predicted_excess": predicted, "y_excess": actual,
                })
    return pd.DataFrame(records)


def test_ic_direction_and_missing_versions_are_explicit():
    evaluated = evaluate_versions(_predictions(), block_days=2, bootstrap_iterations=200)
    summary = evaluated.version_comparison.set_index("version")
    assert summary.loc["V1", "rank_ic_mean"] == pytest.approx(1.0)
    assert summary.loc["B0", "rank_ic_mean"] == pytest.approx(-1.0)
    assert np.isnan(summary.loc["V1", "rank_icir"])
    assert summary.loc["V1", "direction_accuracy_excess"] == 1.0
    assert summary.loc["V1", "direction_coverage"] == 1.0
    assert summary.loc["V1", "majority_class_rate"] == pytest.approx(15 / 20)
    assert summary.loc["V1", "n_valid_ic_dates"] == 6
    assert summary.loc["B1", "status"] == "missing_version"
    assert summary.loc["V4", "status"] == "missing_version"
    assert summary.loc["V1", "strategy_status"] == "not_evaluable_without_executable_portfolio"
    assert np.isnan(summary.loc["V1", "net_sharpe"])


def test_paired_block_bootstrap_and_holm_are_date_aligned():
    evaluated = evaluate_versions(_predictions(), block_days=2, bootstrap_iterations=200, seed=42)
    paired = evaluated.paired_differences.set_index("comparison")
    improved = paired.loc["V1-B0"]
    assert improved["status"] == "evaluated"
    assert improved["n_paired_dates"] == 6
    assert improved["n_common_stock_date"] == 120
    assert improved["rank_ic_delta_mean"] == pytest.approx(2.0)
    assert improved["rank_ic_ci_lower"] == pytest.approx(2.0)
    assert improved["rank_ic_ci_upper"] == pytest.approx(2.0)
    assert improved["holm_family_size"] == 3
    assert improved["holm_p"] >= improved["rank_ic_p"]
    assert np.isfinite(improved["block_half_ci_lower"])
    assert np.isfinite(improved["block_double_ci_upper"])
    assert paired.loc["V4-V3", "status"] == "missing_version"
    assert paired.loc["V1-B1", "status"] == "missing_version"


def test_zero_predictions_count_as_abstentions_and_zero_truth_separate():
    frame = _predictions()
    one = (frame["version"] == "V1") & (frame["date"] == frame["date"].iloc[0]) & (frame["code"] == "000001")
    frame.loc[one, "predicted_excess"] = 0.0
    zero_truth = frame["code"] == "000002"
    frame.loc[zero_truth, "y_excess"] = 0.0
    evaluated = evaluate_versions(frame, block_days=2, bootstrap_iterations=100)
    summary = evaluated.version_comparison.set_index("version")
    assert summary.loc["V1", "n_prediction_abstentions"] == 1
    assert summary.loc["V1", "n_true_zero"] == 6
    assert summary.loc["V1", "direction_coverage"] == pytest.approx(119 / 120)
    assert summary.loc["V1", "n_direction_scored"] == 113


def test_insufficient_daily_stocks_or_block_dates_do_not_fake_significance():
    small = evaluate_versions(_predictions(stocks=19), block_days=2, bootstrap_iterations=100)
    summary = small.version_comparison.set_index("version")
    assert summary.loc["V1", "status"] == "insufficient_daily_stocks_or_variance"
    assert np.isnan(summary.loc["V1", "rank_ic_mean"])
    paired = small.paired_differences.set_index("comparison")
    assert paired.loc["V1-B0", "status"] == "insufficient_daily_stocks_or_variance"
    short = evaluate_versions(_predictions(days=3), block_days=10, bootstrap_iterations=100)
    assert short.paired_differences.set_index("comparison").loc["V1-B0", "status"] == "insufficient_paired_dates_for_bootstrap"


def test_inconsistent_labels_duplicates_and_nonfinite_predictions_fail_closed():
    frame = _predictions()
    inconsistent = frame.copy()
    inconsistent.loc[0, "y_excess"] += 1.0
    with pytest.raises(ValueError, match="disagree"):
        evaluate_versions(inconsistent)
    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_versions(duplicate)
    nonfinite = frame.copy()
    nonfinite.loc[0, "predicted_excess"] = np.inf
    with pytest.raises(ValueError, match="NaN or Inf"):
        evaluate_versions(nonfinite)
