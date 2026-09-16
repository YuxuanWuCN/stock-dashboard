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
        """Placebo 蒙特卡洛边洗牌拓扑检验。

        H0：给定节点得分、边位置和权重，供应商列索引可以随机交换。
        真实网络与 n_shuffles 个洗牌网络共同估计逐节点均值和标准差，
        对所有网络对称地计算平均绝对标准化偏差 T，保留节点间相关性。
        mean_z_score 返回真实网络的 T，仅作描述，不服从标准正态分布。
        p = (1 + count(T_shuffle >= T_real)) / (n_shuffles + 1)，
        并列值计入尾部；绝对偏差已包含两个方向，不再把尾部概率乘二。
        is_topologically_valid 表示 p < 0.05 下拒绝此洗牌零假设，
        不代表预测能力、因果关系或投资收益得到验证。

        n_shuffles 必须是正整数；非有限输入或传播结果抛出 ValueError。
        缺失节点得分沿用传播接口的 0.0 默认值。
        """
        if (
            isinstance(n_shuffles, (bool, np.bool_))
            or not isinstance(n_shuffles, (int, np.integer))
            or n_shuffles < 1
        ):
            raise ValueError("n_shuffles must be a positive integer")
        n_shuffles = int(n_shuffles)
        s0 = np.array([node_scores.get(t, 0.0) for t in self.node_tickers], dtype=float)
        if not np.isfinite(alpha) or not np.all(np.isfinite(s0)):
            raise ValueError("alpha and node scores must be finite")

        real_scores = self.run_nale_propagation(node_scores, alpha, quarter_label)
        N = len(self.node_tickers)

        W_real = self.quarterly_matrices.get(quarter_label)
        if W_real is None:
            W_real = self.build_adjacency_matrix(quarter_label)

        real_vec = np.array([real_scores[t] for t in self.node_tickers])
        if not np.all(np.isfinite(real_vec)):
            raise ValueError("NALE propagation results must be finite")

        # 边洗牌 Monte Carlo
        non_zeros = W_real.nnz

        if non_zeros == 0:
            return {
                "n_shuffles": n_shuffles,
                "mean_z_score": 0.0,
                "p_value": 1.0,
                "is_topologically_valid": False,
            }

        placebo_matrix = np.zeros((n_shuffles, N))
        row_idx, col_idx = W_real.nonzero()
        data_vals = W_real.data

        rng = np.random.default_rng(42)
        for s in range(n_shuffles):
            # 保持边槽的行位置、权重及供应商索引多重集，随机交换供应商。
            shuffled_cols = rng.permutation(col_idx)
            W_shuffled = sp.csr_matrix((data_vals, (row_idx, shuffled_cols)), shape=(N, N))
            # 重新行归一化
            r_sums = np.array(W_shuffled.sum(axis=1)).flatten()
            inv_s = np.divide(1.0, r_sums, out=np.zeros_like(r_sums, dtype=float), where=r_sums != 0)
            W_shuff_norm = sp.diags(inv_s) @ W_shuffled

            p_prop = W_shuff_norm.dot(s0)
            p_nale = (1.0 - alpha) * s0 + alpha * p_prop
            placebo_matrix[s, :] = p_nale

        if not np.all(np.isfinite(placebo_matrix)):
            raise ValueError("Placebo propagation results must be finite")

        # 共享的标准化参数必须对真实样本和洗牌样本一视同仁；仅用洗牌
        # 样本拟合会让它们成为样本内残差，而真实网络成为样本外残差。
        # 先减去同一参考向量，避免恒定列的均值舍入误差产生虚假的 Z 值。
        pooled = np.vstack((real_vec, placebo_matrix)) - real_vec
        centered = pooled - np.mean(pooled, axis=0)
        pooled_std = np.std(pooled, axis=0)
        if not np.all(np.isfinite(centered)) or not np.all(np.isfinite(pooled_std)):
            raise ValueError("Placebo standardization must be finite")
        z_scores = np.divide(
            centered, pooled_std, out=np.zeros_like(centered), where=pooled_std > 0
        )
        test_statistics = np.mean(np.abs(z_scores), axis=1)
        mean_z = float(test_statistics[0])

        # Monte Carlo 加一修正；把浮点舍入范围内的近似并列也计入尾部。
        tolerance = 100 * np.finfo(float).eps * max(1.0, mean_z)
        n_extreme = np.count_nonzero(test_statistics[1:] >= mean_z - tolerance)
        p_val = float((n_extreme + 1) / (n_shuffles + 1))

        return {
            "n_shuffles": n_shuffles,
            "mean_z_score": mean_z,
            "p_value": p_val,
            "is_topologically_valid": bool(p_val < 0.05)
        }
