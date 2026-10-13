# -*- coding: utf-8 -*-
"""src/sector_rotation/position_manager.py —— Rainbow-FinGPT 渐进式调仓管理与风控模块

实现3日渐进式调仓执行调度（Day 1: 50%, Day 2: 30%, Day 3: 20%）、
交易摩擦与滑点成本建模（买入 0.125%, 卖出 0.175%, 总费用 <= 1.0%）、
以及持仓期（>= 5天）、单月频次（<= 3次）、冷却期（>= 7天）风控门禁。
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    BUY_FEE_RATE,
    COOLDOWN_DAYS,
    MAX_ROTATION_PER_MONTH,
    MAX_TOTAL_ROTATION_COST,
    MIN_HOLDING_DAYS,
    REALLOCATION_WEIGHTS,
    ROTATION_EXECUTION_DAYS,
    SECTORS,
    SELL_FEE_RATE,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 1. 异常定义
# ============================================================================

class CostLimitExceededError(ValueError):
    """调仓总交易摩擦或滑点成本超出风控上限（<= 1.0%）时抛出的异常。"""
    pass


# ============================================================================
# 2. 数据结构定义
# ============================================================================

@dataclass
class ReallocationSchedule:
    """板块渐进式调仓计划调度数据结构。

    Attributes:
        from_sector: 调仓转出板块代码/名称
        to_sector: 调仓转入板块代码/名称
        current_day: 当前执行交易日序号（1, 2, 或 3）
        daily_weights: 3日渐进调仓比例调度表，默认 [0.50, 0.30, 0.20]
        is_active: 调仓计划是否处于活跃/进行状态
        accumulated_cost: 截至当前步累计产生的交易摩擦与滑点总成本 (RMB)
        start_date: 调仓启动日期 (YYYY-MM-DD)，可选
        status: 计划当前生命周期状态 ('active', 'completed', 'cancelled')
        cancellation_reason: 取消原因（若被取消）
        executed_steps: 已执行步进详细记录列表
    """
    from_sector: str
    to_sector: str
    current_day: int = 1
    daily_weights: list[float] = field(default_factory=lambda: list(REALLOCATION_WEIGHTS))
    is_active: bool = True
    accumulated_cost: float = 0.0
    start_date: Optional[str] = None
    status: str = "active"
    cancellation_reason: Optional[str] = None
    executed_steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """调仓是否已完整执行完毕。"""
        return self.status == "completed" or (not self.is_active and self.current_day > len(self.daily_weights))

    @property
    def remaining_days(self) -> int:
        """剩余待执行交易日步数。"""
        if not self.is_active:
            return 0
        return max(0, len(self.daily_weights) - self.current_day + 1)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典表示。"""
        return {
            "from_sector": self.from_sector,
            "to_sector": self.to_sector,
            "current_day": self.current_day,
            "daily_weights": list(self.daily_weights),
            "is_active": self.is_active,
            "accumulated_cost": self.accumulated_cost,
            "start_date": self.start_date,
            "status": self.status,
            "cancellation_reason": self.cancellation_reason,
            "is_complete": self.is_complete,
            "remaining_days": self.remaining_days,
            "executed_steps_count": len(self.executed_steps),
        }


