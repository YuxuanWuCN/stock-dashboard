# -*- coding: utf-8 -*-
r"""src/portfolio/allocator.py —— 战略基准 + NALE 主动偏离的 FOF 资产配置器

依据《FOF 组合配置改造意见》§4.1 & §4.2：
\tilde w_{j,t} = w^{base}_{j,t} + \lambda_t \cdot g(S^{fund}_{j,t})

约束：
1. \sum_j w_{j,t} = 1.0 (全额归一，残差由防御资产吸收)
2. 0 <= w_{j,t} <= w_j^{max} (单标的硬上限)
3. \sum_{j \in satellite} w_{j,t} <= B_{satellite,t} (卫星总预算硬上限)
4. 单行业最大暴露约束与最低防御底仓约束
5. 当信号失效或均为负时，平稳退回基准，绝不强行加仓。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.portfolio.contracts import (
    AssetInfo,
    AssetRole,
    PointInTimeSignal,
    PortfolioWeights,
    RiskBudgetConfig,
    RiskState,
)

logger = logging.getLogger("portfolio.allocator")


@dataclass(frozen=True)
class AllocationConfig:
    """组合权重配置规则。"""
    base_defensive_weight: float = 0.50     # 战略防御底仓 (如 50% 纯债/现金)
    base_beta_weight: float = 0.30          # 战略核心 Beta (如 30% 沪深300ETF)
    base_satellite_budget: float = 0.20     # 战略卫星 Alpha 预算上限 (如 20%)
    signal_score_threshold: float = 0.0     # 卫星准入信号得分门槛 (高于此分才准入)
    score_power: float = 1.0                # 信号映射幂次 (线性为 1.0)


class FOFAllocator:
    """FOF 组合主动权重配置引擎。"""

    def __init__(
        self,
        assets: Dict[str, AssetInfo],
        alloc_config: Optional[AllocationConfig] = None,
        risk_config: Optional[RiskBudgetConfig] = None,
    ):
        self.assets = assets
        self.alloc_config = alloc_config or AllocationConfig()
        self.risk_config = risk_config or RiskBudgetConfig()

        # 区分资产角色
        self.defensive_tickers = [
            t for t, a in assets.items() if a.role == AssetRole.CORE_DEFENSIVE
        ]
        self.beta_tickers = [
            t for t, a in assets.items() if a.role == AssetRole.CORE_BETA
        ]
        self.satellite_tickers = [
            t for t, a in assets.items() if a.role == AssetRole.SATELLITE_ALPHA
        ]

        if not self.defensive_tickers:
            raise ValueError("组合必须至少包含一只 CORE_DEFENSIVE 防御底仓标的以作为流动性缓冲池")

    def _rank_standardize(
        self,
        signals: Dict[str, PointInTimeSignal],
        candidate_tickers: List[str],
    ) -> Dict[str, float]:
        """对候选卫星标的信号进行截面标准化与正向映射 g(S)。"""
        valid_scores: Dict[str, float] = {}
        for ticker in candidate_tickers:
            sig = signals.get(ticker)
            if sig is None or not sig.is_valid:
                continue
            if sig.score > self.alloc_config.signal_score_threshold:
                valid_scores[ticker] = sig.score * sig.confidence

        if not valid_scores:
            return {t: 0.0 for t in candidate_tickers}

        # 线性或幂次归一化正向主动偏离比例
        total_positive = sum(v ** self.alloc_config.score_power for v in valid_scores.values())
        if total_positive <= 1e-9:
            return {t: 0.0 for t in candidate_tickers}

        weights: Dict[str, float] = {}
        for t in candidate_tickers:
            if t in valid_scores:
                weights[t] = (valid_scores[t] ** self.alloc_config.score_power) / total_positive
            else:
                weights[t] = 0.0
        return weights

    def allocate(
        self,
        trade_date: str,
        signals: Dict[str, PointInTimeSignal],
        current_risk_state: RiskState = RiskState.NORMAL,
        effective_satellite_budget: Optional[float] = None,
        volatility_scale: float = 1.0,
    ) -> PortfolioWeights:
        """根据战略基准、点时信号、风险状态与预算执行带约束优化配置。"""
        active_constraints: List[str] = []

        # 1. 确定实际卫星可用预算 B_{satellite,t}
        if effective_satellite_budget is not None:
            max_sat_budget = min(effective_satellite_budget, self.risk_config.max_satellite_budget)
        else:
            if current_risk_state == RiskState.NORMAL:
                max_sat_budget = self.alloc_config.base_satellite_budget
            elif current_risk_state == RiskState.WATCH:
                max_sat_budget = self.alloc_config.base_satellite_budget * 0.60
                active_constraints.append("RiskState.WATCH: satellite budget shrunk to 60%")
            elif current_risk_state == RiskState.DEFENSIVE:
                max_sat_budget = self.alloc_config.base_satellite_budget * 0.20
                active_constraints.append("RiskState.DEFENSIVE: satellite budget shrunk to 20%")
            elif current_risk_state == RiskState.PROTECTIVE:
                max_sat_budget = 0.0
                active_constraints.append("RiskState.PROTECTIVE: satellite budget zeroed")
            else:
                max_sat_budget = self.alloc_config.base_satellite_budget

        # 波动率缩放对卫星仓与 Beta 仓的整体调缩
        if volatility_scale < 0.999:
            max_sat_budget *= volatility_scale
            active_constraints.append(f"VolatilityScale: shrunk to {volatility_scale:.3f}")

        # 2. 截面分配卫星仓位
        sat_rel_weights = self._rank_standardize(signals, self.satellite_tickers)
        tentative_satellite: Dict[str, float] = {}
        for t in self.satellite_tickers:
            tentative_satellite[t] = sat_rel_weights.get(t, 0.0) * max_sat_budget

        # 3. 校验并施加单标的上限与行业上限
        # 单标的截断
        clipped_satellite: Dict[str, float] = {}
        for t, w in tentative_satellite.items():
            asset_meta = self.assets[t]
            single_cap = min(asset_meta.max_weight, self.risk_config.max_single_satellite)
            if w > single_cap:
                clipped_satellite[t] = single_cap
                active_constraints.append(f"SingleCap[{t}]: clipped from {w:.4f} to {single_cap:.4f}")
            else:
                clipped_satellite[t] = w

        # 行业上限校验
        sector_usage: Dict[str, float] = {}
        for t, w in clipped_satellite.items():
            sec = self.assets[t].sector or "other"
            sector_usage[sec] = sector_usage.get(sec, 0.0) + w

        final_satellite: Dict[str, float] = {}
        for t, w in clipped_satellite.items():
            sec = self.assets[t].sector or "other"
            if sector_usage.get(sec, 0.0) > self.risk_config.max_sector_exposure:
                scale_factor = self.risk_config.max_sector_exposure / sector_usage[sec]
                final_satellite[t] = w * scale_factor
                active_constraints.append(f"SectorCap[{sec}]: scaled by {scale_factor:.4f}")
            else:
                final_satellite[t] = w

        total_satellite_used = sum(final_satellite.values())

        # 4. 核心 Beta 仓位分配 (经波动率缩放)
        tentative_beta: Dict[str, float] = {}
        target_beta_total = self.alloc_config.base_beta_weight * volatility_scale
        if self.beta_tickers:
            each_beta = target_beta_total / len(self.beta_tickers)
            for t in self.beta_tickers:
                cap = self.assets[t].max_weight
                w_b = min(each_beta, cap)
                tentative_beta[t] = w_b
        total_beta_used = sum(tentative_beta.values())

        # 5. 防御底仓与残差吸收：确保全部权重精准归一为 1.0
        allocated_so_far = total_satellite_used + total_beta_used
        defensive_budget = max(0.0, 1.0 - allocated_so_far)

        # 确保最低防御底仓硬约束
        if defensive_budget < self.risk_config.min_defensive_weight:
            active_constraints.append(
                f"MinDefensiveEnforced: defensive {defensive_budget:.4f} < {self.risk_config.min_defensive_weight}"
            )
            # 挤压卫星与 Beta 仓位
            excess = self.risk_config.min_defensive_weight - defensive_budget
            if total_satellite_used > 0:
                sat_cut = min(total_satellite_used, excess)
                for t in final_satellite:
                    final_satellite[t] *= (1.0 - sat_cut / total_satellite_used)
                excess -= sat_cut
                total_satellite_used = sum(final_satellite.values())
            if excess > 0 and total_beta_used > 0:
                beta_cut = min(total_beta_used, excess)
                for t in tentative_beta:
                    tentative_beta[t] *= (1.0 - beta_cut / total_beta_used)
                total_beta_used = sum(tentative_beta.values())
            defensive_budget = max(0.0, 1.0 - (total_satellite_used + total_beta_used))

        final_defensive: Dict[str, float] = {}
        each_def = defensive_budget / len(self.defensive_tickers)
        for t in self.defensive_tickers:
            final_defensive[t] = each_def

        # 汇总统配字典并消除浮点微小残差 (加到第一个防御资产上)
        all_weights: Dict[str, float] = {}
        for t in self.assets:
            all_weights[t] = (
                final_satellite.get(t, 0.0)
                + tentative_beta.get(t, 0.0)
                + final_defensive.get(t, 0.0)
            )

        sum_w = sum(all_weights.values())
        residual = 1.0 - sum_w
        primary_defensive = self.defensive_tickers[0]
        all_weights[primary_defensive] += residual

        result = PortfolioWeights(
            trade_date=trade_date,
            weights=all_weights,
            risk_state=current_risk_state,
            satellite_budget_used=total_satellite_used,
            volatility_scale=volatility_scale,
            active_constraints=active_constraints,
            cash_or_defensive_residual=all_weights[primary_defensive],
        )
        result.validate_weights()
        return result
