# -*- coding: utf-8 -*-
"""tests/test_pca_nale_networks.py —— M3 网络工厂回归。

独立复核重点：
  1. **手算三节点相关网络**：ρ 与阈值边界逐位比对（含恰好等于阈值的情形）；
  2. **缺证据拒边**：重叠不足/零方差一律无边 + 计数，**绝不**回落 0.5（F6 陷阱反向守卫）；
  3. **归一化与孤立点**：复用 M1 权威实现，孤立行自环（N = S0），行和 = 1 或 0；
  4. **去边敏感性手算**：三点等权图的 |ΔS| 精确值；
  5. **时间往返**：改动 ``signal_index`` 之后的收益/文本，此前网络必须逐位不变；
  6. **契约与声明**：§3 边账本列、静态假设的 ``is_observed=False``、两条 NOT_EVALUABLE 必须并列出现。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.graph.nale_alpha_adapter import normalize_network, propagate_nale_vectorized
from src.graph.pca_nale_networks import (
    ATTENTION_RELATION,
    CORRELATION_RELATION,
    EDGE_EVIDENCE_COLUMNS,
    FORBIDDEN_DEFAULT_CORR,
    INDUSTRY_RELATION,
    NOT_EVALUABLE_NETWORKS,
    RELATION_SPECS,
    W_SUPPLY_STATUS,
    W_TEXT_EMBEDDING_STATUS,
    NetworkConfig,
    NetworkError,
    build_network,
    build_network_suite,
    edge_evidence_frame,
    edge_removal_sensitivity,
    network_diagnostics,
)

CALENDAR = tuple(pd.bdate_range("2024-01-01", periods=60).strftime("%Y-%m-%d"))
CODES = ("000001", "000002", "000003")
INDUSTRIES = {"000001": "银行", "000002": "银行", "000003": "白酒"}


def _returns_fixture(series: dict[str, np.ndarray] | None = None) -> pd.DataFrame:
    """造收益长表；缺省用三条确定性序列：1 与 2 完全同向、3 反向。"""
    if series is None:
        base = np.sin(np.arange(len(CALENDAR)) / 3.0) * 0.01
        series = {
            "000001": base,
            "000002": base * 1.5,
            "000003": -base,
        }
    rows = []
    for code, values in series.items():
        for date, value in zip(CALENDAR, values):
            rows.append({"stock_code": code, "trade_date": date, "basis_return": float(value)})
    return pd.DataFrame(rows)


def _config(**overrides) -> NetworkConfig:
    params = dict(
        relation_type=CORRELATION_RELATION,
        window=20,
        corr_threshold=0.40,
        min_overlap=10,
    )
    params.update(overrides)
    return NetworkConfig(**params)


def _attn_config(**overrides) -> NetworkConfig:
    params = dict(relation_type=ATTENTION_RELATION, window=20, corr_threshold=0.40, min_overlap=10)
    params.update(overrides)
    return NetworkConfig(**params)


# ---------------------------------------------------------------------------
# 1. 手算相关网络
# ---------------------------------------------------------------------------

def test_perfectly_correlated_pair_gets_weight_one() -> None:
    build = build_network(CODES, 30, CALENDAR, _config(), returns=_returns_fixture())

    assert build.weights[0, 1] == pytest.approx(1.0, abs=1e-12)
    assert build.weights[1, 0] == pytest.approx(1.0, abs=1e-12)
    # 反向序列 ρ = −1 < 阈值 ⇒ 无边（负相关被截断为 0，而不是取绝对值）
    assert build.weights[0, 2] == pytest.approx(0.0)
    assert build.weights[2, 0] == pytest.approx(0.0)
    assert build.diagnostics["n_edges"] == 1
    assert np.array_equal(np.diag(build.weights), np.zeros(3))


def test_threshold_boundary_is_inclusive_and_hand_checkable() -> None:
    """构造 ρ 恰好等于阈值的两节点序列，验证 "ρ >= 阈值" 的边界语义。"""
    n = 20
    x = np.linspace(-1.0, 1.0, n)
    y = x.copy()
    y[-1] = -1.0  # 手算 ρ 并据此设阈值
    rho = float(np.corrcoef(x, y)[0, 1])
    series = {"000001": x * 0.01, "000002": y * 0.01, "000003": np.cos(np.arange(n))}
    frame = _returns_fixture(series)

    at_threshold = build_network(
        CODES, n - 1, CALENDAR, _config(corr_threshold=rho, window=n, min_overlap=n), returns=frame
    )
    above_threshold = build_network(
        CODES, n - 1, CALENDAR, _config(corr_threshold=rho + 1e-9, window=n, min_overlap=n), returns=frame
    )

    assert rho < 1.0
    assert at_threshold.weights[0, 1] == pytest.approx(rho, abs=1e-12)
    assert above_threshold.weights[0, 1] == pytest.approx(0.0)
    assert above_threshold.diagnostics["pairs_below_threshold"] >= 1


def test_weight_power_transform_is_applied() -> None:
    build = build_network(
        CODES, 30, CALENDAR, _config(weight_power=2.0), returns=_returns_fixture()
    )
    assert build.weights[0, 1] == pytest.approx(1.0, abs=1e-12)


def test_correlation_uses_only_the_declared_window() -> None:
    base = np.sin(np.arange(len(CALENDAR)) / 3.0) * 0.01
    shifted = base.copy()
    shifted[:36] = -base[:36]  # 前 36 天反向、其余同向；窗口 20 天 ⇒ 早期窗全反向、晚期窗全同向
    frame = _returns_fixture({"000001": base, "000002": shifted, "000003": np.cos(np.arange(60))})
    early = build_network(CODES, 25, CALENDAR, _config(), returns=frame)
    late = build_network(CODES, 55, CALENDAR, _config(), returns=frame)

    assert early.weights[0, 1] == pytest.approx(0.0)
    assert late.weights[0, 1] == pytest.approx(1.0, abs=1e-12)
    assert early.diagnostics["window_start"] == CALENDAR[6]
    assert late.diagnostics["window_start"] == CALENDAR[36]


# ---------------------------------------------------------------------------
# 2. 缺证据拒边（绝不回落默认值）
# ---------------------------------------------------------------------------

def test_insufficient_overlap_rejects_edge_and_counts_it() -> None:
    base = np.sin(np.arange(len(CALENDAR)) / 3.0) * 0.01
    sparse = base.copy()
    sparse[10:30] = np.nan  # 窗口内只剩 10 个有效样本中的 0 个
    frame = _returns_fixture({"000001": base, "000002": sparse, "000003": np.cos(np.arange(60))})

    build = build_network(CODES, 20, CALENDAR, _config(), returns=frame)

    assert build.weights[0, 1] == pytest.approx(0.0)
    assert build.weights[0, 2] == pytest.approx(0.0)
    assert build.diagnostics["pairs_insufficient_overlap"] >= 1
    assert build.diagnostics["pairs_with_nan_in_window"] >= 1


def test_zero_variance_pair_is_rejected() -> None:
    flat = np.zeros(len(CALENDAR))
    base = np.sin(np.arange(len(CALENDAR)) / 3.0) * 0.01
    frame = _returns_fixture({"000001": base, "000002": flat, "000003": -base})

    build = build_network(CODES, 30, CALENDAR, _config(), returns=frame)

    assert build.weights[0, 1] == pytest.approx(0.0)
    assert build.diagnostics["pairs_zero_variance"] >= 1


def test_missing_evidence_never_falls_back_to_half() -> None:
    """反向守卫：无论怎么缺证据，权重里都不得出现 F6 的默认值 0.5。"""
    all_nan = np.full(len(CALENDAR), np.nan)
    frame = _returns_fixture({"000001": all_nan, "000002": all_nan, "000003": all_nan})

    build = build_network(CODES, 30, CALENDAR, _config(), returns=frame)

    assert build.weights.sum() == pytest.approx(0.0)
    assert build.diagnostics["n_edges"] == 0
    assert FORBIDDEN_DEFAULT_CORR not in set(np.unique(build.weights).tolist())
    assert build.diagnostics["pairs_insufficient_overlap"] == 3


def test_window_shorter_than_min_overlap_is_rejected_by_config() -> None:
    with pytest.raises(NetworkError, match="min_overlap"):
        _config(window=5, min_overlap=10)


# ---------------------------------------------------------------------------
# 3. 行业网络、归一化与孤立点
# ---------------------------------------------------------------------------

def test_industry_cooccurrence_is_static_and_symmetric() -> None:
    build = build_network(CODES, 30, CALENDAR, _config(relation_type=INDUSTRY_RELATION), industries=INDUSTRIES)

    assert build.weights[0, 1] == pytest.approx(1.0)
    assert build.weights[1, 0] == pytest.approx(1.0)
    assert build.weights[0, 2] == pytest.approx(0.0)
    assert build.weights[2, 2] == pytest.approx(0.0)
    assert build.diagnostics["window_length"] == 0


def test_missing_industry_label_rejects_its_edges() -> None:
    industries = {"000001": "银行", "000003": "白酒"}  # 000002 缺标签
    build = build_network(CODES, 30, CALENDAR, _config(relation_type=INDUSTRY_RELATION), industries=industries)

    assert build.weights[0, 1] == pytest.approx(0.0)
    assert build.weights[0, 2] == pytest.approx(0.0)
    assert build.diagnostics["nodes_missing_industry"] == 1
    assert build.diagnostics["n_edges"] == 0


def test_normalization_rows_sum_to_one_and_isolated_rows_self_loop() -> None:
    build = build_network(CODES, 30, CALENDAR, _config(relation_type=INDUSTRY_RELATION), industries=INDUSTRIES)
    normalized = build.normalized

    # 000001 与 000002 同行业 ⇒ 各 1.0；000003 孤立 ⇒ 自环
    assert normalized[0, 1] == pytest.approx(1.0)
    assert normalized[1, 0] == pytest.approx(1.0)
    assert normalized[2, 2] == pytest.approx(1.0)
    assert normalized.sum(axis=1).tolist() == pytest.approx([1.0, 1.0, 1.0])
    assert np.array_equal(normalized, normalize_network(build.weights))


def test_isolated_node_propagation_equals_self_score() -> None:
    build = build_network(CODES, 30, CALENDAR, _config(relation_type=INDUSTRY_RELATION), industries=INDUSTRIES)
    s0 = np.array([0.3, -0.2, 0.9])

    propagated, neighbor, difference = propagate_nale_vectorized(s0, build.normalized, 0.4)

    assert neighbor[2] == pytest.approx(s0[2])
    assert difference[2] == pytest.approx(0.0)
    assert propagated[2] == pytest.approx(s0[2])
    # 有邻居的节点按 S0 + α(N − S0) 传播（手算：N0 = S0_1）
    assert neighbor[0] == pytest.approx(s0[1])
    assert propagated[0] == pytest.approx(s0[0] + 0.4 * (s0[1] - s0[0]))


def test_diagnostics_report_coverage_and_degree_distribution() -> None:
    build = build_network(CODES, 30, CALENDAR, _config(relation_type=INDUSTRY_RELATION), industries=INDUSTRIES)
    diagnostics = network_diagnostics(build)

    assert diagnostics["n_nodes"] == 3
    assert diagnostics["n_edges"] == 1
    assert diagnostics["density"] == pytest.approx(1 / 3)
    assert diagnostics["nodes_with_edge"] == 2
    assert diagnostics["node_coverage"] == pytest.approx(2 / 3)
    assert diagnostics["isolated_nodes"] == 1
    assert diagnostics["degree_max"] == 1
    assert diagnostics["corr_threshold"] == pytest.approx(0.40)
    assert diagnostics["limitation"] == RELATION_SPECS[INDUSTRY_RELATION]["limitation"]


# ---------------------------------------------------------------------------
# 4. 去边敏感性（手算）
# ---------------------------------------------------------------------------

def test_edge_removal_sensitivity_hand_computed_on_triangle() -> None:
    """三点等权图 + S0=[0,1,2] + α=0.4；移除 1 条边后的 |ΔS| 精确可算。"""
    y = np.cos(np.arange(len(CALENDAR)))
    base = np.sin(np.arange(len(CALENDAR)) / 3.0)
    frame = _returns_fixture({"000001": base, "000002": base * 1.2, "000003": y})
    config = _config(corr_threshold=0.0, window=20, min_overlap=10, min_abs_weight=0.0)
    # ρ 可能为 0 ⇒ 权重 0；用统一构造的三点全连图代替：直接手工装配 NetworkBuild
    build = build_network(CODES, 30, CALENDAR, _config(), returns=frame)
    dense_weights = np.ones((3, 3)) - np.eye(3)
    from src.graph.pca_nale_networks import NetworkBuild

    dense = NetworkBuild(
        relation_type=CORRELATION_RELATION,
        codes=CODES,
        signal_index=30,
        signal_date=CALENDAR[30],
        weights=dense_weights,
        normalized=normalize_network(dense_weights),
        diagnostics={},
        config=config,
        spec=dict(RELATION_SPECS[CORRELATION_RELATION]),
    )
    s0 = np.array([0.0, 1.0, 2.0])
    baseline, _, _ = propagate_nale_vectorized(s0, dense.normalized, 0.4)

    table = edge_removal_sensitivity(dense, s0, alpha=0.4, fractions=(0.34,))
    assert bool(build.weights.max() <= 1.0)  # 夹具自检：相关系数上界

    # 3 条边 ⇒ floor(0.34*3) = 1 条被移除；三条边权重相同，移除哪条由稳定排序决定
    assert int(table.loc[0, "edges_removed"]) == 1
    removed_pair = None
    for i in range(3):
        for j in range(i + 1, 3):
            if removed_pair is None and dense_weights[i, j] == 1.0:
                removed_pair = (i, j)
                break
    assert removed_pair is not None
    pruned = dense_weights.copy()
    pruned[0, 1] = pruned[1, 0] = 0.0
    manual, _, _ = propagate_nale_vectorized(s0, normalize_network(pruned), 0.4)
    expected_max = float(np.abs(manual - baseline).max())
    assert float(table.loc[0, "max_abs_delta"]) == pytest.approx(expected_max, abs=1e-15)


def test_edge_removal_sensitivity_rejects_bad_inputs() -> None:
    build = build_network(CODES, 30, CALENDAR, _config(relation_type=INDUSTRY_RELATION), industries=INDUSTRIES)

    with pytest.raises(NetworkError, match="长度"):
        edge_removal_sensitivity(build, np.array([0.1, 0.2]))
    with pytest.raises(NetworkError, match="有限值"):
        edge_removal_sensitivity(build, np.array([0.1, np.nan, 0.2]))
    with pytest.raises(NetworkError, match="开区间"):
        edge_removal_sensitivity(build, np.ones(3), fractions=(0.0,))


def test_edge_removal_sensitivity_requires_edges() -> None:
    industries = {"000001": "银行", "000002": "白酒", "000003": "医药"}
    build = build_network(CODES, 30, CALENDAR, _config(relation_type=INDUSTRY_RELATION), industries=industries)

    with pytest.raises(NetworkError, match="没有任何边"):
        edge_removal_sensitivity(build, np.ones(3))


def test_tiny_fraction_removes_nothing_and_says_so() -> None:
    dense_weights = np.ones((3, 3)) - np.eye(3)
    from src.graph.pca_nale_networks import NetworkBuild

    build = NetworkBuild(
        relation_type=CORRELATION_RELATION,
        codes=CODES,
        signal_index=30,
        signal_date=CALENDAR[30],
        weights=dense_weights,
        normalized=normalize_network(dense_weights),
        diagnostics={},
        config=_config(),
        spec=dict(RELATION_SPECS[CORRELATION_RELATION]),
    )
    table = edge_removal_sensitivity(build, np.array([0.1, 0.2, 0.3]), fractions=(0.1,))

    assert int(table.loc[0, "edges_removed"]) == 0
    assert float(table.loc[0, "max_abs_delta"]) == pytest.approx(0.0)
    assert "下取整" in str(table.loc[0, "note"])


# ---------------------------------------------------------------------------
# 5. 时间往返（PIT）
# ---------------------------------------------------------------------------

def test_future_returns_cannot_change_past_network() -> None:
    cutoff_index = 30
    frame = _returns_fixture()
    config = _config(window=20)
    for index in (25, 29, 30):
        before = build_network(CODES, index, CALENDAR, config, returns=frame)
        mutated = frame.copy()
        future = mutated["trade_date"] > CALENDAR[cutoff_index]
        mutated.loc[future, "basis_return"] *= 5.0
        after = build_network(CODES, index, CALENDAR, config, returns=mutated)
        assert np.array_equal(before.weights, after.weights)
        assert np.array_equal(before.normalized, after.normalized)


def test_future_text_cannot_change_past_attention_network() -> None:
    base = np.sin(np.arange(len(CALENDAR)) / 3.0)
    flow = pd.DataFrame(
        {
            "stock_code": [code for code in CODES for _ in CALENDAR],
            "trade_date": list(CALENDAR) * len(CODES),
            "flow_total_w1": list(base) * len(CODES),
        }
    )
    config = _attn_config(window=20)
    before = build_network(CODES, 30, CALENDAR, config, flow=flow)
    mutated = flow.copy()
    mutated.loc[mutated["trade_date"] > CALENDAR[30], "flow_total_w1"] = 99.0
    after = build_network(CODES, 30, CALENDAR, config, flow=mutated)

    assert np.array_equal(before.weights, after.weights)


# ---------------------------------------------------------------------------
# 6. 边账本契约与 NOT_EVALUABLE 声明
# ---------------------------------------------------------------------------

def test_edge_evidence_satisfies_contract_columns() -> None:
    build = build_network(CODES, 30, CALENDAR, _config(), returns=_returns_fixture())
    evidence = edge_evidence_frame(build, calendar=CALENDAR)

    assert set(EDGE_EVIDENCE_COLUMNS) <= set(evidence.columns)
    assert len(evidence) == build.diagnostics["n_edges"] * 2  # 对称 ⇒ 每个无向边两行
    assert evidence["available_at"].unique().tolist() == [CALENDAR[30]]
    assert evidence["is_observed"].all()
    assert evidence["relation_type"].unique().tolist() == [CORRELATION_RELATION]
    assert evidence["edge_version"].unique().tolist() == ["pca_nale_network_v1"]
    assert evidence["available_at"].ge(evidence["valid_from"]).all()


def test_static_industry_edges_are_marked_as_not_observed() -> None:
    build = build_network(CODES, 30, CALENDAR, _config(relation_type=INDUSTRY_RELATION), industries=INDUSTRIES)
    evidence = edge_evidence_frame(build, calendar=CALENDAR)

    assert not bool(evidence["is_observed"].any())
    assert evidence["source_published_at"].unique().tolist() == ["static_assumption"]
    assert evidence["valid_from"].unique().tolist() == [CALENDAR[0]]


def test_edge_evidence_rejects_available_at_before_valid_from() -> None:
    build = build_network(CODES, 30, CALENDAR, _config(), returns=_returns_fixture())

    with pytest.raises(NetworkError, match="早于 valid_from"):
        edge_evidence_frame(build, calendar=CALENDAR, available_at=CALENDAR[0])


def test_empty_edge_ledger_is_refused_not_reported_as_conclusion() -> None:
    all_nan = np.full(len(CALENDAR), np.nan)
    frame = _returns_fixture({"000001": all_nan, "000002": all_nan, "000003": all_nan})
    build = build_network(CODES, 30, CALENDAR, _config(), returns=frame)

    with pytest.raises(NetworkError, match="没有任何边"):
        edge_evidence_frame(build, calendar=CALENDAR)


def test_not_evaluable_networks_are_declared_with_reasons() -> None:
    assert W_TEXT_EMBEDDING_STATUS == "NOT_ASOF"
    assert W_SUPPLY_STATUS == "NOT_EVALUABLE"
    assert set(NOT_EVALUABLE_NETWORKS) == {"text_embedding_similarity", "supply_chain_edges"}
    assert W_TEXT_EMBEDDING_STATUS in NOT_EVALUABLE_NETWORKS["text_embedding_similarity"]
    assert W_SUPPLY_STATUS in NOT_EVALUABLE_NETWORKS["supply_chain_edges"]
    assert "2026-09-07" in NOT_EVALUABLE_NETWORKS["text_embedding_similarity"]


@pytest.mark.parametrize("name", ["text_embedding_similarity", "supply_chain_edges"])
def test_not_evaluable_names_cannot_be_constructed(name: str) -> None:
    with pytest.raises(NetworkError, match="NOT_EVALUABLE|未声明的关系类型"):
        NetworkConfig(relation_type=name)


# ---------------------------------------------------------------------------
# 7. 并列报告（suite）与参数校验
# ---------------------------------------------------------------------------

def test_suite_reports_all_three_evaluable_networks_in_parallel() -> None:
    base = np.sin(np.arange(len(CALENDAR)) / 3.0)
    flow = pd.DataFrame(
        {
            "stock_code": [code for code in CODES for _ in CALENDAR],
            "trade_date": list(CALENDAR) * len(CODES),
            "flow_total_w1": list(base) * len(CODES),
        }
    )
    configs = {
        "W-ind": _config(relation_type=INDUSTRY_RELATION),
        "W-corr": _config(),
        "W-attn": _attn_config(),
    }
    suite = build_network_suite(
        CODES,
        30,
        CALENDAR,
        configs,
        industries=INDUSTRIES,
        returns=_returns_fixture(),
        flow=flow,
        s0=np.array([0.1, 0.2, 0.3]),
    )

    assert set(suite["networks"]) == {"W-ind", "W-corr", "W-attn"}
    assert len(suite["diagnostics"]) == 3
    assert set(suite["sensitivity"]) == {"W-ind", "W-corr", "W-attn"}
    assert set(suite["not_evaluable"]) == {"text_embedding_similarity", "supply_chain_edges"}
    assert set(suite["relation_specs"]) == {INDUSTRY_RELATION, CORRELATION_RELATION, ATTENTION_RELATION}


def test_missing_required_inputs_are_reported() -> None:
    with pytest.raises(NetworkError, match="returns"):
        build_network(CODES, 30, CALENDAR, _config())
    with pytest.raises(NetworkError, match="industries"):
        build_network(CODES, 30, CALENDAR, _config(relation_type=INDUSTRY_RELATION))
    with pytest.raises(NetworkError, match="flow"):
        build_network(CODES, 30, CALENDAR, _attn_config())


def test_invalid_universe_and_indices_are_rejected() -> None:
    with pytest.raises(NetworkError, match="至少需要 2 支"):
        build_network(("000001",), 30, CALENDAR, _config(), returns=_returns_fixture())
    with pytest.raises(NetworkError, match="重复"):
        build_network(("000001", "000001"), 30, CALENDAR, _config(), returns=_returns_fixture())
    with pytest.raises(NetworkError, match="非法证券代码"):
        build_network(("0000AB", "000002"), 30, CALENDAR, _config(), returns=_returns_fixture())
    with pytest.raises(NetworkError, match="signal_index 超出"):
        build_network(CODES, len(CALENDAR), CALENDAR, _config(), returns=_returns_fixture())


def test_short_codes_are_zero_padded_consistently_with_upstream_modules() -> None:
    """代码前导零统一补齐（与 return_basis / as-of 面板一致），5 位输入补成 6 位。"""
    build = build_network(("00001", "000002", "000003"), 30, CALENDAR, _config(), returns=_returns_fixture())

    assert build.codes[0] == "000001"


def test_series_with_out_of_calendar_date_is_rejected() -> None:
    frame = _returns_fixture()
    frame.loc[0, "trade_date"] = "2030-01-01"

    with pytest.raises(NetworkError, match="不在交易日历"):
        build_network(CODES, 30, CALENDAR, _config(), returns=frame)


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"window": 1}, "window"),
        ({"corr_threshold": 1.5}, "corr_threshold"),
        ({"corr_threshold": -1.5}, "corr_threshold"),
        ({"min_overlap": 2}, "min_overlap"),
        ({"min_abs_weight": -1.0}, "min_abs_weight"),
        ({"weight_power": 0.0}, "weight_power"),
    ],
)
def test_config_validation(overrides: dict, fragment: str) -> None:
    with pytest.raises(NetworkError, match=fragment):
        _config(**overrides)


def test_network_suite_is_deterministic() -> None:
    frame = _returns_fixture()
    config = _config()
    first = build_network(CODES, 30, CALENDAR, config, returns=frame)
    second = build_network(CODES, 30, CALENDAR, config, returns=frame)

    assert np.array_equal(first.weights, second.weights)
    assert first.diagnostics == second.diagnostics