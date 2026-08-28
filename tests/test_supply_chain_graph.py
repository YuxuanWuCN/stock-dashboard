# -*- coding: utf-8 -*-
"""tests/test_supply_chain_graph.py —— 供应链图谱网络与 Placebo 检验单元测试 (Weeks 5-6)"""

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
