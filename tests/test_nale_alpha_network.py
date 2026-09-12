"""Small edge-ledger fixtures; no historical supply-chain claims."""

import numpy as np
import pandas as pd
import pytest

from src.graph.nale_alpha_adapter import propagate_nale
from src.graph.nale_alpha_network import make_network_snapshot, validate_edge_ledger


def _edge(source="000001", target="000002", weight=2.0, *, day="2024-06-03", observed=False):
    return {
        "source_code": source,
        "target_code": target,
        "weight": weight,
        "source_published_at": day + "T10:00:00+08:00",
        "available_at": day + "T14:00:00+08:00",
        "valid_from": day,
        "valid_to": None,
        "evidence_id": "math-fixture-" + day + "-" + source + "-" + target,
        "relationship_version": "v1",
        "is_observed": observed,
    }


def _snapshot(edges, *, at="2024-06-03T15:10:00+08:00", codes=("000001", "000002"), **kwargs):
    return make_network_snapshot(
        pd.DataFrame(edges), codes, at, graph_history_id="fixture-ledger-v1",
        allow_fixture=True, **kwargs,
    )


def test_rows_are_targets_and_adapter_handles_isolated_nodes():
    snapshot = _snapshot([_edge()])
    np.testing.assert_allclose(snapshot.adjacency, [[0, 0], [2, 0]])
    assert snapshot.isolated_codes == ("000001",)
    assert len(snapshot.active_evidence) == 1
    assert snapshot.evidence_class == "engineering_fixture"
    result = propagate_nale(snapshot.codes, [0.2, 0.8], snapshot.adjacency)
    np.testing.assert_allclose(result.score, [0.2, 0.56])


def test_future_revision_cannot_change_earlier_snapshot_and_tombstone_removes_edge():
    first = _edge()
    future = _edge(weight=9.0, day="2024-06-04")
    future["relationship_version"] = "v2"
    deleted = _edge(weight=0.0, day="2024-06-05")
    deleted["relationship_version"] = "v3"
    early = _snapshot([first])
    with_future = _snapshot([first, future, deleted])
    np.testing.assert_array_equal(early.adjacency, with_future.adjacency)
    updated = _snapshot([first, future], at="2024-06-04T15:10:00+08:00")
    assert updated.adjacency[1, 0] == 9.0
    removed = _snapshot([first, future, deleted], at="2024-06-05T15:10:00+08:00")
    assert removed.adjacency[1, 0] == 0.0
    assert removed.isolated_codes == ("000001", "000002")


def test_future_effective_date_does_not_displace_current_revision():
    first = _edge()
    future_effect = _edge(weight=7.0, day="2024-06-03")
    future_effect["available_at"] = "2024-06-03T14:30:00+08:00"
    future_effect["valid_from"] = "2024-06-10"
    future_effect["relationship_version"] = "v2"
    snapshot = _snapshot([first, future_effect])
    assert snapshot.adjacency[1, 0] == 2.0


def test_out_of_universe_neighbors_require_explicit_policy():
    edge = _edge(source="000003")
    with pytest.raises(ValueError, match="out-of-universe"):
        _snapshot([edge])
    induced = _snapshot([edge], subgraph_policy="induced")
    assert induced.dropped_neighbors == (("000002", "000003", edge["evidence_id"]),)
    assert induced.isolated_codes == ("000001", "000002")


def test_fixture_default_rejects_and_bad_evidence_fails_closed():
    edge = _edge()
    with pytest.raises(ValueError, match="non-observed"):
        validate_edge_ledger(pd.DataFrame([edge]))
    with pytest.raises(ValueError, match="duplicate"):
        validate_edge_ledger(pd.DataFrame([edge, edge]), allow_fixture=True)
    bad = dict(edge, weight=-1.0)
    with pytest.raises(ValueError, match="nonnegative"):
        validate_edge_ledger(pd.DataFrame([bad]), allow_fixture=True)
    bad = dict(edge, available_at="2024-06-03T09:00:00+08:00")
    with pytest.raises(ValueError, match="published after"):
        validate_edge_ledger(pd.DataFrame([bad]), allow_fixture=True)
    bad = dict(edge, available_at="2024-06-03T14:00:00")
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_edge_ledger(pd.DataFrame([bad]), allow_fixture=True)
    with pytest.raises(ValueError, match="graph_history_id"):
        make_network_snapshot(pd.DataFrame([edge]), ("000001", "000002"), "2024-06-03T15:10:00+08:00", graph_history_id="", allow_fixture=True)
