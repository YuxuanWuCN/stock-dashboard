# -*- coding: utf-8 -*-
"""src/sector_rotation/sector_rotation_engine.py —— 自适应板块轮动量化决策引擎

核心职责：
1. 监控持仓板块健康度：当主动板块情绪得分 < -0.3 且连续呈现下沉趋势 ('declining') 时触发轮动。
2. 候选目标板块动态选拔：筛选情绪得分 > 0.5 的候选板块，并基于多因子综合评分进行排名。
   多因子评分公式：score = 0.5*S + 0.2*T + 0.2*C - 0.1*sigma
3. 极端市场防御降级：当全市场情绪恶化（无候选板块满足 > 0.5 或全市场均为负情绪）时，自动降级至防御板块 ('gold')。若已在防御板块则保持持仓。
4. 交易风控与调仓约束门禁：严格执行最短持仓天数 (>= 5天)、单月轮动频次上限 (<= 3次) 及调仓冷却期 (7天)。
5. 纯量化快速路径执行：纯计算路径严格在 100ms 内完成（目标 < 5ms）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import (
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
from .utils.sector_utils import SectorState, validate_confidence


# ============================================================================
# 1. 轮动决策数据契约
# ============================================================================

@dataclass
class RotationDecision:
    """板块轮动决策契约
    
    支持 current_sector/target_sector 与 from_sector/to_sector 双向属性访问。
    """
    should_rotate: bool
    current_sector: str
    target_sector: Optional[str]
    reason: str
    confidence: float
    is_fallback: bool = False
    llm_rationale: Optional[str] = None
    execution_time_ms: float = 0.0
    timestamp: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    llm_validation: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        self.current_sector = str(self.current_sector).strip().lower()
        if self.target_sector is not None:
            self.target_sector = str(self.target_sector).strip().lower()
        self.confidence = validate_confidence(self.confidence)
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def from_sector(self) -> str:
        """兼容 from_sector 别名"""
        return self.current_sector

    @property
    def to_sector(self) -> Optional[str]:
        """兼容 to_sector 别名"""
        return self.target_sector

    def to_dict(self) -> Dict[str, Any]:
        """序列化为标准字典"""
        return {
            "should_rotate": self.should_rotate,
            "current_sector": self.current_sector,
            "target_sector": self.target_sector,
            "from_sector": self.from_sector,
            "to_sector": self.to_sector,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "is_fallback": self.is_fallback,
            "llm_rationale": self.llm_rationale,
            "execution_time_ms": round(self.execution_time_ms, 3),
            "timestamp": self.timestamp,
            "metrics": self.metrics,
            "llm_validation": self.llm_validation,
        }


# ============================================================================
# 2. 板块轮动决策引擎
# ============================================================================

class SectorRotationEngine:
    """自适应板块轮动量化决策引擎"""

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        decline_threshold: float = SENTIMENT_DECLINE_THRESHOLD,
        target_threshold: float = MIN_TARGET_SENTIMENT,
        min_holding_days: int = MIN_HOLDING_DAYS,
        max_monthly_rotations: int = MAX_ROTATION_PER_MONTH,
        cooldown_days: int = COOLDOWN_DAYS,
        defensive_sector: str = DEFENSIVE_SECTOR,
    ) -> None:
        """初始化轮动决策引擎。

        Args:
            weights: 综合评分多因子权重映射 (w_s, w_t, w_c, w_v)
            decline_threshold: 情绪下沉阈值 (默认 -0.3)
            target_threshold: 候选目标最低情绪要求 (默认 0.5)
            min_holding_days: 最短持仓交易日约束 (默认 5)
            max_monthly_rotations: 单月最大轮动次数 (默认 3)
            cooldown_days: 调仓冷却期 (默认 7)
            defensive_sector: 极端避险默认防御板块 (默认 "gold")
        """
        default_weights = {
            "w_s": 0.5,
            "w_t": 0.2,
            "w_c": 0.2,
            "w_v": 0.1,
        }
        if weights:
            default_weights.update(weights)
        self.weights = default_weights
        self.decline_threshold = float(decline_threshold)
        self.target_threshold = float(target_threshold)
        self.min_holding_days = int(min_holding_days)
        self.max_monthly_rotations = int(max_monthly_rotations)
        self.cooldown_days = int(cooldown_days)
        self.defensive_sector = str(defensive_sector).strip().lower()

    def calculate_composite_score(self, state: SectorState) -> float:
        """计算候选板块的多因子综合评分。

        评分公式（对齐 AGENT_TASK_ASSIGNMENT §1.3 及测试用例推导）：
        score = w_s * S + w_t * T + w_c * C - w_v * sigma
        其中：
        - S: sentiment_score
        - T: 趋势量化映射 (rising -> 0.3, stable -> 0.0, declining -> -0.3)
        - C: confidence
        - sigma: volatility (波动率风险惩罚)
        """
        trend_val = 0.0
        if state.sentiment_trend == TREND_RISING:
            trend_val = 0.3
        elif state.sentiment_trend == TREND_DECLINING:
            trend_val = -0.3

        s = float(state.sentiment_score)
        c = float(state.confidence)
        sigma = float(state.volatility)

        score = (
            self.weights["w_s"] * s
            + self.weights["w_t"] * trend_val
            + self.weights["w_c"] * c
            - self.weights["w_v"] * sigma
        )
        return float(score)

    def evaluate(
        self,
        current_sector: str,
        sector_states: Dict[str, SectorState],
        holding_days: int = 5,
        monthly_rotations: int = 0,
        days_since_last_rotation: int = 10,
        timestamp: str = "",
    ) -> RotationDecision:
        """评估当前板块并输出量化轮动决策。

        纯量化路径，严格保证在 100ms 内完成执行。

        Args:
            current_sector: 当前持仓板块标识 ('green' | 'storage' | 'gold')
            sector_states: 当前各板块状态字典
            holding_days: 当前板块已连续持仓交易日数
            monthly_rotations: 本月已发生轮动调仓次数
            days_since_last_rotation: 距上次轮动调仓间隔的交易日数
            timestamp: 决策生成时间戳（可选）

        Returns:
            RotationDecision 决策结果
        """
        t0 = time.perf_counter()
        curr_sec = str(current_sector).strip().lower()
        now_ts = timestamp or datetime.now().isoformat()

        # --------------------------------------------------------------------
        # 步骤 1: 交易风控与调仓门禁规则检查 (Risk Guardrails)
        # --------------------------------------------------------------------
        # 1.1 最短持仓交易日约束 (MIN_HOLDING_DAYS = 5)
        if holding_days < self.min_holding_days:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return RotationDecision(
                should_rotate=False,
                current_sector=curr_sec,
                target_sector=None,
                reason=f"Holding period too short ({holding_days} < {self.min_holding_days} trading days)",
                confidence=0.0,
                is_fallback=False,
                execution_time_ms=elapsed_ms,
                timestamp=now_ts,
                metrics={"holding_days": holding_days, "min_holding_days": self.min_holding_days},
            )

        # 1.2 单月最大轮动次数约束 (MAX_ROTATION_PER_MONTH = 3)
        if monthly_rotations >= self.max_monthly_rotations:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return RotationDecision(
                should_rotate=False,
                current_sector=curr_sec,
                target_sector=None,
                reason=f"Monthly rotation cap reached ({monthly_rotations} >= {self.max_monthly_rotations})",
                confidence=0.0,
                is_fallback=False,
                execution_time_ms=elapsed_ms,
                timestamp=now_ts,
                metrics={"monthly_rotations": monthly_rotations, "max_monthly_rotations": self.max_monthly_rotations},
            )

        # 1.3 调仓冷却期约束 (COOLDOWN_DAYS = 7)
        if days_since_last_rotation < self.cooldown_days:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return RotationDecision(
                should_rotate=False,
                current_sector=curr_sec,
                target_sector=None,
                reason=f"Cooldown active ({days_since_last_rotation} < {self.cooldown_days} trading days)",
                confidence=0.0,
                is_fallback=False,
                execution_time_ms=elapsed_ms,
                timestamp=now_ts,
                metrics={"days_since_last_rotation": days_since_last_rotation, "cooldown_days": self.cooldown_days},
            )

        # --------------------------------------------------------------------
        # 步骤 2: 当前持仓板块健康度评估与下沉触发判定 (Decline Trigger)
        # --------------------------------------------------------------------
        if curr_sec not in sector_states:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return RotationDecision(
                should_rotate=False,
                current_sector=curr_sec,
                target_sector=None,
                reason=f"Current sector '{curr_sec}' missing from sector states",
                confidence=0.0,
                is_fallback=False,
                execution_time_ms=elapsed_ms,
                timestamp=now_ts,
            )

        curr_state = sector_states[curr_sec]

        # 下沉触发严格条件：得分严格 < -0.3 且趋势确认为 'declining'
        # 边界条件：得分恰好为 -0.3000 不触发 (B7)
        is_declining = (
            curr_state.sentiment_score < self.decline_threshold
            and curr_state.sentiment_trend == TREND_DECLINING
        )

        if not is_declining:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return RotationDecision(
                should_rotate=False,
                current_sector=curr_sec,
                target_sector=None,
                reason=f"Current sector '{curr_sec}' is healthy (score={curr_state.sentiment_score:.4f}, trend='{curr_state.sentiment_trend}')",
                confidence=curr_state.confidence,
                is_fallback=False,
                execution_time_ms=elapsed_ms,
                timestamp=now_ts,
                metrics={
                    "current_score": curr_state.sentiment_score,
                    "current_trend": curr_state.sentiment_trend,
                },
            )

        # --------------------------------------------------------------------
        # 步骤 3: 候选目标板块筛选与多因子评分 (Target Candidate Selection)
        # --------------------------------------------------------------------
        # 排除当前持仓板块
        other_candidates = {
            k: v for k, v in sector_states.items()
            if k.strip().lower() != curr_sec
        }

        # 候选板块最低门槛：得分严格 > 0.5 (B8)
        eligible_candidates = {
            k: v for k, v in other_candidates.items()
            if v.sentiment_score > self.target_threshold
        }

        # --------------------------------------------------------------------
        # 步骤 4: 存在达标候选板块 -> 多因子排序选拔最优
        # --------------------------------------------------------------------
        if eligible_candidates:
            candidate_scores: Dict[str, float] = {}
            for k, v in eligible_candidates.items():
                candidate_scores[k] = self.calculate_composite_score(v)

            # 选取综合评分最高的候选板块
            best_candidate = max(
                candidate_scores.keys(),
                key=lambda k: (
                    candidate_scores[k],
                    eligible_candidates[k].sentiment_score,
                    eligible_candidates[k].confidence,
                ),
            )
            best_state = eligible_candidates[best_candidate]

            # 边界判定：若目标板块与当前板块相同，则为 noop (B10)
            if best_candidate == curr_sec:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                return RotationDecision(
                    should_rotate=False,
                    current_sector=curr_sec,
                    target_sector=curr_sec,
                    reason="Target sector is identical to current sector (noop)",
                    confidence=best_state.confidence,
                    is_fallback=False,
                    execution_time_ms=elapsed_ms,
                    timestamp=now_ts,
                )

            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return RotationDecision(
                should_rotate=True,
                current_sector=curr_sec,
                target_sector=best_candidate,
                reason=(
                    f"Current sector '{curr_sec}' sentiment declined ({curr_state.sentiment_score:.2f}, {curr_state.sentiment_trend}); "
                    f"rotating to candidate '{best_candidate}' (score={best_state.sentiment_score:.2f}, composite={candidate_scores[best_candidate]:.4f})"
                ),
                confidence=best_state.confidence,
                is_fallback=False,
                execution_time_ms=elapsed_ms,
                timestamp=now_ts,
                metrics={
                    "current_score": curr_state.sentiment_score,
                    "target_score": best_state.sentiment_score,
                    "candidate_scores": candidate_scores,
                },
            )

        # --------------------------------------------------------------------
        # 步骤 5: 无合格候选板块 -> 防御资产降级 (Defensive Fallback)
        # --------------------------------------------------------------------
        # 当全市场情绪均处于负面区间，或没有其他板块能突破 0.5 景气阈值时，退守防御资产
        defensive_sec = self.defensive_sector

        # 若当前持仓已在防御资产板块，则维持现有持仓，不触发重复轮动 (B10)
        if curr_sec == defensive_sec:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return RotationDecision(
                should_rotate=False,
                current_sector=curr_sec,
                target_sector=defensive_sec,
                reason=f"Market degraded; already holding defensive sector '{defensive_sec}'",
                confidence=curr_state.confidence,
                is_fallback=True,
                execution_time_ms=elapsed_ms,
                timestamp=now_ts,
            )

        def_state = sector_states.get(defensive_sec)
        def_confidence = def_state.confidence if def_state else 0.80

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return RotationDecision(
            should_rotate=True,
            current_sector=curr_sec,
            target_sector=defensive_sec,
            reason=(
                f"Market sentiment degraded (no candidate sentiment score > {self.target_threshold}); "
                f"defensive fallback triggered to '{defensive_sec}'"
            ),
            confidence=def_confidence,
            is_fallback=True,
            execution_time_ms=elapsed_ms,
            timestamp=now_ts,
            metrics={"fallback_target": defensive_sec},
        )

    def decide(
        self,
        sector_sentiments: Dict[str, SectorState],
        current_sector: str = "",
        portfolio_state: Any = None,
        holding_days: int = 5,
        monthly_rotations: int = 0,
        days_since_last_rotation: int = 10,
        timestamp: str = "",
    ) -> RotationDecision:
        """兼容适配层方法，支持多形式传参。"""
        eff_current = current_sector
        eff_holding_days = holding_days
        eff_monthly_rotations = monthly_rotations
        eff_days_since_last_rotation = days_since_last_rotation

        if portfolio_state is not None:
            if hasattr(portfolio_state, "current_sector") and portfolio_state.current_sector:
                eff_current = portfolio_state.current_sector
            if hasattr(portfolio_state, "holding_days"):
                eff_holding_days = portfolio_state.holding_days
            if hasattr(portfolio_state, "rotation_count_this_month"):
                eff_monthly_rotations = portfolio_state.rotation_count_this_month
            if hasattr(portfolio_state, "days_since_last_rotation"):
                eff_days_since_last_rotation = portfolio_state.days_since_last_rotation

        return self.evaluate(
            current_sector=eff_current,
            sector_states=sector_sentiments,
            holding_days=eff_holding_days,
            monthly_rotations=eff_monthly_rotations,
            days_since_last_rotation=eff_days_since_last_rotation,
            timestamp=timestamp,
        )
