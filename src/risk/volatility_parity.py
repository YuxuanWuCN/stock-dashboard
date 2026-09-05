# -*- coding: utf-8 -*-
"""src/risk/volatility_parity.py —— 波动率反比平价 (IVW) 与极端回撤熔断风控引擎

学术理论依据：
- López de Prado, M. (2018). Advances in Financial Machine Learning. Wiley.
- Roncalli, T. (2013). Introduction to Risk Parity and Budgeting. Chapman and Hall/CRC.

核心目标：
1. 废除粗暴的 20% 静态等权分配机制；
2. 依据各标的的历史波动率或风险评分倒数分配持仓权重 (w_i ∝ 1 / σ_i)；
3. 施加单票权重上下限边界约束（高波科技股压制至 8%~12%，低波蓝筹放宽至 25%）；
4. 提供单日 -7% 自动化虚拟止损熔断机制，彻底防范单票跌停（如浪潮信息 -9.99%）击穿组合 Sharpe。
"""

from typing import Any, Dict, List, Optional, Tuple
import math
import numpy as np


class VolatilityParityOptimizer:
    """波动率反比平价 (Inverse Volatility Weighting) 优化器。"""

    def __init__(
        self,
        default_min_weight: float = 4.0,
        default_max_weight: float = 25.0,
        circuit_breaker_pct: float = -7.0,
    ):
        self.default_min_weight = default_min_weight
        self.default_max_weight = default_max_weight
        self.circuit_breaker_pct = circuit_breaker_pct

    def compute_weights(
        self,
        candidates: List[Dict[str, Any]],
        target_position_pct: float = 80.0,
        risk_profile: str = "conservative",
        custom_min_weight: Optional[float] = None,
        custom_max_weight: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """根据各标的风险/波动率倒数计算加权持仓，并严格满足上下限与总仓位约束。

        参数:
            candidates: 选中的标的列表，每个字典包含 'code', 'name', 'score', 'risk' (或 'volatility')
            target_position_pct: 权益类总仓位预算（如 80.0 表示股票仓位 80%，留 20% 现金）
            risk_profile: 策略风险偏好 ('aggressive', 'conservative', 'defensive', 'tech', 'global')
            custom_min_weight: 自定义单票最小权重 (%)
            custom_max_weight: 自定义单票最大权重 (%)

        返回:
            计算出 'weight_pct' 和 'amount' 的标的字典列表，总权重等于 target_position_pct
        """
        if not candidates:
            return []

        n = len(candidates)
        if n == 1:
            res = [dict(candidates[0])]
            res[0]["weight_pct"] = round(target_position_pct, 1)
            res[0]["amount"] = int(1000000 * target_position_pct / 100.0)
            return res

        # 确定单票上下限
        if custom_min_weight is not None:
            min_w = custom_min_weight
        else:
            min_w = 3.0 if risk_profile in ("aggressive", "tech") else 5.0

        if custom_max_weight is not None:
            max_w = custom_max_weight
        else:
            # 严格按照 A 方案：高波科技股压制在 10%~12% 封顶，蓝筹防御可放宽至 25%~30%
            if risk_profile in ("aggressive", "tech"):
                max_w = min(15.0, max(8.0, target_position_pct / max(n * 0.7, 1)))
            else:
                max_w = min(35.0, max(15.0, target_position_pct / max(n * 0.5, 1)))

        # 保证可行性约束：n * min_w <= target_position_pct <= n * max_w
        if n * min_w > target_position_pct:
            min_w = target_position_pct / n
        if n * max_w < target_position_pct:
            max_w = target_position_pct / n

        # 提取或代理波动率 σ_i
        vols = []
        for c in candidates:
            # 优先使用真实波动率 volatility_20d，其次使用 risk 分数映射
            v = c.get("volatility") or c.get("volatility_20d")
            if v is None:
                risk_score = float(c.get("risk", 40.0) or 40.0)
                # 将 0-100 的 risk_score 映射为年化波动率代理 (10% ~ 70%)
                v = max(10.0, risk_score)
            vols.append(max(float(v), 1.0))

        # 波动率倒数权重: w_raw = 1 / vol
        inv_vols = np.array([1.0 / v for v in vols], dtype=float)
        weights = (inv_vols / np.sum(inv_vols)) * target_position_pct

        # 迭代截断重分配算法 (Bounded Iterative Re-allocation)
        for _ in range(20):
            clipped = np.clip(weights, min_w, max_w)
            excess = target_position_pct - np.sum(clipped)
            if abs(excess) < 1e-4:
                weights = clipped
                break
            # 对未触及边界的元素按比例调整
            unconstrained = (clipped > min_w + 1e-4) & (clipped < max_w - 1e-4)
            if not np.any(unconstrained):
                weights = clipped
                break
            weights[unconstrained] += excess * (inv_vols[unconstrained] / np.sum(inv_vols[unconstrained]))
            weights = np.clip(weights, min_w, max_w)

        # 最终归一化微调
        total_assigned = np.sum(weights)
        if total_assigned > 0:
            weights = weights * (target_position_pct / total_assigned)

        out = []
        for i, c in enumerate(candidates):
            item = dict(c)
            w = round(float(weights[i]), 1)
            item["weight_pct"] = w
            item["pct"] = w  # 保持前端和组合文件兼容
            item["amount"] = int(1000000 * w / 100.0)
            item["weight_method"] = "inverse_volatility_parity"
            out.append(item)

        return out

    def check_circuit_breaker(
        self,
        current_holdings: List[Dict[str, Any]],
        today_changes: Dict[str, float],
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """单日极端跌幅虚拟熔断检查（Option A 规范）。

        当持仓标的单日跌幅 <= -7.0% 时触发熔断，保护组合不被单日跌停穿仓。

        返回:
            (has_triggered, triggered_items_list)
        """
        triggered = []
        for h in current_holdings:
            code = h.get("code")
            chg = today_changes.get(code)
            if chg is not None and float(chg) <= self.circuit_breaker_pct:
                triggered.append({
                    "code": code,
                    "name": h.get("name"),
                    "change_pct": chg,
                    "current_weight": h.get("pct") or h.get("weight_pct"),
                    "action": "virtual_stop_loss_triggered",
                    "reason": f"单日跌幅 {chg:.2f}% 击穿 {self.circuit_breaker_pct:.1f}% 熔断门槛，强制止损防穿仓",
                })

        return len(triggered) > 0, triggered


def calculate_inverse_volatility_weights(
    candidates: List[Dict[str, Any]],
    target_position_pct: float = 80.0,
    risk_profile: str = "conservative",
    custom_min_weight: Optional[float] = None,
    custom_max_weight: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """便捷公共接口：计算波动率反比平价持仓。"""
    optimizer = VolatilityParityOptimizer()
    return optimizer.compute_weights(
        candidates,
        target_position_pct=target_position_pct,
        risk_profile=risk_profile,
        custom_min_weight=custom_min_weight,
        custom_max_weight=custom_max_weight,
    )
