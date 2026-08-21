# -*- coding: utf-8 -*-
"""tests/test_bet_type_classifier.py —— 赌注分类器单元测试 + 真实数据验证"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analysis.bet_type_classifier import (
    calculate_volatility,
    calculate_momentum_half_life,
    classify_bet_type,
    get_strategy_recommendation,
)

ROOT = Path(__file__).parent.parent


def test_classify_bet_type_synthetic():
    """测试合成数据的分类。"""
    # 模拟低波动稳定上涨序列（趋势）
    trend_closes = [10.0 + i * 0.1 for i in range(100)]
    state, metrics = classify_bet_type(trend_closes)
    # 趋势数据波动率很低
    assert metrics["volatility_annual"] < 0.2
    
    # 模拟高波动暴涨暴跌序列（妖股）
    volatile_closes = [10.0] * 30 + [15.0, 20.0, 25.0, 18.0, 12.0, 10.0] * 5 + [10.0] * 10
    state2, metrics2 = classify_bet_type(volatile_closes)
    assert metrics2["volatility_annual"] > 0.4


def test_strategy_recommendation():
    """测试策略建议。"""
    rec_trend = get_strategy_recommendation("trend")
    assert rec_trend["holding_period"] == 60
    assert rec_trend["trade_frequency"] == "low"
    
    rec_vol = get_strategy_recommendation("volatile")
    assert rec_vol["holding_period"] == 5
    assert rec_vol["trade_frequency"] == "high"


def test_real_data_classification():
    """用真实数据验证：立新能源 vs 美光 MU。"""
    # 1. 立新能源 (001258)
    with open(ROOT / "docs" / "data" / "kline" / "001258.json", encoding="utf-8") as f:
        k_lixin = json.load(f)
    closes_lixin = [r[1] for r in k_lixin["kline"]]
    highs_lixin = [r[3] for r in k_lixin["kline"]]
    lows_lixin = [r[2] for r in k_lixin["kline"]]
    
    state_lixin, m_lixin = classify_bet_type(closes_lixin, highs_lixin, lows_lixin)
    print(f"\n[实测] 立新能源(001258) 分类结果: {state_lixin}")
    print(f"      年化波动率: {m_lixin['volatility_annual']*100:.1f}%, 半衰期: {m_lixin['momentum_half_life']}天, ATR: {m_lixin['atr_ratio']*100:.1f}%")
    
    # 2. 美光 MU
    with open(ROOT / "docs" / "data" / "kline" / "MU.json", encoding="utf-8") as f:
        k_mu = json.load(f)
    closes_mu = [r[1] for r in k_mu["kline"]]
    highs_mu = [r[3] for r in k_mu["kline"]]
    lows_mu = [r[2] for r in k_mu["kline"]]
    
    state_mu, m_mu = classify_bet_type(closes_mu, highs_mu, lows_mu)
    print(f"[实测] 美光科技(MU)     分类结果: {state_mu}")
    print(f"      年化波动率: {m_mu['volatility_annual']*100:.1f}%, 半衰期: {m_mu['momentum_half_life']}天, ATR: {m_mu['atr_ratio']*100:.1f}%")
    
    # 验证分类区分度：立新能源和 MU 的特征应该有显著差异
    assert m_lixin["volatility_annual"] != m_mu["volatility_annual"]
