# src/core/math/alpha_gate.py
"""
Rainbow-FinGPT v4.0 核心数学底层 —— 双重一票否决代码门禁 (One-Vote Veto Code Gate)
Statistical Alpha Gate with Dual Hurdle (p-value < 0.05 and Information Ratio >= 0.30)
and Division-by-Zero Safety Safeguard.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional
import math


@dataclass
class GateEvaluationResult:
    """门禁评估决策实体"""
    symbol: str
    p_value: float
    information_ratio: float
    p_hurdle_passed: bool
    ir_hurdle_passed: bool
    veto_passed: bool
    rejection_reason: Optional[str] = None


class AlphaStatisticalGate:
    """
    双重硬门禁 (Dual Hurdle):
    1. 统计显著性门槛: p_value < p_threshold (默认 0.05)
    2. 风险调整信息比率门槛: IR >= ir_threshold (默认 0.30)
    
    任意一项不达标，坚决执行 100% 一票否决 (Veto)，拦截伪 Alpha 与噪音炒作。
    """
    
    def __init__(self, p_threshold: float = 0.05, ir_threshold: float = 0.30):
        self.p_threshold = float(p_threshold)
        self.ir_threshold = float(ir_threshold)

    def evaluate(
        self,
        symbol: str,
        alpha: float,
        sigma_eps: float,
        p_value: float
    ) -> GateEvaluationResult:
        """
        执行统计门禁校验。
        包含对 NaN / Inf 异常与残差方差为 0 的严密防护。
        """
        # 异常值防护
        if math.isnan(p_value) or math.isinf(p_value):
            return GateEvaluationResult(
                symbol=symbol,
                p_value=1.0,
                information_ratio=0.0,
                p_hurdle_passed=False,
                ir_hurdle_passed=False,
                veto_passed=False,
                rejection_reason="Invalid p-value (NaN or Inf)"
            )
            
        # 除零保护: sigma(eps) <= 1e-9 则强制 IR = 0.0
        if math.isnan(sigma_eps) or sigma_eps <= 1e-9:
            ir = 0.0
        else:
            ir = float(alpha) / float(sigma_eps)
            
        if math.isnan(ir) or math.isinf(ir):
            ir = 0.0
            
        p_passed = bool(p_value < self.p_threshold)
        ir_passed = bool(ir >= self.ir_threshold)
        veto_passed = p_passed and ir_passed
        
        reason = None
        if not veto_passed:
            reasons = []
            if not p_passed:
                reasons.append(f"p-value {p_value:.4f} >= {self.p_threshold:.2f}")
            if not ir_passed:
                reasons.append(f"IR {ir:.4f} < {self.ir_threshold:.2f}")
            reason = "Rejected: " + "; ".join(reasons)
            
        return GateEvaluationResult(
            symbol=symbol,
            p_value=p_value,
            information_ratio=ir,
            p_hurdle_passed=p_passed,
            ir_hurdle_passed=ir_passed,
            veto_passed=veto_passed,
            rejection_reason=reason
        )
