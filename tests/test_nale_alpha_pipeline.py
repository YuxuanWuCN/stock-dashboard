"""Phase orchestration fixtures; no observed market-performance claim."""

import pytest

from src.analysis.nale_alpha_pipeline import DataEvidence, run_nale_alpha_pipeline


def test_validation_grid_precedes_one_frozen_test_and_records_unavailable_extensions():
    calls = []

    def run_phase(phase, settings, target):
        calls.append((phase, dict(settings), target))
        return {"phase": phase, "settings": dict(settings), "target": target}

    def score_validation(output, version):
        assert output["phase"] == "validation"
        ridge, history = output["settings"][version]
        score = 0.1 if ridge == 0.01 else 0.0
        if version == "V3" and history == 60:
            score += 0.02
        return score, 21

    result = run_nale_alpha_pipeline(
        evidence=DataEvidence("fixture", "unit-fixture-42"),
        run_phase=run_phase,
        score_validation_rank_ic=score_validation,
        report_versions=lambda _: {"B0": "available", "V1": "available",
                                     "V2": "available", "V3": "available"},
        allow_fixture=True,
    )
    assert len(calls) == 14  # 12 candidate runs, final validation, single test.
    assert all(call[0] == "validation" for call in calls[:-1])
    assert calls[-1][0] == "test" and calls[-1][2] is None
    assert calls[-1][1] == {"V1": (0.01, None), "V2": (0.01, None), "V3": (0.01, 60)}
    assert result.version_status["B1"] == "not_evaluable"
    assert result.version_status["V4"] == "not_evaluable"
    assert result.version_status["V5"] == "not_evaluable"
    assert result.empirical_status == "engineering_fixture_no_market_claim"
    assert len(result.selection.trials) == 12


def test_synthetic_and_unverified_observed_data_fail_before_any_runner_call():
    calls = []

    def runner(*args):
        calls.append(args)
        raise AssertionError("runner must not be called")

    for evidence in (DataEvidence("synthetic", "audit-1"),
                     DataEvidence("observed", "audit-2", ("feed-1",), False)):
        with pytest.raises(ValueError):
            run_nale_alpha_pipeline(evidence=evidence, run_phase=runner,
                                    score_validation_rank_ic=lambda *_: (0.1, 30),
                                    report_versions=lambda _: {})
    assert calls == []


def test_missing_core_version_fails_closed_after_test():
    def runner(phase, settings, target):
        return phase

    with pytest.raises(ValueError, match="required B0"):
        run_nale_alpha_pipeline(
            evidence=DataEvidence("fixture", "fixture"), run_phase=runner,
            score_validation_rank_ic=lambda *_: (0.1, 20),
            report_versions=lambda _: {"B0": "available", "V1": "available",
                                         "V2": "available"},
            allow_fixture=True,
        )
