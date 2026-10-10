# -*- coding: utf-8 -*-
"""tests/test_ast_alpha_miner.py —— AST 因子挖掘与正则化门禁单元测试"""

import numpy as np
import pandas as pd
import pytest

from src.intelligence.ast_alpha_miner import (
    ASTNode,
    ASTRegularizer,
    NeuroSymbolicAlphaEngine,
    op_cs_rank,
    op_decay_linear,
    op_delta,
    op_ts_argmax,
    op_ts_rank,
)


def test_ast_node_structure_and_formula():
    """测试 AST 节点生成与紧凑公式序列化。"""
    sub_node = ASTNode(operator="Ts_Rank", children=["close"], params={"window": 10})
    root = ASTNode(operator="Rank", children=[sub_node])

    assert root.get_depth() == 3
    assert root.get_node_count() == 3
    assert root.to_formula() == "Rank(Ts_Rank(close, window=10))"


def test_ast_regularizer_complexity_bounds():
    """测试 AST 复杂度门控拦截过度参数化与深层嵌套。"""
    reg = ASTRegularizer(max_depth=3, max_nodes=5)

    # 深度为 2，节点数 3 -> 合格
    valid_node = ASTNode(
        operator="Sub",
        children=["close", "open"],
    )
    passed, msg = reg.validate_complexity(valid_node)
    assert passed is True

    # 构造深度为 4 的超标语法树 -> 拦截
    deep_node = ASTNode(
        operator="Rank",
        children=[
            ASTNode(
                operator="Rank",
                children=[
                    ASTNode(
                        operator="Rank",
                        children=[ASTNode(operator="Rank", children=["close"])],
                    )
                ],
            )
        ],
    )
    passed, msg = reg.validate_complexity(deep_node)
    assert passed is False
    assert "Depth 5" in msg or "Depth 4" in msg or "exceeds" in msg


def test_ast_regularizer_tree_similarity():
    """测试 AST 树核相似度排斥机制。"""
    reg = ASTRegularizer(max_similarity_threshold=0.70)

    node_a = ASTNode(operator="Ts_Rank", children=["close"], params={"window": 10})
    node_b = ASTNode(operator="Ts_Rank", children=["close"], params={"window": 10})
    node_c = ASTNode(operator="Correlation", children=["high", "volume"], params={"window": 20})

    # 完全相同或极度相似的树 -> 相似度高
    sim_ab = reg.calculate_tree_similarity(node_a, node_b)
    assert sim_ab >= 0.85

    # 结构迥异的树 -> 相似度低
    sim_ac = reg.calculate_tree_similarity(node_a, node_c)
    assert sim_ac < 0.60


def test_ast_vectorized_operators():
    """测试时间序列基础算子的数值正确性与防溢出特性。"""
    dates = pd.date_range("2026-01-01", periods=15)
    df = pd.DataFrame(
        {
            "s1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 9.0, 8.0, 7.0, 6.0, 5.0],
            "s2": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        },
        index=dates,
    )

    # 1. Delta 算子
    delta_res = op_delta(df, period=1)
    assert delta_res.iloc[1]["s1"] == 1.0
    assert delta_res.iloc[1]["s2"] == -1.0

    # 2. Ts_Rank 算子
    ts_rank_res = op_ts_rank(df, window=5)
    assert 0.0 <= ts_rank_res.iloc[-1]["s1"] <= 1.0

    # 3. Decay_Linear 算子
    decay_res = op_decay_linear(df, window=5)
    assert not np.isnan(decay_res.iloc[-1]["s1"])

    # 4. CS Rank 截面排位
    cs_res = op_cs_rank(df)
    assert (cs_res.iloc[0]["s1"] < cs_res.iloc[0]["s2"])


def test_neuro_symbolic_engine_end_to_end():
    """测试神经-符号因子引擎端到端计算与质量打分。"""
    dates = pd.date_range("2026-01-01", periods=30)
    market_data = {
        "close": pd.DataFrame(np.random.randn(30, 4) * 2 + 10, index=dates, columns=["A", "B", "C", "D"]),
        "volume": pd.DataFrame(np.random.randint(100, 1000, size=(30, 4)), index=dates, columns=["A", "B", "C", "D"]),
    }
    forward_returns = market_data["close"].pct_change(5).shift(-5)

    engine = NeuroSymbolicAlphaEngine()
    ast_root = ASTNode(
        operator="Sub",
        children=[
            ASTNode(operator="Ts_Rank", children=["close"], params={"window": 5}),
            ASTNode(operator="Ts_Rank", children=["volume"], params={"window": 5}),
        ],
    )

    rec = engine.register_candidate_factor(
        name="Test_Alpha",
        hypothesis="测试价量动量动能假说 (Momentum)",
        ast_root=ast_root,
        market_data=market_data,
        forward_returns=forward_returns,
    )

    assert rec["status"] == "APPROVED"
    assert "rank_ic" in rec["quality"]
    assert len(engine.registered_alphas) == 1
