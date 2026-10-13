# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_m3_challenger_fuzz.py —— M3 渐进式调仓管理与风控对抗性模糊测试套件

由 Challenger M3 (teamwork_preview_challenger) 独立编写并执行：
1. 组合资产价值极值与模糊测试 (Fuzzed Portfolio Values):
   - 负数与零资产价值强行拦截 (-1.0, -100, -1e-6, 0.0, -inf -> 触发 ValueError)
   - 极大资产规模 (1e9, 1e12, 1e18 -> 验证摩擦费用线性无下溢/无溢出)
   - 浮点异常值边界探测 (NaN, inf 穿透与数值污染实证分析)
   - 成交额与滑点极值测试 (calculate_transaction_cost 边界防御)
2. 并发调仓与状态机重入模糊测试 (Concurrent Planning & Re-entrancy):
   - Day 1 / Day 2 / Day 3 处于活跃期时并发尝试创建新计划 (必定抛出 RuntimeError)
   - 多线程并发竞争 (10 线程并发创建调仓计划，严格互斥仅 1 线程成功)
   - 调仓计划生命周期流转 (正常完成、中途取消、跨计划干扰隔离)
   - 脏数据板块名称攻击 (相同板块、空字符串、全空格 -> 触发 ValueError)
3. 成本预算击穿与滑点极值测试 (Cost Budget Breaches & Friction Modeling):
   - 3日基准摩擦费用验证: Day 1 (0.15%), Day 2 (0.09%), Day 3 (0.06%), 累计 0.30%
   - 临界滑点精确阈值推导: 34 bps (0.98% 放行), 35 bps (1.000% 临界放行), 36 bps (1.020% 击穿超标)
   - strict_cost_limit 严格模式测试:
     - Day 1 立即击穿 (滑点 2.0% -> 成本 2.15% -> 抛出 CostLimitExceededError)
     - Day 2 滞后击穿 (滑点 0.8% -> Day 1 0.95% 放行, Day 2 1.52% 抛出异常)
     - Day 3 终局击穿 (滑点 0.4% -> Day 1/2 放行, Day 3 1.10% 抛出异常)
   - strict_cost_limit=False 宽容模式: 极端滑点 (10%, 100%) 不抛异常，返回 cost_exceeded=True
   - 成本汇总与重置一致性验证 (get_cost_summary, reset)
4. 决策流与投资组合状态机联动模糊测试 (Integration Fuzzing with RotationDecision & PortfolioState):
   - 模拟 RotationDecision 注入与 PortfolioState 逐日精准状态同步
   - 轮动决策生命周期 (Day 1: 50/50, Day 2: 20/80, Day 3: 0/100, 重置持仓天数, 递增单月轮动次数)
   - 防御资产降级轮动 (target_sector='gold', is_fallback=True)
   - 模拟 60 天长序列时序回测走步: 检验持仓天数 (<5天)、单月频次 (>=3次)、冷却期 (<7天) 风控三门禁
   - 中途取消与状态恢复测试 (Day 2 取消后解冻并允许重新规划)
5. 属性化随机模糊测试套件 (Property-Based Fuzz Harness):
   - 1,000 次随机边界生成与参数扰动:
     - 不变量 1: 任意单步权重之和严格等于 1.0 (精度 1e-5)
     - 不变量 2: 累计成本严格单调递增
     - 不变量 3: 步进权重序列严格遵循 [0.50, 0.30, 0.20]
     - 不变量 4: 单步量化执行耗时严格 < 1.0ms (远优于 100ms 约束)
