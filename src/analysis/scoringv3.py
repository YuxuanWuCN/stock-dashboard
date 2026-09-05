# -*- coding: utf-8 -*-
"""src/analysis/scoringv3.py —— GFCA (Geometric Factor Coordinate Alignment) & NALE Scoring (Weeks 4 & 6)

依据规范：
1. 《StockDashboard v3.0 & Serenity Chokepoint 12-Week Roadmap》Phase I (Week 4) & Phase II (Week 6)
2. GFCA (Geometric Factor Coordinate Alignment):
   - 使用平滑双曲正切 (tanh) 过滤器将多维原始因子载荷映射至标准化 K 维空间 [-1, 1]^K
   - 保留深度的梯度与相对排序信息，有效抑制极端异常值
3. NALE (Network-Augmented LLM Embeddings / Yılkı 2026):
   - 沿供应链拓扑邻接矩阵 W 传导非结构化研报事实/情绪特征向量 (alpha = 0.4)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger("scoringv3")

from src.graph.temporal_nale import (
    TemporalNALEEngine,
    TemporalNALEResult,
    TrajectoryResult,
)


@dataclass
class GFCACoordinates:
    """资产 GFCA 几何因子空间坐标。"""
    ticker: str
    coordinates: Dict[str, float]  # 各因子的 [-1, 1] 归一化空间坐标
    composite_score: float  # 几何综合得分 [-1, 1]
    raw_loadings: Dict[str, float]  # 原始回归载荷/因子值


@dataclass
class NALEScoreResult:
    """NALE 网络增强嵌入传播得分。"""
    ticker: str
    self_score: float  # 本节点原生大模型文本情感/事实得分 [-1, 1]
    upstream_propagated: float  # 沿上游供应商网络传导而来的增强得分
    downstream_propagated: float  # 沿下游客户网络传导而来的增强得分
    final_nale_score: float  # NALE 综合网络嵌入得分 [-1, 1]
    propagation_weight: float = 0.4


class GFCAScoringEngine:
    """几何因子坐标对齐 (GFCA) 与网络传播评分引擎。"""

    def __init__(self, tanh_scaling: float = 1.5, nale_alpha: float = 0.4):
        self.tanh_scaling = tanh_scaling
        self.nale_alpha = nale_alpha

    def align_gfca_coordinates(
        self,
        raw_factor_df: pd.DataFrame,  # 行: 各标的 ticker, 列: 各因子 (MKT, SMB, HML, MOM, etc.)
        factor_weights: Optional[Dict[str, float]] = None,
        impairment_penalties: Optional[Dict[str, float]] = None
    ) -> Dict[str, GFCACoordinates]:
        r"""将资产多维原始因子载荷映射到 [-1, 1]^K 标准化空间。
        
        数学公式:
        1. 截面 Z-Score 标准化: z_{i,k} = \frac{x_{i,k} - \mu_k}{\sigma_k + \epsilon}
        2. 平滑双曲正切过滤: c_{i,k} = \tanh\left(\frac{z_{i,k}}{\text{scale}}\right) \in [-1, 1]
        3. 注入 Nowcasting 减值惩罚动态负漂移: c_{i,k} \leftarrow c_{i,k} + \text{Drift}_{GFCA, i} (clip 至 [-1, 1])
        """
        df = raw_factor_df.copy()
        tickers = list(df.index)
        factors = list(df.columns)
        penalties = impairment_penalties or {}

        # 默认等权
        if factor_weights is None:
            weights = {f: 1.0 / len(factors) for f in factors}
        else:
            w_sum = sum(factor_weights.values())
            weights = {f: factor_weights.get(f, 0.0) / (w_sum if w_sum > 0 else 1.0) for f in factors}

        # 1. 截面均值与标准差
        means = df.mean(axis=0)
        stds = df.std(axis=0).replace(0.0, 1.0)

        results: Dict[str, GFCACoordinates] = {}
        for ticker in tickers:
            row = df.loc[ticker]
            coords: Dict[str, float] = {}
            raw_vals: Dict[str, float] = {}

            penalty_drift = float(penalties.get(ticker, 0.0))

            weighted_sum = 0.0
            for factor in factors:
                val = float(row[factor])
                raw_vals[factor] = val
                z = (val - means[factor]) / (stds[factor] + 1e-8)
                coord = np.tanh(z / self.tanh_scaling)
                # 注入减值漂移 (主要作用于动量/成长类维度)
                coord_adjusted = float(np.clip(coord + penalty_drift, -1.0, 1.0))
                coords[factor] = coord_adjusted
                weighted_sum += weights.get(factor, 0.0) * coord_adjusted

            comp_score = float(np.clip(weighted_sum, -1.0, 1.0))
            results[ticker] = GFCACoordinates(
                ticker=ticker,
                coordinates=coords,
                composite_score=comp_score,
                raw_loadings=raw_vals
            )

        return results

    def calculate_nale_score(
        self,
        node_scores: Dict[str, float],  # 各标的原生大模型事实得分 S_0
        adjacency_matrix: np.ndarray,   # 有向经济邻接矩阵 W (N x N)
        ticker_list: List[str],
        alpha: Optional[float] = None
    ) -> Dict[str, NALEScoreResult]:
        r"""计算 Network-Augmented LLM Embeddings (NALE) 网络增强传导得分。
        
        传导方程 (Yılkı 2026):
        S_{\text{NALE}} = (1 - \alpha) S_0 + \alpha \cdot (W S_0)
        """
        prop_weight = alpha if alpha is not None else self.nale_alpha
        N = len(ticker_list)
        S0_vec = np.array([node_scores.get(t, 0.0) for t in ticker_list]).reshape(-1, 1)

        # 矩阵乘法传播: 沿供应链图谱的加权邻居信息
        if adjacency_matrix.shape != (N, N):
            raise ValueError(f"邻接矩阵维度 {adjacency_matrix.shape} 与标的数 {N} 不匹配。")

        # 归一化邻接矩阵行和 (随机游走矩阵)
        row_sums = adjacency_matrix.sum(axis=1, keepdims=True)
        W_norm = np.divide(adjacency_matrix, row_sums, out=np.zeros_like(adjacency_matrix), where=row_sums != 0)

        propagated_vec = W_norm @ S0_vec
        final_nale_vec = (1.0 - prop_weight) * S0_vec + prop_weight * propagated_vec

        results: Dict[str, NALEScoreResult] = {}
        for i, ticker in enumerate(ticker_list):
            s_self = float(S0_vec[i, 0])
            s_prop = float(propagated_vec[i, 0])
            s_final = float(np.clip(final_nale_vec[i, 0], -1.0, 1.0))

            results[ticker] = NALEScoreResult(
                ticker=ticker,
                self_score=s_self,
                upstream_propagated=s_prop,
                downstream_propagated=0.0,
                final_nale_score=s_final,
                propagation_weight=prop_weight
            )

        return results

    def calculate_temporal_nale_score(
        self,
        node_scores: Dict[str, float],
        adjacency_matrix: np.ndarray,
        ticker_list: List[str],
        horizon_days: float = 5.0,
        node_ages_days: Optional[Dict[str, float]] = None,
        node_source_types: Optional[Dict[str, str]] = None,
        ticker_categories: Optional[Dict[str, str]] = None,
        alpha: Optional[float] = None
    ) -> Dict[str, TemporalNALEResult]:
        r"""计算考虑物理库存时滞与信息半衰期的 Temporal-NALE (T-NALE) 连续时空扩散得分。"""
        engine = TemporalNALEEngine(alpha=alpha if alpha is not None else self.nale_alpha)
        # 归一化邻接矩阵行和 (若尚未归一化)
        row_sums = adjacency_matrix.sum(axis=1, keepdims=True)
        W_norm = np.divide(adjacency_matrix, row_sums, out=np.zeros_like(adjacency_matrix, dtype=float), where=row_sums != 0)
        return engine.calculate_temporal_nale(
            node_scores=node_scores,
            adjacency_matrix=W_norm,
            ticker_list=ticker_list,
            horizon_days=horizon_days,
            node_ages_days=node_ages_days,
            node_source_types=node_source_types,
            ticker_categories=ticker_categories,
            alpha=alpha if alpha is not None else self.nale_alpha
        )
