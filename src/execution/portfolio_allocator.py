# -*- coding: utf-8 -*-
"""src/execution/portfolio_allocator.py —— DynamicBetAllocator 差异化头寸与证据阶段阶梯配置器 (Week 10)

依据规范：
1. 《StockDashboard v3.0 & Serenity Chokepoint 12-Week Roadmap》Phase III: Week 10
2. 催化剂分类 (Bet Types):
   - Catalyst Alpha: 高频战术 Alpha 催化，动态止盈快速轮动 (基础仓位 10%)
   - Super Beta: 产业高景气长周期贝塔跟踪 (基础仓位 20%)
   - Event-Driven: 按证据阶段阶梯式非线性加仓 (Sampling 20% -> Batching 50% -> Mass Production 100%)
3. 与 Trend Gate (G_i in {0, 1}) 联动：G_i = 0 强制头寸归零
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from src.execution.trend_gate import TrendGateDecision

logger = logging.getLogger("portfolio_allocator")


class BetType(str, Enum):
    CATALYST_ALPHA = "Catalyst Alpha"
    SUPER_BETA = "Super Beta"
    EVENT_DRIVEN = "Event-Driven"


class EvidencePhase(str, Enum):
    SAMPLING = "Sampling"          # 样品验证阶段 (20% 额度)
    BATCHING = "Batching"          # 小批量试产阶段 (50% 额度)
    MASS_PRODUCTION = "Mass Production"  # 大规模量产落地 (100% 额度)


class MacroRegime(str, Enum):
    SUPER_BOOM = "Super Boom"    # 产业超级主升期 (仓位上限动态解锁至 45%)
    NORMAL = "Normal"            # 常态平衡期 (标准 30% 上限)
    RECESSION = "Recession"      # 衰退去库存期 (收紧至 15%)


@dataclass
class AllocationOrder:
    """最终头寸与委托指令。"""
    ticker: str
    bet_type: BetType
    evidence_phase: EvidencePhase
    trend_gate_open: bool
    target_weight_pct: float  # 最终目标仓位比例 [0.0, 1.0]
    allocated_capital_cny: float  # 分配绝对资金 (元)
    action_directive: str  # 'OPEN_BUY', 'HOLD', 'LIQUIDATE_ALL'
    rationale: str
    macro_regime: MacroRegime = MacroRegime.NORMAL


class DynamicBetAllocator:
    """差异化头寸分配器。"""

    EVIDENCE_MULTIPLIERS = {
        EvidencePhase.SAMPLING: 0.20,
        EvidencePhase.BATCHING: 0.50,
        EvidencePhase.MASS_PRODUCTION: 1.00
    }

    BASE_CAPACITY = {
        BetType.CATALYST_ALPHA: 0.12,  # 12% 基础上限
        BetType.SUPER_BETA: 0.25,      # 25% 基础上限
        BetType.EVENT_DRIVEN: 0.20     # 20% 基础上限 (受证据阶段调制)
    }

    REGIME_MULTIPLIERS = {
        MacroRegime.SUPER_BOOM: 1.45,
        MacroRegime.NORMAL: 1.00,
        MacroRegime.RECESSION: 0.60
    }

    REGIME_CEILINGS = {
        MacroRegime.SUPER_BOOM: 0.45,
        MacroRegime.NORMAL: 0.30,
        MacroRegime.RECESSION: 0.15
    }

    def __init__(self, total_portfolio_capital: float = 1_000_000.0):
        self.total_portfolio_capital = total_portfolio_capital

    def allocate_position(
        self,
        ticker: str,
        gfca_composite_score: float,
        trend_gate_decision: TrendGateDecision,
        bet_type: BetType = BetType.CATALYST_ALPHA,
        evidence_phase: EvidencePhase = EvidencePhase.MASS_PRODUCTION,
        market_temperature: float = 50.0,
        macro_regime: MacroRegime = MacroRegime.NORMAL
    ) -> AllocationOrder:
        """根据 GFCA 空间得分、Trend Gate 门禁、宏观体制与证据阶段计算目标头寸。"""
        # 1. 检查 Trend Gate: G_i = 0 触发强制清仓
        if not trend_gate_decision.gate_open:
            return AllocationOrder(
                ticker=ticker,
                bet_type=bet_type,
                evidence_phase=evidence_phase,
                macro_regime=macro_regime,
                trend_gate_open=False,
                target_weight_pct=0.0,
                allocated_capital_cny=0.0,
                action_directive="LIQUIDATE_ALL",
                rationale=f"Trend Gate 触发 C 浪阻断，强制将目标头寸归零并清仓退出。"
            )

        # 2. 计算基准分配比例
        base_cap = self.BASE_CAPACITY.get(bet_type, 0.10)
        
        # 根据 GFCA 得分线性调制 (得分 > 0.0 起配)
        score_multiplier = np.clip((gfca_composite_score + 0.20) / 1.0, 0.0, 1.2)
        
        # 根据证据阶段调制 (仅针对 Event-Driven)
        if bet_type == BetType.EVENT_DRIVEN:
            phase_multiplier = self.EVIDENCE_MULTIPLIERS.get(evidence_phase, 0.50)
        else:
            phase_multiplier = 1.0

        # 根据市场温度调制 (极寒 < 30℃ 折减 50%)
        temp_multiplier = 0.50 if market_temperature < 30.0 else (1.10 if market_temperature > 70.0 else 1.0)

        # 根据宏观/产业体制调制 (超级主升期 1.45 倍，上限突破至 45%；衰退期收紧至 15%)
        regime_mult = self.REGIME_MULTIPLIERS.get(macro_regime, 1.00)
        weight_ceiling = self.REGIME_CEILINGS.get(macro_regime, 0.30)

        raw_weight = base_cap * score_multiplier * phase_multiplier * temp_multiplier * regime_mult
        final_weight = float(np.clip(raw_weight, 0.0, weight_ceiling))
        allocated_capital = round(final_weight * self.total_portfolio_capital, 2)

        action = "OPEN_BUY" if final_weight > 0.02 else "HOLD"
        rationale = (
            f"GFCA={gfca_composite_score:.2f}, 催化类型={bet_type.value}, "
            f"证据阶段={evidence_phase.value} ({phase_multiplier*100:.0f}%), 体制={macro_regime.value}, "
            f"温度={market_temperature:.1f}℃ -> 权重 {final_weight*100:.1f}% (上限 {weight_ceiling*100:.0f}%)"
        )

        return AllocationOrder(
            ticker=ticker,
            bet_type=bet_type,
            evidence_phase=evidence_phase,
            macro_regime=macro_regime,
            trend_gate_open=True,
            target_weight_pct=final_weight,
            allocated_capital_cny=allocated_capital,
            action_directive=action,
            rationale=rationale
        )
