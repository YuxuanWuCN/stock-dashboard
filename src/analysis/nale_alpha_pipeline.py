"""Phase-locked NALE selection/experiment orchestration.

The phase runner is the boundary to the prepared point-in-time walk-forward.
This module never receives a test scorer and cannot promote fixture results to
observed-market evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Generic, Mapping, TypeVar

from src.analysis.nale_alpha_selection import (
    GateHyperparameters,
    SelectionResult,
    run_frozen_test,
    select_validation_hyperparameters,
)


T = TypeVar("T")
CORE_VERSIONS = ("B0", "V1", "V2", "V3")
ALL_VERSIONS = ("B0", "B1", "V1", "V2", "V3", "V4", "V5")


@dataclass(frozen=True)
class DataEvidence:
    kind: str  # observed, fixture, or synthetic
    audit_id: str
    source_ids: tuple[str, ...] = ()
    independently_verified: bool = False


@dataclass(frozen=True)
class PipelineResult(Generic[T]):
    evidence: DataEvidence
    selection: SelectionResult
    validation_output: T
    test_output: T
    version_status: Mapping[str, str]
    empirical_status: str


PhaseRunner = Callable[[str, Mapping[str, tuple[float, int | None]], str | None], T]
RankICScorer = Callable[[T, str], tuple[float | None, int]]
VersionReporter = Callable[[T], Mapping[str, str]]


def _require_data_evidence(evidence: DataEvidence, allow_fixture: bool) -> str:
    if not evidence.audit_id.strip():
        raise ValueError("data audit ID is required")
    if evidence.kind == "observed":
        if not evidence.independently_verified or not evidence.source_ids:
            raise ValueError("observed data require independently verified source IDs")
        return "observed_candidate_pending_metrics"
    if evidence.kind == "fixture" and allow_fixture:
        return "engineering_fixture_no_market_claim"
    raise ValueError("synthetic or unapproved fixture data cannot enter a market experiment")


def run_nale_alpha_pipeline(
    *,
    evidence: DataEvidence,
    run_phase: PhaseRunner[T],
    score_validation_rank_ic: RankICScorer[T],
    report_versions: VersionReporter[T],
    allow_fixture: bool = False,
    min_valid_ic_dates: int = 20,
) -> PipelineResult[T]:
    """Tune on validation only, freeze, then execute exactly one test phase.

    ``run_phase`` must itself enforce that each phase sees only its permitted
    rows/labels. Candidate runs request only their target version. Its final
    calls request all available versions (including B0/B1/V4/V5).
    """
    empirical_status = _require_data_evidence(evidence, allow_fixture)

    def score_candidate(
        version: str, ridge: float, history_days: int | None,
        earlier: Mapping[str, tuple[float, int | None]],
    ) -> tuple[float | None, int]:
        settings = dict(earlier)
        settings[version] = (ridge, history_days)
        output = run_phase("validation", MappingProxyType(settings), version)
        return score_validation_rank_ic(output, version)

    selection = select_validation_hyperparameters(
        score_candidate, min_valid_ic_dates=min_valid_ic_dates
    )
    frozen = MappingProxyType({
        "V1": (selection.hyperparameters.v1_ridge, None),
        "V2": (selection.hyperparameters.v2_ridge, None),
        "V3": (selection.hyperparameters.v3_ridge, selection.hyperparameters.v3_history_days),
    })
    validation_output = run_phase("validation", frozen, None)

    def execute_test(_settings: GateHyperparameters) -> T:
        return run_phase("test", frozen, None)

    test_output = run_frozen_test(selection, execute_test)
    reported = dict(report_versions(test_output))
    unknown = set(reported) - set(ALL_VERSIONS)
    if unknown:
        raise ValueError(f"unknown reported versions: {sorted(unknown)}")
    status = {name: reported.get(name, "not_evaluable") for name in ALL_VERSIONS}
    if any(status[name] != "available" for name in CORE_VERSIONS):
        raise ValueError("test phase lacks a required B0/V1/V2/V3 version")
    if any(value not in {"available", "not_evaluable"} for value in status.values()):
        raise ValueError("invalid version status")
    return PipelineResult(
        evidence=evidence,
        selection=selection,
        validation_output=validation_output,
        test_output=test_output,
        version_status=MappingProxyType(status),
        empirical_status=empirical_status,
    )
