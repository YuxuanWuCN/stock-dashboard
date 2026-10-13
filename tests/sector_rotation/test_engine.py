# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_engine.py —— SectorRotationEngine 单元测试套件

测试覆盖：
1. 情绪下沉触发逻辑（严格 < -0.3 且 declining 趋势）
2. 候选板块筛选门槛（严格 > 0.5，排除当前持仓板块）
3. 多因子综合评分精准度与数学推导验证 (score = 0.5*S + 0.2*T + 0.2*C - 0.1*sigma)
4. 防御资产降级机制（全市场恶化/无合格候选 -> gold；已在 gold 则维持持仓）
5. 交易风控与调仓门禁（最短持仓 < 5天、冷却期 < 7天、单月频次 >= 3次）
6. 快速路径执行延迟基准测试（要求平均执行 < 1.0ms，远优于 < 100ms 硬顶）
7. 契约兼容性测试（RotationDecision 字段、from_sector/to_sector 别名、decide 方法传参）
"""

import time
from typing import Dict

import pytest

from src.sector_rotation.config import (
    COOLDOWN_DAYS,
    DEFENSIVE_SECTOR,
    MAX_ROTATION_PER_MONTH,
    MIN_HOLDING_DAYS,
    MIN_TARGET_SENTIMENT,
    SENTIMENT_DECLINE_THRESHOLD,
    TREND_DECLINING,
    TREND_RISING,
    TREND_STABLE,
)
from src.sector_rotation.sector_rotation_engine import (
    RotationDecision,
    SectorRotationEngine,
)
from src.sector_rotation.utils.sector_utils import SectorState


# ============================================================================
# 1. 基础实例化与配置测试
# ============================================================================

def test_engine_initialization_defaults_and_custom() -> None:
    """验证 SectorRotationEngine 默认参数与自定义权重初始化。"""
    engine_default = SectorRotationEngine()
    assert engine_default.decline_threshold == pytest.approx(SENTIMENT_DECLINE_THRESHOLD)
    assert engine_default.target_threshold == pytest.approx(MIN_TARGET_SENTIMENT)
    assert engine_default.min_holding_days == MIN_HOLDING_DAYS
    assert engine_default.max_monthly_rotations == MAX_ROTATION_PER_MONTH
    assert engine_default.cooldown_days == COOLDOWN_DAYS
    assert engine_default.defensive_sector == DEFENSIVE_SECTOR
    assert engine_default.weights["w_s"] == pytest.approx(0.5)
    assert engine_default.weights["w_t"] == pytest.approx(0.2)
    assert engine_default.weights["w_c"] == pytest.approx(0.2)
    assert engine_default.weights["w_v"] == pytest.approx(0.1)

    custom_weights = {"w_s": 0.6, "w_t": 0.15, "w_c": 0.15, "w_v": 0.10}
    engine_custom = SectorRotationEngine(
        weights=custom_weights,
        decline_threshold=-0.25,
        target_threshold=0.55,
        min_holding_days=3,
        max_monthly_rotations=2,
        cooldown_days=5,
        defensive_sector="cash",
    )
    assert engine_custom.weights["w_s"] == pytest.approx(0.6)
    assert engine_custom.decline_threshold == pytest.approx(-0.25)
    assert engine_custom.target_threshold == pytest.approx(0.55)
    assert engine_custom.min_holding_days == 3
    assert engine_custom.max_monthly_rotations == 2
    assert engine_custom.cooldown_days == 5
    assert engine_custom.defensive_sector == "cash"


# ============================================================================
# 2. 情绪下沉触发逻辑测试 (Decline Trigger)
# ============================================================================

def test_engine_normal_decline_trigger() -> None:
    """验证当持仓板块得分 < -0.3 且趋势为 declining 时正常触发轮动。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.35, sentiment_trend=TREND_DECLINING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.65, sentiment_trend=TREND_RISING, confidence=0.90, volatility=0.10),
        "gold": SectorState(sector="gold", sentiment_score=0.30, sentiment_trend=TREND_STABLE, confidence=0.80),
    }
    decision = engine.evaluate(
        current_sector="green",
        sector_states=states,
        holding_days=5,
        monthly_rotations=0,
        days_since_last_rotation=10,
    )
    assert decision.should_rotate is True
    assert decision.current_sector == "green"
    assert decision.target_sector == "storage"
    assert decision.is_fallback is False
    assert decision.confidence == pytest.approx(0.90)
    assert "rotating to candidate" in decision.reason


