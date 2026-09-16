# -*- coding: utf-8 -*-
"""tests/test_supply_chain_graph.py —— 供应链图谱网络与 Placebo 检验单元测试 (Weeks 5-6)"""

from itertools import permutations

import numpy as np
import pytest

from src.graph.supply_chain_graph import SupplyChainGraph


def test_supply_chain_graph_and_placebo():
    """测试有向经济邻接矩阵 W 构建、NALE 传播与 100 次边洗牌 Placebo 检验。"""
    graph = SupplyChainGraph(node_tickers=["SK_HYNIX", "001309", "CH_GREATWALL", "UNCONNECTED_ASSET"])

    # 1. 注入上下游供应链边：SK海力士 (上游供应商) -> 德明利 (中游卡点) -> 中国长城 (下游客户)
    graph.add_edge("SK_HYNIX", "001309", weight=0.60)
    graph.add_edge("001309", "CH_GREATWALL", weight=0.40)

    W = graph.build_adjacency_matrix("2024Q1")
    assert W.shape == (4, 4)

    # 2. 原生大模型事实得分：上游突发涨价与订单爆发 (+0.80)
    node_scores = {
        "SK_HYNIX": 0.80,
        "001309": 0.10,
        "CH_GREATWALL": 0.00,
        "UNCONNECTED_ASSET": -0.20
    }

    nale_scores = graph.run_nale_propagation(node_scores, alpha=0.4)
    # 德明利接收到来自 SK 海力士的强动能溢出
    assert nale_scores["001309"] > node_scores["001309"]

    # 3. 运行 100 次 Placebo 边洗牌 Monte Carlo 检验
    placebo_res = graph.run_placebo_verification(node_scores, n_shuffles=100, alpha=0.4)
    assert placebo_res["n_shuffles"] == 100
    assert "mean_z_score" in placebo_res
    assert "p_value" in placebo_res


def _self_loop_graph(isolated_nodes=0):
    """Synthetic graph: each of three nodes initially receives its own score."""
    graph = SupplyChainGraph(["A", "B", "C"] + [
        f"ISOLATED_{i}" for i in range(isolated_nodes)
    ])
    for ticker in ("A", "B", "C"):
        graph.add_edge(ticker, ticker)
    return graph


def _stub_shuffles(monkeypatch, permutations):
    """Supply known edge permutations so tail counts can be checked by hand."""
    sequence = iter(permutations)

    class FixedRng:
        def permutation(self, columns):
            shuffled = np.asarray(next(sequence))
            np.testing.assert_array_equal(np.sort(shuffled), np.sort(columns))
            return shuffled

    monkeypatch.setattr(np.random, "default_rng", lambda seed: FixedRng())


@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_placebo_empirical_tail_includes_ties(monkeypatch, sign):
    graph = _self_loop_graph()
    # Observed [0, 0, sign]; one identical and three [sign, 0, 0] shuffles.
    # Of the five pooled vectors, the two observed-type vectors are most extreme.
    _stub_shuffles(monkeypatch, [[0, 1, 2]] + [[2, 0, 1]] * 3)

    result = graph.run_placebo_verification({"C": sign}, n_shuffles=4, alpha=1.0)

    assert result["mean_z_score"] == pytest.approx(2 * np.sqrt(3 / 2) / 3)
    assert result["p_value"] == pytest.approx(2 / 5)
    assert result["is_topologically_valid"] is False


@pytest.mark.parametrize("isolated_nodes", [0, 7])
def test_placebo_significance_uses_empirical_pvalue(monkeypatch, isolated_nodes):
    graph = _self_loop_graph(isolated_nodes)
    _stub_shuffles(monkeypatch, [[2, 0, 1]] * 20)

    result = graph.run_placebo_verification({"C": 1.0}, n_shuffles=20, alpha=1.0)

    # One extreme observation among 21; inactive nodes dilute mean |Z| only.
    assert result["mean_z_score"] == pytest.approx(
        2 * np.sqrt(20) / (3 + isolated_nodes)
    )
    assert result["p_value"] == pytest.approx(1 / 21)
    assert result["is_topologically_valid"] is True
    if isolated_nodes:
        assert result["mean_z_score"] < 1.96


def test_placebo_five_percent_boundary_is_not_significant(monkeypatch):
    graph = _self_loop_graph()
    _stub_shuffles(monkeypatch, [[2, 0, 1]] * 19)

    result = graph.run_placebo_verification({"C": 1.0}, n_shuffles=19, alpha=1.0)

    assert result["p_value"] == pytest.approx(0.05)
    assert result["is_topologically_valid"] is False


