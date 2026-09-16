"""Validation-only hyperparameter selection for the NALE alpha gate.

The caller must supply a validation scorer built from validation predictions.
The selection API deliberately has no test observations or test scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Callable, Mapping, TypeVar


RIDGE_CANDIDATES = (0.001, 0.01, 0.1)
HISTORY_CANDIDATES = (20, 60)
MIN_VALID_IC_DATES = 20


@dataclass(frozen=True)
class GateHyperparameters:
    v1_ridge: float
    v2_ridge: float
    v3_ridge: float
    v3_history_days: int


@dataclass(frozen=True)
class ValidationTrial:
    version: str
    ridge: float
    history_days: int | None
    mean_rank_ic: float | None
    valid_ic_dates: int
    eligible: bool
    selected: bool


@dataclass(frozen=True)
class SelectionResult:
    hyperparameters: GateHyperparameters
    trials: tuple[ValidationTrial, ...]
    min_valid_ic_dates: int


ValidationScorer = Callable[[str, float, int | None, Mapping[str, tuple[float, int | None]]], tuple[float | None, int]]
T = TypeVar("T")


def select_validation_hyperparameters(
    score_validation: ValidationScorer,
    *,
    min_valid_ic_dates: int = MIN_VALID_IC_DATES,
) -> SelectionResult:
    """Select V1, V2, then V3 using only validation mean daily Rank IC.

    ``score_validation`` receives the version, candidate ridge/history, and
    previously frozen stage choices. It must return (mean Rank IC, number of
    valid dates). Invalid/insufficient candidates are recorded but cannot win.
    Equal scores retain the first candidate in the predefined grid order.
    """
    if min_valid_ic_dates < 1:
        raise ValueError("min_valid_ic_dates must be positive")

    frozen: dict[str, tuple[float, int | None]] = {}
    trials: list[ValidationTrial] = []
    for version in ("V1", "V2", "V3"):
        best_index: int | None = None
        best_score = float("-inf")
        histories = (None,) if version != "V3" else HISTORY_CANDIDATES
        for ridge in RIDGE_CANDIDATES:
            for history_days in histories:
                score, n_dates = score_validation(version, ridge, history_days, dict(frozen))
                if not isinstance(n_dates, int) or n_dates < 0:
                    raise ValueError("validation scorer returned invalid date count")
                eligible = (
                    n_dates >= min_valid_ic_dates
                    and score is not None
                    and isfinite(score)
                )
                trial = ValidationTrial(
                    version=version,
                    ridge=ridge,
                    history_days=history_days,
                    mean_rank_ic=score if score is not None and isfinite(score) else None,
                    valid_ic_dates=n_dates,
                    eligible=eligible,
                    selected=False,
                )
                trials.append(trial)
                if eligible and score > best_score:
                    best_score = score
                    best_index = len(trials) - 1
        if best_index is None:
            raise ValueError(f"{version} has no eligible validation candidate")
        winner = trials[best_index]
        trials[best_index] = ValidationTrial(**{**winner.__dict__, "selected": True})
        frozen[version] = (winner.ridge, winner.history_days)

    return SelectionResult(
        hyperparameters=GateHyperparameters(
            v1_ridge=frozen["V1"][0],
            v2_ridge=frozen["V2"][0],
            v3_ridge=frozen["V3"][0],
            v3_history_days=int(frozen["V3"][1]),
        ),
        trials=tuple(trials),
        min_valid_ic_dates=min_valid_ic_dates,
    )


def run_frozen_test(selection: SelectionResult, test_runner: Callable[[GateHyperparameters], T]) -> T:
    """Run the test phase once with immutable validation-selected settings."""
    return test_runner(selection.hyperparameters)
