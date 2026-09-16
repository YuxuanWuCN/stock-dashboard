"""Engineering fixtures only; these tests make no market-performance claim."""

import pytest

from src.analysis.nale_alpha_selection import (
    GateHyperparameters,
    select_validation_hyperparameters,
    run_frozen_test,
)


def test_selection_uses_validation_stages_and_freezes_before_single_test_run():
    calls = []

    def score_validation(version, ridge, history_days, frozen):
        calls.append((version, ridge, history_days, frozen))
        if version == "V1":
            return ({0.001: 0.01, 0.01: 0.03, 0.1: 0.02}[ridge], 25)
        if version == "V2":
            assert frozen == {"V1": (0.01, None)}
            return (0.04, 25)  # Tie must select the first preset ridge.
        assert frozen == {"V1": (0.01, None), "V2": (0.001, None)}
        return (0.06 if (ridge, history_days) == (0.1, 60) else 0.02, 25)

    result = select_validation_hyperparameters(score_validation)
    assert result.hyperparameters == GateHyperparameters(0.01, 0.001, 0.1, 60)
    assert len(result.trials) == 12
    assert len([trial for trial in result.trials if trial.selected]) == 3
    assert len(calls) == 12

    test_calls = []

    def test_runner(settings):
        test_calls.append(settings)
        return {"phase": "test", "configuration": settings}

    output = run_frozen_test(result, test_runner)
    assert output["phase"] == "test"
    assert test_calls == [result.hyperparameters]
    assert len(calls) == 12


def test_insufficient_dates_cannot_win_even_with_higher_score():
    def score_validation(version, ridge, history_days, frozen):
        return (1.0 if ridge == 0.001 else 0.1, 19 if ridge == 0.001 else 20)

    result = select_validation_hyperparameters(score_validation)
    assert result.hyperparameters.v1_ridge == 0.01
    assert result.hyperparameters.v2_ridge == 0.01
    assert result.hyperparameters.v3_ridge == 0.01
    assert result.hyperparameters.v3_history_days == 20
    assert all(not trial.selected for trial in result.trials if trial.valid_ic_dates == 19)


def test_all_ineligible_candidates_fail_closed():
    with pytest.raises(ValueError, match="V1 has no eligible"):
        select_validation_hyperparameters(lambda *_: (0.4, 19))


def test_invalid_date_count_rejected():
    with pytest.raises(ValueError, match="invalid date count"):
        select_validation_hyperparameters(lambda *_: (0.4, -1))
