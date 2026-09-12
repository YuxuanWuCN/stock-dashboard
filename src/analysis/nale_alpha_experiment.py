"""Compose the existing NALE walk-forward, validation selector and metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

import pandas as pd

from src.analysis.nale_alpha_metrics import EvaluationResult, evaluate_versions
from src.analysis.nale_alpha_phase_runner import make_walkforward_phase_runner
from src.analysis.nale_alpha_pipeline import (
    ALL_VERSIONS,
    DataEvidence,
    PipelineResult,
    run_nale_alpha_pipeline,
)
from src.analysis.nale_alpha_walkforward import WalkForwardConfig, WalkForwardResult
from src.graph.nale_alpha_network import NetworkSnapshot


@dataclass(frozen=True)
class PreparedExperimentResult:
    pipeline: PipelineResult[WalkForwardResult]
    validation_metrics: EvaluationResult
    test_metrics: EvaluationResult


def _score_validation(
    output: WalkForwardResult, version: str, *, min_stocks: int, horizon_days: int,
) -> tuple[float | None, int]:
    if output.phase != "validation":
        raise ValueError("hyperparameters may only be scored on validation")
    metrics = evaluate_versions(
        output.predictions, horizon_days=horizon_days, min_stocks=min_stocks,
        bootstrap_iterations=10, seed=42,
    )
    rows = metrics.version_comparison.loc[metrics.version_comparison["version"].eq(version)]
    if len(rows) != 1:
        return None, 0
    row = rows.iloc[0]
    count = row["n_valid_ic_dates"]
    value = row["rank_ic_mean"]
    if pd.isna(count) or pd.isna(value) or not math.isfinite(float(value)):
        return None, 0
    return float(value), int(count)


def _reported_versions(output: WalkForwardResult) -> Mapping[str, str]:
    if "version" not in output.predictions.columns:
        raise ValueError("walk-forward predictions require version")
    present = set(output.predictions["version"].dropna())
    unknown = present - set(ALL_VERSIONS)
    if unknown:
        raise ValueError(f"unknown predicted versions: {sorted(unknown)}")
    return {name: "available" if name in present else "not_evaluable" for name in ALL_VERSIONS}


def _require_declared_label_horizon(
    output: WalkForwardResult, horizon_days: int,
) -> WalkForwardResult:
    if horizon_days == 20:
        predictions = output.predictions
        if (predictions.empty or "label_horizon_days" not in predictions.columns
                or not predictions["label_horizon_days"].eq(20).all()):
            raise ValueError("20-day study requires explicitly declared 20-day labels")
    return output


def run_prepared_nale_experiment(
    panel: pd.DataFrame,
    networks: Mapping[str, NetworkSnapshot],
    trading_dates: Sequence[str],
    base_config: WalkForwardConfig,
    *,
    evidence: DataEvidence,
    start_date: str | None = None,
    allow_fixture: bool = False,
    min_valid_ic_dates: int = 20,
    min_stocks: int = 20,
    horizon_days: int = 5,
    bootstrap_iterations: int = 2000,
) -> PreparedExperimentResult:
    """Tune on validation, freeze, run one test, and evaluate both OOS phases."""
    if horizon_days not in (5, 20):
        raise ValueError("only separately declared 5/20-day studies are supported")
    phase_runner = make_walkforward_phase_runner(
        panel, networks, trading_dates, base_config,
        evidence=evidence, start_date=start_date, allow_fixture=allow_fixture,
    )
    pipeline = run_nale_alpha_pipeline(
        evidence=evidence,
        run_phase=lambda *args, **kwargs: _require_declared_label_horizon(
            phase_runner(*args, **kwargs), horizon_days
        ),
        score_validation_rank_ic=lambda output, version: _score_validation(
            output, version, min_stocks=min_stocks, horizon_days=horizon_days
        ),
        report_versions=_reported_versions,
        allow_fixture=allow_fixture,
        min_valid_ic_dates=min_valid_ic_dates,
    )
    validation_metrics = evaluate_versions(
        pipeline.validation_output.predictions, horizon_days=horizon_days,
        min_stocks=min_stocks, bootstrap_iterations=bootstrap_iterations, seed=42,
    )
    test_metrics = evaluate_versions(
        pipeline.test_output.predictions, horizon_days=horizon_days,
        min_stocks=min_stocks, bootstrap_iterations=bootstrap_iterations, seed=42,
    )
    return PreparedExperimentResult(pipeline, validation_metrics, test_metrics)
