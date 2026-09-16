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


def test_dynamic_bet_allocator_macro_regime_elasticity():
    """测试宏观产业体制驱动的仓位上限解锁与收紧。"""
    from src.execution.portfolio_allocator import MacroRegime

    allocator = DynamicBetAllocator(total_portfolio_capital=1_000_000.0)

    open_gate = TrendGateDecision(
        ticker="688525",
        gate_open=True,
        ma20_val=50.0,
        current_price=55.0,
        macd_hist=0.8,
        is_c_wave_downtrend=False,
        recommended_action="PERMIT_LONG",
        reason="Super Bull Momentum"
    )

    # 1. 常规体制 (Normal): 上限为 30%
    order_normal = allocator.allocate_position(
        ticker="688525",
        gfca_composite_score=0.95,
        trend_gate_decision=open_gate,
        bet_type=BetType.SUPER_BETA,
        macro_regime=MacroRegime.NORMAL
    )
    assert order_normal.target_weight_pct <= 0.30
    assert order_normal.macro_regime == MacroRegime.NORMAL

    # 2. 超级主升爆发期 (Super Boom): 仓位上限突破 30%，解锁至 40% 以上
    order_boom = allocator.allocate_position(
        ticker="688525",
        gfca_composite_score=0.95,
        trend_gate_decision=open_gate,
        bet_type=BetType.SUPER_BETA,
        macro_regime=MacroRegime.SUPER_BOOM
    )
    assert order_boom.target_weight_pct > 0.30
    assert order_boom.target_weight_pct <= 0.45
    assert order_boom.macro_regime == MacroRegime.SUPER_BOOM
    assert "Super Boom" in order_boom.rationale

    # 3. 衰退去库存期 (Recession): 仓位主动收紧，上限 <= 15%
    order_recession = allocator.allocate_position(
        ticker="688525",
        gfca_composite_score=0.95,
        trend_gate_decision=open_gate,
        bet_type=BetType.SUPER_BETA,
        macro_regime=MacroRegime.RECESSION
    )
    assert order_recession.target_weight_pct <= 0.15
    assert order_recession.target_weight_pct < order_normal.target_weight_pct
    assert order_recession.macro_regime == MacroRegime.RECESSION

