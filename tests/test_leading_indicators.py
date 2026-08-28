"""tests/test_leading_indicators.py —— 产业链领先指标与源头追踪单元测试"""

import pytest
import pandas as pd
from unittest.mock import MagicMock

from src.analysis.leading_indicators import (
    calculate_momentum_and_inflection,
    LeadingIndicatorEngine,
)
from src.llm.leading_indicator_tracker import LeadingIndicatorTracker


def test_momentum_and_inflection_acceleration():
    """测试加速上涨序列的动量计算。"""
    # 模拟一个从 100 持续上升到 130 的序列
    data = pd.Series([100, 102, 105, 108, 112, 118, 125, 130])
    res = calculate_momentum_and_inflection(data, window=8)
    assert res["slope_pct"] == 30.0
    assert res["momentum"] == "accelerating"
    assert res["confidence"] == "high"


def test_momentum_positive_reversal():
    """测试触底反转拐点识别。"""
    # 模拟先下跌后剧烈反弹的 V 型拐点
    data = pd.Series([100, 95, 90, 88, 92, 98, 105, 110])
    res = calculate_momentum_and_inflection(data, window=8)
    assert res["inflection_flag"] == "positive_reversal"


def test_leading_indicator_engine_mapping():
    """测试行业到先行指标的分类映射。"""
    engine = LeadingIndicatorEngine()
    assert engine.match_industry_category("光模块CPO") == "optical_communication"
    assert engine.match_industry_category("半导体存储芯片") == "semiconductor"
    assert engine.match_industry_category("光伏电池组件") == "new_energy"
    assert engine.match_industry_category("山东黄金采掘") == "gold_resources"
    assert engine.match_industry_category("未知行业") == "general"


def test_tracker_fallback_mode():
    """测试大模型不可用时的降级规则兜底输出。"""
    # 模拟 client 不可用
    mock_client = MagicMock()
    mock_client.backend = "deepseek"
    mock_client.model = "deepseek-v4-flash"
    mock_client.is_available = False
    mock_client.unavailable_reason = "Mocked offline"

    tracker = LeadingIndicatorTracker(client=mock_client)
    res = tracker.analyze_source_signals(
        stock_code="600519",
        stock_name="贵州茅台",
        industry="白酒饮料",
        news_list=[{"title": "批价企稳回升", "source": "酒业网", "date": "2026-08-16"}],
    )
    assert res["stock_code"] == "600519"
    assert res["fallback"] is True
    assert "leading_signals" in res
    assert len(res["leading_signals"]) > 0
    assert res["leading_signals"][0]["type"] == "FACT"
