# -*- coding: utf-8 -*-
"""src/graph/supply_chain_graph.py —— 供应链知识图谱、动态稀疏邻接矩阵与 Placebo 检验套件 (Weeks 5-6)

依据规范：
1. 《StockDashboard v3.0 & Serenity Chokepoint 12-Week Roadmap》Phase II: Weeks 5–6
2. 动态经济邻接矩阵 W_t：边权重 w_{ji} 依据采购比例、预付款项、营收依赖度动态定权
3. 财报季切片动态 CSR 稀疏矩阵存储
4. Yılkı (2026) NALE 100 次边洗牌 Placebo 蒙特卡洛拓扑显著性检验套件
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import scipy.sparse as sp

logger = logging.getLogger("supply_chain_graph")


@dataclass
class EdgeLink:
    """供应链有向边。"""
    source_ticker: str  # 供应商
    target_ticker: str  # 客户
    dependency_weight: float  # 依赖度权重 [0.0, 1.0] (如采购占比、营收占比)
    link_type: str = "SUPPLIER_TO_CUSTOMER"


class SupplyChainGraph:
    """供应链知识图谱与动态拓扑传播引擎。"""

    def __init__(self, node_tickers: Optional[List[str]] = None):
        self.node_tickers = node_tickers or []
        self._ticker_to_idx = {t: i for i, t in enumerate(self.node_tickers)}
        self.edges: List[EdgeLink] = []
        self.quarterly_matrices: Dict[str, sp.csr_matrix] = {}

    def add_node(self, ticker: str) -> int:
        """添加节点并返回索引。"""
        if ticker not in self._ticker_to_idx:
            idx = len(self.node_tickers)
            self.node_tickers.append(ticker)
            self._ticker_to_idx[ticker] = idx
            return idx
        return self._ticker_to_idx[ticker]

    def add_edge(self, supplier_ticker: str, customer_ticker: str, weight: float = 1.0, link_type: str = "SUPPLY") -> None:
        """添加有向供应链关联边。"""
        self.add_node(supplier_ticker)
        self.add_node(customer_ticker)
        self.edges.append(EdgeLink(
            source_ticker=supplier_ticker,
            target_ticker=customer_ticker,
            dependency_weight=float(weight),
            link_type=link_type
        ))

    def build_adjacency_matrix(self, quarter_label: str = "2024Q1") -> sp.csr_matrix:
        """构建归一化有向经济邻接矩阵 W_t (CSR 格式)。"""
        N = len(self.node_tickers)
        if N == 0:
            return sp.csr_matrix((0, 0))

        row_indices = []
        col_indices = []
        data_values = []

        for edge in self.edges:
            src_idx = self._ticker_to_idx[edge.source_ticker]
            tgt_idx = self._ticker_to_idx[edge.target_ticker]
            row_indices.append(tgt_idx)
            col_indices.append(src_idx)
            data_values.append(edge.dependency_weight)

        adj = sp.csr_matrix((data_values, (row_indices, col_indices)), shape=(N, N), dtype=float)

        # 行和归一化 (Row normalization)
        row_sums = np.array(adj.sum(axis=1)).flatten()
        inv_sums = np.divide(1.0, row_sums, out=np.zeros_like(row_sums, dtype=float), where=row_sums != 0)
        norm_diag = sp.diags(inv_sums)
        normalized_adj = norm_diag @ adj

        self.quarterly_matrices[quarter_label] = normalized_adj.tocsr()
        return self.quarterly_matrices[quarter_label]

    def run_nale_propagation(
        self,
        node_scores: Dict[str, float],
        alpha: float = 0.4,
        quarter_label: str = "2024Q1"
    ) -> Dict[str, float]:
        """运行 NALE 网络增强嵌入传导 (Yılkı 2026)。"""
        W = self.quarterly_matrices.get(quarter_label)
        if W is None:
            W = self.build_adjacency_matrix(quarter_label)

        N = len(self.node_tickers)
        s0 = np.array([node_scores.get(t, 0.0) for t in self.node_tickers])
        
        # S_{NALE} = (1 - alpha) * s0 + alpha * (W @ s0)
        propagated = W.dot(s0)
        s_nale = (1.0 - alpha) * s0 + alpha * propagated

        return {self.node_tickers[i]: float(s_nale[i]) for i in range(N)}

    def run_placebo_verification(
        self,
        node_scores: Dict[str, float],
        n_shuffles: int = 100,
        alpha: float = 0.4,
        quarter_label: str = "2024Q1"
    ) -> Dict[str, Any]:
        """Placebo 蒙特卡洛边洗牌拓扑检验 (100 次边重排)。
        
        检验零假设 H0: NALE 得分的预测增强纯属随机网络连通性噪音。
        若真实网络得分与洗牌随机均值的 Z-Score > 2.0 (p < 0.05)，则拒绝 H0，确认真实拓扑有效性。
        """
        real_scores = self.run_nale_propagation(node_scores, alpha, quarter_label)
        N = len(self.node_tickers)

        W_real = self.quarterly_matrices.get(quarter_label)
        if W_real is None:
            W_real = self.build_adjacency_matrix(quarter_label)

        s0 = np.array([node_scores.get(t, 0.0) for t in self.node_tickers])
        real_vec = np.array([real_scores[t] for t in self.node_tickers])

        # 边洗牌 Monte Carlo
        placebo_matrix = np.zeros((n_shuffles, N))
        non_zeros = W_real.nnz

        if non_zeros == 0:
            return {"is_topologically_valid": False, "mean_z_score": 0.0, "p_value": 1.0}

        row_idx, col_idx = W_real.nonzero()
        data_vals = W_real.data

        np.random.seed(42)
        for s in range(n_shuffles):
            # 随机打乱列索引 (保持出度结构，破坏真实经济关联)
            shuffled_cols = np.random.permutation(col_idx)
            W_shuffled = sp.csr_matrix((data_vals, (row_idx, shuffled_cols)), shape=(N, N))
            # 重新行归一化
            r_sums = np.array(W_shuffled.sum(axis=1)).flatten()
            inv_s = np.divide(1.0, r_sums, out=np.zeros_like(r_sums, dtype=float), where=r_sums != 0)
            W_shuff_norm = sp.diags(inv_s) @ W_shuffled

            p_prop = W_shuff_norm.dot(s0)
            p_nale = (1.0 - alpha) * s0 + alpha * p_prop
            placebo_matrix[s, :] = p_nale

        placebo_mean = np.mean(placebo_matrix, axis=0)
        placebo_std = np.std(placebo_matrix, axis=0) + 1e-8

        z_scores = (real_vec - placebo_mean) / placebo_std
        mean_z = float(np.mean(np.abs(z_scores)))
        p_val = float(2.0 * (1.0 - stats_norm_cdf(mean_z)))

        return {
            "n_shuffles": n_shuffles,
            "mean_z_score": mean_z,
            "p_value": p_val,
            "is_topologically_valid": bool(mean_z >= 1.96)
        }


def stats_norm_cdf(x: float) -> float:
    """高斯累积分布函数近似。"""
    import math
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