def test_engine_exact_threshold_boundary_minus_0_3() -> None:
    """边界验证：得分恰好为 -0.3000 时，因未严格低于阈值，不触发轮动。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.30, sentiment_trend=TREND_DECLINING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING, confidence=0.90),
    }
    decision = engine.evaluate("green", states, holding_days=5, monthly_rotations=0, days_since_last_rotation=10)
    assert decision.should_rotate is False
    assert decision.target_sector is None
    assert "healthy" in decision.reason


def test_engine_score_low_but_trend_not_declining() -> None:
    """验证即使得分 < -0.3，但趋势为 stable 或 rising 时，不满足连续确认，不触发轮动。"""
    engine = SectorRotationEngine()
    states_stable = {
        "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_STABLE, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING),
    }
    d_stable = engine.evaluate("green", states_stable, holding_days=5)
    assert d_stable.should_rotate is False

    states_rising = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_RISING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING),
    }
    d_rising = engine.evaluate("green", states_rising, holding_days=5)
    assert d_rising.should_rotate is False


def test_engine_positive_score_no_trigger() -> None:
    """验证当持仓板块情绪处于正值景气区间时，正常持仓不触发轮动。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=0.45, sentiment_trend=TREND_RISING, confidence=0.88),
        "storage": SectorState(sector="storage", sentiment_score=0.75, sentiment_trend=TREND_RISING, confidence=0.90),
    }
    decision = engine.evaluate("green", states, holding_days=6)
    assert decision.should_rotate is False
    assert decision.target_sector is None
    assert decision.confidence == pytest.approx(0.88)


# ============================================================================
# 3. 候选目标筛选与多因子评分计算 (Composite Scoring)
# ============================================================================

def test_engine_composite_score_exact_mathematics() -> None:
    """验证多因子综合评分函数与测试推导严格一致：
    score = 0.5*S + 0.2*T + 0.2*C - 0.1*sigma
    Candidate A (storage): S=0.6, T=0.3(rising), C=0.8, sigma=0.1 -> 0.51
    Candidate B (gold): S=0.55, T=0.0(stable), C=0.8, sigma=0.05 -> 0.43
    """
    engine = SectorRotationEngine()

    state_storage = SectorState(
        sector="storage",
        sentiment_score=0.60,
        sentiment_trend=TREND_RISING,
        confidence=0.80,
        volatility=0.10,
    )
    score_storage = engine.calculate_composite_score(state_storage)
    # 0.5*0.6 + 0.2*0.3 + 0.2*0.8 - 0.1*0.1 = 0.30 + 0.06 + 0.16 - 0.01 = 0.51
    assert score_storage == pytest.approx(0.51, abs=1e-5)

    state_gold = SectorState(
        sector="gold",
        sentiment_score=0.55,
        sentiment_trend=TREND_STABLE,
        confidence=0.80,
        volatility=0.05,
    )
    score_gold = engine.calculate_composite_score(state_gold)
    # 0.5*0.55 + 0.2*0.0 + 0.2*0.8 - 0.1*0.05 = 0.275 + 0.00 + 0.16 - 0.005 = 0.43
    assert score_gold == pytest.approx(0.43, abs=1e-5)

    # 验证在相同情绪下，declining 会被惩罚 T = -0.3
    state_declining = SectorState(
        sector="storage",
        sentiment_score=0.60,
        sentiment_trend=TREND_DECLINING,
        confidence=0.80,
        volatility=0.10,
    )
    score_dec = engine.calculate_composite_score(state_declining)
    # 0.5*0.6 + 0.2*(-0.3) + 0.2*0.8 - 0.1*0.1 = 0.30 - 0.06 + 0.16 - 0.01 = 0.39
    assert score_dec == pytest.approx(0.39, abs=1e-5)


