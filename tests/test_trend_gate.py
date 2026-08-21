# -*- coding: utf-8 -*-
"""tests/test_trend_gate.py —— 趋势门单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategies.trend_gate import detect_trend, apply_trend_filter, get_trend_weight


def test_detect_trend_uptrend():
    """测试上升趋势判定（20日上涨 + 价格>60日均线）。"""
    # 模拟上涨行情：从 10 涨到 15，60 日均线约 12
    closes = [10.0] * 40 + [10.5] * 10 + [12.0] * 5 + [13.0] * 3 + [14.0] * 1 + [15.0]
    state, metrics = detect_trend(closes)
    assert state == "uptrend"
    assert metrics["mom_positive"] is True
    assert metrics["above_ma60"] is True


def test_detect_trend_downtrend():
    """测试下跌趋势判定（20日下跌 + 价格<60日均线）。"""
    # 模拟下跌：从 15 跌到 10
    closes = [15.0] * 40 + [14.0] * 10 + [12.0] * 5 + [11.0] * 3 + [10.5] * 1 + [10.0]
    state, metrics = detect_trend(closes)
    assert state == "downtrend"
    assert metrics["mom_positive"] is False
    assert metrics["above_ma60"] is False


def test_detect_trend_neutral():
    """测试震荡趋势（20日上涨但价格<60日均线，或反之）。"""
    # 模拟震荡：20日微涨但仍在60日均线下
    closes = [15.0] * 40 + [12.0] * 15 + [13.0] * 5
    state, metrics = detect_trend(closes)
    assert state == "neutral"


def test_apply_trend_filter_suppress_down():
    """测试下跌趋势禁止看多。"""
    # 下跌趋势 + 看多信号 → None
    assert apply_trend_filter(1, "downtrend", "suppress_down") is None
    # 下跌趋势 + 看跌信号 → 保留
    assert apply_trend_filter(-1, "downtrend", "suppress_down") == -1
    # 上涨趋势 + 看多信号 → 保留
    assert apply_trend_filter(1, "uptrend", "suppress_down") == 1


def test_apply_trend_filter_suppress_counter():
    """测试双向逆势抑制。"""
    # 下跌趋势禁看多
    assert apply_trend_filter(1, "downtrend", "suppress_counter") is None
    # 上涨趋势禁看空
    assert apply_trend_filter(-1, "uptrend", "suppress_counter") is None
    # 顺势保留
    assert apply_trend_filter(1, "uptrend", "suppress_counter") == 1
    assert apply_trend_filter(-1, "downtrend", "suppress_counter") == -1


def test_get_trend_weight():
    """测试趋势权重系数。"""
    assert get_trend_weight("uptrend") == 1.5
    assert get_trend_weight("neutral") == 1.0
    assert get_trend_weight("downtrend") == 0.5
