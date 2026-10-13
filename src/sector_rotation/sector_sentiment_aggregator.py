# -*- coding: utf-8 -*-
"""src/sector_rotation/sector_sentiment_aggregator.py —— 板块级情绪聚合器

实现 Milestone M1 核心功能：
1. 成分股情绪加权聚合（基于个股置信度与新闻样本篇数）
2. 成分股情绪离散度/波动率计算（样本标准差 ddof=1）
3. 板块综合置信度评估（覆盖广度 + 观点一致性）
4. 3日情绪趋势动态判定（'rising' | 'stable' | 'declining'）
5. 全市场多板块批量聚合与默认中性状态补齐
6. 完整兼容 v2.6 LLMSentimentResult 及通用字典输入
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from .config import (
    EXPECTED_STOCKS_PER_SECTOR,
    SECTORS,
    SENTIMENT_BOUND_MAX,
    SENTIMENT_BOUND_MIN,
    TREND_CONFIRM_DAYS,
    TREND_DECLINING,
    TREND_RISING,
    TREND_STABLE,
)
from .utils.sector_utils import (
    SectorState,
    StockSentimentInput,
    validate_stock_input,
)

logger = logging.getLogger("stock-dashboard.sector_rotation.aggregator")


class SectorSentimentAggregator:
    """板块级情绪聚合器

    将个股粒度的新闻语义情绪、置信度与样本量，汇总为板块级的高维情绪特征。
    """

    def __init__(
        self,
        expected_stocks_per_sector: int = EXPECTED_STOCKS_PER_SECTOR,
        trend_threshold: float = 0.05,
    ) -> None:
        """初始化聚合器

        Args:
            expected_stocks_per_sector: 行业基准成分股数（默认6），用于覆盖度归一化
            trend_threshold: 3日趋势认定的绝对变化幅度阈值（默认0.05）
        """
        self.expected_stocks = max(1, int(expected_stocks_per_sector))
        self.trend_threshold = float(trend_threshold)

    # -------------------------------------------------------------------------
    # 核心聚合方法
    # -------------------------------------------------------------------------

    def aggregate(
        self,
        stocks: List[Union[StockSentimentInput, Dict[str, Any], Any]],
        sector: str,
        historical_scores: Optional[List[float]] = None,
        timestamp: Optional[str] = None,
    ) -> SectorState:
        """从个股列表聚合生成单一板块的完整情绪状态。

        Args:
            stocks: 成分股情绪输入列表（可为 StockSentimentInput 或 dict）
            sector: 板块标识符（如 'green', 'storage', 'gold'）
            historical_scores: 该板块过去各交易日的情绪历史得分列表
            timestamp: 状态更新时间戳（留空则取当前系统时间）

        Returns:
            SectorState 板块状态契约对象
        """
        sector_id = str(sector).strip()
        current_ts = timestamp if timestamp else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 过滤并清洗该板块的成分股
        matched_stocks: List[StockSentimentInput] = []
        for raw in stocks:
            item = validate_stock_input(raw)
            # 若单票未标记板块，则默认归属当前聚合板块；若标记了且一致则纳入
            if not item.sector or item.sector == sector_id:
                matched_stocks.append(item)

        # 边界情况：成分股列表为空
        if not matched_stocks:
            hist = list(historical_scores) if historical_scores is not None else []
            trend = self.calculate_trend(hist) if hist else TREND_STABLE
            return SectorState(
                sector=sector_id,
                sentiment_score=0.0,
                sentiment_trend=trend,
                volatility=0.0,
                stock_count=0,
                confidence=0.0,
                last_updated=current_ts,
                stock_sentiments=[],
            )

        # 提取成分股得分与计算权重
        scores: List[float] = [s.sentiment_score for s in matched_stocks]
        confidences: List[float] = [s.sentiment_confidence for s in matched_stocks]
        news_counts: List[int] = [s.news_count for s in matched_stocks]

        # 1. 权重公式：w_i = c_i * max(v_i, 1)
        weights = [c * max(v, 1) for c, v in zip(confidences, news_counts)]
        total_weight = sum(weights)

        # 权重退化保底：全为 0 时退化为等权算术平均
        if total_weight <= 0.0:
            weights = [1.0 / len(matched_stocks)] * len(matched_stocks)
            total_weight = 1.0

        # 2. 板块加权平均情绪：\bar{S} = clip(sum(w_i * s_i) / sum(w_i), -1.0, 1.0)
        weighted_sum = sum(w * s for w, s in zip(weights, scores))
        avg_score = weighted_sum / total_weight
        clamped_score = max(SENTIMENT_BOUND_MIN, min(SENTIMENT_BOUND_MAX, avg_score))

        # 3. 情绪离散度/波动率：样本标准差（ddof=1，N<=1 时为 0.0）
        volatility = self.calculate_volatility(scores)

        # 4. 板块综合置信度
        confidence = self.calculate_confidence(
            weights=weights,
            confidences=confidences,
            volatility=volatility,
            stock_count=len(matched_stocks),
        )

        # 5. 3日情绪趋势判定
        trend = self.update_trend(
            sector=sector_id,
            current_score=clamped_score,
            history=historical_scores,
        )

        return SectorState(
            sector=sector_id,
            sentiment_score=round(clamped_score, 4),
            sentiment_trend=trend,
            volatility=round(volatility, 4),
            stock_count=len(matched_stocks),
            confidence=round(confidence, 4),
            last_updated=current_ts,
            stock_sentiments=[round(s, 4) for s in scores],
        )

    def aggregate_market(
        self,
        stock_universe: List[Union[StockSentimentInput, Dict[str, Any], Any]],
        history_map: Optional[Dict[str, List[float]]] = None,
        timestamp: Optional[str] = None,
    ) -> Dict[str, SectorState]:
        """批量聚合全市场各板块情绪状态。

        包含 SECTORS 中所有预设板块，若全市场中某板块无数据，自动填充中性默认状态。

        Args:
            stock_universe: 全市场个股情绪输入列表
            history_map: 各板块历史得分映射表 {sector_id: [score1, score2, ...]}
            timestamp: 状态更新时间戳

        Returns:
            Dict[str, SectorState]: 各板块最新状态字典
        """
        histories = history_map or {}
        current_ts = timestamp if timestamp else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 归类全市场股票
        sector_buckets: Dict[str, List[StockSentimentInput]] = {}
        for sector_id in SECTORS.keys():
            sector_buckets[sector_id] = []

        for raw in stock_universe:
            item = validate_stock_input(raw)
            sec = item.sector
            if sec not in sector_buckets:
                sector_buckets[sec] = []
            sector_buckets[sec].append(item)

        results: Dict[str, SectorState] = {}
        for sector_id, stocks in sector_buckets.items():
            if not sector_id:
                # 忽略无板块归属的散落股票
                continue
            hist = histories.get(sector_id, [])
            results[sector_id] = self.aggregate(
                stocks=stocks,
                sector=sector_id,
                historical_scores=hist,
                timestamp=current_ts,
            )

        return results

    # -------------------------------------------------------------------------
    # 统计与特征计算辅助方法
    # -------------------------------------------------------------------------

    def calculate_volatility(self, scores: List[float]) -> float:
        """计算成分股情绪样本标准差（ddof=1）。

        当 N <= 1 或所有得分完全相同时返回 0.0。

        Args:
            scores: 成分股情绪得分列表

        Returns:
            float 波动率标准差 >= 0.0
        """
        n = len(scores)
        if n <= 1:
            return 0.0

        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / (n - 1)
        if variance <= 0.0:
            return 0.0
        return math.sqrt(variance)

    def calculate_confidence(
        self,
        weights: List[float],
        confidences: List[float],
        volatility: float,
        stock_count: int,
    ) -> float:
        """计算板块综合置信度。

        公式：
        C_base = sum(w_i * c_i) / sum(w_i)
        C_breadth = min(1.0, sqrt(N / N_expected))
        C_consistency = max(0.2, 1.0 - 0.5 * sigma)
        C_sector = clip(C_base * C_breadth * C_consistency, 0.0, 1.0)

        Args:
            weights: 各成分股权重序列
            confidences: 各成分股置信度序列
            volatility: 成分股离散度标准差
            stock_count: 成分股实际数量

        Returns:
            float 板块置信度 [0.0, 1.0]
        """
        if stock_count <= 0:
            return 0.0

        total_weight = sum(weights)
        if total_weight > 0.0:
            c_base = sum(w * c for w, c in zip(weights, confidences)) / total_weight
        else:
            c_base = sum(confidences) / stock_count

        # 样本覆盖广度调整因子
        c_breadth = min(1.0, math.sqrt(stock_count / self.expected_stocks))

        # 内部观点一致性调整因子（离散度越高，惩罚越重）
        c_consistency = max(0.2, 1.0 - 0.5 * float(volatility))

        raw_c = c_base * c_breadth * c_consistency
        return max(0.0, min(1.0, raw_c))

    def calculate_trend(self, historical_scores: List[float]) -> str:
        """根据历史序列判定情绪趋势。

        要求至少具备 3 个连续观察点。
        - 连续递降且两端变化超过阈值 -> 'declining'
        - 连续递增且两端变化超过阈值 -> 'rising'
        - 其余情况 -> 'stable'

        Args:
            historical_scores: 连续历史得分序列

        Returns:
            'rising' | 'stable' | 'declining'
        """
        if not historical_scores or len(historical_scores) < TREND_CONFIRM_DAYS:
            return TREND_STABLE

        # 取最近 TREND_CONFIRM_DAYS 个观测值
        recent = historical_scores[-TREND_CONFIRM_DAYS:]
        s_t2, s_t1, s_t = recent[0], recent[1], recent[2]

        # 连续下沉判定
        if s_t < s_t1 < s_t2 and (s_t - s_t2) < -self.trend_threshold:
            return TREND_DECLINING

        # 连续上升判定
        if s_t > s_t1 > s_t2 and (s_t - s_t2) > self.trend_threshold:
            return TREND_RISING

        return TREND_STABLE

    def update_trend(
        self,
        sector: str,
        current_score: float,
        history: Optional[List[float]] = None,
    ) -> str:
        """结合历史记录与当前得分，动态更新 3 日趋势。

        Args:
            sector: 板块标识符
            current_score: 当前计算得到的板块情绪得分
            history: 历史得分列表

        Returns:
            'rising' | 'stable' | 'declining'
        """
        full_series: List[float] = list(history) if history is not None else []
        full_series.append(current_score)
        return self.calculate_trend(full_series)
