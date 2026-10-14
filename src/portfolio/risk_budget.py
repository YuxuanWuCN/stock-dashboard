# -*- coding: utf-8 -*-
r"""src/portfolio/risk_budget.py —— FOF 风险预算与动态回撤状态机

依据《FOF 组合配置改造意见》§4.3：
1. 组合波动率目标风险缩放：
   w_t^{risk} = w_t \cdot \min(1, \frac{\sigma^*}{\hat\sigma_{p,t} + \epsilon})
2. 分层触发式最大回撤状态机：
   - NORMAL: MaxDD < 5%
   - WATCH: 5% <= MaxDD < 8%
   - DEFENSIVE: 8% <= MaxDD < 10%
   - PROTECTIVE: MaxDD >= 10% (保护状态，停止新增风险仓，全额防御底仓)
3. 恢复确认机制：防范单日脉冲假恢复导致反复假开仓。
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.portfolio.contracts import (
    RiskBudgetConfig,
    RiskState,
)

logger = logging.getLogger("portfolio.risk_budget")


class RiskBudgetManager:
    """组合风险预算与分层回撤状态机管理器。"""

    def __init__(self, config: Optional[RiskBudgetConfig] = None):
        self.config = config or RiskBudgetConfig()
        self.current_state = RiskState.NORMAL
        self.peak_nav = 1.0
        self.recovery_counter = 0

    def compute_volatility_scale(
        self,
        historical_returns: List[float],
        epsilon: float = 1e-6,
    ) -> float:
        """根据历史滚动日收益率估计年化波动率并计算缩放因子。"""
        lookback = self.config.vol_lookback_days
        if len(historical_returns) < max(5, lookback // 2):
            return 1.0

        recent_returns = historical_returns[-lookback:]
        daily_vol = float(np.std(recent_returns, ddof=1))
        annualized_vol = daily_vol * math.sqrt(252.0)

        if annualized_vol <= 1e-4:
            return 1.0

        target_vol = self.config.target_volatility
        scale = min(1.0, target_vol / (annualized_vol + epsilon))
        return float(np.clip(scale, 0.1, 1.0))

    def update_risk_state(
        self,
        current_nav: float,
    ) -> Tuple[RiskState, float, float]:
        """根据最新净值更新历史最高峰、回撤深度并推进状态机。

        返回: (当前判定状态, 当前回撤深度, 历史最高净值)
        """
        if current_nav > self.peak_nav:
            self.peak_nav = current_nav

        drawdown = max(0.0, (self.peak_nav - current_nav) / (self.peak_nav + 1e-9))

        # 分层阈值候选
        th_watch = self.config.dd_threshold_watch
        th_def = self.config.dd_threshold_defensive
        th_prot = self.config.dd_threshold_protective

        target_tier: RiskState
        if drawdown >= th_prot:
            target_tier = RiskState.PROTECTIVE
        elif drawdown >= th_def:
            target_tier = RiskState.DEFENSIVE
        elif drawdown >= th_watch:
            target_tier = RiskState.WATCH
        else:
            target_tier = RiskState.NORMAL

        # 状态降级逻辑 (更危险): 立即响应，绝不延迟
        risk_severity = {
            RiskState.NORMAL: 0,
            RiskState.WATCH: 1,
            RiskState.DEFENSIVE: 2,
            RiskState.PROTECTIVE: 3,
        }

        if risk_severity[target_tier] > risk_severity[self.current_state]:
            self.current_state = target_tier
            self.recovery_counter = 0
            logger.info(
                f"[RiskState Demotion] DD={drawdown:.2%} -> Transition to {self.current_state.value}"
            )
        # 状态升级逻辑 (企稳恢复): 必须持续满足 recovery_confirmation_days 天
        elif risk_severity[target_tier] < risk_severity[self.current_state]:
            self.recovery_counter += 1
            if self.recovery_counter >= self.config.recovery_confirmation_days:
                logger.info(
                    f"[RiskState Promotion Confirmed] DD={drawdown:.2%} -> Recovered to {target_tier.value}"
                )
                self.current_state = target_tier
                self.recovery_counter = 0
        else:
            self.recovery_counter = 0

        return self.current_state, drawdown, self.peak_nav

    def reset(self, initial_nav: float = 1.0) -> None:
        """重置状态机为初始干净状态。"""
        self.current_state = RiskState.NORMAL
        self.peak_nav = initial_nav
        self.recovery_counter = 0
