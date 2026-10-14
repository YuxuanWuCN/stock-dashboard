# -*- coding: utf-8 -*-
r"""src/portfolio/signal_adapter.py —— 股票/行业 NALE 信号向基金/ETF 层的点时适配器

依据《FOF 组合配置改造意见》§3.2：
S_{j,t}^{fund} = \frac{\sum_{i \in j} AUMWeight_{i,j,t} \cdot q_{i,t} \cdot S_{i,t}}{\sum_{i \in j} AUMWeight_{i,j,t} \cdot q_{i,t}}

核心特性：
1. Fail-Closed 熔断设计：当无有效成分股、分母为 0 或数据异常时，显式标记拒识 (is_valid=False) 并记录原因，
   严禁静默伪造或使用默认强信号。
2. 聚合方式对比支持：等权 (equal_weight)、流通市值权重 (mcap_weight)、置信度权重 (confidence_weight)。
3. 与既有 NALE (静态)、T-NALE (时效时滞) 及 Sentiment-only (无网络传播) 的统一适配接口。
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.portfolio.contracts import (
    AggregationMethod,
    PointInTimeSignal,
)

logger = logging.getLogger("portfolio.signal_adapter")


class NALESignalAdapter:
    """NALE 信号转基金/ETF 层适配引擎。"""

    def __init__(self, default_alpha: float = 0.4):
        self.default_alpha = default_alpha

    def compute_static_nale(
        self,
        node_scores: Dict[str, float],
        adjacency_matrix: np.ndarray,
        ticker_list: List[str],
        alpha: Optional[float] = None,
    ) -> Dict[str, float]:
        r"""经典 NALE 矩阵网络传导手算/实现接口:
        S_{NALE} = (1 - \alpha) S_0 + \alpha W_{norm} S_0
        """
        a = alpha if alpha is not None else self.default_alpha
        N = len(ticker_list)
        if N == 0:
            return {}
        if adjacency_matrix.shape != (N, N):
            raise ValueError(f"邻接矩阵维度 {adjacency_matrix.shape} 与标的数 {N} 不匹配")

        s0 = np.array([float(node_scores.get(t, 0.0)) for t in ticker_list], dtype=float).reshape(-1, 1)

        # 检查 NaN / Inf
        if np.isnan(s0).any() or np.isinf(s0).any():
            s0 = np.nan_to_num(s0, nan=0.0, posinf=1.0, neginf=-1.0)

        row_sums = adjacency_matrix.sum(axis=1, keepdims=True)
        w_norm = np.divide(
            adjacency_matrix,
            row_sums,
            out=np.zeros_like(adjacency_matrix, dtype=float),
            where=row_sums != 0,
        )

        propagated = w_norm @ s0
        final_vec = (1.0 - a) * s0 + a * propagated
        final_vec = np.clip(final_vec, -1.0, 1.0)

        return {ticker_list[i]: float(final_vec[i, 0]) for i in range(N)}

    def aggregate_to_fund_signal(
        self,
        as_of_date: str,
        fund_ticker: str,
        constituents: List[str],
        stock_scores: Dict[str, float],
        stock_confidences: Optional[Dict[str, float]] = None,
        constituent_weights: Optional[Dict[str, float]] = None,
        method: AggregationMethod = AggregationMethod.EQUAL_WEIGHT,
        source_method: str = "nale_aggregated",
    ) -> PointInTimeSignal:
        r"""将成分股信号点时聚合为单个基金/ETF信号。

        Fail-Closed 校验：
        - 成分股列表为空 -> 拒识
        - 有效可用成分股为 0 -> 拒识
        - 分母之和 <= 1e-9 -> 拒识
        """
        if not constituents:
            return PointInTimeSignal(
                as_of_date=as_of_date,
                ticker=fund_ticker,
                score=0.0,
                confidence=0.0,
                source_method=source_method,
                is_valid=False,
                refusal_reason="Constituent list is empty",
                details={"method": method.value, "valid_count": 0},
            )

        confs = stock_confidences or {}
        raw_weights = constituent_weights or {}

        numerator = 0.0
        denominator = 0.0
        valid_items_count = 0
        total_conf = 0.0

        for stock in constituents:
            if stock not in stock_scores:
                continue

            score = float(stock_scores[stock])
            if math.isnan(score) or math.isinf(score):
                continue

            q = float(confs.get(stock, 1.0))
            if math.isnan(q) or math.isinf(q) or q < 0.0:
                q = 0.0

            if method == AggregationMethod.EQUAL_WEIGHT:
                effective_weight = 1.0
            elif method == AggregationMethod.MCAP_WEIGHT:
                w_base = float(raw_weights.get(stock, 1.0))
                if w_base <= 0.0 or math.isnan(w_base):
                    w_base = 0.0
                effective_weight = w_base
            elif method == AggregationMethod.CONFIDENCE_WEIGHT:
                effective_weight = q
            else:
                effective_weight = 1.0

            if effective_weight > 0.0:
                numerator += effective_weight * score
                denominator += effective_weight
                valid_items_count += 1
                total_conf += q

        if valid_items_count == 0 or denominator <= 1e-9:
            return PointInTimeSignal(
                as_of_date=as_of_date,
                ticker=fund_ticker,
                score=0.0,
                confidence=0.0,
                source_method=source_method,
                is_valid=False,
                refusal_reason=f"Zero valid constituents or zero denominator (valid_count={valid_items_count})",
                details={
                    "method": method.value,
                    "constituents_total": len(constituents),
                    "valid_count": valid_items_count,
                    "denominator": denominator,
                },
            )

        aggregated_score = float(np.clip(numerator / denominator, -1.0, 1.0))
        avg_confidence = float(np.clip(total_conf / valid_items_count, 0.0, 1.0))

        return PointInTimeSignal(
            as_of_date=as_of_date,
            ticker=fund_ticker,
            score=aggregated_score,
            confidence=avg_confidence,
            source_method=source_method,
            is_valid=True,
            refusal_reason=None,
            details={
                "method": method.value,
                "constituents_total": len(constituents),
                "valid_count": valid_items_count,
                "coverage_ratio": valid_items_count / len(constituents),
            },
        )

    def aggregate_batch(
        self,
        as_of_date: str,
        fund_constituents_map: Dict[str, List[str]],
        stock_scores: Dict[str, float],
        stock_confidences: Optional[Dict[str, float]] = None,
        constituent_weights_map: Optional[Dict[str, Dict[str, float]]] = None,
        method: AggregationMethod = AggregationMethod.EQUAL_WEIGHT,
        source_method: str = "nale_aggregated",
    ) -> Dict[str, PointInTimeSignal]:
        """批量聚合多个基金/ETF 的信号。"""
        results: Dict[str, PointInTimeSignal] = {}
        for fund_ticker, constituents in fund_constituents_map.items():
            weights = (constituent_weights_map or {}).get(fund_ticker, None)
            sig = self.aggregate_to_fund_signal(
                as_of_date=as_of_date,
                fund_ticker=fund_ticker,
                constituents=constituents,
                stock_scores=stock_scores,
                stock_confidences=stock_confidences,
                constituent_weights=weights,
                method=method,
                source_method=source_method,
            )
            results[fund_ticker] = sig
        return results
