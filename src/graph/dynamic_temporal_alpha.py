# -*- coding: utf-8 -*-
"""src/graph/dynamic_temporal_alpha.py —— 双波峰时空时滞共振扩散参数 α(t, τ, σ) 动力学模型。

数学公式：
α(t; τ, σ, H) = clip(α_base + f_sentiment(t) + f_physical(t), α_min, α_max)

其中：
1. α_base = 0.20 (无事件平稳期的背景网络协同强度)
2. f_sentiment(t) = α_sentiment * 2^(-t / H_sentiment) (首发事件冲击情绪指数衰减分量, H=3d)
3. f_physical(t) = α_physical * exp(- (t - τ)^2 / (2 * σ^2)) (物理流转时滞到货高斯共振分量)
4. 截断区间：[α_min, α_max] = [0.05, 0.75]，保证 (1 - α) ∈ [0.25, 0.95] 具有严格有界凸组合性。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

import numpy as np

# 默认全局先验参数基线
DEFAULT_ALPHA_BASE: float = 0.20
DEFAULT_ALPHA_SENTIMENT: float = 0.35
DEFAULT_ALPHA_PHYSICAL: float = 0.35
DEFAULT_SENTIMENT_HALF_LIFE: float = 3.0  # 交易日
DEFAULT_ALPHA_MIN: float = 0.05
DEFAULT_ALPHA_MAX: float = 0.75


@dataclass(frozen=True)
class AlphaBreakdown:
    """动态扩散参数分解构成。"""
    t_days: float
    tau_days: float
    sigma_days: float
    alpha_base: float
    f_sentiment: float
    f_physical: float
    alpha_raw: float
    alpha_clipped: float
    is_at_sentiment_peak: bool
    is_at_physical_peak: bool
    is_in_verification_valley: bool


class DynamicTemporalAlpha:
    """双波峰时空时滞共振扩散参数 α(t, τ, σ) 计算引擎。"""

    def __init__(
        self,
        alpha_base: float = DEFAULT_ALPHA_BASE,
        alpha_sentiment: float = DEFAULT_ALPHA_SENTIMENT,
        alpha_physical: float = DEFAULT_ALPHA_PHYSICAL,
        sentiment_half_life: float = DEFAULT_SENTIMENT_HALF_LIFE,
        alpha_min: float = DEFAULT_ALPHA_MIN,
        alpha_max: float = DEFAULT_ALPHA_MAX,
    ):
        self.alpha_base = float(alpha_base)
        self.alpha_sentiment = float(alpha_sentiment)
        self.alpha_physical = float(alpha_physical)
        self.sentiment_half_life = max(1e-3, float(sentiment_half_life))
        self.alpha_min = float(alpha_min)
        self.alpha_max = float(alpha_max)

    def compute_alpha(
        self,
        t: float,
        tau: float,
        sigma: float,
        has_limit_up_or_event: bool = True
    ) -> float:
        r"""计算连续时域时间 t 时的网络扩散强度 α(t)。
        
        参数:
            t: 距离冲击/催化事件发生以来的交易日数 (连续变量, t >= 0)
            tau: 产业链物理流转先验时滞均值 (如存储 20d, 锂电 35d, 算力 28d)
            sigma: 产业链物理流转不确定性方差 (如存储 5d, 锂电 8d)
            has_limit_up_or_event: 是否存在冲击催化事件 (若无事件，退化为基准稳态 α_base)
            
        返回:
            alpha: 截断在 [alpha_min, alpha_max] 内的实数
        """
        if not has_limit_up_or_event:
            return float(np.clip(self.alpha_base, self.alpha_min, self.alpha_max))

        t_val = max(0.0, float(t))
        tau_val = max(0.1, float(tau))
        sigma_val = max(0.5, float(sigma))

        # 1. 情绪衰减分量
        f_sent = self.alpha_sentiment * (2.0 ** (-t_val / self.sentiment_half_life))

        # 2. 物理流转到货高斯共振分量
        diff = t_val - tau_val
        exponent = - (diff * diff) / (2.0 * sigma_val * sigma_val)
        # 保护下溢
        f_phys = self.alpha_physical * math.exp(max(-50.0, exponent))

        raw_alpha = self.alpha_base + f_sent + f_phys
        return float(np.clip(raw_alpha, self.alpha_min, self.alpha_max))

    def compute_alpha_trajectory(
        self,
        time_grid: Union[List[float], np.ndarray],
        tau: float,
        sigma: float,
        has_limit_up_or_event: bool = True
    ) -> np.ndarray:
        """向量化计算连续时间网格上的 α(t) 动力学轨迹。"""
        grid = np.maximum(0.0, np.asarray(time_grid, dtype=np.float64))
        if not has_limit_up_or_event:
            return np.full_like(grid, np.clip(self.alpha_base, self.alpha_min, self.alpha_max))

        tau_val = max(0.1, float(tau))
        sigma_val = max(0.5, float(sigma))

        # 情绪分量
        f_sent = self.alpha_sentiment * (2.0 ** (-grid / self.sentiment_half_life))

        # 物理分量
        diff = grid - tau_val
        exponent = - (diff * diff) / (2.0 * sigma_val * sigma_val)
        exponent = np.maximum(-50.0, exponent)
        f_phys = self.alpha_physical * np.exp(exponent)

        raw_alpha = self.alpha_base + f_sent + f_phys
        return np.clip(raw_alpha, self.alpha_min, self.alpha_max)

    def get_alpha_breakdown(
        self,
        t: float,
        tau: float,
        sigma: float,
        has_limit_up_or_event: bool = True
    ) -> AlphaBreakdown:
        """获取各分量明细及状态标识，用于可解释性白盒追溯。"""
        t_val = max(0.0, float(t))
        tau_val = max(0.1, float(tau))
        sigma_val = max(0.5, float(sigma))

        if not has_limit_up_or_event:
            val = float(np.clip(self.alpha_base, self.alpha_min, self.alpha_max))
            return AlphaBreakdown(
                t_days=t_val,
                tau_days=tau_val,
                sigma_days=sigma_val,
                alpha_base=self.alpha_base,
                f_sentiment=0.0,
                f_physical=0.0,
                alpha_raw=self.alpha_base,
                alpha_clipped=val,
                is_at_sentiment_peak=False,
                is_at_physical_peak=False,
                is_in_verification_valley=True,
            )

        f_sent = float(self.alpha_sentiment * (2.0 ** (-t_val / self.sentiment_half_life)))
        diff = t_val - tau_val
        f_phys = float(self.alpha_physical * math.exp(max(-50.0, - (diff * diff) / (2.0 * sigma_val * sigma_val))))
        raw = self.alpha_base + f_sent + f_phys
        clipped = float(np.clip(raw, self.alpha_min, self.alpha_max))

        is_sent_peak = bool(t_val <= 1.0)
        is_phys_peak = bool(abs(t_val - tau_val) <= sigma_val * 0.5)
        # 处于两波峰之间的验证休整谷底
        is_valley = bool(t_val > 2.0 * self.sentiment_half_life and (tau_val - t_val) > sigma_val)

        return AlphaBreakdown(
            t_days=t_val,
            tau_days=tau_val,
            sigma_days=sigma_val,
            alpha_base=self.alpha_base,
            f_sentiment=f_sent,
            f_physical=f_phys,
            alpha_raw=raw,
            alpha_clipped=clipped,
            is_at_sentiment_peak=is_sent_peak,
            is_at_physical_peak=is_phys_peak,
            is_in_verification_valley=is_valley,
        )


# 单例全局引擎实例
_default_dynamic_alpha_engine = DynamicTemporalAlpha()


def compute_temporal_alpha(
    t: float,
    tau: float,
    sigma: float,
    has_event: bool = True
) -> float:
    """快捷入口：计算瞬时 α(t)。"""
    return _default_dynamic_alpha_engine.compute_alpha(t, tau, sigma, has_event)