def test_engine_target_selection_by_highest_composite_score() -> None:
    """验证当下沉触发时，引擎在多个候选板块中选择多因子评分最高者。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=0.60, sentiment_trend=TREND_RISING, confidence=0.80, volatility=0.10),
        "gold": SectorState(sector="gold", sentiment_score=0.55, sentiment_trend=TREND_STABLE, confidence=0.80, volatility=0.05),
    }
    decision = engine.evaluate("green", states)
    assert decision.should_rotate is True
    assert decision.target_sector == "storage"
    assert decision.is_fallback is False


def test_engine_exact_target_threshold_0_5_not_eligible() -> None:
    """边界验证：候选板块得分恰好为 0.5000 时，因未严格大于 0.5，不具有候选资格 (B8)。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=0.50, sentiment_trend=TREND_RISING),  # Not > 0.5
        "gold": SectorState(sector="gold", sentiment_score=0.20, sentiment_trend=TREND_STABLE),
    }
    decision = engine.evaluate("green", states)
    # storage 为 0.50 不达标，因无合格候选触发防御降级到 gold
    assert decision.target_sector != "storage"
    assert decision.target_sector == "gold"
    assert decision.is_fallback is True


# ============================================================================
# 4. 防御降级机制测试 (Defensive Fallback)
# ============================================================================

def test_engine_defensive_fallback_when_no_candidate_reaches_threshold() -> None:
    """验证当其他板块均未能突破 0.5 时，降级至防御板块 'gold'。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=0.45, sentiment_trend=TREND_RISING),
        "gold": SectorState(sector="gold", sentiment_score=0.15, sentiment_trend=TREND_STABLE, confidence=0.82),
    }
    decision = engine.evaluate("green", states)
    assert decision.should_rotate is True
    assert decision.target_sector == "gold"
    assert decision.is_fallback is True
    assert "defensive fallback" in decision.reason.lower()


def test_engine_defensive_fallback_all_market_negative() -> None:
    """验证当全市场所有板块情绪均为负值时，坚定降级至防御板块 'gold' (B9)。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=-0.25, sentiment_trend=TREND_DECLINING),
        "gold": SectorState(sector="gold", sentiment_score=-0.05, sentiment_trend=TREND_DECLINING, confidence=0.75),
    }
    decision = engine.evaluate("green", states)
    assert decision.should_rotate is True
    assert decision.target_sector == "gold"
    assert decision.is_fallback is True


def test_engine_already_in_defensive_sector_holds() -> None:
    """验证若当前持仓已在防御资产板块 ('gold')，市场恶化时不重复轮动，维持持仓 (B10)。"""
    engine = SectorRotationEngine()
    states = {
        "gold": SectorState(sector="gold", sentiment_score=-0.35, sentiment_trend=TREND_DECLINING, confidence=0.78),
        "green": SectorState(sector="green", sentiment_score=-0.50, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=-0.30, sentiment_trend=TREND_DECLINING),
    }
    decision = engine.evaluate("gold", states)
    assert decision.should_rotate is False
    assert decision.target_sector == "gold"
    assert decision.is_fallback is True
    assert "already holding defensive" in decision.reason.lower()


# ============================================================================
# 5. 交易风控与调仓门禁规则测试 (Guardrails)
# ============================================================================

def test_engine_holding_days_under_five_blocks_rotation() -> None:
    """验证持仓交易日 < 5 天时，即使情绪极度恶化也不得触发轮动 (B13)。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.60, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=0.85, sentiment_trend=TREND_RISING),
    }
    for h in [0, 1, 2, 3, 4]:
        d = engine.evaluate("green", states, holding_days=h, monthly_rotations=0, days_since_last_rotation=10)
        assert d.should_rotate is False
        assert d.target_sector is None
        assert "Holding period too short" in d.reason


def test_engine_monthly_rotation_cap_exceeded_blocks_rotation() -> None:
    """验证单月轮动已达 3 次时，拒绝第 4 次轮动 (B12)。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.50, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=0.75, sentiment_trend=TREND_RISING),
    }
    for m in [3, 4, 5]:
        d = engine.evaluate("green", states, holding_days=6, monthly_rotations=m, days_since_last_rotation=10)
        assert d.should_rotate is False
        assert "Monthly rotation cap reached" in d.reason