@dataclass
class PortfolioState:
    """投资组合全局持仓与轮动状态追踪。

    Attributes:
        current_sector: 当前核心重仓板块 ('green' | 'storage' | 'gold')
        sector_weights: 各板块实际权重分布，如 {'green': 0.5, 'storage': 0.5}
        cash_ratio: 现金资产比例，默认 0.0
        last_rotation_date: 最近一次完成调仓的日期 (YYYY-MM-DD)
        rotation_count_this_month: 当前自然月内已完成的轮动次数
        is_in_rotation: 当前是否正在执行渐进式调仓
        rotation_day_step: 当前调仓处于第几日步进 (1, 2, 3)
        holding_days: 当前板块已连续持仓交易日数
        days_since_last_rotation: 距上次调仓完成已过交易日数
        portfolio_value: 投资组合总资产净值 (RMB)
    """
    current_sector: str = ""
    sector_weights: dict[str, float] = field(default_factory=dict)
    cash_ratio: float = 0.0
    last_rotation_date: Optional[str] = None
    rotation_count_this_month: int = 0
    is_in_rotation: bool = False
    rotation_day_step: int = 0
    holding_days: int = 0
    days_since_last_rotation: int = 0
    portfolio_value: float = 1_000_000.0

    def get_weight(self, sector: str) -> float:
        """获取指定板块权重。"""
        return self.sector_weights.get(sector, 0.0)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典表示。"""
        return {
            "current_sector": self.current_sector,
            "sector_weights": dict(self.sector_weights),
            "cash_ratio": self.cash_ratio,
            "last_rotation_date": self.last_rotation_date,
            "rotation_count_this_month": self.rotation_count_this_month,
            "is_in_rotation": self.is_in_rotation,
            "rotation_day_step": self.rotation_day_step,
            "holding_days": self.holding_days,
            "days_since_last_rotation": self.days_since_last_rotation,
            "portfolio_value": self.portfolio_value,
        }


# ============================================================================
# 3. PositionManager 核心实现
# ============================================================================

class PositionManager:
    """渐进式调仓管理与风控执行引擎。

    核心职责：
    1. 规划3日渐进调仓调度（Day 1: 50%, Day 2: 30%, Day 3: 20%）。
    2. 交易摩擦成本（买0.125%，卖0.175%）与滑点建模，验证总成本不超过1.0%。
    3. 风控门禁校验：持仓期 >= 5天、单月频次 <= 3次、冷却期 >= 7天。
    4. 调仓计划生命周期管理（步进执行、取消、中途断言、成本汇总）。
    """

    def __init__(
        self,
        buy_fee_rate: float = BUY_FEE_RATE,
        sell_fee_rate: float = SELL_FEE_RATE,
        total_cost_ceiling: float = MAX_TOTAL_ROTATION_COST,
        min_holding_days: int = MIN_HOLDING_DAYS,
        max_rotation_per_month: int = MAX_ROTATION_PER_MONTH,
        cooldown_days: int = COOLDOWN_DAYS,
        reallocation_weights: Optional[list[float]] = None,
    ):
        """初始化 PositionManager。

        Args:
            buy_fee_rate: 买入交易费率，默认 0.00125 (0.125%)
            sell_fee_rate: 卖出交易费率，默认 0.00175 (0.175%)
            total_cost_ceiling: 单次轮动累计成本硬顶，默认 0.01 (1.0%)
            min_holding_days: 最短持仓交易日，默认 5
            max_rotation_per_month: 每月最大轮动次数，默认 3
            cooldown_days: 调仓冷却交易日，默认 7
            reallocation_weights: 每日渐进调仓比例，默认 [0.50, 0.30, 0.20]
        """
        self.buy_fee_rate: float = float(buy_fee_rate)
        self.sell_fee_rate: float = float(sell_fee_rate)
        self.total_cost_ceiling: float = float(total_cost_ceiling)
        self.min_holding_days: int = int(min_holding_days)
        self.max_rotation_per_month: int = int(max_rotation_per_month)
        self.cooldown_days: int = int(cooldown_days)
        self.reallocation_weights: list[float] = (
            [float(w) for w in reallocation_weights]
            if reallocation_weights is not None
            else list(REALLOCATION_WEIGHTS)
        )

        # 内部状态追踪
        self._active_schedule: Optional[ReallocationSchedule] = None
        self._schedule_history: list[ReallocationSchedule] = []
        self._total_fees_accumulated: float = 0.0
        self._total_slippage_accumulated: float = 0.0
        self._execution_records: list[dict[str, Any]] = []

    # ------------------------------------------------------------------------
    # 风控门禁校验
    # ------------------------------------------------------------------------

    def check_constraints(
        self,
        holding_days: int,
        monthly_rotations: int,
        cooldown_days: int,
    ) -> tuple[bool, str]:
        """校验持仓与轮动风控规则三门禁。

        门禁规则：
        1. holding_days < MIN_HOLDING_DAYS (5): 阻断（防止频繁调仓磨损）
        2. monthly_rotations >= MAX_ROTATION_PER_MONTH (3): 阻断（防止单月频繁换仓）
        3. cooldown_days < COOLDOWN_DAYS (7): 阻断（处于调仓强制冷却期）

        Args:
            holding_days: 当前板块已连续持仓交易日数
            monthly_rotations: 当前自然月已发生的轮动次数
            cooldown_days: 距上一次轮动完成已过去的交易日数

        Returns:
            (is_allowed, reason): 是否允许轮动及原因说明
        """
        if holding_days < self.min_holding_days:
            return False, f"持仓天数不足: 当前 {holding_days} 天，需至少 {self.min_holding_days} 个交易日"

        if monthly_rotations >= self.max_rotation_per_month:
            return False, f"单月轮动次数超限: 当前已轮动 {monthly_rotations} 次，上限为 {self.max_rotation_per_month} 次"

        if cooldown_days < self.cooldown_days:
            return False, f"处于轮动冷却期: 距上次调仓仅 {cooldown_days} 天，冷却期需 {self.cooldown_days} 个交易日"

        return True, "风控约束校验通过"

    # ------------------------------------------------------------------------
    # 交易摩擦与滑点成本计算
    # ------------------------------------------------------------------------

    def calculate_transaction_cost(
        self,
        turnover_volume: float,
        is_buy: bool = True,
        is_sell: bool = True,
        slippage: float = 0.0,
    ) -> float:
        """计算指定换手成交额下的总摩擦成本（买入费 + 卖出费 + 市场滑点）。

        Args:
            turnover_volume: 成交资金规模 (RMB)
            is_buy: 是否包含买入费用，默认 True
            is_sell: 是否包含卖出费用，默认 True
            slippage: 单边滑点费率，默认 0.0

        Returns:
            总交易摩擦成本 (RMB)
        """
        if turnover_volume < 0:
            raise ValueError(f"成交额不能为负数: {turnover_volume}")

        buy_fee = turnover_volume * self.buy_fee_rate if is_buy else 0.0
        sell_fee = turnover_volume * self.sell_fee_rate if is_sell else 0.0
        slippage_cost = turnover_volume * slippage if slippage > 0 else 0.0
        return buy_fee + sell_fee + slippage_cost

    # ------------------------------------------------------------------------
    # 调仓计划规划
    # ------------------------------------------------------------------------

    def plan_reallocation(
        self,
        from_sector: str,
        to_sector: str,
        start_date: Optional[str] = None,
    ) -> ReallocationSchedule:
        """规划并初始化新的3日渐进式调仓计划。

        Args:
            from_sector: 调出板块代码/名称
            to_sector: 调入板块代码/名称
            start_date: 调仓启动日期 (YYYY-MM-DD)，可选

        Returns:
            初始化的 ReallocationSchedule 计划对象

        Raises:
            ValueError: 当板块为空或起点与目标相同时抛出
            RuntimeError: 当已有未完成的活跃调仓计划时抛出
        """
        from_sec = str(from_sector).strip()
        to_sec = str(to_sector).strip()

        if not from_sec or not to_sec:
            raise ValueError(f"调仓起点或目标板块不可为空: from='{from_sector}', to='{to_sector}'")

        if from_sec == to_sec:
            raise ValueError(f"调仓起点板块与目标板块相同: '{from_sec}'，无需启动调仓")

        if self._active_schedule is not None and self._active_schedule.is_active:
            raise RuntimeError(
                f"已有进行中的调仓计划 ({self._active_schedule.from_sector} -> {self._active_schedule.to_sector}, "
                f"Day {self._active_schedule.current_day})，不可并发创建新的调仓"
            )

        schedule = ReallocationSchedule(
            from_sector=from_sec,
            to_sector=to_sec,
            current_day=1,
            daily_weights=list(self.reallocation_weights),
            is_active=True,
            accumulated_cost=0.0,
            start_date=start_date,
            status="active",
        )
        self._active_schedule = schedule
        return schedule

    # ------------------------------------------------------------------------
    # 单日步进执行
    # ------------------------------------------------------------------------

    def execute_step(
        self,
        schedule: Optional[ReallocationSchedule] = None,
        portfolio_value: float = 1_000_000.0,
        current_weights: Optional[dict[str, float]] = None,
        slippage: float = 0.0,
        strict_cost_limit: bool = False,
        portfolio_state: Optional[PortfolioState] = None,
    ) -> dict[str, Any]:
        """执行调仓计划的单日步进。

        执行逻辑：
        1. 读取当前步进天数（1, 2, 3）及对应权重比率（0.50, 0.30, 0.20）。
        2. 模拟计算卖出旧板块与买入新板块的摩擦费用和滑点。
        3. 累计调仓成本并检验是否超出风控上限（1.0%）。
        4. 计算执行后组合权重分布（渐进过渡）。
        5. 更新计划状态，若达到第3日则自动标记 completed 并归档。

        Args:
            schedule: 目标调仓计划，为 None 时使用当前活跃计划
            portfolio_value: 当前组合总资产规模 (RMB)，默认 1,000,000.0
            current_weights: 当前各板块权重字典，为 None 时按默认全额切换计算
            slippage: 单边市场滑点费率，默认 0.0
            strict_cost_limit: 若累计成本超 1.0% 是否强行抛出 CostLimitExceededError
            portfolio_state: 可选关联更新的 PortfolioState 对象

        Returns:
            步进执行结果字典，包含 executed_weights, cost, remaining_days, is_complete 等

        Raises:
            RuntimeError: 无活跃计划或计划处于非活跃/天数越界状态时抛出
            ValueError: 资产价值非正时抛出
            CostLimitExceededError: strict_cost_limit 为 True 且成本超过 1.0% 时抛出
        """
        target_schedule = schedule if schedule is not None else self._active_schedule
        if target_schedule is None:
            raise RuntimeError("当前无活跃的调仓计划可执行")

        if not target_schedule.is_active:
            raise RuntimeError(
                f"调仓计划已非活跃状态 (status='{target_schedule.status}')，无法继续执行调仓步进"
            )

        if (
            target_schedule.current_day < 1
            or target_schedule.current_day > len(target_schedule.daily_weights)
        ):
            raise RuntimeError(
                f"无效的调仓步进天数: Day {target_schedule.current_day} (总天数: {len(target_schedule.daily_weights)})"
            )

        if portfolio_value <= 0:
            raise ValueError(f"投资组合净值必须为正数: {portfolio_value}")

        day_idx = target_schedule.current_day - 1
        step_ratio = target_schedule.daily_weights[day_idx]

        # 调仓买卖规模与摩擦费用
        sell_volume = portfolio_value * step_ratio
        buy_volume = portfolio_value * step_ratio
        sell_fee = sell_volume * self.sell_fee_rate
        buy_fee = buy_volume * self.buy_fee_rate
        step_fees = sell_fee + buy_fee
        slippage_cost = (sell_volume + buy_volume) * slippage if slippage > 0 else 0.0
        step_cost = step_fees + slippage_cost

        new_accumulated_cost = target_schedule.accumulated_cost + step_cost
        cost_ratio = new_accumulated_cost / portfolio_value
        cost_exceeded = cost_ratio > self.total_cost_ceiling

        if strict_cost_limit and cost_exceeded:
            raise CostLimitExceededError(
                f"累计调仓成本 {new_accumulated_cost:.2f} (占净值 {cost_ratio:.4%}) "
                f"超出风控上限 {self.total_cost_ceiling:.2%} (上限额: {portfolio_value * self.total_cost_ceiling:.2f})"
            )

        # 计算执行后的持仓权重
        cum_weight = sum(target_schedule.daily_weights[: target_schedule.current_day])
        cum_weight = min(1.0, cum_weight)

        if current_weights is not None:
            executed_weights = dict(current_weights)
            from_w = executed_weights.get(target_schedule.from_sector, 1.0)
            executed_weights[target_schedule.from_sector] = max(
                0.0, round(from_w - step_ratio, 6)
            )
            to_w = executed_weights.get(target_schedule.to_sector, 0.0)
            executed_weights[target_schedule.to_sector] = round(to_w + step_ratio, 6)
        else:
            executed_weights = {
                target_schedule.from_sector: round(1.0 - cum_weight, 6),
                target_schedule.to_sector: round(cum_weight, 6),
            }

        is_complete = target_schedule.current_day >= len(target_schedule.daily_weights)
        remaining_days = max(
            0, len(target_schedule.daily_weights) - target_schedule.current_day
        )
        day_executed = target_schedule.current_day

        target_schedule.accumulated_cost = new_accumulated_cost

        step_result: dict[str, Any] = {
            "day": day_executed,
            "step_ratio": step_ratio,
            "weight": step_ratio,  # 兼容测试字典索引
            "sell_volume": sell_volume,
            "buy_volume": buy_volume,
            "sell_fee": sell_fee,
            "buy_fee": buy_fee,
            "fees": step_fees,
            "slippage_cost": slippage_cost,
            "cost": step_cost,
            "step_cost": step_cost,
            "accumulated_cost": new_accumulated_cost,
            "cost_ratio": cost_ratio,
            "cost_exceeded": cost_exceeded,
            "remaining_days": remaining_days,
            "is_complete": is_complete,
            "executed_weights": executed_weights,
            "weights": executed_weights,
            "from_sector": target_schedule.from_sector,
            "to_sector": target_schedule.to_sector,
        }

        target_schedule.executed_steps.append(step_result)
        self._execution_records.append(step_result)
        self._total_fees_accumulated += step_fees
        self._total_slippage_accumulated += slippage_cost

        # 同步更新 PortfolioState
        if portfolio_state is not None:
            portfolio_state.sector_weights = dict(executed_weights)
            portfolio_state.is_in_rotation = not is_complete
            portfolio_state.rotation_day_step = day_executed if not is_complete else 0
            if is_complete:
                portfolio_state.current_sector = target_schedule.to_sector
                portfolio_state.holding_days = 0
                portfolio_state.rotation_count_this_month += 1
                if target_schedule.start_date:
                    portfolio_state.last_rotation_date = target_schedule.start_date

        # 生命周期流转
        if is_complete:
            target_schedule.is_active = False
            target_schedule.status = "completed"
            self._schedule_history.append(target_schedule)
            if self._active_schedule is target_schedule:
                self._active_schedule = None
        else:
            target_schedule.current_day += 1

        return step_result

    # ------------------------------------------------------------------------
    # 查询与管理接口
    # ------------------------------------------------------------------------

    def get_active_schedule(self) -> Optional[ReallocationSchedule]:
        """获取当前正在执行中的活跃调仓计划。"""
        if self._active_schedule is not None and self._active_schedule.is_active:
            return self._active_schedule
        return None

    def cancel_schedule(self, reason: str = "User cancelled") -> None:
        """取消当前活跃调仓计划并记录取消原因。"""
        if self._active_schedule is not None and self._active_schedule.is_active:
            self._active_schedule.is_active = False
            self._active_schedule.status = "cancelled"
            self._active_schedule.cancellation_reason = str(reason)
            self._schedule_history.append(self._active_schedule)
            self._active_schedule = None
            logger.info("调仓计划已取消: %s", reason)

    def get_cost_summary(self) -> dict[str, float]:
        """获取累计交易摩擦与滑点成本统计摘要。"""
        total_cost = self._total_fees_accumulated + self._total_slippage_accumulated
        return {
            "total_fees": self._total_fees_accumulated,
            "total_slippage": self._total_slippage_accumulated,
            "total_cost": total_cost,
            "buy_fee_rate": self.buy_fee_rate,
            "sell_fee_rate": self.sell_fee_rate,
            "total_cost_ceiling": self.total_cost_ceiling,
        }

    def verify_cost_within_limit(
        self,
        schedule: Optional[ReallocationSchedule] = None,
        portfolio_value: float = 1_000_000.0,
    ) -> tuple[bool, str]:
        """检验指定调仓计划的累计成本是否符合 <= 1.0% 风控上限。

        Args:
            schedule: 调仓计划对象，为 None 时检测全局累计
            portfolio_value: 投资组合净值

        Returns:
            (is_valid, message): 是否符合上限及描述
        """
        target = schedule if schedule is not None else self._active_schedule
        cost = target.accumulated_cost if target is not None else (
            self._total_fees_accumulated + self._total_slippage_accumulated
        )
        ratio = cost / portfolio_value if portfolio_value > 0 else 0.0
        if ratio <= self.total_cost_ceiling:
            return True, f"调仓成本率 {ratio:.4%} 符合风控上限 (<= {self.total_cost_ceiling:.2%})"
        return False, f"调仓成本率 {ratio:.4%} 超出风控上限 ({self.total_cost_ceiling:.2%})"

    def execute_rotation(
        self,
        from_sector: str,
        to_sector: str,
        capital: float = 1_000_000.0,
        slippage: float = 0.0,
        start_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """连续模拟执行完整的3日渐进式调仓过程（便利封装方法）。"""
        schedule = self.plan_reallocation(from_sector, to_sector, start_date=start_date)
        results: list[dict[str, Any]] = []
        while schedule.is_active:
            step_res = self.execute_step(
                schedule, portfolio_value=capital, slippage=slippage
            )
            results.append(step_res)
        return results

    def reset(self) -> None:
        """重置 PositionManager 内部的所有状态和累计计数器。"""
        self._active_schedule = None
        self._schedule_history.clear()
        self._total_fees_accumulated = 0.0
        self._total_slippage_accumulated = 0.0
        self._execution_records.clear()
