# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_m2_challenger_fuzz.py —— M2 状态机与临界阈值对抗性模糊测试套件

由 Challenger M2 (Instance 2 - Boundary & State Machine Fuzzing) 编写并实测：
1. 临界阈值极值模糊测试 (Exact Boundary Thresholds):
   - 情绪下沉触发阈值: -0.3000 (边界维持 hold), -0.2999 (未达标维持 hold), -0.3001 (突破下沉触发 rotate)
   - 候选板块筛选阈值: 0.5000 (未突破不合格 -> 降级 gold), 0.4999 (未达标 -> 降级 gold), 0.5001 (突破达标 -> 候选选中)
2. 约束门禁边界极值测试 (Constraint Boundaries):
   - 最短持仓天数: holding_days = 4 (阻断 hold), 5 (放行 rotate), 6 (放行 rotate)
   - 单月轮动频次上限: monthly_rotations = 2 (放行 rotate), 3 (阻断 hold), 4 (阻断 hold)
   - 调仓冷却期: days_since_last_rotation = 6 (阻断 hold), 7 (放行 rotate), 8 (放行 rotate)
   - 组合约束网格: 3x3x3 = 27 种全组合极值测试
3. 极端市场情景组合模糊测试 (Market Regimes):
   - 全负市场 (All Negative): 全板块得分 < 0，必定退守防御资产 ('gold')
   - 全正市场 (All Positive): 全板块得分 > 0.5，当前持仓健康，绝对不触发轮动
   - 混合分化市场 (Mixed Regimes): 下沉板块识别与多因子最优候选板块选拔
   - 全相同市场 (All Identical): 得分全相同负值、全相同零值、全相同正值时的状态机鲁棒性
4. 核心系统不变量验证 (System Invariants):
   - Invariant 1: 当 should_rotate == False 时，target_sector 必须为 None 或等于 current_sector
   - Invariant 2: 当全市场板块均为负情绪时，若触发轮动，target_sector 必须为防御资产 ('gold')
5. 属性化随机模糊测试框架 (Property-Based Fuzz Harness):
   - 2,000 次随机边界生成与参数扰动，严格验证零未捕获异常、不变量 100% 保持、执行延迟 < 10ms
