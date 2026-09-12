"""Structural point-in-time audit for candidate observed NALE input panels.

Passing this audit is not proof that a vendor supplied genuine historical data.
Independent raw-source and licensing checks remain mandatory before research.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

import numpy as np
import pandas as pd


EMBEDDING_COLUMNS = tuple(f"embedding_{index:03d}" for index in range(768))
SOURCE_NAMES = ("prices", "benchmark", "features", "scores", "edges")
PANEL_COLUMNS = {
    "prices": {"date", "code", "close", "available_at", "decision_cutoff", "source_id",
               "trade_status", "volume", "limit_status", "adjustment_basis"},
    "benchmark": {"date", "close", "available_at", "decision_cutoff", "source_id"},
    "features": {"date", "code", "available_at", "decision_cutoff", "source_id",
                 "source_doc_id", "source_published_at", "source_revision_id", "embedding_version",
                 *EMBEDDING_COLUMNS},
    "scores": {"date", "code", "S0", "available_at", "decision_cutoff", "source_id", "score_version"},
    "edges": {"target_code", "neighbor_code", "weight", "valid_from", "valid_to",
              "available_at", "source_id", "source_revision_id"},
}


@dataclass(frozen=True)
class SourceClaim:
    kind: str
    provider: str
    source_uri: str
    raw_sha256: str


@dataclass(frozen=True)
class CandidateSources:
    prices: pd.DataFrame
    benchmark: pd.DataFrame
    features: pd.DataFrame
    scores: pd.DataFrame
    edges: pd.DataFrame
    claims: Mapping[str, SourceClaim]


@dataclass(frozen=True)
class StructuralAudit:
    status: str
    issues: tuple[str, ...]
    stock_count: int
    signal_day_count: int
    source_claims_verified: bool
    minimum_stocks: int
    minimum_days: int


def _valid_dates(frame: pd.DataFrame, column: str, name: str, issues: list[str]) -> pd.Series | None:
    raw = frame[column]
    if raw.isna().any() or not raw.astype(str).str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        issues.append(f"{name}.{column} must be ISO dates")
        return None
    parsed = pd.to_datetime(raw, format="%Y-%m-%d", errors="coerce")
    if parsed.isna().any():
        issues.append(f"{name}.{column} has invalid calendar dates")
        return None
    return parsed


def _valid_timestamps(frame: pd.DataFrame, column: str, name: str, issues: list[str]) -> pd.Series | None:
    raw = frame[column]
    if raw.isna().any() or not raw.astype(str).str.contains(r"(Z|[+-]\d{2}:\d{2})$", regex=True).all():
        issues.append(f"{name}.{column} must have an explicit timezone")
        return None
    parsed = pd.to_datetime(raw, utc=True, errors="coerce")
    if parsed.isna().any():
        issues.append(f"{name}.{column} has invalid timestamps")
        return None
    return parsed


def _codes(frame: pd.DataFrame, column: str, name: str, issues: list[str]) -> None:
    if frame[column].isna().any() or not frame[column].map(
        lambda value: isinstance(value, str) and re.fullmatch(r"[0-9]{6}", value) is not None
    ).all():
        issues.append(f"{name}.{column} must be a six-character string")


def _finite(frame: pd.DataFrame, columns: tuple[str, ...], name: str, issues: list[str]) -> None:
    try:
        values = frame[list(columns)].to_numpy(dtype=np.float64)
        if not np.isfinite(values).all():
            issues.append(f"{name} has nonfinite {columns[0]} data")
    except (TypeError, ValueError):
        issues.append(f"{name} has nonnumeric {columns[0]} data")


def audit_candidate_sources(
    sources: CandidateSources, *, minimum_stocks: int = 30, minimum_days: int = 222,
) -> StructuralAudit:
    """Audit a prepared daily MVP/full panel; never return 'verified observed'."""
    if minimum_stocks < 1 or minimum_days < 1:
        raise ValueError("audit minimums must be positive")
    issues: list[str] = []
    frames = {name: getattr(sources, name) for name in SOURCE_NAMES}
    for name, frame in frames.items():
        if frame.empty:
            issues.append(f"{name} is empty")
        missing = PANEL_COLUMNS[name] - set(frame.columns)
        if missing:
            issues.append(f"{name} missing columns: {','.join(sorted(missing))}")
    if issues:
        return StructuralAudit("BLOCKED", tuple(issues), 0, 0, False, minimum_stocks, minimum_days)

    for name in SOURCE_NAMES:
        claim = sources.claims.get(name)
        if claim is None:
            issues.append(f"{name} source claim missing")
        elif (claim.kind != "observed" or not claim.provider.strip() or not claim.source_uri.strip()
              or re.fullmatch(r"[0-9a-fA-F]{64}", claim.raw_sha256) is None):
            issues.append(f"{name} source claim is synthetic or incomplete")
        if frames[name]["source_id"].isna().any() or frames[name]["source_id"].astype(str).str.strip().eq("").any():
            issues.append(f"{name} has empty source IDs")

    for name in ("prices", "features", "scores"):
        _codes(frames[name], "code", name, issues)
        if frames[name].duplicated(["date", "code"]).any():
            issues.append(f"{name} has duplicate date/code keys")
    for column in ("target_code", "neighbor_code"):
        _codes(sources.edges, column, "edges", issues)
    if sources.benchmark.duplicated(["date"]).any():
        issues.append("benchmark has duplicate dates")
    if sources.edges.duplicated(["target_code", "neighbor_code", "valid_from"]).any():
        issues.append("edges have duplicate revision keys")

    parsed_dates = {}
    for name in ("prices", "benchmark", "features", "scores"):
        frame = frames[name]
        day = _valid_dates(frame, "date", name, issues)
        available = _valid_timestamps(frame, "available_at", name, issues)
        cutoff = _valid_timestamps(frame, "decision_cutoff", name, issues)
        if day is not None:
            parsed_dates[name] = day
        if day is not None and available is not None and cutoff is not None:
            cutoff_local_day = cutoff.dt.tz_convert("Asia/Shanghai").dt.strftime("%Y-%m-%d")
            if not (cutoff_local_day == frame["date"]).all() or (available > cutoff).any():
                issues.append(f"{name} has future-available input or mismatched decision cutoff")

    edge_from = _valid_dates(sources.edges, "valid_from", "edges", issues)
    edge_to_raw = sources.edges["valid_to"]
    if edge_to_raw.notna().any():
        edge_to = pd.to_datetime(edge_to_raw, format="%Y-%m-%d", errors="coerce")
        if edge_to_raw.notna().sum() != edge_to.notna().sum() or (edge_from is not None and (edge_to.dropna() < edge_from[edge_to.notna()]).any()):
            issues.append("edges have invalid retirement dates")
    edge_available = _valid_timestamps(sources.edges, "available_at", "edges", issues)
    if edge_from is not None and edge_available is not None:
        available_day = edge_available.dt.tz_convert("Asia/Shanghai").dt.strftime("%Y-%m-%d")
        if (available_day > sources.edges["valid_from"]).any():
            issues.append("edges backdate relationships before public availability")

    published = _valid_timestamps(sources.features, "source_published_at", "features", issues)
    feature_available = _valid_timestamps(sources.features, "available_at", "features", issues)
    if published is not None and feature_available is not None and (published > feature_available).any():
        issues.append("features predate their source publication")
    for name, column in (("features", "source_doc_id"), ("features", "source_revision_id"),
                         ("features", "embedding_version"), ("scores", "score_version"),
                         ("edges", "source_revision_id")):
        if frames[name][column].isna().any() or frames[name][column].astype(str).str.strip().eq("").any():
            issues.append(f"{name}.{column} is empty")

    _finite(sources.prices, ("close", "volume"), "prices", issues)
    _finite(sources.benchmark, ("close",), "benchmark", issues)
    _finite(sources.features, EMBEDDING_COLUMNS, "features", issues)
    _finite(sources.scores, ("S0",), "scores", issues)
    _finite(sources.edges, ("weight",), "edges", issues)
    if (pd.to_numeric(sources.prices["close"], errors="coerce") <= 0).any():
        issues.append("prices have nonpositive closes")
    if (pd.to_numeric(sources.benchmark["close"], errors="coerce") <= 0).any():
        issues.append("benchmark has nonpositive closes")
    if (pd.to_numeric(sources.edges["weight"], errors="coerce") < 0).any():
        issues.append("edges have negative weights")

    stock_count = int(sources.prices["code"].nunique())
    signal_day_count = int(sources.prices["date"].nunique())
    if stock_count < minimum_stocks or signal_day_count < minimum_days:
        issues.append("insufficient stock/day coverage for requested audit minimums")
    keys = {name: set(zip(frames[name]["date"], frames[name]["code"]))
            for name in ("prices", "features", "scores")}
    if not (keys["prices"] == keys["features"] == keys["scores"]):
        issues.append("price/feature/S0 daily keys do not align")
    if not set(sources.prices["date"]).issubset(set(sources.benchmark["date"])):
        issues.append("benchmark misses price signal days")

    return StructuralAudit(
        "BLOCKED" if issues else "STRUCTURAL_PASS_PROVENANCE_UNVERIFIED",
        tuple(issues), stock_count, signal_day_count, False,
        minimum_stocks, minimum_days,
    )