def test_single_shuffle_is_symmetric_and_cannot_claim_significance(monkeypatch):
    graph = _self_loop_graph()
    _stub_shuffles(monkeypatch, [[2, 0, 1]])

    result = graph.run_placebo_verification({"C": 1.0}, n_shuffles=1, alpha=1.0)

    # With two vectors, both are equidistant from their pooled midpoint.
    assert result["mean_z_score"] == pytest.approx(2 / 3)
    assert result["p_value"] == 1.0
    assert result["is_topologically_valid"] is False


def test_placebo_full_orbit_ties_are_not_split_by_roundoff(monkeypatch):
    graph = _self_loop_graph()
    _stub_shuffles(monkeypatch, list(permutations([0, 1, 2]))[1:])

    result = graph.run_placebo_verification(
        {"A": 0.1, "B": 0.2, "C": 0.3}, n_shuffles=5, alpha=1.0
    )

    # The observed graph plus five shuffles exhaust the six permutations.
    # Each vector has the same absolute deviation, up to floating point error.
    assert result["mean_z_score"] == pytest.approx(np.sqrt(2 / 3))
    assert result["p_value"] == 1.0
    assert result["is_topologically_valid"] is False


@pytest.mark.parametrize("node_tickers", [[], ["A", "B"]])
def test_placebo_without_edges_returns_complete_nonsignificant_result(node_tickers):
    graph = SupplyChainGraph(node_tickers)
    result = graph.run_placebo_verification({}, n_shuffles=7)
    assert result == {
        "n_shuffles": 7,
        "mean_z_score": 0.0,
        "p_value": 1.0,
        "is_topologically_valid": False,
    }


@pytest.mark.parametrize("scores,alpha", [
    ({}, 0.4),
    ({"A": 0.7, "B": 0.7, "C": 0.7}, 0.4),
    ({"A": 1.0, "B": -0.5, "C": 0.1}, 0.0),
])
def test_placebo_invariant_scores_have_no_topological_evidence(scores, alpha):
    result = _self_loop_graph().run_placebo_verification(
        scores, n_shuffles=23, alpha=alpha
    )
    assert result["mean_z_score"] == 0.0
    assert result["p_value"] == 1.0
    assert result["is_topologically_valid"] is False


def test_placebo_unshufflable_topology_has_no_evidence():
    graph = SupplyChainGraph()
    graph.add_edge("A", "B")
    graph.add_edge("A", "C")

    result = graph.run_placebo_verification({"A": 0.9}, n_shuffles=23)

    assert result["mean_z_score"] == 0.0
    assert result["p_value"] == 1.0
    assert result["is_topologically_valid"] is False


@pytest.mark.parametrize("n_shuffles", [0, -1, 1.5, True, np.bool_(True)])
def test_placebo_rejects_invalid_shuffle_counts(n_shuffles):
    with pytest.raises(ValueError, match="n_shuffles"):
        _self_loop_graph().run_placebo_verification({}, n_shuffles=n_shuffles)


def test_placebo_accepts_numpy_integer_shuffle_count():
    result = _self_loop_graph().run_placebo_verification(
        {}, n_shuffles=np.int64(3)
    )
    assert result["n_shuffles"] == 3
    assert result["p_value"] == 1.0


@pytest.mark.parametrize("bad_score", [np.nan, np.inf, -np.inf])
def test_placebo_rejects_nonfinite_scores(bad_score):
    with pytest.raises(ValueError, match="finite"):
        _self_loop_graph().run_placebo_verification({"A": bad_score})


@pytest.mark.parametrize("bad_alpha", [np.nan, np.inf, -np.inf])
def test_placebo_rejects_nonfinite_alpha(bad_alpha):
    with pytest.raises(ValueError, match="finite"):
        _self_loop_graph().run_placebo_verification({"A": 1.0}, alpha=bad_alpha)


def test_placebo_reproducible_without_changing_global_rng_or_graph():
    graph = _self_loop_graph()
    original_matrix = graph.build_adjacency_matrix("2026Q3").copy()
    saved_state = np.random.get_state()
    state_before = np.random.RandomState(123456).get_state()
    np.random.set_state(state_before)
    try:
        first = graph.run_placebo_verification({"C": 1.0}, quarter_label="2026Q3")
        second = graph.run_placebo_verification({"C": 1.0}, quarter_label="2026Q3")
        state_after = np.random.get_state()
    finally:
        np.random.set_state(saved_state)
    assert first == second
    assert 1 / 101 <= first["p_value"] <= 1.0
    assert first["is_topologically_valid"] == (first["p_value"] < 0.05)
    assert state_before[0] == state_after[0]
    np.testing.assert_array_equal(state_before[1], state_after[1])
    assert state_before[2:] == state_after[2:]
    np.testing.assert_array_equal(
        graph.quarterly_matrices["2026Q3"].toarray(), original_matrix.toarray()
    )