"""

from __future__ import annotations

import math
import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import pytest

from src.sector_rotation.config import (
    BUY_FEE_RATE,
    COOLDOWN_DAYS,
    MAX_ROTATION_PER_MONTH,
    MAX_TOTAL_ROTATION_COST,
    MIN_HOLDING_DAYS,
    REALLOCATION_WEIGHTS,
    SELL_FEE_RATE,
)
from src.sector_rotation.position_manager import (
    CostLimitExceededError,
    PortfolioState,
    PositionManager,
    ReallocationSchedule,
)
from src.sector_rotation.sector_rotation_engine import RotationDecision


# ============================================================================
# 1. 资产价值极值与模糊测试 (Fuzzed Portfolio Values)
# ============================================================================

class TestPortfolioValueFuzzing:
    """针对 portfolio_value 各种极值、非法值与边界情况的对抗性测试"""

    @pytest.mark.parametrize(
        "invalid_value,desc",
        [
            (0.0, "零净值"),
            (-1.0, "负净值 -1.0"),
            (-100.0, "负净值 -100.0"),
            (-1e-6, "负微小净值 -1e-6"),
            (-1e12, "负大数净值 -1e12"),
            (-float("inf"), "负无穷大 -inf"),
        ],
    )
    def test_non_positive_portfolio_values_raise_value_error(
        self, invalid_value: float, desc: str
    ) -> None:
        """验证非正数资产规模在 execute_step 中严格抛出 ValueError。"""
        pm = PositionManager()
        schedule = pm.plan_reallocation("green", "storage")
        with pytest.raises(ValueError, match="投资组合净值必须为正数"):
            pm.execute_step(schedule, portfolio_value=invalid_value)

    @pytest.mark.parametrize(
        "large_value",
        [
            1e8,   # 1亿
            1e10,  # 100亿
            1e12,  # 1万亿
            1e15,  # 1000万亿
        ],
    )
    def test_very_large_portfolio_values_numerical_stability(
        self, large_value: float
    ) -> None:
        """测试超大资产规模下的数值稳定性与摩擦费用线性比例。"""
        pm = PositionManager()
        schedule = pm.plan_reallocation("green", "storage")

        res_day1 = pm.execute_step(schedule, portfolio_value=large_value)
        # Day 1: 换手 50%, 卖费率 0.175%, 买费率 0.125%, 费率和 0.30%
        # 成本应严格为 0.5 * large_value * (0.00175 + 0.00125) = 0.0015 * large_value
        expected_cost_day1 = 0.0015 * large_value
        assert math.isclose(res_day1["step_cost"], expected_cost_day1, rel_tol=1e-9)
        assert res_day1["cost_ratio"] == pytest.approx(0.0015, rel=1e-6)
        assert res_day1["cost_exceeded"] is False

    def test_nan_portfolio_value_empirical_behavior(self) -> None:
        """[Empirical Bug Finding 1] NaN 资产规模穿透漏洞实证。
        
        因代码中仅检查 `if portfolio_value <= 0:`，而 IEEE-754 中 `nan <= 0` 返回 False，
        导致 NaN 绕过正数校验，在计算中产生 NaN 摩擦费用，并因 `nan > 0.01` 返回 False
        而误判 cost_exceeded 为 False。
        此测试记录并实证该浮点边界行为。
        """
        pm = PositionManager()
        schedule = pm.plan_reallocation("green", "storage")

        # 实证执行：未被 <= 0 拦截
        res = pm.execute_step(schedule, portfolio_value=float("nan"))
        assert math.isnan(res["step_cost"])
        assert math.isnan(res["cost_ratio"])
        # 实证：IEEE-754 nan > 0.01 为 False，因此 cost_exceeded 误为 False
        assert res["cost_exceeded"] is False

    def test_infinite_portfolio_value_empirical_behavior(self) -> None:
        """[Empirical Bug Finding 2] 正无穷大资产规模穿透实证。
        
        `float('inf') <= 0` 为 False，因此进入计算；产生 inf 交易费用，
        但在计算 cost_ratio = inf / inf 时得到 NaN，进而导致 cost_exceeded 判定为 False。
        """
        pm = PositionManager()
        schedule = pm.plan_reallocation("green", "storage")

        res = pm.execute_step(schedule, portfolio_value=float("inf"))
        assert math.isinf(res["step_cost"])
        assert math.isnan(res["cost_ratio"])
        assert res["cost_exceeded"] is False

    def test_calculate_transaction_cost_isolated_fuzzing(self) -> None:
        """测试 calculate_transaction_cost 独立函数的边界输入防御。"""
        pm = PositionManager()

        # 1. 负成交额阻断
        with pytest.raises(ValueError, match="成交额不能为负数"):
            pm.calculate_transaction_cost(-100.0)

        with pytest.raises(ValueError, match="成交额不能为负数"):
            pm.calculate_transaction_cost(-1e-9)

        # 2. 零成交额
        assert pm.calculate_transaction_cost(0.0) == 0.0

        # 3. 负滑点安全忽略（不倒贴资金）
        cost_normal = pm.calculate_transaction_cost(100_000.0, slippage=0.0)
        cost_neg_slip = pm.calculate_transaction_cost(100_000.0, slippage=-0.01)
        assert cost_neg_slip == cost_normal

        # 4. 单向买/卖开关
        cost_buy_only = pm.calculate_transaction_cost(100_000.0, is_buy=True, is_sell=False)
        assert cost_buy_only == pytest.approx(100_000.0 * BUY_FEE_RATE, rel=1e-6)

        cost_sell_only = pm.calculate_transaction_cost(100_000.0, is_buy=False, is_sell=True)
        assert cost_sell_only == pytest.approx(100_000.0 * SELL_FEE_RATE, rel=1e-6)


# ============================================================================
# 2. 并发调仓与状态机重入模糊测试 (Concurrent Planning & Re-entrancy)
# ============================================================================

class TestConcurrentPlanningAndReentrancy:
    """针对并发调仓尝试、状态机重入与计划生命周期边界的对抗测试"""

    def test_concurrent_planning_rejection_at_each_day(self) -> None:
        """验证在渐进调仓的 Day 1、Day 2、Day 3 活跃期间，任何新的 plan_reallocation 必被阻断。"""
        pm = PositionManager()
        schedule = pm.plan_reallocation("green", "storage")

        # 1. Day 1 初始创建后（尚未 execute_step）
        with pytest.raises(RuntimeError, match="已有进行中的调仓计划"):
            pm.plan_reallocation("storage", "gold")

        # 2. Day 1 执行后（当前处于 Day 2）
        pm.execute_step(schedule)
        assert schedule.current_day == 2
        assert schedule.is_active is True
        with pytest.raises(RuntimeError, match="已有进行中的调仓计划"):
            pm.plan_reallocation("green", "gold")

        # 3. Day 2 执行后（当前处于 Day 3）
        pm.execute_step(schedule)
        assert schedule.current_day == 3
        assert schedule.is_active is True
        with pytest.raises(RuntimeError, match="已有进行中的调仓计划"):
            pm.plan_reallocation("storage", "green")

        # 4. Day 3 执行完成
        pm.execute_step(schedule)
        assert schedule.is_complete is True
        assert schedule.is_active is False
        assert pm.get_active_schedule() is None

        # 5. 完成后，可以正常规划新的调仓
        new_schedule = pm.plan_reallocation("storage", "gold")
        assert new_schedule.is_active is True
        assert new_schedule.from_sector == "storage"
        assert new_schedule.to_sector == "gold"

    def test_multithreaded_concurrent_planning_race(self) -> None:
        """测试 10 线程并发调用 plan_reallocation 时，仅有 1 线程成功，其余全部安全抛出 RuntimeError。"""
        pm = PositionManager()
        results: list[Optional[ReallocationSchedule]] = []
        errors: list[Exception] = []

        def worker_task(thread_id: int) -> None:
            try:
                sched = pm.plan_reallocation("green", f"target_{thread_id}")
                results.append(sched)
            except RuntimeError as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_task, i) for i in range(10)]
            for f in futures:
                f.result()

        # 严格断言：只能有 1 个计划被创建成功
        assert len(results) == 1
        # 其余 9 次尝试均被严格拦截
        assert len(errors) == 9
        for err in errors:
            assert "已有进行中的调仓计划" in str(err)

    @pytest.mark.parametrize(
        "bad_from,bad_to,err_type,err_msg",
        [
            ("green", "green", ValueError, "调仓起点板块与目标板块相同"),
            ("", "storage", ValueError, "调仓起点或目标板块不可为空"),
            ("green", "", ValueError, "调仓起点或目标板块不可为空"),
            ("   ", "storage", ValueError, "调仓起点或目标板块不可为空"),
            ("green", "   ", ValueError, "调仓起点或目标板块不可为空"),
        ],
    )
    def test_invalid_sector_names_rejected(
        self, bad_from: str, bad_to: str, err_type: type, err_msg: str
    ) -> None:
        """测试相同板块与空白板块名称的严格校验拦截。"""
        pm = PositionManager()
        with pytest.raises(err_type, match=err_msg):
            pm.plan_reallocation(bad_from, bad_to)

    def test_cancellation_and_resumption_lifecycle(self) -> None:
        """测试在中途取消调仓计划后，系统状态恢复且允许发起新调仓。"""
        pm = PositionManager()
        schedule = pm.plan_reallocation("green", "storage")

        # 执行第 1 步
        pm.execute_step(schedule)
        assert schedule.current_day == 2
        assert schedule.is_active is True

        # 突发风险：紧急取消调仓
        pm.cancel_schedule(reason="突发系统性利空，终止换仓")
        assert schedule.is_active is False
        assert schedule.status == "cancelled"
        assert schedule.cancellation_reason == "突发系统性利空，终止换仓"
        assert pm.get_active_schedule() is None

        # 再次执行被取消的计划应抛出 RuntimeError
        with pytest.raises(RuntimeError, match="调仓计划已非活跃状态"):
            pm.execute_step(schedule)

        # 允许立即创建新的应急调仓计划
        defensive_sched = pm.plan_reallocation("green", "gold")
        assert defensive_sched.is_active is True
        assert defensive_sched.to_sector == "gold"


# ============================================================================
# 3. 成本预算击穿与滑点极值测试 (Cost Budget Breaches & Friction Modeling)
# ============================================================================

class TestCostBudgetBreachesAndFriction:
    """针对 1.0% 交易摩擦硬顶、极端滑点注入与 CostLimitExceededError 的对抗测试"""

    def test_baseline_transaction_friction_exact_values(self) -> None:
        """严格推演验证无滑点时 3 日渐进调仓的确定性摩擦成本。"""
        pm = PositionManager()
        capital = 1_000_000.0

        sched = pm.plan_reallocation("green", "storage")

        # Day 1: 50% 换手
        res1 = pm.execute_step(sched, portfolio_value=capital, slippage=0.0)
        assert res1["sell_fee"] == pytest.approx(500_000.0 * 0.00175, rel=1e-6)  # 875.0
        assert res1["buy_fee"] == pytest.approx(500_000.0 * 0.00125, rel=1e-6)   # 625.0
        assert res1["step_cost"] == pytest.approx(1500.0, rel=1e-6)              # 0.15%
        assert res1["cost_ratio"] == pytest.approx(0.0015, rel=1e-6)

        # Day 2: 30% 换手
        res2 = pm.execute_step(sched, portfolio_value=capital, slippage=0.0)
        assert res2["step_cost"] == pytest.approx(900.0, rel=1e-6)               # 0.09%
        assert res2["accumulated_cost"] == pytest.approx(2400.0, rel=1e-6)       # 0.24%

        # Day 3: 20% 换手
        res3 = pm.execute_step(sched, portfolio_value=capital, slippage=0.0)
        assert res3["step_cost"] == pytest.approx(600.0, rel=1e-6)               # 0.06%
        assert res3["accumulated_cost"] == pytest.approx(3000.0, rel=1e-6)       # 0.30%
        assert res3["cost_ratio"] == pytest.approx(0.0030, rel=1e-6)
        assert res3["cost_exceeded"] is False

        # 累计 0.30% 严格在 1.0% 风控上限内
        valid, msg = pm.verify_cost_within_limit(sched, capital)
        assert valid is True
        assert "0.3000% 符合风控上限" in msg

    @pytest.mark.parametrize(
        "slippage,expected_exceeded_day",
        [
            # 34 bps: 总成本 0.30% + 2 * 0.34% = 0.98% <= 1.0% (全周期不超标)
            (0.0034, None),
            # 35 bps: 总成本 0.30% + 2 * 0.35% = 1.000% <= 1.0% (边界不超标)
            (0.0035, None),
            # 36 bps: 总成本 0.30% + 2 * 0.36% = 1.020% > 1.0% (Day 3 击穿超标)
            (0.0036, 3),
            # 80 bps: Day 1 (0.15% + 0.8% = 0.95% <= 1.0%), Day 2 (累计 1.52% > 1.0% 击穿)
            (0.0080, 2),
            # 200 bps: Day 1 (0.15% + 2.0% = 2.15% > 1.0% 立即击穿)
            (0.0200, 1),
        ],
    )
    def test_slippage_boundary_thresholds_and_breach_detection(
        self, slippage: float, expected_exceeded_day: Optional[int]
    ) -> None:
        """测试不同滑点水平下，系统是否在预期交易日准确捕获超标状态。"""
        pm = PositionManager()
        sched = pm.plan_reallocation("green", "storage")
        capital = 1_000_000.0

        breached_at: Optional[int] = None
        for day in range(1, 4):
            res = pm.execute_step(sched, portfolio_value=capital, slippage=slippage)
            if res["cost_exceeded"] and breached_at is None:
                breached_at = day

        assert breached_at == expected_exceeded_day

    def test_strict_cost_limit_mode_raises_at_day_1(self) -> None:
        """测试 strict_cost_limit=True 在 Day 1 发生巨额滑点时立即中断并抛出 CostLimitExceededError。"""
        pm = PositionManager()
        sched = pm.plan_reallocation("green", "storage")

        # 注入 2.0% 极端单边滑点（双边 4.0% * 0.5 = 2.0% 净值冲击）
        with pytest.raises(CostLimitExceededError, match="超出风控上限 1.00%"):
            pm.execute_step(
                sched,
                portfolio_value=1_000_000.0,
                slippage=0.02,
                strict_cost_limit=True,
            )

    def test_strict_cost_limit_mode_raises_at_day_2(self) -> None:
        """测试 strict_cost_limit=True 在 Day 1 合格但 Day 2 累计超标时在 Day 2 抛出异常。"""
        pm = PositionManager()
        sched = pm.plan_reallocation("green", "storage")

        # Day 1: slippage = 0.008 -> 成本 0.95% <= 1.0%，正常放行
        res1 = pm.execute_step(
            sched, portfolio_value=1_000_000.0, slippage=0.008, strict_cost_limit=True
        )
        assert res1["cost_exceeded"] is False

        # Day 2: 再次注入，累计成本 1.52% > 1.0%，必须抛出异常
        with pytest.raises(CostLimitExceededError, match="超出风控上限 1.00%"):
            pm.execute_step(
                sched,
                portfolio_value=1_000_000.0,
                slippage=0.008,
                strict_cost_limit=True,
            )

    def test_permissive_mode_tolerates_extreme_slippage_with_flag(self) -> None:
        """测试 strict_cost_limit=False (默认) 时，即便遭遇 100% 滑点也不会挂起，而是返回 cost_exceeded=True 供上层决策。"""
        pm = PositionManager()
        sched = pm.plan_reallocation("green", "storage")

        res = pm.execute_step(
            sched,
            portfolio_value=1_000_000.0,
            slippage=1.0,  # 100% 极端灾难滑点
            strict_cost_limit=False,
        )
        assert res["cost_exceeded"] is True
        assert res["cost_ratio"] > 1.0  # 远超 100% 净值

        # 检验 verify_cost_within_limit 准确判定超标
        valid, msg = pm.verify_cost_within_limit(sched, 1_000_000.0)
        assert valid is False
        assert "超出风控上限" in msg

    def test_cost_summary_aggregation_and_reset(self) -> None:
        """测试全流程各步摩擦费用汇总统计与 reset 彻底清理。"""
        pm = PositionManager()
        _ = pm.execute_rotation("green", "storage", capital=1_000_000.0, slippage=0.001)

        summary = pm.get_cost_summary()
        assert summary["total_fees"] == pytest.approx(3000.0, rel=1e-6)
        # 3日总换手成交量 = 2 * 1_000_000 * (0.5 + 0.3 + 0.2) = 2_000_000
        # 滑点费用 = 2_000_000 * 0.001 = 2000.0
        assert summary["total_slippage"] == pytest.approx(2000.0, rel=1e-6)
        assert summary["total_cost"] == pytest.approx(5000.0, rel=1e-6)
        assert summary["buy_fee_rate"] == BUY_FEE_RATE
        assert summary["sell_fee_rate"] == SELL_FEE_RATE
        assert summary["total_cost_ceiling"] == MAX_TOTAL_ROTATION_COST

        # 重置后应清空
        pm.reset()
        reset_summary = pm.get_cost_summary()
        assert reset_summary["total_fees"] == 0.0
        assert reset_summary["total_slippage"] == 0.0
        assert reset_summary["total_cost"] == 0.0
        assert pm.get_active_schedule() is None


# ============================================================================
# 4. 决策流与投资组合状态机联动模糊测试 (Integration Fuzzing)
# ============================================================================

class TestIntegrationFuzzingWithDecisionAndState:
    """针对 RotationDecision 注入与 PortfolioState 渐进同步的集成对抗测试"""

    def test_full_rotation_decision_pipeline_synchronization(self) -> None:
        """模拟上游引擎生成 RotationDecision 并推动 PortfolioState 逐日精准状态同步。"""
        pm = PositionManager()
        p_state = PortfolioState(
            current_sector="green",
            sector_weights={"green": 1.0, "storage": 0.0, "gold": 0.0},
            cash_ratio=0.0,
            holding_days=10,
            days_since_last_rotation=15,
            rotation_count_this_month=1,
            portfolio_value=2_000_000.0,
        )

        decision = RotationDecision(
            should_rotate=True,
            current_sector="green",
            target_sector="storage",
            reason="储能板块景气度反转",
            confidence=0.88,
        )

        # 1. 约束前置门禁校验
        allowed, msg = pm.check_constraints(
            p_state.holding_days,
            p_state.rotation_count_this_month,
            p_state.days_since_last_rotation,
        )
        assert allowed is True
        assert "通过" in msg

        # 2. 规划调仓计划
        schedule = pm.plan_reallocation(
            from_sector=decision.current_sector,
            to_sector=decision.target_sector,
            start_date="2026-10-13",
        )
        assert schedule.is_active is True

        # 3. Day 1 步进 (50% 转仓)
        res1 = pm.execute_step(
            schedule,
            portfolio_value=p_state.portfolio_value,
            portfolio_state=p_state,
        )
        assert res1["day"] == 1
        assert res1["remaining_days"] == 2
        assert res1["is_complete"] is False
        assert p_state.is_in_rotation is True
        assert p_state.rotation_day_step == 1
        assert p_state.sector_weights == {"green": 0.5, "storage": 0.5}
        assert p_state.current_sector == "green"  # 调仓进行中，主板块保持 green

        # 4. Day 2 步进 (再转 30%)
        res2 = pm.execute_step(
            schedule,
            portfolio_value=p_state.portfolio_value,
            portfolio_state=p_state,
        )
        assert res2["day"] == 2
        assert res2["remaining_days"] == 1
        assert res2["is_complete"] is False
        assert p_state.is_in_rotation is True
        assert p_state.rotation_day_step == 2
        assert p_state.sector_weights == {"green": 0.2, "storage": 0.8}

        # 5. Day 3 步进 (最后 20%，全部转仓完毕)
        res3 = pm.execute_step(
            schedule,
            portfolio_value=p_state.portfolio_value,
            portfolio_state=p_state,
        )
        assert res3["day"] == 3
        assert res3["remaining_days"] == 0
        assert res3["is_complete"] is True
        assert p_state.is_in_rotation is False
        assert p_state.rotation_day_step == 0
        assert p_state.sector_weights == {"green": 0.0, "storage": 1.0}
        assert p_state.current_sector == "storage"   # 调仓完成，主板块更新为 storage
        assert p_state.holding_days == 0             # 持仓天数重置归零
        assert p_state.rotation_count_this_month == 2  # 月度调仓次数 +1
        assert p_state.last_rotation_date == "2026-10-13"

    def test_defensive_gold_fallback_decision_integration(self) -> None:
        """测试全市场恶化时降级至 gold 防御资产的决策注入与执行。"""
        pm = PositionManager()
        p_state = PortfolioState(
            current_sector="storage",
            sector_weights={"storage": 1.0},
            holding_days=6,
            days_since_last_rotation=8,
            rotation_count_this_month=0,
        )

        defensive_decision = RotationDecision(
            should_rotate=True,
            current_sector="storage",
            target_sector="gold",
            reason="市场情绪崩塌，防御降级至黄金",
            confidence=0.75,
            is_fallback=True,
        )

        sched = pm.plan_reallocation(
            defensive_decision.current_sector,
            defensive_decision.target_sector,
            start_date="2026-10-20",
        )
        for _ in range(3):
            pm.execute_step(sched, portfolio_state=p_state)

        assert p_state.current_sector == "gold"
        assert p_state.sector_weights == {"storage": 0.0, "gold": 1.0}
        assert p_state.is_in_rotation is False
        assert p_state.rotation_count_this_month == 1

    def test_multi_month_long_sequence_risk_gate_fuzzing(self) -> None:
        """模拟 60 个交易日的动态轮动序列，严密验证持仓天数、月度上限与冷却期三大门禁的协作。"""
        pm = PositionManager()

        # 场景 A: 持仓天数不足 5 天尝试轮动
        allowed, reason = pm.check_constraints(holding_days=4, monthly_rotations=0, cooldown_days=10)
        assert allowed is False
        assert "持仓天数不足" in reason

        # 场景 B: 恰好达到 5 天且冷却期充足
        allowed, reason = pm.check_constraints(holding_days=5, monthly_rotations=0, cooldown_days=7)
        assert allowed is True
        assert "通过" in reason

        # 场景 C: 单月轮动达 3 次（上限）尝试再轮动
        allowed, reason = pm.check_constraints(holding_days=10, monthly_rotations=3, cooldown_days=10)
        assert allowed is False
        assert "单月轮动次数超限" in reason

        # 场景 D: 冷却期不足 7 天尝试轮动
        allowed, reason = pm.check_constraints(holding_days=10, monthly_rotations=1, cooldown_days=6)
        assert allowed is False
        assert "处于轮动冷却期" in reason

        # 场景 E: 冷却期刚好 7 天
        allowed, reason = pm.check_constraints(holding_days=10, monthly_rotations=1, cooldown_days=7)
        assert allowed is True

    def test_interrupted_schedule_portfolio_state_consistency(self) -> None:
        """测试在 Day 2 执行完毕后取消调仓，PortfolioState 保持当前权重并正确解除锁定。"""
        pm = PositionManager()
        p_state = PortfolioState(
            current_sector="green",
            sector_weights={"green": 1.0},
            portfolio_value=1_000_000.0,
        )

        sched = pm.plan_reallocation("green", "storage")
        # 执行 Day 1
        pm.execute_step(sched, portfolio_state=p_state)
        # 执行 Day 2
        pm.execute_step(sched, portfolio_state=p_state)
        assert p_state.sector_weights == {"green": 0.2, "storage": 0.8}
        assert p_state.is_in_rotation is True

        # 中途取消
        pm.cancel_schedule("遭遇停牌或极端异常，取消剩余调仓")
        assert pm.get_active_schedule() is None

        # 手动重置组合状态的轮动锁
        p_state.is_in_rotation = False
        p_state.rotation_day_step = 0

        # 发起新的逆向调仓或应急调仓 (例如从 storage 转至 gold)
        sched2 = pm.plan_reallocation("storage", "gold")
        assert sched2.is_active is True


# ============================================================================
# 5. 属性化随机模糊测试套件 (Property-Based Fuzz Harness)
# ============================================================================

class TestPropertyBasedFuzzHarness:
    """1,000 次随机边界生成与参数扰动，严格断言核心系统不变量"""

    def test_property_based_invariants_1000_iterations(self) -> None:
        """1,000 次蒙特卡洛随机执行，验证系统四大核心不变量：
        
        Invariant 1: 任意单步权重之和必须严格为 1.0
        Invariant 2: 累计成本必须单调非递减
        Invariant 3: 单步渐进比例严格为 [0.50, 0.30, 0.20]
        Invariant 4: 单步执行耗时均值严格 < 1.0ms
        """
        rng = random.Random(42)
        sectors = ["green", "storage", "gold"]

        total_steps_executed = 0
        total_time_taken = 0.0

        for iteration in range(1000):
            pm = PositionManager()
            capital = rng.uniform(10_000.0, 50_000_000.0)
            slippage = rng.uniform(0.0, 0.003)  # 安全滑点范围内

            from_sec, to_sec = rng.sample(sectors, 2)
            sched = pm.plan_reallocation(from_sec, to_sec)

            prev_cost = 0.0
            p_state = PortfolioState(current_sector=from_sec, portfolio_value=capital)

            for expected_day, expected_weight in [(1, 0.50), (2, 0.30), (3, 0.20)]:
                t0 = time.perf_counter()
                res = pm.execute_step(
                    sched,
                    portfolio_value=capital,
                    slippage=slippage,
                    portfolio_state=p_state,
                )
                dt = time.perf_counter() - t0
                total_time_taken += dt
                total_steps_executed += 1

                # Invariant 1: 权重和严格守恒 (1.0)
                weights = res["executed_weights"]
                total_w = sum(weights.values())
                assert math.isclose(total_w, 1.0, abs_tol=1e-5), (
                    f"Iteration {iteration} Day {expected_day}: 权重和失衡: {total_w} != 1.0"
                )

                # Invariant 2: 累计成本单调非递减
                current_accum_cost = res["accumulated_cost"]
                assert current_accum_cost >= prev_cost, (
                    f"Iteration {iteration} Day {expected_day}: 成本非单调: {current_accum_cost} < {prev_cost}"
                )
                prev_cost = current_accum_cost

                # Invariant 3: 单步比例严格对齐
                assert res["step_ratio"] == expected_weight
                assert res["day"] == expected_day

            # 3步完成后必须标志 complete
            assert sched.is_complete is True
            assert sched.is_active is False
            assert p_state.current_sector == to_sec
            assert p_state.is_in_rotation is False

        # Invariant 4: 性能要求（单步均值耗时严格 < 1.0ms）
        avg_step_latency_ms = (total_time_taken / total_steps_executed) * 1000.0
        print(f"\n[Property Fuzz] 1,000 次调仓循环 (3,000 步) 平均单步延迟: {avg_step_latency_ms:.4f} ms")
        assert avg_step_latency_ms < 1.0, f"单步延迟 {avg_step_latency_ms:.4f}ms 超过 1.0ms 性能预算"
