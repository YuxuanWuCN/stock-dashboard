"""Construct a point-in-time NALE adjacency matrix from a revision ledger.

Rows of W are targets and columns are information sources. A zero-weight
revision is a tombstone. The propagation adapter owns row normalization and
self-loops for isolated rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
import pandas as pd


EDGE_COLUMNS = (
    "source_code", "target_code", "weight", "source_published_at",
    "available_at", "valid_from", "valid_to", "evidence_id",
    "relationship_version", "is_observed",
)


def _timestamp(value: object, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return timestamp.tz_convert("UTC")


def _iso_date(value: object, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError(f"{field} must be an ISO calendar date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid calendar date") from exc
    return value


def validate_edge_ledger(edges: pd.DataFrame, *, allow_fixture: bool = False) -> pd.DataFrame:
    """Validate evidence fields without discarding future revisions."""
    if not isinstance(edges, pd.DataFrame) or edges.empty:
        raise ValueError("edge ledger must be a nonempty DataFrame")
    missing = set(EDGE_COLUMNS) - set(edges.columns)
    if missing:
        raise ValueError(f"missing edge columns: {sorted(missing)}")
    ledger = edges.copy()
    for field in ("source_code", "target_code"):
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}", value) for value in ledger[field]):
            raise ValueError(f"{field} must be a six-digit string")
    for field in ("evidence_id", "relationship_version"):
        if any(not isinstance(value, str) or not value.strip() for value in ledger[field]):
            raise ValueError(f"{field} must be nonempty")
    if any(not isinstance(value, (bool, np.bool_)) for value in ledger["is_observed"]):
        raise ValueError("is_observed must contain booleans")
    if not allow_fixture and not ledger["is_observed"].all():
        raise ValueError("non-observed network edges require engineering-fixture mode")
    try:
        ledger["weight"] = pd.to_numeric(ledger["weight"], errors="raise").astype(np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("edge weight must be numeric") from exc
    if not np.isfinite(ledger["weight"].to_numpy()).all() or (ledger["weight"] < 0).any():
        raise ValueError("edge weight must be finite and nonnegative")
    ledger["source_published_at"] = pd.DatetimeIndex([
        _timestamp(value, "source_published_at") for value in ledger["source_published_at"]
    ])
    ledger["available_at"] = pd.DatetimeIndex([
        _timestamp(value, "available_at") for value in ledger["available_at"]
    ])
    if (ledger["source_published_at"] > ledger["available_at"]).any():
        raise ValueError("edge source was published after its claimed availability")
    ledger["valid_from"] = [_iso_date(value, "valid_from") for value in ledger["valid_from"]]
    valid_until = []
    for value in ledger["valid_to"]:
        valid_until.append(None if value is None or pd.isna(value) else _iso_date(value, "valid_to"))
    ledger["valid_to"] = valid_until
    if any(end is not None and end <= start for start, end in zip(ledger["valid_from"], ledger["valid_to"])):
        raise ValueError("valid_to must follow valid_from and is exclusive")
    if ledger.duplicated(["source_code", "target_code", "available_at"]).any():
        raise ValueError("duplicate edge revision at one availability time")
    return ledger


@dataclass(frozen=True)
class NetworkSnapshot:
    codes: tuple[str, ...]
    adjacency: np.ndarray
    signal_at: str
    graph_history_id: str
    active_evidence: pd.DataFrame
    isolated_codes: tuple[str, ...]
    dropped_neighbors: tuple[tuple[str, str, str], ...]
    evidence_class: str


def make_network_snapshot(
    edges: pd.DataFrame,
    codes: Sequence[str],
    signal_at: str,
    *,
    graph_history_id: str,
    subgraph_policy: str = "strict",
    allow_fixture: bool = False,
) -> NetworkSnapshot:
    """Select revisions known at a close and construct unnormalized W."""
    ordered_codes = tuple(codes)
    if not ordered_codes or any(not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code) for code in ordered_codes):
        raise ValueError("codes must be nonempty six-digit strings")
    if len(set(ordered_codes)) != len(ordered_codes):
        raise ValueError("duplicate stock code")
    if not isinstance(graph_history_id, str) or not graph_history_id.strip():
        raise ValueError("graph_history_id is required to trace the full edge ledger")
    if subgraph_policy not in {"strict", "induced"}:
        raise ValueError("subgraph_policy must be strict or induced")
    cutoff = _timestamp(signal_at, "signal_at")
    local_cutoff = cutoff.tz_convert("Asia/Shanghai")
    if local_cutoff.hour < 15:
        raise ValueError("signal_at must be after the A-share close")
    decision_day = local_cutoff.date().isoformat()
    ledger = validate_edge_ledger(edges, allow_fixture=allow_fixture)
    eligible = ledger.loc[
        (ledger["available_at"] <= cutoff) & (ledger["valid_from"] <= decision_day)
    ]
    latest = eligible.sort_values(
        ["available_at", "source_code", "target_code"], kind="mergesort"
    ).drop_duplicates(["source_code", "target_code"], keep="last")
    active = latest.loc[
        latest["valid_to"].isna() | (latest["valid_to"] > decision_day)
    ]
    active = active.loc[active["weight"] > 0].copy()
    included = set(ordered_codes)
    index = {code: position for position, code in enumerate(ordered_codes)}
    adjacency = np.zeros((len(ordered_codes), len(ordered_codes)), dtype=np.float64)
    dropped: list[tuple[str, str, str]] = []
    for row in active.itertuples(index=False):
        if row.target_code not in included:
            continue
        if row.source_code not in included:
            if subgraph_policy == "strict":
                raise ValueError(f"out-of-universe network neighbor: {row.source_code} -> {row.target_code}")
            dropped.append((row.target_code, row.source_code, row.evidence_id))
            continue
        adjacency[index[row.target_code], index[row.source_code]] = float(row.weight)
    isolated = tuple(code for code, total in zip(ordered_codes, adjacency.sum(axis=1)) if total == 0)
    return NetworkSnapshot(
        codes=ordered_codes,
        adjacency=adjacency,
        signal_at=cutoff.isoformat(),
        graph_history_id=graph_history_id,
        active_evidence=active,
        isolated_codes=isolated,
        dropped_neighbors=tuple(dropped),
        evidence_class=("observed_claim" if ledger["is_observed"].all() else "engineering_fixture"),
    )
