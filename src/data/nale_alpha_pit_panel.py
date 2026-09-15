"""Materialize revisioned NALE inputs for an explicit decision-time calendar."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from src.data.nale_alpha_asof import AsOfError, select_asof_revision


@dataclass(frozen=True)
class PointInTimePanel:
    features: pd.DataFrame
    s0: pd.DataFrame
    edges: pd.DataFrame
    decision_cutoffs: dict[str, str]


def materialize_point_in_time_panel(
    features: pd.DataFrame,
    s0: pd.DataFrame,
    edges: pd.DataFrame,
    decision_cutoffs: Mapping[str, str],
    *,
    feature_available_at: str = "available_at",
    s0_available_at: str = "available_at",
    edge_available_at: str = "source_available_at",
    edge_source: str = "source_code",
    edge_target: str = "target_code",
    edge_effective_from: str = "effective_from",
    edge_effective_to: str = "effective_to",
) -> PointInTimePanel:
    """Select only data known by each cutoff; missing feature/S0 days fail closed."""
    if not decision_cutoffs:
        raise AsOfError("decision_cutoffs cannot be empty")
    if "date" not in features.columns or "date" not in s0.columns:
        raise AsOfError("features and s0 require a date column")
    feature_parts: list[pd.DataFrame] = []
    s0_parts: list[pd.DataFrame] = []
    edge_parts: list[pd.DataFrame] = []
    for day in sorted(decision_cutoffs):
        cutoff = decision_cutoffs[day]
        feature_candidates = features.loc[features["date"].eq(day)]
        s0_candidates = s0.loc[s0["date"].eq(day)]
        if feature_candidates.empty or s0_candidates.empty:
            raise AsOfError(f"{day}: features or s0 have no candidate rows")
        selected_features = select_asof_revision(
            feature_candidates, signal_date=day, decision_cutoff=cutoff,
            keys=("date", "code"), available_at_column=feature_available_at,
        )
        selected_s0 = select_asof_revision(
            s0_candidates, signal_date=day, decision_cutoff=cutoff,
            keys=("date", "code"), available_at_column=s0_available_at,
        )
        if selected_features.empty or selected_s0.empty:
            raise AsOfError(f"{day}: features or s0 were unavailable at the decision cutoff")
        feature_codes = set(selected_features["code"])
        s0_codes = set(selected_s0["code"])
        if feature_codes != s0_codes:
            raise AsOfError(f"{day}: feature and s0 stock keys differ")
        if any(not isinstance(code, str) or re.fullmatch(r"\d{6}", code) is None for code in feature_codes):
            raise AsOfError(f"{day}: stock codes must be six-digit strings")
        selected_edges = select_asof_revision(
            edges, signal_date=day, decision_cutoff=cutoff,
            keys=(edge_source, edge_target), available_at_column=edge_available_at,
            date_column=None, effective_from_column=edge_effective_from,
            effective_to_column=edge_effective_to,
        )
        selected_edges = selected_edges.copy()
        selected_edges["signal_date"] = day
        feature_parts.append(selected_features)
        s0_parts.append(selected_s0)
        edge_parts.append(selected_edges)
    return PointInTimePanel(
        features=pd.concat(feature_parts, ignore_index=True),
        s0=pd.concat(s0_parts, ignore_index=True),
        edges=pd.concat(edge_parts, ignore_index=True),
        decision_cutoffs=dict(sorted(decision_cutoffs.items())),
    )
