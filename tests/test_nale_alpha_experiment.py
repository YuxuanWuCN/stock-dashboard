from unittest.mock import patch

import pandas as pd

from src.analysis.nale_alpha_experiment import run_prepared_nale_experiment
from src.analysis.nale_alpha_metrics import EvaluationResult
from src.analysis.nale_alpha_pipeline import DataEvidence
from src.analysis.nale_alpha_walkforward import WalkForwardConfig, WalkForwardResult


def test_validation_selection_then_exactly_one_frozen_test():
    calls = []

    def run_phase(phase, parameters, target):
        calls.append((phase, tuple(sorted(parameters)), target))
        versions = [target] if target else ["B0", "V1", "V2", "V3"]
        return WalkForwardResult(
            predictions=pd.DataFrame({"version": versions, "phase": phase, "evidence_class": "fixture"}),
            monthly_weights=pd.DataFrame(), date_plan=object(), phase=phase, evidence_class="fixture",
        )

    def metrics(predictions, **kwargs):
        phase = predictions["phase"].iloc[0]
        versions = predictions["version"].tolist()
        return EvaluationResult(
            daily_ics=pd.DataFrame(),
            version_comparison=pd.DataFrame({
                "version": versions,
                "rank_ic_mean": [0.02] * len(versions),
                "n_valid_ic_dates": [20] * len(versions),
            }),
            paired_differences=pd.DataFrame(),
            phase=phase, evidence_class="fixture",
        )

    with patch("src.analysis.nale_alpha_experiment.make_walkforward_phase_runner", return_value=run_phase), patch(
        "src.analysis.nale_alpha_experiment.evaluate_versions", side_effect=metrics
    ) as evaluator:
        result = run_prepared_nale_experiment(
            pd.DataFrame(), {}, ["2024-01-02"], WalkForwardConfig(),
            evidence=DataEvidence(kind="fixture", audit_id="fixture-audit"),
            allow_fixture=True, min_valid_ic_dates=20,
        )
    assert sum(phase == "test" for phase, _, _ in calls) == 1
    assert calls[-1][0] == "test"
    assert calls[-1][2] is None
    assert result.pipeline.version_status["B0"] == "available"
    assert result.pipeline.version_status["V4"] == "not_evaluable"
    assert result.test_metrics.phase == "test"
    assert evaluator.call_args.kwargs["bootstrap_iterations"] == 2000
