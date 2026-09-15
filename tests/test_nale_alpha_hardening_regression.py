"""Regression checks for horizon selection and artifact preflight."""

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from src.analysis.nale_alpha_artifacts import (
    ArtifactTables,
    PAIRS,
    PREDICTION_COLUMNS,
    WEIGHT_COLUMNS,
    _validate_split_manifest,
    _validate_tables,
)
from src.analysis.nale_alpha_experiment import _score_validation
from src.analysis.nale_alpha_pipeline import ALL_VERSIONS, CORE_VERSIONS


def test_validation_score_uses_requested_twenty_day_horizon():
    output = SimpleNamespace(phase="validation", predictions=pd.DataFrame())
    metrics = SimpleNamespace(version_comparison=pd.DataFrame([
        {"version": "V1", "n_valid_ic_dates": 21, "rank_ic_mean": 0.12}
    ]))
    with patch("src.analysis.nale_alpha_experiment.evaluate_versions", return_value=metrics) as evaluate:
        assert _score_validation(output, "V1", min_stocks=20, horizon_days=20) == (0.12, 21)
    assert evaluate.call_args.kwargs["horizon_days"] == 20


def test_monthly_weights_reject_infinite_coefficient():
    predictions = pd.DataFrame([
        {**dict.fromkeys(PREDICTION_COLUMNS, 0), "date": "2024-02-01", "code": "000001", "version": version,
         "phase": "test"}
        for version in sorted(CORE_VERSIONS)
    ])
    weights = pd.DataFrame([
        {"version": version, "fit_date": "2024-02-01", "fit_cutoff": "2024-01-31",
         "status": "fitted", "b": 0.0, **dict.fromkeys(WEIGHT_COLUMNS, 0.0)}
        for version in sorted(set(CORE_VERSIONS) - {"B0", "B1"})
    ])
    weights.loc[weights.index[0], WEIGHT_COLUMNS[0]] = float("inf")
    comparison = pd.DataFrame([
        {"version": version, "phase": "test",
         "status": "available" if version in CORE_VERSIONS else "not_evaluable",
         "rank_ic_mean": 0.0 if version in CORE_VERSIONS else None}
        for version in sorted(ALL_VERSIONS)
    ])
    paired = pd.DataFrame([{"comparison": pair, "phase": "test", "status": "not_evaluable"} for pair in PAIRS])
    with pytest.raises(ValueError, match="finite fitted coefficients"):
        _validate_tables(ArtifactTables(predictions, weights, comparison, paired))


def _valid_split_manifest():
    train = pd.bdate_range("2024-01-01", periods=126)
    validation = pd.bdate_range(train[-1] + pd.offsets.BDay(10), periods=42)
    test = pd.bdate_range(validation[-1] + pd.offsets.BDay(10), periods=42)
    return {
        "train_dates": train.strftime("%Y-%m-%d").tolist(),
        "validation_dates": validation.strftime("%Y-%m-%d").tolist(),
        "test_dates": test.strftime("%Y-%m-%d").tolist(),
        "horizon_trading_days": 5,
        "label_maturity_buffer_trading_days": 6,
        "train_label_available_at_max": (train[-1] + pd.offsets.BDay(2)).isoformat(),
        "validation_first_prediction_cutoff": validation[0].isoformat(),
        "validation_label_available_at_max": (validation[-1] + pd.offsets.BDay(2)).isoformat(),
        "test_first_prediction_cutoff": test[0].isoformat(),
    }


def test_prediction_cutoff_must_match_first_listed_signal_date():
    manifest = _valid_split_manifest()
    _validate_split_manifest(manifest)
    manifest["validation_first_prediction_cutoff"] = (
        pd.Timestamp(manifest["validation_dates"][0]) - pd.offsets.BDay(1)
    ).isoformat()
    with pytest.raises(ValueError, match="first listed signal dates"):
        _validate_split_manifest(manifest)


def test_label_maturity_must_follow_partition_signal_dates():
    manifest = _valid_split_manifest()
    manifest["validation_label_available_at_max"] = manifest["validation_dates"][-2]
    with pytest.raises(ValueError, match="maturity must follow"):
        _validate_split_manifest(manifest)
