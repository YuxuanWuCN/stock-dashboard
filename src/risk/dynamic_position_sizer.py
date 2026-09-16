# -*- coding: utf-8 -*-
"""src/risk/dynamic_position_sizer.py —— 动态仓位管理器

核心功能：
1. 基于市场状态的仓位系数（BULL 加仓 / BEAR 减仓 / SIDEWAYS 中性）
2. 回撤惩罚机制（超过阈值后线性衰减，带指数代替方案）
3. 波动率自适应平滑调整（高波动降仓，低波动加仓，采用线性插值平滑过渡）

设计原则：
- 零前视偏差：只使用截至当前日期的历史数据
- 仓位限制：最终仓位限制在 [min_position, max_position] 范围内
- 参数可配置：所有阈值和系数通过 config dataclass 暴露
- 平滑处理：支持 EMA 平滑仓位变化，避免日间剧烈波动

参考：
- specs/contest-2026/spec.md §2.3 Trend Gate 风控机制增强
- 回撤惩罚公式：Kelly 准则的保守变体
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("dynamic_position_sizer")


@dataclass
class PositionSizerConfig:
    """动态仓位管理器配置参数。

    所有参数均为可调，支持通过配置对象注入。
    """
    # 基础仓位系数
    base_position: float = 1.0

    # 各市场状态的仓位倍数
    bull_multiplier: float = 1.2
    bear_multiplier: float = 0.6
    sideways_multiplier: float = 0.9

    # 回撤惩罚参数
    drawdown_threshold: float = 0.10          # 回撤超过此阈值开始惩罚
    drawdown_penalty_factor: float = 2.0       # 惩罚力度（线性斜率）
    drawdown_penalty_min: float = 0.5          # 最低惩罚值（防止过度惩罚）

    # 波动率调整参数
    volatility_high_threshold: float = 0.05    # 高于此值为高波动
    volatility_low_threshold: float = 0.02     # 低于此值为低波动
    volatility_high_adj: float = 0.8           # 高波动时的仓位调整系数
    volatility_low_adj: float = 1.1            # 低波动时的仓位调整系数

    # 仓位限制
    min_position: float = 0.3
    max_position: float = 2.0

    # 平滑参数（EMA alpha，0=不平滑）
    smoothing_alpha: float = 0.0

    # 是否使用指数衰减回撤惩罚（替代线性衰减）
    use_exponential_drawdown: bool = False
    exponential_drawdown_k: float = 3.0

    def validate(self) -> None:
        """参数合理性检查。"""
        assert 0.1 <= self.base_position <= 2.0, "base_position 应在 0.1-2.0 范围"
        assert 0.1 <= self.bull_multiplier <= 3.0, "bull_multiplier 应在 0.1-3.0 范围"
        assert 0.1 <= self.bear_multiplier <= 1.5, "bear_multiplier 应在 0.1-1.5 范围"
        assert 0.1 <= self.sideways_multiplier <= 1.5, "sideways_multiplier 应在 0.1-1.5 范围"
        assert 0.0 <= self.drawdown_threshold <= 0.50, "drawdown_threshold 应在 0.0-0.50 范围"
        assert 0.0 <= self.drawdown_penalty_min <= 1.0, "drawdown_penalty_min 应在 0.0-1.0 范围"
        assert 0.0 < self.volatility_high_adj <= 1.5, "volatility_high_adj 应在 0.0-1.5 范围"
        assert 0.0 < self.volatility_low_adj <= 2.0, "volatility_low_adj 应在 0.0-2.0 范围"
        assert 0.0 <= self.min_position < self.max_position <= 3.0, "仓位限制范围不合理"
        assert 0.0 <= self.smoothing_alpha < 1.0, "smoothing_alpha 应在 0.0-1.0 范围"


# 默认配置
DEFAULT_POSITION_CONFIG = PositionSizerConfig()

# 激进配置（牛市更高仓位，更弱惩罚）
AGGRESSIVE_POSITION_CONFIG = PositionSizerConfig(
    bull_multiplier=1.4,
    bear_multiplier=0.5,
    drawdown_penalty_min=0.6,
    max_position=2.5,
)

# 保守配置（更强调风控）
CONSERVATIVE_POSITION_CONFIG = PositionSizerConfig(
    bull_multiplier=1.1,
    bear_multiplier=0.5,
    sideways_multiplier=0.8,
    drawdown_threshold=0.08,
    drawdown_penalty_factor=2.5,
    drawdown_penalty_min=0.4,
    max_position=1.5,
)


class DynamicPositionSizer:
    """动态仓位管理器。

    根据市场状态（Regime）、当前回撤和波动率综合计算目标仓位系数。
    """

    def __init__(self, config: Optional[PositionSizerConfig] = None):
        """
        Parameters
        ----------
        config : Optional[PositionSizerConfig]
            仓位管理配置（若未提供则使用 DEFAULT_POSITION_CONFIG）
        """
        self.config = config or DEFAULT_POSITION_CONFIG
        self.config.validate()

        # 内部状态：用于 EMA 平滑
        self._last_position: Optional[float] = None
        self._position_history: List[Dict[str, Any]] = []

    def calculate_position(
        self,
        regime: str,
        current_drawdown: float,
        volatility: float,
    ) -> float:
        """计算当前仓位系数。

        Parameters
        ----------
        regime : str
            市场状态，'BULL' | 'BEAR' | 'SIDEWAYS'
        current_drawdown : float
            当前回撤，范围 [0.0, 1.0]（0.10 = 10% 回撤）
        volatility : float
            当前波动率，ATR/Price 比值

        Returns
        -------
        float
            仓位系数，范围 [min_position, max_position]
        """
        # 输入边界严格保护
        assert 0.0 <= current_drawdown <= 1.0, f"回撤值 ({current_drawdown}) 应在 0.0-1.0 范围"
        assert volatility >= 0.0, f"波动率 ({volatility}) 不能为负数"

        cfg = self.config

        # 1. 基于市场状态的基础仓位
        regime_upper = regime.upper().strip()
        if regime_upper == "BULL":
            base_pos = cfg.base_position * cfg.bull_multiplier
        elif regime_upper == "BEAR":
            base_pos = cfg.base_position * cfg.bear_multiplier
        elif regime_upper == "SIDEWAYS":
            base_pos = cfg.base_position * cfg.sideways_multiplier
        else:
            logger.warning(f"未知市场状态: {regime}，使用 SIDEWAYS 默认值")
            base_pos = cfg.base_position * cfg.sideways_multiplier

        # 2. 回撤惩罚
        drawdown_penalty = self._calculate_drawdown_penalty(current_drawdown, cfg)

        # 3. 波动率平滑调整
        volatility_adj = self._calculate_volatility_adjustment(volatility, cfg)

        # 4. 最终仓位
        position = base_pos * drawdown_penalty * volatility_adj
        position = float(np.clip(position, cfg.min_position, cfg.max_position))

        # 5. 可选：EMA 平滑（防止日间剧烈波动）
        if cfg.smoothing_alpha > 0.0 and self._last_position is not None:
            position = (
                cfg.smoothing_alpha * position
                + (1.0 - cfg.smoothing_alpha) * self._last_position
            )

        self._last_position = position

        # 记录仓位决策
        self._position_history.append({
            "regime": regime_upper,
            "drawdown": round(current_drawdown, 4),
            "volatility": round(volatility, 4),
            "base_position": round(base_pos, 4),
            "drawdown_penalty": round(drawdown_penalty, 4),
            "volatility_adj": round(volatility_adj, 4),
            "final_position": round(position, 4),
        })

        return position

    def _calculate_drawdown_penalty(
        self,
        drawdown: float,
        cfg: PositionSizerConfig,
    ) -> float:
        """计算回撤惩罚系数。"""
        if drawdown <= cfg.drawdown_threshold:
            return 1.0

        excess = drawdown - cfg.drawdown_threshold

        if cfg.use_exponential_drawdown:
            penalty = float(np.exp(-cfg.exponential_drawdown_k * excess))
        else:
            penalty = 1.0 - cfg.drawdown_penalty_factor * excess

        return float(max(penalty, cfg.drawdown_penalty_min))

    def _calculate_volatility_adjustment(
        self,
        volatility: float,
        cfg: PositionSizerConfig,
    ) -> float:
        """计算波动率调整系数。"""
        if volatility < cfg.volatility_low_threshold:
            return cfg.volatility_low_adj
        elif volatility >= cfg.volatility_high_threshold:
            return cfg.volatility_high_adj
        else:
            return 1.0

    def get_position_history(self) -> pd.DataFrame:
        """获取历史仓位记录。"""
        return pd.DataFrame(self._position_history)

    def reset_history(self) -> None:
        """重置内部历史状态。"""
        self._last_position = None
        self._position_history = []

    def reset(self) -> None:
        """重置内部历史状态（reset_history 别名）。"""
        self.reset_history()
