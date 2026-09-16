# -*- coding: utf-8 -*-
"""tests/test_volatility_parity.py —— 波动率反比平价与极端回撤熔断单元测试"""

import pytest
from src.risk.volatility_parity import (
    VolatilityParityOptimizer,
    calculate_inverse_volatility_weights,
)


def test_inverse_volatility_weighting_basic():
    """验证低风险标的获得更高权重，高风险标的被压缩。"""
    candidates = [
        {"code": "600519", "name": "贵州茅台", "score": 80, "risk": 20.0},  # 低风险
        {"code": "300750", "name": "宁德时代", "score": 75, "risk": 40.0},  # 中风险
        {"code": "000977", "name": "浪潮信息", "score": 70, "risk": 80.0},  # 高风险
    ]
    weighted = calculate_inverse_volatility_weights(
        candidates, target_position_pct=80.0, risk_profile="conservative"
    )

    assert len(weighted) == 3
    # 权重大小顺序应为：茅台 > 宁德时代 > 浪潮信息
    w_maotai = next(w["weight_pct"] for w in weighted if w["code"] == "600519")
    w_catl = next(w["weight_pct"] for w in weighted if w["code"] == "300750")
    w_inspur = next(w["weight_pct"] for w in weighted if w["code"] == "000977")

    assert w_maotai > w_catl > w_inspur
    # 总权重严格等于目标 80% (允许 0.1 精度误差)
    total_w = sum(w["weight_pct"] for w in weighted)
    assert pytest.approx(total_w, abs=0.2) == 80.0


def test_aggressive_portfolio_max_weight_capping():
    """激进/科技组合中，单票最大权重被严格压制在上限内（防止单票跌停穿仓）。"""
    candidates = [
        {"code": f"TECH_{i}", "name": f"科技股_{i}", "score": 80, "risk": 15.0 if i == 0 else 60.0}
        for i in range(10)
    ]
    # 10 只股票，总仓位 100%，单票上限 15%（数学可行 10 * 15% = 150% >= 100%）
    weighted = calculate_inverse_volatility_weights(
        candidates, target_position_pct=100.0, risk_profile="tech", custom_max_weight=15.0
    )

    for item in weighted:
        assert item["weight_pct"] <= 15.0 + 1e-4

    total_w = sum(w["weight_pct"] for w in weighted)
    assert pytest.approx(total_w, abs=0.5) == 100.0


def test_single_asset_edge_case():
    """单只标的分配全部仓位预算。"""
    candidates = [{"code": "510300", "name": "300ETF", "score": 90, "risk": 15.0}]
    weighted = calculate_inverse_volatility_weights(candidates, target_position_pct=60.0)
    assert len(weighted) == 1
    assert weighted[0]["weight_pct"] == 60.0


def test_circuit_breaker_detection():
    """单日跌幅 <= -7% 触发自动化虚拟熔断。"""
    optimizer = VolatilityParityOptimizer(circuit_breaker_pct=-7.0)
    holdings = [
        {"code": "000977", "name": "浪潮信息", "pct": 12.0},
        {"code": "600519", "name": "贵州茅台", "pct": 25.0},
    ]
    today_changes = {
        "000977": -9.99,  # 跌停，触发熔断
        "600519": -1.50,  # 正常波动
    }
    has_triggered, triggered_items = optimizer.check_circuit_breaker(holdings, today_changes)
    assert has_triggered is True
    assert len(triggered_items) == 1
    assert triggered_items[0]["code"] == "000977"
    assert "跌幅 -9.99%" in triggered_items[0]["reason"]