"""

import math
import random
import time
from typing import Dict, List, Optional

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
from src.sector_rotation.llm_decision_advisor import LLMDecisionAdvisor
from src.sector_rotation.sector_rotation_engine import (
    RotationDecision,
    SectorRotationEngine,
)
from src.sector_rotation.utils.sector_utils import SectorState


# ============================================================================
# 1. 临界阈值极值模糊测试 (Exact Boundary Thresholds)
# ============================================================================

class TestExactBoundaryThresholds:
    """针对 SENTIMENT_DECLINE_THRESHOLD (-0.3) 与 MIN_TARGET_SENTIMENT (0.5) 的浮点极值测试"""

    @pytest.mark.parametrize(
        "score,expected_rotate,test_desc",
        [
            (-0.3000, False, "精确等于 -0.3000，因未严格低于阈值，必须维持 hold"),
            (-0.2999, False, "微幅高于 -0.3000 (-0.2999)，健康度合格，维持 hold"),
            (-0.3001, True, "微幅低于 -0.3000 (-0.3001)，突破下沉阈值，必须触发轮动"),
            (-0.2999999, False, "单精度浮点极近上侧 -0.2999999，必须维持 hold"),
            (-0.3000001, True, "单精度浮点极近下侧 -0.3000001，必须触发轮动"),
        ],
    )
    def test_decline_threshold_exact_boundaries(
        self, score: float, expected_rotate: bool, test_desc: str
    ) -> None:
        """实测持仓板块情绪得分在 -0.3 边界两侧的精确判定"""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(
                sector="green",
                sentiment_score=score,
                sentiment_trend=TREND_DECLINING,
                confidence=0.85,
            ),
            "storage": SectorState(
                sector="storage",
                sentiment_score=0.70,
                sentiment_trend=TREND_RISING,
                confidence=0.90,
            ),
            "gold": SectorState(
                sector="gold",
                sentiment_score=0.20,
                sentiment_trend=TREND_STABLE,
                confidence=0.80,
            ),
        }

        decision = engine.evaluate(
            current_sector="green",
            sector_states=states,
            holding_days=5,
            monthly_rotations=0,
            days_since_last_rotation=10,
        )

        assert decision.should_rotate is expected_rotate, f"Failed on: {test_desc}"
        if expected_rotate:
            assert decision.target_sector == "storage"
            assert decision.is_fallback is False
        else:
            assert decision.target_sector is None or decision.target_sector == "green"
            assert "healthy" in decision.reason or "too short" in decision.reason

    @pytest.mark.parametrize(
        "candidate_score,expected_target,expected_fallback,test_desc",
        [
            (0.5000, "gold", True, "精确等于 0.5000，未严格突破 0.5 门槛，不合格，退守防御资产 gold"),
            (0.4999, "gold", True, "微幅低于 0.5000 (0.4999)，不合格，退守防御资产 gold"),
            (0.5001, "storage", False, "微幅高于 0.5000 (0.5001)，突破合格门槛，成功选拔为 target_sector"),
            (0.4999999, "gold", True, "单精度极近下侧 0.4999999，不合格，退守防御资产 gold"),
            (0.5000001, "storage", False, "单精度极近上侧 0.5000001，合格，成功选拔 storage"),
        ],
    )
    def test_candidate_threshold_exact_boundaries(
        self,
        candidate_score: float,
        expected_target: str,
        expected_fallback: bool,
        test_desc: str,
    ) -> None:
        """实测候选板块情绪得分在 0.5 门槛两侧的精确判定"""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(
                sector="green",
                sentiment_score=-0.40,
                sentiment_trend=TREND_DECLINING,
                confidence=0.85,
            ),
            "storage": SectorState(
                sector="storage",
                sentiment_score=candidate_score,
                sentiment_trend=TREND_RISING,
                confidence=0.90,
                volatility=0.05,
            ),
            "gold": SectorState(
                sector="gold",
                sentiment_score=0.10,
                sentiment_trend=TREND_STABLE,
                confidence=0.80,
            ),
        }

        decision = engine.evaluate(
            current_sector="green",
            sector_states=states,
            holding_days=5,
            monthly_rotations=0,
            days_since_last_rotation=10,
        )

        assert decision.should_rotate is True
        assert decision.target_sector == expected_target, f"Failed on: {test_desc}"
        assert decision.is_fallback is expected_fallback, f"Fallback mismatch on: {test_desc}"


# ============================================================================
# 2. 约束门禁边界极值测试 (Constraint Boundaries)
# ============================================================================

class TestConstraintBoundaries:
    """针对持仓天数 (5天)、单月频次 (3次)、冷却期 (7天) 的离散边界组合测试"""

    @pytest.mark.parametrize(
        "holding_days,expected_permitted",
        [
            (4, False),  # 4 < 5 -> Blocked
            (5, True),   # 5 >= 5 -> Permitted
            (6, True),   # 6 >= 5 -> Permitted
        ],
    )
    def test_holding_days_boundaries(self, holding_days: int, expected_permitted: bool) -> None:
        """持仓天数 4, 5, 6 临界值测试"""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING),
        }
        decision = engine.evaluate(
            "green",
            states,
            holding_days=holding_days,
            monthly_rotations=0,
            days_since_last_rotation=10,
        )
        assert decision.should_rotate is expected_permitted
        if not expected_permitted:
            assert "Holding period too short" in decision.reason
            assert decision.target_sector is None

    @pytest.mark.parametrize(
        "monthly_rotations,expected_permitted",
        [
            (2, True),   # 2 < 3 -> Permitted
            (3, False),  # 3 >= 3 -> Blocked
            (4, False),  # 4 >= 3 -> Blocked
        ],
    )
    def test_monthly_rotations_boundaries(self, monthly_rotations: int, expected_permitted: bool) -> None:
        """单月轮动频次 2, 3, 4 临界值测试"""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING),
        }
        decision = engine.evaluate(
            "green",
            states,
            holding_days=6,
            monthly_rotations=monthly_rotations,
            days_since_last_rotation=10,
        )
        assert decision.should_rotate is expected_permitted
        if not expected_permitted:
            assert "Monthly rotation cap reached" in decision.reason
            assert decision.target_sector is None

    @pytest.mark.parametrize(
        "cooldown,expected_permitted",
        [
            (6, False),  # 6 < 7 -> Blocked
            (7, True),   # 7 >= 7 -> Permitted
            (8, True),   # 8 >= 7 -> Permitted
        ],
    )
    def test_cooldown_days_boundaries(self, cooldown: int, expected_permitted: bool) -> None:
        """调仓冷却期 6, 7, 8 临界值测试"""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING),
        }
        decision = engine.evaluate(
            "green",
            states,
            holding_days=6,
            monthly_rotations=1,
            days_since_last_rotation=cooldown,
        )
        assert decision.should_rotate is expected_permitted
        if not expected_permitted:
            assert "Cooldown active" in decision.reason
            assert decision.target_sector is None

    def test_full_constraint_grid_27_combinations(self) -> None:
        """遍历 3x3x3 = 27 种全网格约束状态，确保规则短路与准入严丝合缝"""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.50, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.80, sentiment_trend=TREND_RISING),
        }

        h_values = [4, 5, 6]
        m_values = [2, 3, 4]
        c_values = [6, 7, 8]

        for h in h_values:
            for m in m_values:
                for c in c_values:
                    decision = engine.evaluate(
                        "green",
                        states,
                        holding_days=h,
                        monthly_rotations=m,
                        days_since_last_rotation=c,
                    )

                    # 只有同时满足 h >= 5 且 m < 3 且 c >= 7 时才允许轮动
                    expected_rotate = (h >= 5) and (m < 3) and (c >= 7)

                    assert decision.should_rotate is expected_rotate, (
                        f"Grid failed on h={h}, m={m}, c={c}: got {decision.should_rotate}, expected {expected_rotate}"
                    )
                    if not expected_rotate:
                        assert decision.target_sector is None


# ============================================================================
# 3. 极端市场情景组合模糊测试 (Market Regimes)
# ============================================================================

class TestMarketRegimesCombinatorial:
    """测试全负、全正、分化、全相同等全部极端行情组合"""

    def test_regime_all_negative_market(self) -> None:
        """情景 1: 全市场负面行情 (All Negative)
        所有板块 sentiment < 0。
        - 若当前板块处于下沉通道，目标必须必定降级至防御板块 ('gold')。
        - 若当前已在防御板块 ('gold')，必须保持持仓不发生重复轮动。
        """
        engine = SectorRotationEngine()

        all_neg_states = {
            "green": SectorState(sector="green", sentiment_score=-0.60, sentiment_trend=TREND_DECLINING, confidence=0.8),
            "storage": SectorState(sector="storage", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING, confidence=0.8),
            "gold": SectorState(sector="gold", sentiment_score=-0.15, sentiment_trend=TREND_DECLINING, confidence=0.85),
        }

        # 1.1 从 green 出发
        d_green = engine.evaluate("green", all_neg_states, holding_days=6, monthly_rotations=0, days_since_last_rotation=10)
        assert d_green.should_rotate is True
        assert d_green.target_sector == "gold"
        assert d_green.is_fallback is True

        # 1.2 从 storage 出发
        d_storage = engine.evaluate("storage", all_neg_states, holding_days=6, monthly_rotations=0, days_since_last_rotation=10)
        assert d_storage.should_rotate is True
        assert d_storage.target_sector == "gold"
        assert d_storage.is_fallback is True

        # 1.3 从 gold 出发（已在防御资产）
        # 1.3.1 若 gold 得分为 -0.15（未达 -0.3 下沉门槛），作为持仓板块判定为 healthy -> should_rotate=False, target_sector=None
        d_gold_mild = engine.evaluate("gold", all_neg_states, holding_days=6, monthly_rotations=0, days_since_last_rotation=10)
        assert d_gold_mild.should_rotate is False
        assert d_gold_mild.target_sector in (None, "gold")

        # 1.3.2 若 gold 得分也深度下沉至 -0.35 (< -0.3 且 declining)，引擎判定已在防御资产 -> should_rotate=False, target_sector="gold"
        all_neg_deep = dict(all_neg_states)
        all_neg_deep["gold"] = SectorState(sector="gold", sentiment_score=-0.35, sentiment_trend=TREND_DECLINING, confidence=0.85)
        d_gold_deep = engine.evaluate("gold", all_neg_deep, holding_days=6, monthly_rotations=0, days_since_last_rotation=10)
        assert d_gold_deep.should_rotate is False
        assert d_gold_deep.target_sector == "gold"
        assert d_gold_deep.is_fallback is True

    def test_regime_all_positive_market(self) -> None:
        """情景 2: 全市场正向繁荣行情 (All Positive)
        所有板块 sentiment > 0.5。
        由于持仓板块处于极高景气区间 (> -0.3)，绝对不满足下沉触发，必须保持持有原板块。
        """
        engine = SectorRotationEngine()

        all_pos_states = {
            "green": SectorState(sector="green", sentiment_score=0.65, sentiment_trend=TREND_RISING, confidence=0.9),
            "storage": SectorState(sector="storage", sentiment_score=0.85, sentiment_trend=TREND_RISING, confidence=0.9),
            "gold": SectorState(sector="gold", sentiment_score=0.55, sentiment_trend=TREND_STABLE, confidence=0.85),
        }

        for sec in ["green", "storage", "gold"]:
            d = engine.evaluate(sec, all_pos_states, holding_days=6, monthly_rotations=0, days_since_last_rotation=10)
            assert d.should_rotate is False
            assert d.target_sector is None
            assert "healthy" in d.reason

    def test_regime_mixed_divergent_market(self) -> None:
        """情景 3: 市场剧烈分化行情 (Mixed Regimes)
        当前板块下沉 (-0.45, declining)，候选板块中存在多个 > 0.5 标的。
        检验多因子评分算法能够精确选出最优板块。
        """
        engine = SectorRotationEngine()

        states = {
            "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING, confidence=0.8),
            # Candidate 1: score=0.65, rising, conf=0.85, vol=0.08
            # composite = 0.5*0.65 + 0.2*0.3 + 0.2*0.85 - 0.1*0.08 = 0.325 + 0.06 + 0.17 - 0.008 = 0.547
            "storage": SectorState(sector="storage", sentiment_score=0.65, sentiment_trend=TREND_RISING, confidence=0.85, volatility=0.08),
            # Candidate 2: score=0.75, stable, conf=0.80, vol=0.20
            # composite = 0.5*0.75 + 0.2*0.0 + 0.2*0.80 - 0.1*0.20 = 0.375 + 0.00 + 0.16 - 0.02 = 0.515
            "gold": SectorState(sector="gold", sentiment_score=0.75, sentiment_trend=TREND_STABLE, confidence=0.80, volatility=0.20),
        }

        d = engine.evaluate("green", states, holding_days=6, monthly_rotations=0, days_since_last_rotation=10)
        assert d.should_rotate is True
        # 尽管 gold 的情绪得分 (0.75) 高于 storage (0.65)，但 storage 的上升趋势与低波动优势在综合评分上更胜一筹
        assert d.target_sector == "storage"
        assert d.is_fallback is False

    def test_regime_all_identical_scores(self) -> None:
        """情景 4: 全市场得分完全相同行情 (All Identical)
        4.1 全相同负值 (-0.50): 触发轮动，退守 gold
        4.2 全相同零值 (0.00): 当前持仓 healthy，不轮动
        4.3 全相同景气 (0.70): 当前持仓 healthy，不轮动
        4.4 全相同边界 (-0.3000): 未严格低于 -0.3，不轮动
        """
        engine = SectorRotationEngine()

        # 4.1 全相同负值 -0.50
        neg_identical = {
            s: SectorState(sector=s, sentiment_score=-0.50, sentiment_trend=TREND_DECLINING, confidence=0.8)
            for s in ["green", "storage", "gold"]
        }
        d_neg_from_green = engine.evaluate("green", neg_identical, holding_days=6)
        assert d_neg_from_green.should_rotate is True
        assert d_neg_from_green.target_sector == "gold"
        assert d_neg_from_green.is_fallback is True

        d_neg_from_gold = engine.evaluate("gold", neg_identical, holding_days=6)
        assert d_neg_from_gold.should_rotate is False
        assert d_neg_from_gold.target_sector == "gold"

        # 4.2 全相同零值 0.00
        zero_identical = {
            s: SectorState(sector=s, sentiment_score=0.00, sentiment_trend=TREND_STABLE, confidence=0.8)
            for s in ["green", "storage", "gold"]
        }
        d_zero = engine.evaluate("green", zero_identical, holding_days=6)
        assert d_zero.should_rotate is False
        assert d_zero.target_sector is None

        # 4.3 全相同景气 0.70
        pos_identical = {
            s: SectorState(sector=s, sentiment_score=0.70, sentiment_trend=TREND_RISING, confidence=0.9)
            for s in ["green", "storage", "gold"]
        }
        d_pos = engine.evaluate("green", pos_identical, holding_days=6)
        assert d_pos.should_rotate is False
        assert d_pos.target_sector is None

        # 4.4 全相同临界 -0.3000
        boundary_identical = {
            s: SectorState(sector=s, sentiment_score=-0.3000, sentiment_trend=TREND_DECLINING, confidence=0.8)
            for s in ["green", "storage", "gold"]
        }
        d_bound = engine.evaluate("green", boundary_identical, holding_days=6)
        assert d_bound.should_rotate is False
        assert d_bound.target_sector is None


# ============================================================================
# 4. 核心系统不变量验证 (System Invariants)
# ============================================================================

class TestRotationInvariants:
    """验证两大核心理论不变量：
    Invariant 1: When should_rotate is False, target_sector must either be None or equal to current_sector.
    Invariant 2: When all sectors are negative, target_sector must be 'gold' (or defensive asset).
    """

    def test_invariant_1_hold_target_sector_consistency(self) -> None:
        """实测 Invariant 1:
        不论何种原因导致 should_rotate 为 False（持仓不足、月频受限、冷却期未满、持仓健康、已在防御等），
        target_sector 必须且只能为 None 或等于 current_sector。
        """
        engine = SectorRotationEngine()

        test_cases = [
            # Case 1: 持仓不足
            ("green", {"green": SectorState(sector="green", sentiment_score=-0.5, sentiment_trend=TREND_DECLINING)}, 3, 0, 10),
            # Case 2: 月频超限
            ("green", {"green": SectorState(sector="green", sentiment_score=-0.5, sentiment_trend=TREND_DECLINING)}, 6, 3, 10),
            # Case 3: 冷却生效
            ("green", {"green": SectorState(sector="green", sentiment_score=-0.5, sentiment_trend=TREND_DECLINING)}, 6, 0, 5),
            # Case 4: 得分健康
            ("green", {"green": SectorState(sector="green", sentiment_score=0.1, sentiment_trend=TREND_RISING)}, 6, 0, 10),
            # Case 5: 趋势未下沉
            ("green", {"green": SectorState(sector="green", sentiment_score=-0.4, sentiment_trend=TREND_STABLE)}, 6, 0, 10),
            # Case 6: 缺失持仓
            ("unknown", {"green": SectorState(sector="green", sentiment_score=0.5)}, 6, 0, 10),
            # Case 7: 已在防御资产维持
            ("gold", {
                "gold": SectorState(sector="gold", sentiment_score=-0.4, sentiment_trend=TREND_DECLINING),
                "green": SectorState(sector="green", sentiment_score=-0.5),
            }, 6, 0, 10),
        ]

        for idx, (curr, states, h, m, c) in enumerate(test_cases):
            dec = engine.evaluate(curr, states, holding_days=h, monthly_rotations=m, days_since_last_rotation=c)
            assert dec.should_rotate is False, f"Test case {idx} should have should_rotate == False"
            # 严格验证不变量 1
            assert dec.target_sector is None or dec.target_sector == dec.current_sector, (
                f"Invariant 1 violated in case {idx}: current={dec.current_sector}, target={dec.target_sector}"
            )

    def test_invariant_2_all_negative_routes_to_gold(self) -> None:
        """实测 Invariant 2:
        当全市场所有板块均为负面情绪时，任何轮动动作的目标板块必须严格为 'gold'（防御资产）。
        """
        engine = SectorRotationEngine()

        # 生成 50 组不同的全负市场分布
        random.seed(42)
        for trial in range(50):
            scores = {
                "green": -random.uniform(0.31, 0.99),
                "storage": -random.uniform(0.01, 0.99),
                "gold": -random.uniform(0.01, 0.99),
            }
            states = {
                s: SectorState(
                    sector=s,
                    sentiment_score=scores[s],
                    sentiment_trend=TREND_DECLINING,
                    confidence=random.uniform(0.6, 0.95),
                    volatility=random.uniform(0.05, 0.3),
                )
                for s in ["green", "storage", "gold"]
            }

            # 从 green 触发轮动
            dec = engine.evaluate("green", states, holding_days=6, monthly_rotations=0, days_since_last_rotation=10)
            assert dec.should_rotate is True
            # 严格验证不变量 2
            assert dec.target_sector == "gold", f"Invariant 2 violated on trial {trial}: target={dec.target_sector}"
            assert dec.is_fallback is True

            # 从 storage 触发轮动
            states["storage"].sentiment_score = -random.uniform(0.31, 0.99)
            dec2 = engine.evaluate("storage", states, holding_days=6, monthly_rotations=0, days_since_last_rotation=10)
            assert dec2.should_rotate is True
            assert dec2.target_sector == "gold", f"Invariant 2 violated for storage on trial {trial}: target={dec2.target_sector}"

            # 从 gold 评估：已在防御资产板块，无论得分轻微还是深度负值，绝对不得轮出到其他板块
            dec_gold = engine.evaluate("gold", states, holding_days=6, monthly_rotations=0, days_since_last_rotation=10)
            assert dec_gold.should_rotate is False
            assert dec_gold.target_sector in (None, "gold")  # 维持持有 gold，不变量 1 与 2 双重满足


# ============================================================================
# 5. 属性化随机模糊测试框架 (Property-Based Fuzz Harness)
# ============================================================================

class TestPropertyBasedFuzzHarness:
    """自动化生成 2,000 组随机状态，进行全参数空间模糊压力测试"""

    def test_random_fuzzing_2000_iterations_invariants_and_safety(self) -> None:
        """2,000 次随机输入模糊测试，验证：
        1. 零未捕获异常或运行时崩溃
        2. Invariant 1: should_rotate == False => target_sector in (None, current_sector)
        3. Invariant 2: should_rotate == True 且无候选 > 0.5 时 => target_sector == 'gold'
        4. 置信度范围严格在 [0.0, 1.0] 内
        5. 单次调用耗时均严格 < 10ms (硬指标 < 100ms)
        6. to_dict() 序列化完备无异常
        """
        engine = SectorRotationEngine()
        random.seed(20261013)

        sectors_pool = ["green", "storage", "gold", "unknown_sector"]
        trends_pool = [TREND_RISING, TREND_STABLE, TREND_DECLINING, "invalid_trend"]

        max_latencies_ms: List[float] = []
        total_runs = 2000

        for run_idx in range(total_runs):
            curr_sec = random.choice(sectors_pool)

            # 随机生成包含 1~4 个板块的状态字典
            num_secs = random.randint(1, 4)
            chosen_secs = random.sample(sectors_pool, num_secs)
            states: Dict[str, SectorState] = {}
            for s in chosen_secs:
                score = round(random.uniform(-1.2, 1.2), 4)
                trend = random.choice(trends_pool)
                conf = round(random.uniform(-0.2, 1.2), 4)
                vol = round(random.uniform(-0.1, 1.5), 4)
                states[s] = SectorState(
                    sector=s,
                    sentiment_score=score,
                    sentiment_trend=trend,
                    confidence=conf,
                    volatility=vol,
                )

            holding_days = random.randint(-5, 20)
            monthly_rotations = random.randint(-2, 10)
            cooldown_days = random.randint(-5, 20)

            t0 = time.perf_counter()
            dec = engine.evaluate(
                current_sector=curr_sec,
                sector_states=states,
                holding_days=holding_days,
                monthly_rotations=monthly_rotations,
                days_since_last_rotation=cooldown_days,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            max_latencies_ms.append(elapsed_ms)

            # 断言 1: 执行时间
            assert elapsed_ms < 10.0, f"Run {run_idx}: Latency {elapsed_ms:.2f}ms exceeded 10ms limit"

            # 断言 2: 置信度合规
            assert 0.0 <= dec.confidence <= 1.0, f"Run {run_idx}: Invalid confidence {dec.confidence}"

            # 断言 3: Invariant 1 (Hold 状态下的目标板块安全性)
            if not dec.should_rotate:
                assert dec.target_sector in (None, dec.current_sector), (
                    f"Run {run_idx}: Invariant 1 violated! curr={dec.current_sector}, target={dec.target_sector}"
                )

            # 断言 4: Invariant 2 (无有效候选时的防御回退安全性)
            if dec.should_rotate:
                # 检查是否存在得分 > 0.5 且不为当前板块的候选
                eligible_exists = any(
                    k != dec.current_sector and v.sentiment_score > 0.5
                    for k, v in states.items()
                )
                if not eligible_exists:
                    assert dec.target_sector == "gold", (
                        f"Run {run_idx}: Invariant 2 violated! No candidate > 0.5, but target was '{dec.target_sector}'"
                    )
                    assert dec.is_fallback is True

            # 断言 5: 字典序列化与关键字段存在性
            dct = dec.to_dict()
            assert isinstance(dct, dict)
            assert "should_rotate" in dct
            assert "current_sector" in dct
            assert "target_sector" in dct
            assert "execution_time_ms" in dct

        avg_lat = sum(max_latencies_ms) / total_runs
        p99_lat = sorted(max_latencies_ms)[int(total_runs * 0.99)]
        print(f"\n[Fuzz Harness Completed] {total_runs} runs: avg={avg_lat:.4f}ms, p99={p99_lat:.4f}ms, max={max(max_latencies_ms):.4f}ms")


# ============================================================================
# 6. LLM 顾问状态机与不变量交互测试
# ============================================================================

class TestAdvisorInvariantPreservation:
    """验证 LLMDecisionAdvisor 在状态机输出时是否无缝维护不变量"""

    def test_advisor_preserves_invariant_1_when_hold(self) -> None:
        """验证当大模型返回 should_rotate == False 时，target_sector 必须强制归一化为 None"""
        advisor = LLMDecisionAdvisor()

        # 模拟 LLM 即使返回了某个 target_sector，只要 should_rotate 为 False，
        # 解析层与 advise 决策对象必须自动确保 target_sector 为 None
        parsed = advisor._parse_llm_response(
            '{"should_rotate": false, "target_sector": "storage", "reason": "保持持仓", "confidence": 0.85}'
        )
        assert parsed["should_rotate"] is False
        # 在 advise 步骤中组装 RotationDecision 时必须为 None
        quant_decision = RotationDecision(
            should_rotate=False,
            current_sector="green",
            target_sector=None,
            reason="Hold",
            confidence=0.8,
        )

        dummy_client = lambda p: '{"should_rotate": false, "target_sector": "storage", "reason": "维持持仓", "confidence": 0.85}'
        final_dec = advisor.advise(
            current_sector="green",
            sector_states={},
            quantitative_decision=quant_decision,
            llm_client=dummy_client,
        )

        assert final_dec.should_rotate is False
        # 严格验证 Invariant 1
        assert final_dec.target_sector is None or final_dec.target_sector == "green"
        assert final_dec.target_sector is None
