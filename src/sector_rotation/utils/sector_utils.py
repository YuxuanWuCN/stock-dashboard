# -*- coding: utf-8 -*-
"""src/sector_rotation/utils/sector_utils.py —— 板块轮动数据契约、校验器与兼容适配器

包含：
1. StockSentimentInput 与 SectorState 核心数据结构（双向兼容 sector/sector_id 字段）
2. 数值范围校验器与清洗函数
3. 交易日历辅助工具（A股非交易日过滤、持仓天数计算）
4. v2.6 LLMSentimentResult 及通用字典的兼容转换函数
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from ..config import (
    SECTORS,
    SENTIMENT_BOUND_MAX,
    SENTIMENT_BOUND_MIN,
    TREND_DECLINING,
    TREND_RISING,
    TREND_STABLE,
    get_sector_for_ticker,
)


# ============================================================================
# 1. 核心数据契约
# ============================================================================

@dataclass
class StockSentimentInput:
    """个股情感分析输入契约

    用于 SectorSentimentAggregator 接收上游单票分析成果。
    """
    code: str
    name: str = ""
    sector: str = ""
    sentiment_score: float = 0.0         # 范围 [-1.0, 1.0]
    sentiment_confidence: float = 0.8    # 范围 [0.0, 1.0]
    news_count: int = 1                  # 样本新闻/研报篇数 >= 0
    timestamp: str = ""

    def __post_init__(self) -> None:
        self.code = str(self.code).strip()
        self.name = str(self.name).strip()
        self.sector = str(self.sector).strip()
        self.sentiment_score = validate_sentiment_score(self.sentiment_score)
        self.sentiment_confidence = validate_confidence(self.sentiment_confidence)
        self.news_count = validate_news_count(self.news_count)
        self.timestamp = str(self.timestamp).strip()

    def to_dict(self) -> Dict[str, Any]:
        """序列化为标准字典"""
        return {
            "code": self.code,
            "name": self.name,
            "sector": self.sector,
            "sentiment_score": round(self.sentiment_score, 4),
            "sentiment_confidence": round(self.sentiment_confidence, 4),
            "news_count": self.news_count,
            "timestamp": self.timestamp,
        }


@dataclass
class SectorState:
    """板块状态聚合输出契约

    既支持通过 .sector 访问，也支持通过 .sector_id 访问，以兼容不同调用方的契约规范。
    """
    sector: str
    sentiment_score: float               # [-1.0, 1.0]
    sentiment_trend: str                 # "rising" | "stable" | "declining"
    volatility: float                    # >= 0.0 (样本标准差 ddof=1)
    stock_count: int                     # 成分股数量 >= 0
    confidence: float                    # [0.0, 1.0] 板块综合置信度
    last_updated: str = ""
    stock_sentiments: List[float] = field(default_factory=list)

    def __init__(
        self,
        sector: str = "",
        sentiment_score: float = 0.0,
        sentiment_trend: str = TREND_STABLE,
        volatility: float = 0.0,
        stock_count: int = 0,
        confidence: float = 0.0,
        last_updated: str = "",
        stock_sentiments: Optional[List[float]] = None,
        sector_id: Optional[str] = None,
    ) -> None:
        # 支持 sector 或 sector_id 入参
        effective_sector = sector_id if (sector_id is not None and not sector) else sector
        self.sector = str(effective_sector).strip()
        self.sentiment_score = validate_sentiment_score(sentiment_score)
        self.sentiment_trend = str(sentiment_trend) if str(sentiment_trend) in (
            TREND_RISING, TREND_STABLE, TREND_DECLINING
        ) else TREND_STABLE
        self.volatility = max(0.0, float(volatility))
        self.stock_count = max(0, int(stock_count))
        self.confidence = validate_confidence(confidence)
        self.last_updated = str(last_updated).strip()
        self.stock_sentiments = list(stock_sentiments) if stock_sentiments is not None else []

    @property
    def sector_id(self) -> str:
        """兼容 sector_id 访问"""
        return self.sector

    @sector_id.setter
    def sector_id(self, val: str) -> None:
        self.sector = str(val).strip()

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 友好字典"""
        return {
            "sector": self.sector,
            "sector_id": self.sector,
            "sentiment_score": round(self.sentiment_score, 4),
            "sentiment_trend": self.sentiment_trend,
            "volatility": round(self.volatility, 4),
            "stock_count": self.stock_count,
            "confidence": round(self.confidence, 4),
            "last_updated": self.last_updated,
            "stock_sentiments": [round(s, 4) for s in self.stock_sentiments],
        }


