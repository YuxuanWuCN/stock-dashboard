"""src/analysis/thesis.py —— 信念-执行分离（005 融合 US4 / Graham 层）

对应师叔 claw-quant 的 Graham 层："预测错≠执行错"。
- Thesis（信念）：为什么看好/看空 + 预期差 + 失效条件。价格波动不改写信念，
  只有失效条件被触发才转 invalid（触发"信念再验证"）。
- Holdings（执行）：实际仓位 + 盯市价值。价格波动只更新盯市，不直接触发买卖。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Thesis:
    """信念（为什么看好/看空），与执行（holdings）分离。"""

    code: str
    name: str = ""
    core_logic: str = ""                     # 核心逻辑
    expectation_gap: str = ""                # 预期差（市场共识 vs 自己判断）
    invalidation_conditions: List[str] = field(default_factory=list)  # 失效条件
    status: str = "valid"                    # valid | review | invalid
    created_at: str = ""
    updated_at: str = ""
    history: List[dict] = field(default_factory=list)  # 再验证记录

    def __post_init__(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def revalidate(self, triggered_conditions: Optional[List[str]] = None) -> dict:
        """信念再验证：价格波动触发，但只核对失效条件。

        价格波动本身不改写信念内容；命中失效条件才转 review/invalid。
        """
        triggered = list(triggered_conditions or [])
        result = {
            "price_moved": True,
            "thesis_unchanged": True,
            "triggered": triggered,
            "status": self.status,
        }
        if triggered:
            self.status = "invalid"
            result["status"] = self.status
            result["thesis_unchanged"] = False
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        self.history.append({
            "ts": self.updated_at,
            "action": "revalidate",
            "triggered": triggered,
            "status": self.status,
        })
        return result

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "core_logic": self.core_logic,
            "expectation_gap": self.expectation_gap,
            "invalidation_conditions": self.invalidation_conditions,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class Holdings:
    """执行（实际仓位），与信念（thesis）分离。"""

    code: str
    weight: float = 0.0
    quantity: float = 0.0
    avg_cost: float = 0.0
    last_price: float = 0.0
    last_rebalance: str = ""

    @property
    def market_value(self) -> float:
        return self.quantity * self.last_price

    @property
    def unrealized_pnl_pct(self) -> Optional[float]:
        if self.avg_cost and self.avg_cost > 0:
            return (self.last_price - self.avg_cost) / self.avg_cost * 100.0
        return None

    def mark_to_market(self, price: float) -> dict:
        """价格波动只更新盯市价值，不触发任何信念改写。"""
        self.last_price = price
        return {
            "market_value": round(self.market_value, 2),
            "unrealized_pnl_pct": (
                round(self.unrealized_pnl_pct, 2)
                if self.unrealized_pnl_pct is not None
                else None
            ),
        }
