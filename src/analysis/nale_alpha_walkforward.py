"""Calendar-frozen monthly walk-forward core for B0 and ten-PC V1/V2/V3.

This module consumes audited feature/label rows and dated network snapshots.
It never tunes hyperparameters or labels an engineering fixture as market data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from src.data.nale_alpha_panel import PC_COLUMNS
from src.graph.nale_alpha_adapter import propagate_nale
from src.graph.nale_alpha_network import NetworkSnapshot
from src.pricing.nale_alpha_models import TrainingPanel, fit_b0_calibration, fit_gate


@dataclass(frozen=True)
class WalkForwardConfig:
    train_days: int = 126
    validation_days: int = 42
    test_days: int = 42
    purge_days: int = 6
    ridge_v1: float = 0.01
    ridge_v2: float = 0.01
    ridge_v3: float = 0.01
    half_life_days: float = 20.0


@dataclass(frozen=True)
class DatePlan:
    train_dates: tuple[str, ...]
    purged_after_train: tuple[str, ...]
    validation_dates: tuple[str, ...]
    purged_after_validation: tuple[str, ...]
    test_dates: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "train_dates": list(self.train_dates),
            "purged_after_train": list(self.purged_after_train),
            "validation_dates": list(self.validation_dates),
            "purged_after_validation": list(self.purged_after_validation),
            "test_dates": list(self.test_dates),
        }


@dataclass(frozen=True)
class WalkForwardResult:
    predictions: pd.DataFrame
    monthly_weights: pd.DataFrame
    date_plan: DatePlan
    phase: str
    evidence_class: str


def _calendar(values: Sequence[str]) -> tuple[str, ...]:
    days = tuple(values)
    if not days or any(not isinstance(day, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day) for day in days):
        raise ValueError("trading calendar requires ISO date strings")
    try:
        for day in days:
            date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("trading calendar contains an invalid date") from exc
    if tuple(sorted(set(days))) != days:
        raise ValueError("trading calendar must be sorted and unique")
    return days


def plan_dates(
    trading_dates: Sequence[str], config: WalkForwardConfig,
    *, start_date: str | None = None,
) -> DatePlan:
    """Freeze partitions from the exchange calendar, independent of outcomes."""
    calendar = _calendar(trading_dates)
    counts = (config.train_days, config.validation_days, config.test_days)
    if any(not isinstance(count, int) or count < 1 for count in counts):
        raise ValueError("train, validation, and test day counts must be positive integers")
    if not isinstance(config.purge_days, int) or config.purge_days < 0:
        raise ValueError("purge_days must be a nonnegative integer")
    needed = sum(counts) + 2 * config.purge_days
    if start_date is None:
        start = 0
    else:
        try:
            start = calendar.index(start_date)
        except ValueError as exc:
            raise ValueError("start_date is absent from the trading calendar") from exc
    if len(calendar) - start < needed:
        raise ValueError(f"insufficient trading dates: need {needed}")
    cursor = start
    train = calendar[cursor:cursor + config.train_days]
    cursor += config.train_days
    gap1 = calendar[cursor:cursor + config.purge_days]
    cursor += config.purge_days
    validation = calendar[cursor:cursor + config.validation_days]
    cursor += config.validation_days
    gap2 = calendar[cursor:cursor + config.purge_days]
    cursor += config.purge_days
    test = calendar[cursor:cursor + config.test_days]
    return DatePlan(train, gap1, validation, gap2, test)


def _timestamp(value: object, name: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return stamp.tz_convert("UTC")


def _validated_rows(
    panel: pd.DataFrame,
    networks: Mapping[str, NetworkSnapshot],
    calendar: tuple[str, ...],
    *,
    allow_fixture: bool,
    source_audit_id: str | None,
) -> pd.DataFrame:
    if not isinstance(panel, pd.DataFrame) or panel.empty:
        raise ValueError("aligned experiment panel must be nonempty")
    required = {
        "date", "code", "signal_at", "label_available_at", "s0", "y_excess",
        "pca_version", "feature_source_id", "network_evidence_id",
        "price_source_id", "evidence_class", *PC_COLUMNS,
    }
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"missing experiment columns: {sorted(missing)}")
    rows = panel.copy().reset_index(drop=True)
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}", value) for value in rows["code"]):
        raise ValueError("code must be a six-digit string")
    if rows.duplicated(["date", "code"]).any():
        raise ValueError("duplicate date/code key")
    if any(not isinstance(day, str) or day not in calendar for day in rows["date"]):
        raise ValueError("panel date is absent from the trading calendar")
    for column in ("pca_version", "feature_source_id", "network_evidence_id", "price_source_id"):
        if any(not isinstance(value, str) or not value.strip() for value in rows[column]):
            raise ValueError(f"{column} must be nonempty")
    if rows["pca_version"].nunique() != 1:
        raise ValueError("PCA version must remain frozen across all dates")
    classes = set(rows["evidence_class"])
    if allow_fixture:
        if classes != {"engineering_fixture"}:
            raise ValueError("fixture mode requires explicit engineering_fixture labels")
    elif classes != {"observed_verified"} or not isinstance(source_audit_id, str) or not source_audit_id.strip():
        raise ValueError("observed runs require verified evidence and a source_audit_id")
    for column in ("s0", "y_excess", *PC_COLUMNS):
        try:
            rows[column] = pd.to_numeric(rows[column], errors="raise").astype(np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{column} must be numeric") from exc
        if not np.isfinite(rows[column].to_numpy()).all():
            raise ValueError(f"{column} contains NaN or Inf")
    for column in ("signal_at", "label_available_at"):
        rows[column] = pd.DatetimeIndex([_timestamp(value, column) for value in rows[column]])
    for signal_at, label_at, day in zip(rows["signal_at"], rows["label_available_at"], rows["date"]):
        local = signal_at.tz_convert("Asia/Shanghai")
        if local.date().isoformat() != day or local.hour < 15:
            raise ValueError("signal_at must follow the A-share close on its date")
        if label_at <= signal_at:
            raise ValueError("label_available_at must follow signal_at")

    rows["neighbor_score"] = np.nan
    rows["difference"] = np.nan
    rows["edge_evidence_ids"] = ""
    for day, group in rows.groupby("date", sort=False):
        snapshot = networks.get(day)
        if snapshot is None:
            raise ValueError(f"missing point-in-time network for {day}")
        if set(snapshot.codes) != set(group["code"]):
            raise ValueError("network code universe differs from same-date panel")
        if any(value != snapshot.graph_history_id for value in group["network_evidence_id"]):
            raise ValueError("network_evidence_id does not match the supplied graph history")
        if _timestamp(snapshot.signal_at, "network snapshot time") > group["signal_at"].min():
            raise ValueError("network snapshot uses evidence after a signal")
        if allow_fixture and snapshot.evidence_class != "engineering_fixture":
            raise ValueError("fixture panel requires fixture network evidence")
        if not allow_fixture and snapshot.evidence_class != "observed_claim":
            raise ValueError("verified panel cannot use fixture network evidence")
        ordered = group.set_index("code").loc[list(snapshot.codes)]
        z = ordered.loc[:, list(PC_COLUMNS)].to_numpy(dtype=np.float64)
        base = propagate_nale(snapshot.codes, ordered["s0"].to_numpy(), snapshot.adjacency, z=z)
        rows.loc[ordered.index.map(lambda code: group.loc[group["code"] == code].index[0]), "neighbor_score"] = base.neighbor_score
        rows.loc[ordered.index.map(lambda code: group.loc[group["code"] == code].index[0]), "difference"] = base.difference
        ids = sorted(str(value) for value in snapshot.active_evidence["evidence_id"])
        rows.loc[group.index, "edge_evidence_ids"] = json.dumps(ids, ensure_ascii=False)
    return rows.sort_values(["date", "code"], kind="mergesort").reset_index(drop=True)


def _training_panel(
    rows: pd.DataFrame, day: str, calendar_index: Mapping[str, int],
    plan: DatePlan, train_days: int,
) -> TrainingPanel:
    cutoff = pd.Timestamp(f"{day}T09:30:00+08:00").tz_convert("UTC")
    embargo = set(plan.purged_after_train) | set(plan.purged_after_validation)
    matured = rows.loc[
        (rows["date"] < day)
        & (rows["label_available_at"] < cutoff)
        & (~rows["date"].isin(embargo))
    ]
    mature_dates = sorted(matured["date"].unique())
    if len(mature_dates) < train_days:
        raise ValueError(f"fewer than {train_days} mature training signal dates at {day}")
    selected_dates = set(mature_dates[-train_days:])
    selected = matured.loc[matured["date"].isin(selected_dates)].sort_values(["date", "code"])
    age = np.asarray([calendar_index[day] - calendar_index[value] for value in selected["date"]], dtype=int)
    return TrainingPanel(
        signal_dates=selected["date"].tolist(),
        label_available_at=[value.isoformat() for value in selected["label_available_at"]],
        s0=selected["s0"].to_numpy(dtype=np.float64),
        difference=selected["difference"].to_numpy(dtype=np.float64),
        z=selected.loc[:, list(PC_COLUMNS)].to_numpy(dtype=np.float64),
        excess_return=selected["y_excess"].to_numpy(dtype=np.float64),
        age_trading_days=age,
    )


def _weight_row(version: str, cutoff: str, calibration, gate, config: WalkForwardConfig) -> dict:
    if gate is None:
        record = {
            "version": "B0", "fit_cutoff": cutoff, "gate_fit_cutoff": None,
            "intercept": np.nan, "ridge_lambda": np.nan, "half_life_days": np.nan,
            "calibration_a": calibration.intercept, "calibration_c": calibration.slope,
            "n_signal_dates": calibration.n_signal_dates, "n_rows": calibration.n_rows,
            "converged": True, "objective": np.nan, "gradient_norm": np.nan,
            "gradient_check_error": np.nan, "fallback_reason": None,
        }
        record.update({f"w{index:02d}": np.nan for index in range(1, 11)})
        return record
    record = {
        "version": version, "fit_cutoff": cutoff,
        "gate_fit_cutoff": gate.fit_cutoff,
        "intercept": gate.intercept,
        "ridge_lambda": gate.ridge_lambda,
        "half_life_days": gate.half_life_days,
        "calibration_a": calibration.intercept,
        "calibration_c": calibration.slope,
        "n_signal_dates": gate.n_signal_dates,
        "n_rows": gate.n_rows,
        "converged": gate.converged,
        "objective": gate.objective,
        "gradient_norm": gate.gradient_norm,
        "gradient_check_error": gate.gradient_check_error,
        "fallback_reason": gate.fallback_reason,
    }
    record.update({f"w{index:02d}": float(value) for index, value in enumerate(gate.weights, 1)})
    return record


def run_walkforward(
    panel: pd.DataFrame,
    networks: Mapping[str, NetworkSnapshot],
    trading_dates: Sequence[str],
    config: WalkForwardConfig,
    *,
    phase: str,
    start_date: str | None = None,
    allow_fixture: bool = False,
    source_audit_id: str | None = None,
) -> WalkForwardResult:
    """Predict validation or test with hyperparameters fixed by the caller."""
    if phase not in {"validation", "test"}:
        raise ValueError("phase must be validation or test")
    for penalty in (config.ridge_v1, config.ridge_v2, config.ridge_v3):
        if not np.isfinite(penalty) or penalty < 0:
            raise ValueError("ridge penalties must be finite and nonnegative")
    if not np.isfinite(config.half_life_days) or config.half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    calendar = _calendar(trading_dates)
    plan = plan_dates(calendar, config, start_date=start_date)
    last_day = plan.validation_dates[-1] if phase == "validation" else plan.test_dates[-1]
    if not isinstance(panel, pd.DataFrame) or "date" not in panel.columns:
        raise ValueError("aligned experiment panel requires a date column")
    visible_panel = panel.loc[panel["date"].astype(str) <= last_day]
    rows = _validated_rows(
        visible_panel, networks, calendar, allow_fixture=allow_fixture,
        source_audit_id=source_audit_id,
    )
    required_dates = plan.validation_dates if phase == "validation" else (*plan.validation_dates, *plan.test_dates)
    for day in required_dates:
        if day not in set(rows["date"]):
            raise ValueError(f"prediction date {day} has no aligned rows")
    calendar_index = {day: index for index, day in enumerate(calendar)}
    target_dates = set(plan.validation_dates if phase == "validation" else plan.test_dates)
    timeline = calendar[calendar_index[plan.validation_dates[0]]:calendar_index[last_day] + 1]
    predictions: list[dict] = []
    weights: list[dict] = []
    first_gate = None
    current_gates = {}
    calibration = None
    current_cutoff = None
    previous_month = None

    for day in timeline:
        month = day[:7]
        if day == plan.validation_dates[0] or month != previous_month:
            current_cutoff = pd.Timestamp(f"{day}T09:30:00+08:00").isoformat()
            training = _training_panel(rows, day, calendar_index, plan, config.train_days)
            calibration = fit_b0_calibration(training, fit_cutoff=current_cutoff, min_train_dates=config.train_days)
            if first_gate is None:
                first_gate = fit_gate(
                    training, version="V1", fit_cutoff=current_cutoff,
                    ridge_lambda=config.ridge_v1, min_train_dates=config.train_days,
                )
            current_gates = {
                "V1": first_gate,
                "V2": fit_gate(
                    training, version="V2", fit_cutoff=current_cutoff,
                    ridge_lambda=config.ridge_v2, min_train_dates=config.train_days,
                ),
                "V3": fit_gate(
                    training, version="V3", fit_cutoff=current_cutoff,
                    ridge_lambda=config.ridge_v3,
                    half_life_days=config.half_life_days, min_train_dates=config.train_days,
                ),
            }
            for version in ("B0", "V1", "V2", "V3"):
                weights.append(_weight_row(
                    version, current_cutoff, calibration,
                    None if version == "B0" else current_gates[version], config,
                ))
        previous_month = month
        if day not in target_dates:
            continue
        group = rows.loc[rows["date"] == day]
        snapshot = networks[day]
        ordered = group.set_index("code").loc[list(snapshot.codes)]
        z = ordered.loc[:, list(PC_COLUMNS)].to_numpy(dtype=np.float64)
        s0 = ordered["s0"].to_numpy(dtype=np.float64)
        baseline = propagate_nale(snapshot.codes, s0, snapshot.adjacency, z=z)
        for version in ("B0", "V1", "V2", "V3"):
            gate = None if version == "B0" else current_gates[version]
            if gate is None:
                propagated = baseline
            elif gate.fallback_reason is not None:
                propagated = propagate_nale(snapshot.codes, s0, snapshot.adjacency, z=z, alpha_override=0.4)
            else:
                propagated = propagate_nale(
                    snapshot.codes, s0, snapshot.adjacency,
                    z=z, weights=gate.weights, intercept=gate.intercept,
                )
            calibrated_prediction = calibration.predict(propagated.score)
            for index, code in enumerate(snapshot.codes):
                evidence_row = ordered.loc[code]
                row = {
                    "date": day, "code": code, "phase": phase,
                    "version": version, "s0": float(propagated.s0[index]),
                    "neighbor_score": float(propagated.neighbor_score[index]),
                    "difference": float(propagated.difference[index]),
                    "u": 0.0 if propagated.u is None else float(propagated.u[index]),
                    "alpha_nale": float(propagated.alpha_nale[index]),
                    "score": float(propagated.score[index]),
                    "predicted_excess": float(calibrated_prediction[index]),
                    "y_excess": float(evidence_row["y_excess"]),
                    "label_available_at": evidence_row["label_available_at"].isoformat(),
                    "training_cutoff": current_cutoff,
                    "gate_fit_cutoff": None if gate is None else gate.fit_cutoff,
                    "fallback_reason": "fixed_B0" if gate is None else gate.fallback_reason,
                    "pca_version": evidence_row["pca_version"],
                    "feature_source_id": evidence_row["feature_source_id"],
                    "network_evidence_id": evidence_row["network_evidence_id"],
                    "edge_evidence_ids": evidence_row["edge_evidence_ids"],
                    "price_source_id": evidence_row["price_source_id"],
                    "evidence_class": evidence_row["evidence_class"],
                    "source_audit_id": source_audit_id,
                }
                for component in range(10):
                    row[f"PC{component + 1:02d}"] = float(z[index, component])
                    row[f"contribution_{component + 1:02d}"] = (
                        0.0 if propagated.contributions is None
                        else float(propagated.contributions[index, component])
                    )
                predictions.append(row)
    result = pd.DataFrame(predictions)
    return WalkForwardResult(
        predictions=result,
        monthly_weights=pd.DataFrame(weights),
        date_plan=plan,
        phase=phase,
        evidence_class="engineering_fixture" if allow_fixture else "observed_verified",
    )
