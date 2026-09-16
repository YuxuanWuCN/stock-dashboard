"""Bridge point-in-time inputs to the existing NALE panel and network APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import pandas as pd

from src.data.nale_alpha_panel import validate_nale_panel
from src.data.nale_alpha_pit_panel import PointInTimePanel
from src.graph.nale_alpha_network import NetworkSnapshot, make_network_snapshot


FEATURE_METADATA = ("date", "code", "available_at", "source_published_at", "feature_source_id", "feature_version", "embedding_version")


@dataclass(frozen=True)
class CanonicalNALEInputs:
    panel: pd.DataFrame
    networks: Mapping[str, NetworkSnapshot]
    embedding_columns: tuple[str, ...]
    trading_dates: tuple[str, ...]


def assemble_canonical_inputs(
    point_in_time: PointInTimePanel,
    edge_ledger: pd.DataFrame,
    embedding_columns: Sequence[str],
    *,
    graph_history_id: str,
    declared_pca_version: str,
    subgraph_policy: str = "strict",
    allow_fixture: bool = False,
) -> CanonicalNALEInputs:
    """Use observed historical inputs, never deriving source time from future rows."""
    columns = tuple(embedding_columns)
    if len(columns) != len(set(columns)) or len(columns) < 10:
        raise ValueError("at least ten distinct embedding columns are required")
    if not allow_fixture and len(columns) != 768:
        raise ValueError("real NALE input requires exactly 768 embedding columns")
    if not graph_history_id or not declared_pca_version:
        raise ValueError("graph history and declared PCA version are required")
    features = point_in_time.features
    s0 = point_in_time.s0
    missing = sorted((set(FEATURE_METADATA) | set(columns)) - set(features.columns))
    if missing:
        raise ValueError(f"feature columns missing: {missing}")
    if not {"date", "code", "available_at", "s0"}.issubset(s0.columns):
        raise ValueError("S0 requires date, code, available_at, and s0")
    if "s0" in features.columns:
        raise ValueError("feature input must not duplicate the S0 column")
    combined = features.rename(columns={"available_at": "feature_available_at"}).merge(
        s0[["date", "code", "available_at", "s0"]].rename(columns={"available_at": "s0_available_at"}),
        on=["date", "code"], how="outer", validate="one_to_one", indicator=True,
    )
    if not combined["_merge"].eq("both").all():
        raise ValueError("feature and S0 date/code keys differ")
    combined = combined.drop(columns="_merge")
    networks: dict[str, NetworkSnapshot] = {}
    for day, cutoff in sorted(point_in_time.decision_cutoffs.items()):
        mask = combined["date"].eq(day)
        if not mask.any():
            raise ValueError(f"{day}: no feature/S0 rows")
        codes = tuple(sorted(combined.loc[mask, "code"].tolist()))
        snapshot = make_network_snapshot(
            edge_ledger, codes, cutoff,
            graph_history_id=graph_history_id,
            subgraph_policy=subgraph_policy,
            allow_fixture=allow_fixture,
        )
        networks[day] = snapshot
        combined.loc[mask, "signal_at"] = cutoff
        combined.loc[mask, "available_at"] = cutoff
        combined.loc[mask, "network_available_at"] = cutoff
        combined.loc[mask, "network_evidence_id"] = f"graph-snapshot:{graph_history_id}:{day}"
        combined.loc[mask, "pca_version"] = declared_pca_version
    validated = validate_nale_panel(combined, columns)
    return CanonicalNALEInputs(
        panel=validated,
        networks=networks,
        embedding_columns=columns,
        trading_dates=tuple(sorted(point_in_time.decision_cutoffs)),
    )