# ============================================================================
# 2. 字段级校验器与清洗工具
# ============================================================================

def validate_sentiment_score(score: Any) -> float:
    """校验并将情绪得分约束在 [-1.0, 1.0] 区间内。

    Args:
        score: 输入原始得分

    Returns:
        float 范围在 [-1.0, 1.0]

    Raises:
        ValueError: 当输入无法转为数值或为 NaN 时
    """
    try:
        val = float(score)
    except (TypeError, ValueError) as err:
        raise ValueError(f"情绪得分必须为有效数值，收到: {score}") from err

    if math.isnan(val):
        raise ValueError("情绪得分不能为 NaN")
    if math.isinf(val):
        return SENTIMENT_BOUND_MAX if val > 0 else SENTIMENT_BOUND_MIN

    return max(SENTIMENT_BOUND_MIN, min(SENTIMENT_BOUND_MAX, val))


def validate_confidence(confidence: Any) -> float:
    """校验并将置信度约束在 [0.0, 1.0] 区间内。

    Args:
        confidence: 输入置信度

    Returns:
        float 范围在 [0.0, 1.0]
    """
    try:
        val = float(confidence)
    except (TypeError, ValueError):
        return 0.5  # 降级默认置信度

    if math.isnan(val) or val < 0.0:
        return 0.0
    if val > 1.0:
        return 1.0
    return val


def validate_news_count(news_count: Any) -> int:
    """校验新闻样本篇数，确保为非负整数。"""
    try:
        val = int(news_count)
        return max(0, val)
    except (TypeError, ValueError):
        return 1


def validate_sector(sector: str, allow_unknown: bool = False) -> str:
    """校验板块标识符是否合法。

    Args:
        sector: 待校验板块标识符
        allow_unknown: 是否允许不在 SECTORS 配置中的自定义板块

    Returns:
        规范化后的板块标识符小写字符串

    Raises:
        ValueError: 当板块标识符非法时
    """
    cleaned = str(sector).strip().lower()
    if not cleaned:
        raise ValueError("板块标识符不能为空")
    if not allow_unknown and cleaned not in SECTORS:
        raise ValueError(f"未知的板块标识: '{cleaned}'，合法板块包含: {list(SECTORS.keys())}")
    return cleaned


def validate_stock_input(item: Union[StockSentimentInput, Dict[str, Any], Any]) -> StockSentimentInput:
    """将任意输入形式标准化并校验为 StockSentimentInput 实例。"""
    if isinstance(item, StockSentimentInput):
        return item
    if isinstance(item, dict):
        return from_v26_sentiment(item)
    # 处理具有属性的对象（如自定义 dataclass 或 namedtuple）
    return from_v26_sentiment(item)


# ============================================================================
# 3. 交易日历辅助工具
# ============================================================================

def _parse_date(date_input: Union[str, date, datetime]) -> date:
    """将多种日期形式解析为 datetime.date 对象。"""
    if isinstance(date_input, datetime):
        return date_input.date()
    if isinstance(date_input, date):
        return date_input
    raw = str(date_input).strip()
    # 尝试标准格式 YYYY-MM-DD
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    # 截取前 10 字符（兼容 ISO 带时区时间戳）
    if len(raw) >= 10:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    raise ValueError(f"无法解析的日期格式: '{date_input}'")


def is_trading_day(date_input: Union[str, date, datetime]) -> bool:
    """判断指定日期是否为工作交易日（周一至周五）。

    Note:
        在基础日历模型中，以周一到周五（weekday < 5）作为交易日判断准则。
    """
    d = _parse_date(date_input)
    return d.weekday() < 5


def trading_days_between(
    start_date: Union[str, date, datetime],
    end_date: Union[str, date, datetime],
) -> int:
    """计算两个日期之间的交易日数量（含头不含尾，若 start == end 返回 0）。

    Args:
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        交易日总数。若 start_date > end_date 则返回负数。
    """
    d1 = _parse_date(start_date)
    d2 = _parse_date(end_date)
    if d1 == d2:
        return 0

    step = 1 if d2 > d1 else -1
    curr = d1
    count = 0
    while curr != d2:
        if curr.weekday() < 5:
            count += 1
        curr += timedelta(days=step)

    return count if step > 0 else -count


