# -*- coding: utf-8 -*-
"""tests/test_nale_propagation_authority.py —— M1 收敛回归：NALE 传播核唯一权威实现。

背景（规则 §8-V4 / 交接书 M1）：
    修复前项目里存在两套并行传播实现——
      * ``src/pricing/dynamic_nale_alpha.propagate_nale``（向量化，S0 @ W.T）
      * ``src/graph/nale_alpha_adapter`` 内部路径（字典式 API）
    两者语义相同但可各自漂移。M1 收敛为唯一权威实现
    ``src.graph.nale_alpha_adapter.propagate_nale_vectorized``，
    ``dynamic_nale_alpha.propagate_nale`` 以**模块级别名**再导出。

本文件不依赖门禁退出码，用可手算小样本独立复核三件事：
    1. 同一性：别名必须指向同一函数对象（避免后人用 def 包装悄悄分叉）；
    2. 数值等价：两条入口逐位一致（bit-identical，非“近似相等”）；
    3. 语义守恒：收敛前后行为契约（B0 不动点、u=0 ⇒ α=0.4、孤立行自环、
       校验拒绝规则）逐条仍在。
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from src.graph.nale_alpha_adapter import (
    propagate_nale as adapter_dict_style_propagate,
    propagate_nale_vectorized as canonical_kernel,
)
from src.pricing import dynamic_nale_alpha as dynamic_module


def _row_normalized(matrix: np.ndarray) -> np.ndarray:
    """把非负方阵按行归一化（全零行保持全零，交给核内自环处理）。"""
    w = np.asarray(matrix, dtype=float).copy()
    sums = w.sum(axis=1)
    safe = np.where(sums > 0, sums, 1.0)
    return w / safe[:, None]


# ---------------------------------------------------------------------------
# 1. 同一性
# ---------------------------------------------------------------------------

def test_dynamic_alias_points_to_canonical_kernel() -> None:
    """dynamic_nale_alpha.propagate_nale 必须就是权威核本身（不是包装函数）。"""
    assert dynamic_module.propagate_nale is canonical_kernel
    assert dynamic_module.propagate_nale is not None


def test_alias_did_not_become_a_def_wrapper() -> None:
    """反向能力守卫：包一层 def 会让 ``is`` 失效，必须在源码层面挡住。"""
    wrapper = lambda *a, **k: canonical_kernel(*a, **k)  # noqa: E731
    assert wrapper is not canonical_kernel  # 证明 is 判定确实有区分力


def test_canonical_kernel_is_importable_from_both_entry_points() -> None:
    """两条 import 路径解析到的是同一个对象（无重复注册/影子模块）。"""
    from src.pricing.dynamic_nale_alpha import propagate_nale as via_pricing
    from src.graph.nale_alpha_adapter import propagate_nale_vectorized as via_graph

    assert via_pricing is via_graph
    assert via_pricing.__module__ == "src.graph.nale_alpha_adapter"


def test_canonical_kernel_signature_supports_alpha_keyword() -> None:
    """历史调用方使用 ``alpha=`` 关键字，别名必须保留同签名。"""
    params = list(inspect.signature(canonical_kernel).parameters)
    assert params == ["S0", "W_norm", "alpha"]


# ---------------------------------------------------------------------------
# 2. 数值等价（逐位）
# ---------------------------------------------------------------------------

def test_one_dimensional_outputs_are_bit_identical() -> None:
    s0 = np.array([0.2, 0.8, 0.5])
    w = _row_normalized([[0.0, 3.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 0.0]])

    a = dynamic_module.propagate_nale(s0, w, alpha=0.40)
    b = canonical_kernel(s0, w, 0.40)

    assert len(a) == 3 and len(b) == 3
    for left, right in zip(a, b):
        assert np.array_equal(left, right)


def test_two_dimensional_batch_outputs_are_bit_identical() -> None:
    rng = np.random.default_rng(20260914)
    s0 = rng.normal(0.0, 1.0, size=(4, 3))
    w = _row_normalized(rng.random((3, 3)))

    a = dynamic_module.propagate_nale(s0, w, alpha=0.25)
    b = canonical_kernel(s0, w, 0.25)

    for left, right in zip(a, b):
        assert np.array_equal(left, right)


def test_vector_alpha_outputs_are_bit_identical() -> None:
    s0 = np.array([0.1, 0.9, 0.4])
    w = _row_normalized([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]])
    alpha = np.array([0.05, 0.40, 0.75])

    a = dynamic_module.propagate_nale(S0=s0, W_norm=w, alpha=alpha)
    b = canonical_kernel(s0, w, alpha)

    for left, right in zip(a, b):
        assert np.array_equal(left, right)


def test_dict_style_api_matches_canonical_kernel_on_same_network() -> None:
    """字典式 API 与向量化核在同一下游图上给出相同 S（跨 API 一致性）。"""
    codes = ["000001", "000002", "600519"]
    s0 = [0.3, -0.2, 0.7]
    adjacency = np.array([
        [0.0, 1.0, 1.0],
        [2.0, 0.0, 2.0],
        [1.0, 0.0, 0.0],
    ])
    alpha = 0.30

    dict_result = adapter_dict_style_propagate(codes, s0, adjacency, alpha_override=alpha)
    kernel_result = canonical_kernel(np.asarray(s0), _row_normalized(adjacency), alpha)

    assert np.allclose(dict_result.score, kernel_result[0], rtol=0.0, atol=1e-12)
    assert np.allclose(dict_result.alpha_nale, alpha)


# ---------------------------------------------------------------------------
# 3. 语义守恒（手算小样本）
# ---------------------------------------------------------------------------

def test_alpha_zero_is_b0_fixed_point() -> None:
    """α=0 ⇒ S ≡ S0（B0 不动点），手算：S0 + 0·D = S0。"""
    s0 = np.array([0.2, 0.8, 0.5])
    w = _row_normalized([[0.0, 3.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 0.0]])

    s, n_agg, d = dynamic_module.propagate_nale(s0, w, alpha=0.0)

    assert np.array_equal(s, s0)
    assert np.array_equal(d, n_agg - s0)


def test_two_node_hand_computed_case() -> None:
    """手算：S0=[0,1]，W=[[0,1],[1,0]] ⇒ N=[1,0]，D=[1,-1]，α=0.5 ⇒ S=[0.5,0.5]。"""
    s0 = np.array([0.0, 1.0])
    w = np.array([[0.0, 1.0], [1.0, 0.0]])

    s, n_agg, d = dynamic_module.propagate_nale(s0, w, alpha=0.5)

    assert np.array_equal(n_agg, np.array([1.0, 0.0]))
    assert np.array_equal(d, np.array([1.0, -1.0]))
    assert np.array_equal(s, np.array([0.5, 0.5]))


def test_zero_gate_maps_to_point_four() -> None:
    """u=0 ⇒ α=0.4（两端: 0.05 + 0.70·0.5 = 0.40）。"""
    assert dynamic_module.compute_alpha_gating(np.array([0.0]))[0] == pytest.approx(0.4)
    assert dynamic_module.compute_alpha_gating(np.array([-500.0]))[0] == pytest.approx(0.05, abs=1e-12)
    assert dynamic_module.compute_alpha_gating(np.array([500.0]))[0] == pytest.approx(0.75, abs=1e-12)


def test_isolated_row_becomes_self_loop_and_keeps_score() -> None:
    """孤立行（行和 0）被置为自环 ⇒ 无邻居传播，自身得分不变。"""
    s0 = np.array([0.5, 0.5])
    w = np.array([[0.0, 1.0], [0.0, 0.0]])

    s, n_agg, d = dynamic_module.propagate_nale(s0, w, alpha=0.75)

    assert n_agg[1] == pytest.approx(s0[1])
    assert d[1] == pytest.approx(0.0)
    assert s[1] == pytest.approx(s0[1])


# ---------------------------------------------------------------------------
# 4. 校验规则守恒（拒绝路径必须原样保留，不得 fail-open）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"S0": np.array([0.1, np.nan]), "W_norm": np.eye(2), "alpha": 0.4},
         "must all be finite"),
        ({"S0": np.array([0.1, 0.2]), "W_norm": np.eye(3), "alpha": 0.4},
         "shapes do not align"),
        ({"S0": np.array([0.1, 0.2]), "W_norm": np.array([[0.5, 0.5], [-1.0, 2.0]]), "alpha": 0.4},
         "nonnegative"),
        ({"S0": np.array([0.1, 0.2]), "W_norm": np.eye(2), "alpha": 1.5},
         "in \\[0,1\\]"),
        ({"S0": np.array([0.1, 0.2]), "W_norm": np.array([[0.2, 0.2], [0.5, 0.5]]), "alpha": 0.4},
         "row-normalized"),
    ],
)
def test_validation_rejections_are_preserved(kwargs: dict, message: str) -> None:
    """非法输入必须抛 ValueError，且 dynamic 入口与权威核报同一原因。"""
    with pytest.raises(ValueError, match=message):
        canonical_kernel(**kwargs)
    with pytest.raises(ValueError, match=message):
        dynamic_module.propagate_nale(**kwargs)


def test_unbounded_alpha_is_rejected_not_clipped() -> None:
    """α 越界必须拒绝而不是静默裁剪（静默裁剪会伪装成合法传播）。"""
    s0 = np.array([0.1, 0.2])
    w = np.eye(2)
    for bad in (1.0 + 1e-9, -1e-9, 1.01):
        with pytest.raises(ValueError):
            dynamic_module.propagate_nale(s0, w, alpha=bad)