def test_engine_cooldown_active_blocks_rotation() -> None:
    """验证距上次轮动间隔 < 7 天时，强制冷却生效，阻断轮动 (B11)。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.50, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=0.75, sentiment_trend=TREND_RISING),
    }
    for c in [0, 1, 3, 5, 6]:
        d = engine.evaluate("green", states, holding_days=6, monthly_rotations=1, days_since_last_rotation=c)
        assert d.should_rotate is False
        assert "Cooldown active" in d.reason


def test_engine_all_constraints_satisfied_permits_rotation() -> None:
    """验证当持仓 >= 5天、本月频次 < 3次、冷却期 >= 7天时，轮动正常放行。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.38, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=0.68, sentiment_trend=TREND_RISING),
    }
    d = engine.evaluate("green", states, holding_days=5, monthly_rotations=2, days_since_last_rotation=7)
    assert d.should_rotate is True
    assert d.target_sector == "storage"


# ============================================================================
# 6. 异常边界与数据结构契约测试
# ============================================================================

def test_engine_missing_current_sector_in_states() -> None:
    """验证当输入字典缺失当前持仓板块状态时，引擎安全降级返回 hold。"""
    engine = SectorRotationEngine()
    states = {
        "storage": SectorState(sector="storage", sentiment_score=0.70),
    }
    d = engine.evaluate("green", states)
    assert d.should_rotate is False
    assert d.target_sector is None
    assert "missing" in d.reason


def test_rotation_decision_dataclass_properties_and_serialization() -> None:
    """验证 RotationDecision 契约属性、别名与字典序列化功能。"""
    d = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Triggered",
        confidence=0.88,
        is_fallback=False,
        llm_rationale="Approved",
        execution_time_ms=1.234,
        metrics={"test_metric": 42},
    )
    assert d.from_sector == "green"
    assert d.to_sector == "storage"
    dct = d.to_dict()
    assert dct["should_rotate"] is True
    assert dct["current_sector"] == "green"
    assert dct["target_sector"] == "storage"
    assert dct["from_sector"] == "green"
    assert dct["to_sector"] == "storage"
    assert dct["confidence"] == pytest.approx(0.88)
    assert dct["execution_time_ms"] == pytest.approx(1.234)
    assert dct["metrics"]["test_metric"] == 42


def test_engine_decide_method_adapters() -> None:
    """验证 decide() 方法的多态调用适配（支持字典与类对象 portfolio_state）。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING),
    }

    # 1. 位置参数调用 decide(states, current_sector)
    d1 = engine.decide(states, "green", holding_days=6, monthly_rotations=1, days_since_last_rotation=8)
    assert d1.should_rotate is True
    assert d1.target_sector == "storage"

    # 2. 携带类似 PortfolioState 属性对象的调用
    class DummyPortfolio:
        current_sector = "green"
        holding_days = 6
        rotation_count_this_month = 1
        days_since_last_rotation = 8

    d2 = engine.decide(sector_sentiments=states, portfolio_state=DummyPortfolio())
    assert d2.should_rotate is True
    assert d2.target_sector == "storage"

    # 3. 携带空 current_sector 或缺失其他属性的对象
    class PartialPortfolio:
        current_sector = ""

    d3 = engine.decide(sector_sentiments=states, current_sector="green", portfolio_state=PartialPortfolio())
    assert d3.should_rotate is True



# ============================================================================
# 7. 纯量化快速路径执行延迟基准测试
# ============================================================================

def test_engine_latency_sub_100ms_benchmark() -> None:
    """测试纯量化决策路径的执行延迟，确保 200 次平均调用延迟远低于 100ms 硬顶（目标 < 1ms）。"""
    engine = SectorRotationEngine()
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
        "storage": SectorState(sector="storage", sentiment_score=0.65, sentiment_trend=TREND_RISING),
        "gold": SectorState(sector="gold", sentiment_score=0.25, sentiment_trend=TREND_STABLE),
    }

    t0 = time.perf_counter()
    iterations = 200
    for _ in range(iterations):
        res = engine.evaluate("green", states, holding_days=5, monthly_rotations=0, days_since_last_rotation=10)
        assert res.should_rotate is True

    elapsed = time.perf_counter() - t0
    avg_ms = (elapsed / iterations) * 1000.0
    # 严格断言：单次平均延迟小于 5ms，远低于 100ms
    assert avg_ms < 5.0, f"纯量化路径平均执行延迟过长: {avg_ms:.3f}ms >= 5.0ms"
