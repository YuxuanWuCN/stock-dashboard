from unittest.mock import patch

import pandas as pd
import pytest

from src.analysis.nale_alpha_phase_runner import make_walkforward_phase_runner
from src.analysis.nale_alpha_pipeline import DataEvidence
from src.analysis.nale_alpha_walkforward import WalkForwardConfig, WalkForwardResult


def _evidence(verified=False):
    return DataEvidence(kind="fixture", audit_id="fixture-audit", independently_verified=verified)


def _result(phase="validation"):
    return WalkForwardResult(
        predictions=pd.DataFrame({"version": ["B0", "V1", "V2", "V3"], "score": [0.4, 0.5, 0.6, 0.7]}),
        monthly_weights=pd.DataFrame({"version": ["V1", "V2", "V3"], "intercept": [0.0, 0.1, 0.2]}),
        date_plan=object(), phase=phase, evidence_class="fixture",
    )


def _runner(*, allow_fixture=True):
    return make_walkforward_phase_runner(
        pd.DataFrame(), {}, ["2024-01-02"], WalkForwardConfig(),
        evidence=_evidence(), allow_fixture=allow_fixture,
    )


def test_unverified_nonfixture_run_is_rejected():
    with pytest.raises(ValueError, match="independently verified"):
        _runner(allow_fixture=False)


def test_validation_candidate_only_exposes_target_version():
    with patch("src.analysis.nale_alpha_phase_runner.run_walkforward", return_value=_result()) as engine:
        output = _runner()("validation", {"V1": (0.001, None)}, "V1")
    assert output.predictions["version"].tolist() == ["V1"]
    assert output.monthly_weights["version"].tolist() == ["V1"]
    assert engine.call_args.kwargs["phase"] == "validation"
    assert engine.call_args.args[3].ridge_v1 == 0.001


def test_test_phase_requires_full_frozen_request():
    runner = _runner()
    with pytest.raises(ValueError, match="frozen full-version"):
        runner("test", {"V3": (0.01, 20)}, "V3")
    with patch("src.analysis.nale_alpha_phase_runner.run_walkforward", return_value=_result("test")):
        output = runner("test", {"V1": (0.001, None), "V2": (0.01, None), "V3": (0.1, 60)}, None)
    assert output.predictions["version"].tolist() == ["B0", "V1", "V2", "V3"]


def test_v4_candidate_does_not_silently_run_as_v3():
    with pytest.raises(ValueError, match="V1/V2/V3"):
        _runner()("validation", {"V4": (0.01, 20)}, "V4")


def test_invalid_half_life_fails_before_model_call():
    with patch("src.analysis.nale_alpha_phase_runner.run_walkforward") as engine:
        with pytest.raises(ValueError, match="half-life"):
            _runner()("validation", {"V3": (0.01, 0)}, "V3")
    engine.assert_not_called()
