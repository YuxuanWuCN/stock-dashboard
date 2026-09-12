import pandas as pd
import pytest

from src.data.nale_alpha_canonical import assemble_canonical_inputs
from src.data.nale_alpha_pit_panel import PointInTimePanel


def _inputs():
    cutoffs = {
        "2024-01-02": "2024-01-02T17:00:00+08:00",
        "2024-01-03": "2024-01-03T17:00:00+08:00",
    }
    feature_rows = []
    s0_rows = []
    for day in cutoffs:
        for code in ("000001", "000002"):
            feature_rows.append({
                "date": day, "code": code, "available_at": f"{day}T16:00:00+08:00",
                "source_published_at": f"{day}T15:00:00+08:00",
                "feature_source_id": "fixture-source", "feature_version": "fixture-v1",
                "embedding_version": "fixture-v1",
                **{f"embedding_{i:03d}": float(i + 1) for i in range(10)},
            })
            s0_rows.append({"date": day, "code": code, "available_at": f"{day}T16:00:00+08:00", "s0": 0.2})
    ledger = pd.DataFrame([{
        "source_code": "000001", "target_code": "000002", "weight": 1.0,
        "source_published_at": "2024-01-02T12:00:00+08:00",
        "available_at": "2024-01-02T12:00:00+08:00",
        "valid_from": "2024-01-02", "valid_to": None,
        "evidence_id": "fixture-edge", "is_observed": True,
        "relationship_version": "fixture-v1",
    }])
    point_in_time = PointInTimePanel(
        features=pd.DataFrame(feature_rows), s0=pd.DataFrame(s0_rows),
        edges=pd.DataFrame(), decision_cutoffs=cutoffs,
    )
    return point_in_time, ledger


def test_canonical_fixture_uses_existing_panel_and_network_contracts():
    point_in_time, ledger = _inputs()
    result = assemble_canonical_inputs(
        point_in_time, ledger, [f"embedding_{i:03d}" for i in range(10)],
        graph_history_id="fixture-graph", declared_pca_version="fixture-pca",
        allow_fixture=True,
    )
    assert len(result.panel) == 4
    assert result.panel["available_at"].eq(result.panel["signal_at"]).all()
    assert result.panel["feature_available_at"].lt(result.panel["available_at"]).all()
    assert set(result.networks) == set(point_in_time.decision_cutoffs)
    assert result.embedding_columns[0] == "embedding_000"


def test_ten_dimension_fixture_cannot_be_misdeclared_as_real():
    point_in_time, ledger = _inputs()
    with pytest.raises(ValueError, match="768"):
        assemble_canonical_inputs(
            point_in_time, ledger, [f"embedding_{i:03d}" for i in range(10)],
            graph_history_id="fixture-graph", declared_pca_version="fixture-pca",
        )


def test_missing_publication_time_fails_closed():
    point_in_time, ledger = _inputs()
    point_in_time.features.drop(columns="source_published_at", inplace=True)
    with pytest.raises(ValueError, match="source_published_at"):
        assemble_canonical_inputs(
            point_in_time, ledger, [f"embedding_{i:03d}" for i in range(10)],
            graph_history_id="fixture-graph", declared_pca_version="fixture-pca",
            allow_fixture=True,
        )
