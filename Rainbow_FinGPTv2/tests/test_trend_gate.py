# -*- coding: utf-8 -*-
"""tests/test_trend_gate.py —— Trend Gate™ 布尔硬门禁单元测试 (Week 9)"""

import pandas as pd
import numpy as np
import pytest

from src.execution.trend_gate import TrendGate, TrendGateDecision


def test_trend_gate_c_wave_liquidation():
    """测试 Trend Gate 在 C 浪下跌与均线破位时的紧急强制清仓判定。"""
    gate = TrendGate(ma_period=20)

    # 1. 模拟健康多头行情 (价格持续站在 MA20 上方，MACD 多头)
    prices_uptrend = np.linspace(10.0, 25.0, 40)
    kline_uptrend = pd.DataFrame({"close": prices_uptrend})

    decision_up = gate.evaluate_gate("001309", kline_uptrend)
    assert isinstance(decision_up, TrendGateDecision)
    assert decision_up.gate_open is True
    assert decision_up.recommended_action == "PERMIT_LONG"

    # 2. 模拟 C 浪主跌破位 (从 25 暴跌至 15，均线拐头向下，MACD 负动量扩大)
    prices_c_wave = np.concatenate([np.linspace(10.0, 25.0, 30), np.linspace(25.0, 15.0, 15)])
    kline_c_wave = pd.DataFrame({"close": prices_c_wave})

    decision_c = gate.evaluate_gate("001309", kline_c_wave)
    assert decision_c.gate_open is False
    assert decision_c.is_c_wave_downtrend is True
    assert decision_c.recommended_action == "EMERGENCY_LIQUIDATE"
    assert "清仓" in decision_c.reason
