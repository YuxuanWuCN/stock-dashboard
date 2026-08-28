# -*- coding: utf-8 -*-
"""tests/test_bet_allocator.py —— 差异化头寸与证据阶段分配器单元测试 (Week 10)"""

import pytest
from src.execution.trend_gate import TrendGateDecision
from src.execution.portfolio_allocator import (
    DynamicBetAllocator,
    BetType,
    EvidencePhase,
    AllocationOrder
)


def test_dynamic_bet_allocator_staged_sizing():
    """测试 Event-Driven 证据阶段阶梯加仓与 Trend Gate 阻断强制归零。"""
    allocator = DynamicBetAllocator(total_portfolio_capital=1_000_000.0)

    # 1. 正常放行决策
    open_gate = TrendGateDecision(
        ticker="001309",
        gate_open=True,
        ma20_val=20.0,
        current_price=22.0,
        macd_hist=0.5,
        is_c_wave_downtrend=False,
        recommended_action="PERMIT_LONG",
        reason="Healthy"
    )

    # 1.1 样品阶段 (Sampling -> 20% 额度)
    order_sample = allocator.allocate_position(
        ticker="001309",
        gfca_composite_score=0.80,
        trend_gate_decision=open_gate,
        bet_type=BetType.EVENT_DRIVEN,
        evidence_phase=EvidencePhase.SAMPLING
    )
    assert isinstance(order_sample, AllocationOrder)
    assert order_sample.action_directive == "OPEN_BUY"

    # 1.2 量产落地阶段 (Mass Production -> 100% 额度)
    order_mass = allocator.allocate_position(
        ticker="001309",
        gfca_composite_score=0.80,
        trend_gate_decision=open_gate,
        bet_type=BetType.EVENT_DRIVEN,
        evidence_phase=EvidencePhase.MASS_PRODUCTION
    )
    assert order_mass.target_weight_pct > order_sample.target_weight_pct * 3.5

    # 2. Trend Gate 触发 C 浪阻断 (gate_open=False) -> 头寸归零并清仓
    closed_gate = TrendGateDecision(
        ticker="001309",
        gate_open=False,
        ma20_val=25.0,
        current_price=18.0,
        macd_hist=-1.2,
        is_c_wave_downtrend=True,
        recommended_action="EMERGENCY_LIQUIDATE",
        reason="C-Wave Crash"
    )
    order_liquidate = allocator.allocate_position(
        ticker="001309",
        gfca_composite_score=0.80,
        trend_gate_decision=closed_gate
    )
    assert order_liquidate.target_weight_pct == 0.0
    assert order_liquidate.action_directive == "LIQUIDATE_ALL"
