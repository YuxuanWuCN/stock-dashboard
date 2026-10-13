# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_position_manager.py —— PositionManager 单元与风控测试套件

测试范围覆盖：
1. ReallocationSchedule 与 PortfolioState 数据结构完整性
2. 3日渐进式调仓调度（Day 1: 50%, Day 2: 30%, Day 3: 20%）
3. 交易摩擦成本建模与总费用约束（<= 1.0%）
4. 持仓期约束（< 5天阻断，>= 5天允许）
5. 单月频次上限（>= 3次阻断，< 3次允许）
6. 7日冷却期约束（< 7天阻断，>= 7天允许）
7. 调仓计划中断、取消、异常步进状态机流转
8. 滑点建模与极值超标检测
9. 与 PortfolioState 的动态状态联动
"""

from __future__ import annotations

import math
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


# ============================================================================
# 1. 数据结构测试
# ============================================================================

def test_reallocation_schedule_dataclass_initialization_and_properties() -> None:
    """测试 ReallocationSchedule 数据结构初始化、属性及序列化。"""
    schedule = ReallocationSchedule(
        from_sector="green",
        to_sector="storage",
        current_day=1,
        daily_weights=[0.50, 0.30, 0.20],
        is_active=True,
        accumulated_cost=0.0,
        start_date="2026-10-13",
    )
    assert schedule.from_sector == "green"
    assert schedule.to_sector == "storage"
    assert schedule.current_day == 1
    assert schedule.daily_weights == [0.50, 0.30, 0.20]
    assert schedule.is_active is True
    assert schedule.accumulated_cost == 0.0
    assert schedule.start_date == "2026-10-13"
    assert schedule.status == "active"
    assert schedule.is_complete is False
    assert schedule.remaining_days == 3

    # 字典序列化
    d = schedule.to_dict()
    assert d["from_sector"] == "green"
    assert d["to_sector"] == "storage"
    assert d["current_day"] == 1
    assert d["is_complete"] is False
    assert d["remaining_days"] == 3
    assert d["executed_steps_count"] == 0

    # 状态转换后的 is_complete 与 remaining_days
    schedule.current_day = 4
    schedule.is_active = False
    schedule.status = "completed"
    assert schedule.is_complete is True
    assert schedule.remaining_days == 0


def test_portfolio_state_dataclass_initialization_and_properties() -> None:
    """测试 PortfolioState 数据结构的默认值、赋值与权重查询。"""
    p_state = PortfolioState(
        current_sector="green",
        sector_weights={"green": 0.8, "storage": 0.2},
        cash_ratio=0.05,
        last_rotation_date="2026-10-01",
        rotation_count_this_month=1,
        is_in_rotation=True,
        rotation_day_step=2,
        holding_days=6,
        days_since_last_rotation=12,
        portfolio_value=1_500_000.0,
    )
    assert p_state.current_sector == "green"
    assert p_state.get_weight("green") == 0.8
    assert p_state.get_weight("storage") == 0.2
    assert p_state.get_weight("gold") == 0.0
    assert p_state.cash_ratio == 0.05
    assert p_state.portfolio_value == 1_500_000.0

    d = p_state.to_dict()
    assert d["current_sector"] == "green"
    assert d["sector_weights"]["green"] == 0.8
    assert d["holding_days"] == 6
    assert d["days_since_last_rotation"] == 12


# ============================================================================
# 2. PositionManager 初始化与风控规则校验
# ============================================================================

def test_position_manager_initialization_defaults_and_custom() -> None:
    """测试 PositionManager 默认与自定义参数初始化。"""
    mgr_default = PositionManager()
    assert mgr_default.buy_fee_rate == pytest.approx(BUY_FEE_RATE, abs=1e-6)
    assert mgr_default.sell_fee_rate == pytest.approx(SELL_FEE_RATE, abs=1e-6)
    assert mgr_default.total_cost_ceiling == pytest.approx(MAX_TOTAL_ROTATION_COST, abs=1e-6)
    assert mgr_default.min_holding_days == MIN_HOLDING_DAYS
    assert mgr_default.max_rotation_per_month == MAX_ROTATION_PER_MONTH
    assert mgr_default.cooldown_days == COOLDOWN_DAYS
    assert mgr_default.reallocation_weights == [0.50, 0.30, 0.20]

    mgr_custom = PositionManager(
        buy_fee_rate=0.001,
        sell_fee_rate=0.002,
        total_cost_ceiling=0.015,
        min_holding_days=3,
        max_rotation_per_month=5,
        cooldown_days=5,
        reallocation_weights=[0.60, 0.40],
    )
    assert mgr_custom.buy_fee_rate == 0.001
    assert mgr_custom.sell_fee_rate == 0.002
    assert mgr_custom.total_cost_ceiling == 0.015
    assert mgr_custom.min_holding_days == 3
    assert mgr_custom.max_rotation_per_month == 5
    assert mgr_custom.cooldown_days == 5
    assert mgr_custom.reallocation_weights == [0.60, 0.40]


def test_check_constraints_holding_days_boundaries() -> None:
    """测试持仓天数风控门禁（MIN_HOLDING_DAYS = 5）。"""
    mgr = PositionManager()

    # 边界阻断：holding_days < 5 (0, 1, 4)
    for d in [0, 1, 4]:
        allowed, reason = mgr.check_constraints(holding_days=d, monthly_rotations=0, cooldown_days=10)
        assert allowed is False
        assert "持仓天数不足" in reason
        assert f"当前 {d} 天" in reason

    # 边界放行：holding_days >= 5 (5, 6, 20)
    for d in [5, 6, 20]:
        allowed, reason = mgr.check_constraints(holding_days=d, monthly_rotations=0, cooldown_days=10)
        assert allowed is True
        assert "风控约束校验通过" in reason


def test_check_constraints_monthly_rotations_boundaries() -> None:
    """测试单月轮动频次上限风控门禁（MAX_ROTATION_PER_MONTH = 3）。"""
    mgr = PositionManager()

    # 边界放行：monthly_rotations < 3 (0, 1, 2)
    for r in [0, 1, 2]:
        allowed, reason = mgr.check_constraints(holding_days=6, monthly_rotations=r, cooldown_days=10)
        assert allowed is True
        assert "风控约束校验通过" in reason

    # 边界阻断：monthly_rotations >= 3 (3, 4, 10)
    for r in [3, 4, 10]:
        allowed, reason = mgr.check_constraints(holding_days=6, monthly_rotations=r, cooldown_days=10)
        assert allowed is False
        assert "单月轮动次数超限" in reason
        assert f"当前已轮动 {r} 次" in reason


def test_check_constraints_cooldown_days_boundaries() -> None:
    """测试调仓冷却期风控门禁（COOLDOWN_DAYS = 7）。"""
    mgr = PositionManager()

    # 边界阻断：cooldown_days < 7 (0, 3, 6)
    for c in [0, 3, 6]:
        allowed, reason = mgr.check_constraints(holding_days=6, monthly_rotations=1, cooldown_days=c)
        assert allowed is False
        assert "处于轮动冷却期" in reason
        assert f"距上次调仓仅 {c} 天" in reason

    # 边界放行：cooldown_days >= 7 (7, 8, 30)
    for c in [7, 8, 30]:
        allowed, reason = mgr.check_constraints(holding_days=6, monthly_rotations=1, cooldown_days=c)
        assert allowed is True
        assert "风控约束校验通过" in reason


# ============================================================================
# 3. 调仓计划规划（plan_reallocation）测试
# ============================================================================

def test_plan_reallocation_normal() -> None:
    """测试正常规划调仓计划。"""
    mgr = PositionManager()
    schedule = mgr.plan_reallocation("green", "storage", start_date="2026-10-15")
    assert schedule.from_sector == "green"
    assert schedule.to_sector == "storage"
    assert schedule.current_day == 1
    assert schedule.daily_weights == [0.50, 0.30, 0.20]
    assert schedule.is_active is True
    assert schedule.accumulated_cost == 0.0
    assert schedule.start_date == "2026-10-15"

    # get_active_schedule 能够正确返回
    active = mgr.get_active_schedule()
    assert active is schedule


def test_plan_reallocation_invalid_parameters_raise_value_error() -> None:
    """测试调仓规划传入空字符串或相同板块抛出 ValueError。"""
    mgr = PositionManager()

    with pytest.raises(ValueError, match="调仓起点或目标板块不可为空"):
        mgr.plan_reallocation("", "storage")

    with pytest.raises(ValueError, match="调仓起点或目标板块不可为空"):
        mgr.plan_reallocation("green", "  ")

    with pytest.raises(ValueError, match="调仓起点板块与目标板块相同"):
        mgr.plan_reallocation("green", "green")


def test_plan_reallocation_concurrent_active_raises_runtime_error() -> None:
    """测试存在活跃调仓时尝试并发创建新调仓抛出 RuntimeError。"""
    mgr = PositionManager()
    mgr.plan_reallocation("green", "storage")

    with pytest.raises(RuntimeError, match="已有进行中的调仓计划"):
        mgr.plan_reallocation("storage", "gold")


# ============================================================================
# 4. 3日渐进调仓执行与权重演变
# ============================================================================

def test_three_day_progressive_reallocation_execution_full_cycle() -> None:
    """测试完整的3日渐进调仓执行（Day 1: 50%, Day 2: 30%, Day 3: 20%）。"""
    mgr = PositionManager()
    capital = 1_000_000.0  # 100万总资产

    schedule = mgr.plan_reallocation("green", "storage", start_date="2026-10-15")

    # -------------------------------------------------------------
    # Day 1 步进 (50%)
    # -------------------------------------------------------------
    step1 = mgr.execute_step(schedule, portfolio_value=capital)
    assert step1["day"] == 1
    assert step1["step_ratio"] == 0.50
    assert step1["weight"] == 0.50
    assert step1["sell_volume"] == 500_000.0
    assert step1["buy_volume"] == 500_000.0
    # 费率：卖 0.175% (875), 买 0.125% (625) -> 总计 1500
    assert step1["sell_fee"] == pytest.approx(875.0, abs=1e-4)
    assert step1["buy_fee"] == pytest.approx(625.0, abs=1e-4)
    assert step1["cost"] == pytest.approx(1500.0, abs=1e-4)
    assert step1["accumulated_cost"] == pytest.approx(1500.0, abs=1e-4)
    assert step1["remaining_days"] == 2
    assert step1["is_complete"] is False
    # 权重转移：green: 50%, storage: 50%
    assert step1["executed_weights"]["green"] == 0.50
    assert step1["executed_weights"]["storage"] == 0.50
    assert schedule.current_day == 2
    assert schedule.is_active is True

    # -------------------------------------------------------------
    # Day 2 步进 (30%)
    # -------------------------------------------------------------
    step2 = mgr.execute_step(schedule, portfolio_value=capital)
    assert step2["day"] == 2
    assert step2["step_ratio"] == 0.30
    assert step2["sell_volume"] == 300_000.0
    assert step2["buy_volume"] == 300_000.0
    # 费率：卖 0.175% (525), 买 0.125% (375) -> 总计 900
    assert step2["sell_fee"] == pytest.approx(525.0, abs=1e-4)
    assert step2["buy_fee"] == pytest.approx(375.0, abs=1e-4)
    assert step2["cost"] == pytest.approx(900.0, abs=1e-4)
    assert step2["accumulated_cost"] == pytest.approx(2400.0, abs=1e-4)
    assert step2["remaining_days"] == 1
    assert step2["is_complete"] is False
    # 权重转移：green: 20%, storage: 80%
    assert step2["executed_weights"]["green"] == 0.20
    assert step2["executed_weights"]["storage"] == 0.80
    assert schedule.current_day == 3
    assert schedule.is_active is True

    # -------------------------------------------------------------
    # Day 3 步进 (20%)
    # -------------------------------------------------------------
    step3 = mgr.execute_step(schedule, portfolio_value=capital)
    assert step3["day"] == 3
    assert step3["step_ratio"] == 0.20
    assert step3["sell_volume"] == 200_000.0
    assert step3["buy_volume"] == 200_000.0
    # 费率：卖 0.175% (350), 买 0.125% (250) -> 总计 600
    assert step3["sell_fee"] == pytest.approx(350.0, abs=1e-4)
    assert step3["buy_fee"] == pytest.approx(250.0, abs=1e-4)
    assert step3["cost"] == pytest.approx(600.0, abs=1e-4)
    assert step3["accumulated_cost"] == pytest.approx(3000.0, abs=1e-4)
    assert step3["remaining_days"] == 0
    assert step3["is_complete"] is True
    # 权重转移：green: 0%, storage: 100%
    assert step3["executed_weights"]["green"] == 0.0
    assert step3["executed_weights"]["storage"] == 1.0

    # 调仓完成后的状态检查
    assert schedule.is_active is False
    assert schedule.status == "completed"
    assert mgr.get_active_schedule() is None
    assert len(schedule.executed_steps) == 3


def test_transaction_cost_ceiling_under_one_percent() -> None:
    """测试3日调仓总摩擦成本严格满足 <= 1.0% 风控硬顶。"""
    mgr = PositionManager()
    capital = 2_000_000.0

    # 连续执行完整轮动
    steps = mgr.execute_rotation("green", "storage", capital=capital)
    assert len(steps) == 3

    # 3天累计费用：
    # 50% * 2M * 0.003 + 30% * 2M * 0.003 + 20% * 2M * 0.003 = 2M * 0.0030 = 6,000 RMB
    total_cost = steps[-1]["accumulated_cost"]
    cost_ratio = total_cost / capital
    assert total_cost == pytest.approx(6000.0, abs=1e-4)
    assert cost_ratio == pytest.approx(0.0030, abs=1e-6)  # 0.30%
    assert cost_ratio <= MAX_TOTAL_ROTATION_COST          # <= 1.0%

    # 验证 verify_cost_within_limit
    is_valid, msg = mgr.verify_cost_within_limit(portfolio_value=capital)
    assert is_valid is True
    assert "符合风控上限" in msg


def test_slippage_modeling_and_cost_budget() -> None:
    """测试加入滑点建模后的调仓成本计算。"""
    mgr = PositionManager()
    capital = 1_000_000.0
    slippage = 0.001  # 单边千分之一滑点 (0.1%)

    schedule = mgr.plan_reallocation("storage", "gold")
    # Day 1: 500k sell + 500k buy = 1,000k turnover
    # fee = 1500, slippage = 1,000k * 0.001 = 1000 -> step cost = 2500
    s1 = mgr.execute_step(schedule, portfolio_value=capital, slippage=slippage)
    assert s1["fees"] == pytest.approx(1500.0, abs=1e-4)
    assert s1["slippage_cost"] == pytest.approx(1000.0, abs=1e-4)
    assert s1["cost"] == pytest.approx(2500.0, abs=1e-4)

    # Day 2: 300k sell + 300k buy = 600k turnover
    # fee = 900, slippage = 600k * 0.001 = 600 -> step cost = 1500
    s2 = mgr.execute_step(schedule, portfolio_value=capital, slippage=slippage)
    assert s2["fees"] == pytest.approx(900.0, abs=1e-4)
    assert s2["slippage_cost"] == pytest.approx(600.0, abs=1e-4)
    assert s2["cost"] == pytest.approx(1500.0, abs=1e-4)

    # Day 3: 200k sell + 200k buy = 400k turnover
    # fee = 600, slippage = 400k * 0.001 = 400 -> step cost = 1000
    s3 = mgr.execute_step(schedule, portfolio_value=capital, slippage=slippage)
    assert s3["fees"] == pytest.approx(600.0, abs=1e-4)
    assert s3["slippage_cost"] == pytest.approx(400.0, abs=1e-4)
    assert s3["cost"] == pytest.approx(1000.0, abs=1e-4)

    # 总成本：2500 + 1500 + 1000 = 5000 RMB (0.50% <= 1.0%)
    total_cost = s3["accumulated_cost"]
    assert total_cost == pytest.approx(5000.0, abs=1e-4)
    assert total_cost / capital <= MAX_TOTAL_ROTATION_COST


def test_cost_limit_exceeded_error_and_flag() -> None:
    """测试极端滑点下成本超出 1.0% 时 cost_exceeded 标记与严格模式异常。"""
    mgr = PositionManager()
    capital = 1_000_000.0
    extreme_slippage = 0.008  # 0.8% 单边滑点 -> turnover 200% * 0.8% = 1.6% 滑点

    schedule = mgr.plan_reallocation("green", "gold")

    # 非严格模式下记录 cost_exceeded 标记
    s1 = mgr.execute_step(schedule, portfolio_value=capital, slippage=extreme_slippage, strict_cost_limit=False)
    # Day 1: fee=1500 + slip=8000 = 9500 (0.95%)
    assert s1["cost_exceeded"] is False

    # Day 2: fee=900 + slip=4800 = 5700 -> 累计 15200 (1.52% > 1.0%)
    # 此时以 strict_cost_limit=True 执行应抛出 CostLimitExceededError
    with pytest.raises(CostLimitExceededError, match="超出风控上限"):
        mgr.execute_step(schedule, portfolio_value=capital, slippage=extreme_slippage, strict_cost_limit=True)


# ============================================================================
# 5. 计划取消与异常状态转换
# ============================================================================

def test_cancel_schedule_lifecycle() -> None:
    """测试调仓计划的主动取消流程。"""
    mgr = PositionManager()
    schedule = mgr.plan_reallocation("green", "storage")

    # 执行 Day 1
    mgr.execute_step(schedule, portfolio_value=1_000_000.0)
    assert schedule.current_day == 2
    assert schedule.is_active is True

    # 外部条件突变，取消调仓
    mgr.cancel_schedule(reason="行情突发黑天鹅，取消调仓")
    assert schedule.is_active is False
    assert schedule.status == "cancelled"
    assert schedule.cancellation_reason == "行情突发黑天鹅，取消调仓"
    assert mgr.get_active_schedule() is None

    # 取消后尝试继续执行步进应报错
    with pytest.raises(RuntimeError, match="调仓计划已非活跃状态"):
        mgr.execute_step(schedule)

    # 取消后可以重新规划新的调仓
    new_schedule = mgr.plan_reallocation("green", "gold")
    assert new_schedule.is_active is True
    assert mgr.get_active_schedule() is new_schedule


def test_invalid_day_transitions_and_edge_conditions() -> None:
    """测试无效天数步进与边界异常情况。"""
    mgr = PositionManager()

    # 无活跃计划调用 execute_step
    with pytest.raises(RuntimeError, match="当前无活跃的调仓计划可执行"):
        mgr.execute_step(None)

    # 资产净值非正
    schedule = mgr.plan_reallocation("green", "storage")
    with pytest.raises(ValueError, match="投资组合净值必须为正数"):
        mgr.execute_step(schedule, portfolio_value=0.0)

    # 天数越界
    schedule.current_day = 5
    with pytest.raises(RuntimeError, match="无效的调仓步进天数"):
        mgr.execute_step(schedule, portfolio_value=1_000_000.0)


# ============================================================================
# 6. PortfolioState 与外部权重的联动
# ============================================================================

def test_execute_step_with_custom_current_weights() -> None:
    """测试传入自定义现存权重时的调仓权重变动。"""
    mgr = PositionManager()
    schedule = mgr.plan_reallocation("green", "storage")

    # 假设初始权重 green 0.70, gold 0.30
    initial_weights = {"green": 0.70, "gold": 0.30, "storage": 0.0}

    # Day 1: 从 green 移出 0.50 给 storage
    step1 = mgr.execute_step(schedule, portfolio_value=1_000_000.0, current_weights=initial_weights)
    assert step1["executed_weights"]["green"] == pytest.approx(0.20, abs=1e-4)
    assert step1["executed_weights"]["storage"] == pytest.approx(0.50, abs=1e-4)
    assert step1["executed_weights"]["gold"] == pytest.approx(0.30, abs=1e-4)


def test_execute_step_portfolio_state_synchronization() -> None:
    """测试步进执行同步更新传入的 PortfolioState 实例。"""
    mgr = PositionManager()
    p_state = PortfolioState(
        current_sector="green",
        sector_weights={"green": 1.0, "storage": 0.0},
        holding_days=8,
        rotation_count_this_month=0,
    )

    schedule = mgr.plan_reallocation("green", "storage", start_date="2026-10-20")

    # 执行 Day 1
    mgr.execute_step(schedule, portfolio_value=1_000_000.0, portfolio_state=p_state)
    assert p_state.is_in_rotation is True
    assert p_state.rotation_day_step == 1
    assert p_state.sector_weights["green"] == 0.50
    assert p_state.sector_weights["storage"] == 0.50

    # 执行 Day 2
    mgr.execute_step(schedule, portfolio_value=1_000_000.0, portfolio_state=p_state)
    assert p_state.is_in_rotation is True
    assert p_state.rotation_day_step == 2
    assert p_state.sector_weights["green"] == 0.20
    assert p_state.sector_weights["storage"] == 0.80

    # 执行 Day 3 (调仓结束)
    mgr.execute_step(schedule, portfolio_value=1_000_000.0, portfolio_state=p_state)
    assert p_state.is_in_rotation is False
    assert p_state.rotation_day_step == 0
    assert p_state.current_sector == "storage"
    assert p_state.holding_days == 0
    assert p_state.rotation_count_this_month == 1
    assert p_state.last_rotation_date == "2026-10-20"
    assert p_state.sector_weights["green"] == 0.0
    assert p_state.sector_weights["storage"] == 1.0


# ============================================================================
# 7. 辅助方法与汇总清理测试
# ============================================================================

def test_calculate_transaction_cost_isolated_method() -> None:
    """测试独立的 calculate_transaction_cost 方法。"""
    mgr = PositionManager()

    # 100万，买卖均收
    cost_both = mgr.calculate_transaction_cost(1_000_000.0, is_buy=True, is_sell=True, slippage=0.0)
    assert cost_both == pytest.approx(1_000_000.0 * (BUY_FEE_RATE + SELL_FEE_RATE), abs=1e-4)

    # 仅买入
    cost_buy = mgr.calculate_transaction_cost(1_000_000.0, is_buy=True, is_sell=False)
    assert cost_buy == pytest.approx(1_000_000.0 * BUY_FEE_RATE, abs=1e-4)

    # 仅卖出
    cost_sell = mgr.calculate_transaction_cost(1_000_000.0, is_buy=False, is_sell=True)
    assert cost_sell == pytest.approx(1_000_000.0 * SELL_FEE_RATE, abs=1e-4)

    # 带滑点
    cost_slip = mgr.calculate_transaction_cost(1_000_000.0, is_buy=True, is_sell=True, slippage=0.0005)
    assert cost_slip == pytest.approx(1_000_000.0 * (BUY_FEE_RATE + SELL_FEE_RATE + 0.0005), abs=1e-4)

    # 负成交额报错
    with pytest.raises(ValueError, match="成交额不能为负数"):
        mgr.calculate_transaction_cost(-100.0)


def test_cost_summary_and_reset() -> None:
    """测试成本汇总字典及管理器状态重置。"""
    mgr = PositionManager()
    mgr.execute_rotation("green", "storage", capital=1_000_000.0, slippage=0.0005)

    summary = mgr.get_cost_summary()
    assert summary["total_fees"] == pytest.approx(3000.0, abs=1e-4)
    assert summary["total_slippage"] == pytest.approx(1000.0, abs=1e-4)
    assert summary["total_cost"] == pytest.approx(4000.0, abs=1e-4)
    assert summary["buy_fee_rate"] == pytest.approx(BUY_FEE_RATE, abs=1e-6)
    assert summary["sell_fee_rate"] == pytest.approx(SELL_FEE_RATE, abs=1e-6)
    assert summary["total_cost_ceiling"] == pytest.approx(MAX_TOTAL_ROTATION_COST, abs=1e-6)

    # 重置
    mgr.reset()
    assert mgr.get_active_schedule() is None
    reset_summary = mgr.get_cost_summary()
    assert reset_summary["total_fees"] == 0.0
    assert reset_summary["total_slippage"] == 0.0
    assert reset_summary["total_cost"] == 0.0


def test_cancel_schedule_when_none_active_is_noop() -> None:
    """测试在没有活跃调仓计划时调用 cancel_schedule 能够安全空转不报错。"""
    mgr = PositionManager()
    assert mgr.get_active_schedule() is None
    # 安全调用
    mgr.cancel_schedule(reason="无计划时取消测试")
    assert mgr.get_active_schedule() is None


def test_verify_cost_within_limit_exceeded_returns_false() -> None:
    """测试当调仓成本超出 1.0% 时 verify_cost_within_limit 返回 False。"""
    mgr = PositionManager()
    schedule = ReallocationSchedule(
        from_sector="green",
        to_sector="storage",
        accumulated_cost=15_000.0,  # 15,000 / 1,000,000 = 1.5% > 1.0%
        is_active=False,
        status="completed",
    )
    is_valid, msg = mgr.verify_cost_within_limit(schedule, portfolio_value=1_000_000.0)
    assert is_valid is False
    assert "超出风控上限" in msg
    assert "1.5000%" in msg


def test_execute_step_with_external_schedule_and_no_start_date() -> None:
    """测试使用独立 schedule 对象执行且无 start_date 时 portfolio_state 的联动。"""
    mgr = PositionManager()
    external_sched = ReallocationSchedule(
        from_sector="storage",
        to_sector="gold",
        current_day=3,
        daily_weights=[0.50, 0.30, 0.20],
        is_active=True,
        accumulated_cost=2400.0,
        start_date=None,  # 无起始日期
    )
    p_state = PortfolioState(
        current_sector="storage",
        last_rotation_date="2026-09-01",
    )

    res = mgr.execute_step(external_sched, portfolio_value=1_000_000.0, portfolio_state=p_state)
    assert res["is_complete"] is True
    assert external_sched.status == "completed"
    assert p_state.current_sector == "gold"
    # start_date 为 None 时，保留原有 last_rotation_date
    assert p_state.last_rotation_date == "2026-09-01"

