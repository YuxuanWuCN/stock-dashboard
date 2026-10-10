# -*- coding: utf-8 -*-
"""tests/test_debate_committee.py —— 对抗式多智能体投决会单元测试"""

import pytest

from src.agents.debate_committee import (
    BullAnalystAgent,
    BearRedTeamAgent,
    MacroGatekeeperAgent,
    CIOCommitteeArbiter,
)


def test_bull_and_bear_argument_generation():
    """测试多头分析师与空头红队独立生成证据链与置信度。"""
    bull = BullAnalystAgent()
    bear = BearRedTeamAgent()

    # 1. 多头高景气标的
    bull_arg = bull.generate_argument(
        symbol="688525",
        financial_facts={"revenue_growth_yoy": 0.50},
        chokepoint_score=15.0,
        ast_factor_score=0.75,
    )
    assert bull_arg.stance == "BULLISH"
    assert bull_arg.confidence > 0.70
    assert len(bull_arg.evidences) >= 2

    # 2. 空头高风险标的
    bear_arg = bear.generate_argument(
        symbol="688525",
        financial_facts={"major_shareholder_selling": True},
        pe_percentile=0.95,
        inventory_growth_vs_rev=0.45,
    )
    assert bear_arg.stance == "BEARISH"
    assert bear_arg.confidence > 0.75
    assert len(bear_arg.evidences) >= 3


def test_cio_bayesian_fusion_and_consensus():
    """测试 CIO 投决会贝叶斯证据融合与动作决策。"""
    bull = BullAnalystAgent()
    bear = BearRedTeamAgent()
    macro = MacroGatekeeperAgent()
    cio = CIOCommitteeArbiter()

    # 构造温和偏多格局
    bull_arg = bull.generate_argument("MU", {"revenue_growth_yoy": 0.30}, 14.0, 0.65)
    bear_arg = bear.generate_argument("MU", {}, 0.50, 0.10)
    macro_arg = macro.generate_argument(0.08, "ABUNDANT")

    prob, brier = cio.bayesian_evidence_fusion(bull_arg, bear_arg, macro_arg)
    assert 0.50 < prob <= 0.99
    assert 0.0 <= brier <= 0.50

    decision = cio.arbitrate_decision(
        symbol="MU",
        bull_arg=bull_arg,
        bear_arg=bear_arg,
        macro_arg=macro_arg,
        trend_gate_approved=True,
        wave_phase="Phase_3_Impulse",
        current_drawdown=0.03,
    )
    assert decision.action in ["BUY", "STRONG_BUY"]
    assert decision.recommended_position > 0.0
    assert decision.trend_gate_passed is True


def test_trend_gate_one_vote_veto_in_cio_arbitration():
    """测试核心硬门禁：即便定性概率极高，遭遇 C 浪杀跌必须强制一票否决。"""
    bull = BullAnalystAgent()
    bear = BearRedTeamAgent()
    macro = MacroGatekeeperAgent()
    cio = CIOCommitteeArbiter()

    bull_arg = bull.generate_argument("688525", {"revenue_growth_yoy": 0.80}, 18.0, 0.90)
    bear_arg = bear.generate_argument("688525", {}, 0.40, 0.05)
    macro_arg = macro.generate_argument(0.10, "ABUNDANT")

    # 处于 C 浪下跌破位状态
    decision = cio.arbitrate_decision(
        symbol="688525",
        bull_arg=bull_arg,
        bear_arg=bear_arg,
        macro_arg=macro_arg,
        trend_gate_approved=False,
        wave_phase="Phase_C",
        current_drawdown=0.18,
    )

    assert decision.action == "VETO_BY_TREND_GATE"
    assert decision.recommended_position == 0.0
    assert "Trend Gate 触发硬拦截" in decision.veto_reason
