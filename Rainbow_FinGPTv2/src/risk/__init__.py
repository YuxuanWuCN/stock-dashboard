# -*- coding: utf-8 -*-
"""src/risk/__init__.py —— 市场状态机与动态仓位管理模块"""

from src.risk.market_regime_detector import (
    MarketRegimeDetector,
    RegimeDetectorConfig,
    RegimeType,
    DEFAULT_REGIME_CONFIG,
    AGGRESSIVE_REGIME_CONFIG,
    CONSERVATIVE_REGIME_CONFIG,
)
from src.risk.dynamic_position_sizer import (
    DynamicPositionSizer,
    PositionSizerConfig,
    DEFAULT_POSITION_CONFIG,
    AGGRESSIVE_POSITION_CONFIG,
    CONSERVATIVE_POSITION_CONFIG,
)

__all__ = [
    "MarketRegimeDetector",
    "RegimeDetectorConfig",
    "RegimeType",
    "DEFAULT_REGIME_CONFIG",
    "AGGRESSIVE_REGIME_CONFIG",
    "CONSERVATIVE_REGIME_CONFIG",
    "DynamicPositionSizer",
    "PositionSizerConfig",
    "DEFAULT_POSITION_CONFIG",
    "AGGRESSIVE_POSITION_CONFIG",
    "CONSERVATIVE_POSITION_CONFIG",
]
