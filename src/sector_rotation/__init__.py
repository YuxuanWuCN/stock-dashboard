# -*- coding: utf-8 -*-
"""src/sector_rotation/__init__.py —— Rainbow-FinGPT 板块轮动系统核心包

导出模块基础配置、数据契约、转换工具与情绪聚合器。
"""

from .config import (
    BENCHMARK_MAPPINGS,
    BUY_FEE_RATE,
    COOLDOWN_DAYS,
    DEFENSIVE_SECTOR,
    EXPECTED_STOCKS_PER_SECTOR,
    LLM_TIMEOUT,
    MAX_ROTATION_PER_MONTH,
    MAX_TOTAL_ROTATION_COST,
    MIN_HOLDING_DAYS,
    MIN_TARGET_SENTIMENT,
    REALLOCATION_WEIGHTS,
    ROTATION_EXECUTION_DAYS,
    SECTORS,
    SELL_FEE_RATE,
    SENTIMENT_BOUND_MAX,
    SENTIMENT_BOUND_MIN,
    SENTIMENT_DECLINE_THRESHOLD,
    TICKER_TO_SECTOR,
    TRANSACTION_COST_RATE,
    TREND_CONFIRM_DAYS,
    TREND_DECLINING,
    TREND_RISING,
    TREND_STABLE,
    SectorConfig,
    get_all_sector_ids,
    get_all_tickers,
    get_sector_config,
    get_sector_for_ticker,
)
from .llm_decision_advisor import AuditRecord, LLMDecisionAdvisor
from .position_manager import (
    CostLimitExceededError,
    PortfolioState,
    PositionManager,
    ReallocationSchedule,
)
from .sector_rotation_engine import RotationDecision, SectorRotationEngine
from .sector_sentiment_aggregator import SectorSentimentAggregator
from .utils.sector_utils import (
    SectorState,
    StockSentimentInput,
    add_trading_days,
    from_v26_sentiment,
    is_trading_day,
    trading_days_between,
    validate_confidence,
    validate_news_count,
    validate_sector,
    validate_sentiment_score,
    validate_stock_input,
)

__all__ = [
    # 核心类
    "SectorSentimentAggregator",
    "SectorRotationEngine",
    "RotationDecision",
    "LLMDecisionAdvisor",
    "AuditRecord",
    "PositionManager",
    "ReallocationSchedule",
    "PortfolioState",
    "CostLimitExceededError",
    "SectorState",
    "StockSentimentInput",
    "SectorConfig",
    # 配置与字典
    "SECTORS",
    "BENCHMARK_MAPPINGS",
    "TICKER_TO_SECTOR",
    "get_sector_config",
    "get_all_sector_ids",
    "get_all_tickers",
    "get_sector_for_ticker",
    # 阈值常量
    "SENTIMENT_DECLINE_THRESHOLD",
    "TREND_CONFIRM_DAYS",
    "MIN_TARGET_SENTIMENT",
    "ROTATION_EXECUTION_DAYS",
    "TRANSACTION_COST_RATE",
    "MIN_HOLDING_DAYS",
    "MAX_ROTATION_PER_MONTH",
    "COOLDOWN_DAYS",
    "BUY_FEE_RATE",
    "SELL_FEE_RATE",
    "MAX_TOTAL_ROTATION_COST",
    "LLM_TIMEOUT",
    "DEFENSIVE_SECTOR",
    "EXPECTED_STOCKS_PER_SECTOR",
    "SENTIMENT_BOUND_MIN",
    "SENTIMENT_BOUND_MAX",
    "TREND_RISING",
    "TREND_STABLE",
    "TREND_DECLINING",
    "REALLOCATION_WEIGHTS",
    # 工具函数
    "validate_sentiment_score",
    "validate_confidence",
    "validate_news_count",
    "validate_stock_input",
    "validate_sector",
    "is_trading_day",
    "trading_days_between",
    "add_trading_days",
    "from_v26_sentiment",
]