def add_trading_days(
    start_date: Union[str, date, datetime],
    n_days: int,
) -> str:
    """在指定日期上增加 n 个交易日（自动跳过周末）。

    Args:
        start_date: 基准日期
        n_days: 增加的交易日天数（可正可负）

    Returns:
        计算后的日期字符串 (YYYY-MM-DD)
    """
    curr = _parse_date(start_date)
    step = 1 if n_days >= 0 else -1
    remaining = abs(n_days)

    while remaining > 0:
        curr += timedelta(days=step)
        if curr.weekday() < 5:
            remaining -= 1

    return curr.strftime("%Y-%m-%d")


# ============================================================================
# 4. v2.6 兼容转换适配器
# ============================================================================

def from_v26_sentiment(
    raw_data: Any,
    code: str = "",
    name: str = "",
    sector: str = "",
    timestamp: str = "",
) -> StockSentimentInput:
    """从 v2.6 的输出（LLMSentimentResult、字典、或其他单票结果）适配到 StockSentimentInput。

    支持从对象属性或字典多样式键名中自适应提取：
    - score / sentiment_score / sentiment
    - confidence / sentiment_confidence
    - code / ticker
    - news_count / count / volume
    - timestamp / date / time
    若 sector 为空，则自动通过股票代码反查注册板块。
    """
    if isinstance(raw_data, StockSentimentInput):
        # 复制并可选覆盖
        return StockSentimentInput(
            code=code or raw_data.code,
            name=name or raw_data.name,
            sector=sector or raw_data.sector,
            sentiment_score=raw_data.sentiment_score,
            sentiment_confidence=raw_data.sentiment_confidence,
            news_count=raw_data.news_count,
            timestamp=timestamp or raw_data.timestamp,
        )

    # 提取字段
    extracted_code = code
    extracted_name = name
    extracted_sector = sector
    extracted_score = 0.0
    extracted_confidence = 0.8
    extracted_news_count = 1
    extracted_timestamp = timestamp

    if isinstance(raw_data, dict):
        extracted_code = str(raw_data.get("code") or raw_data.get("ticker") or extracted_code).strip()
        extracted_name = str(raw_data.get("name") or raw_data.get("stock_name") or extracted_name).strip()
        extracted_sector = str(raw_data.get("sector") or raw_data.get("sector_id") or extracted_sector).strip()
        
        # 得分提取
        for sk in ("sentiment_score", "score", "sentiment"):
            if sk in raw_data and raw_data[sk] is not None:
                extracted_score = float(raw_data[sk])
                break

        # 置信度提取
        for ck in ("sentiment_confidence", "confidence"):
            if ck in raw_data and raw_data[ck] is not None:
                extracted_confidence = float(raw_data[ck])
                break

        # 新闻条数提取
        for nk in ("news_count", "count", "volume"):
            if nk in raw_data and raw_data[nk] is not None:
                extracted_news_count = int(raw_data[nk])
                break

        # 时间戳提取
        for tk in ("timestamp", "date", "time"):
            if tk in raw_data and raw_data[tk] is not None:
                extracted_timestamp = str(raw_data[tk]).strip()
                break

    else:
        # 对象属性提取（例如 LLMSentimentResult 实例）
        if hasattr(raw_data, "score"):
            extracted_score = float(raw_data.score)
        elif hasattr(raw_data, "sentiment_score"):
            extracted_score = float(raw_data.sentiment_score)

        if hasattr(raw_data, "code"):
            extracted_code = str(raw_data.code).strip()
        if hasattr(raw_data, "name"):
            extracted_name = str(raw_data.name).strip()
        if hasattr(raw_data, "sector"):
            extracted_sector = str(raw_data.sector).strip()

        # 根据来源推断置信度
        if hasattr(raw_data, "confidence"):
            extracted_confidence = float(raw_data.confidence)
        elif hasattr(raw_data, "source"):
            # LLM 来源置信度高于纯规则词典
            extracted_confidence = 0.85 if getattr(raw_data, "source") == "llm" else 0.70

        if hasattr(raw_data, "news_count"):
            extracted_news_count = int(raw_data.news_count)
        if hasattr(raw_data, "timestamp"):
            extracted_timestamp = str(raw_data.timestamp).strip()

    # 若未指定板块，根据股票代码自动推断
    if not extracted_sector and extracted_code:
        inferred = get_sector_for_ticker(extracted_code)
        if inferred:
            extracted_sector = inferred

    return StockSentimentInput(
        code=extracted_code,
        name=extracted_name,
        sector=extracted_sector,
        sentiment_score=extracted_score,
        sentiment_confidence=extracted_confidence,
        news_count=extracted_news_count,
        timestamp=extracted_timestamp,
    )
