"""Adapt the existing walk-forward engine to the NALE selection pipeline."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Callable, Mapping, Sequence

import pandas as pd

from src.analysis.nale_alpha_pipeline import DataEvidence
from src.analysis.nale_alpha_walkforward import WalkForwardConfig, WalkForwardResult, run_walkforward
from src.graph.nale_alpha_network import NetworkSnapshot


TUNABLE_VERSIONS = frozenset({"V1", "V2", "V3"})


def _version_column(frame: pd.DataFrame) -> str:
    for name in ("version", "model_version"):
        if name in frame.columns:
            return name
    raise ValueError("walk-forward table has no model version column")


def make_walkforward_phase_runner(
    panel: pd.DataFrame,
    networks: Mapping[str, NetworkSnapshot],
    trading_dates: Sequence[str],
    base_config: WalkForwardConfig,
    *,
    evidence: DataEvidence,
    start_date: str | None = None,
    allow_fixture: bool = False,
) -> Callable[[str, Mapping[str, tuple[float, int | None]], str | None], WalkForwardResult]:
    """Bind prepared inputs to a phase-safe runner; no authenticity is inferred."""
    if not allow_fixture and not evidence.independently_verified:
        raise ValueError("independently verified real-data evidence is required")
    if not evidence.audit_id:
        raise ValueError("source audit id is required")

    def run_phase(
        phase: str,
        parameters: Mapping[str, tuple[float, int | None]],
        target_version: str | None,
    ) -> WalkForwardResult:
        if phase not in {"validation", "test"}:
            raise ValueError("phase must be validation or test")
        if phase == "test" and target_version is not None:
            raise ValueError("test must request the frozen full-version run")
        if target_version is not None and (target_version not in TUNABLE_VERSIONS or target_version not in parameters):
            raise ValueError("only an explicitly configured V1/V2/V3 validation candidate is allowed")
        if set(parameters) - TUNABLE_VERSIONS:
            raise ValueError("unsupported version hyperparameters")
        overrides: dict[str, float] = {}
        for version, (ridge, history_days) in parameters.items():
            if not math.isfinite(ridge) or ridge < 0:
                raise ValueError(f"{version}: ridge must be finite and nonnegative")
            overrides[{"V1": "ridge_v1", "V2": "ridge_v2", "V3": "ridge_v3"}[version]] = ridge
            if version == "V3":
                if history_days is None or not math.isfinite(history_days) or history_days <= 0:
                    raise ValueError("V3 half-life must be positive and finite")
                overrides["half_life_days"] = float(history_days)
            elif history_days is not None:
                raise ValueError(f"{version}: half-life is not applicable")
        config = replace(base_config, **overrides)
        result = run_walkforward(
            panel, networks, trading_dates, config,
            phase=phase, start_date=start_date,
            allow_fixture=allow_fixture, source_audit_id=evidence.audit_id,
        )
        if result.phase != phase:
            raise ValueError("walk-forward returned the wrong phase")
        if target_version is None:
            return result
        prediction_version = _version_column(result.predictions)
        predictions = result.predictions.loc[result.predictions[prediction_version].eq(target_version)].copy()
        if predictions.empty:
            raise ValueError(f"{target_version}: no candidate predictions")
        weight_version = _version_column(result.monthly_weights)
        monthly_weights = result.monthly_weights.loc[
            result.monthly_weights[weight_version].eq(target_version)
        ].copy()
        return WalkForwardResult(
            predictions=predictions,
            monthly_weights=monthly_weights,
            date_plan=result.date_plan,
            phase=result.phase,
            evidence_class=result.evidence_class,
        )

    return run_phase
