# -*- coding: utf-8 -*-
"""tests/test_dynamic_temporal_alpha.py —— 双波峰时空时滞共振扩散参数 α(t, τ, σ) 单元测试套件。

涵盖数学定理：
1. 有界凸组合性定理：任意 t >= 0，0.05 <= α(t) <= 0.75，谱半径恒定平稳；
2. 首发事件冲击情绪峰值与快速指数衰减；
3. 产业链物理流转时滞 (t = τ) 高斯共振波峰；
4. 估值验证休整谷底 (0 < t < τ)；
5. 长时渐近收敛性定理：t -> ∞ 时 lim α(t) = α_base；
6. 无事件平稳期退化定理；
7. 向量化轨迹推演与标量点态计算严格数值对齐；
8. 异常边界输入健壮性 (负数、0、极端方差)。
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from src.graph.dynamic_temporal_alpha import (
    AlphaBreakdown,
    DynamicTemporalAlpha,
    compute_temporal_alpha,
)


def test_bounded_convexity_theorem():
    """定理 1：有界凸组合性检验。在任意时点 t，α(t) 必须严格落在 [0.05, 0.75] 内。"""
    engine = DynamicTemporalAlpha(alpha_min=0.05, alpha_max=0.75)
    time_points = np.linspace(0.0, 150.0, 301)
    
    for tau in [14.0, 20.0, 35.0]:
        for sigma in [3.0, 5.0, 8.0]:
            alphas = engine.compute_alpha_trajectory(time_points, tau=tau, sigma=sigma)
            assert np.all(alphas >= 0.05), "α(t) 不得低于 α_min = 0.05"
            assert np.all(alphas <= 0.75), "α(t) 不得高于 α_max = 0.75"
            # 凸组合余量
            one_minus_alpha = 1.0 - alphas
            assert np.all(one_minus_alpha >= 0.25)
            assert np.all(one_minus_alpha <= 0.95)


def test_two_stage_dual_peaks_and_valley():
    """定理 2：双峰与洗盘休整谷底形态检验。
    
    半导体存储链：tau = 20d, sigma = 5d, H = 3d。
    应满足：
    1. 首发冲击峰值：alpha(0) 达到高位 (~0.55)；
    2. 快速衰减：alpha(3) < alpha(0)；
    3. 检验休整谷底：在 t = 9d 处 alpha(9) 出现局部低谷；
    4. 物理到货共振峰：在 t = 20d 处再次脉冲放大，alpha(20) > alpha(9)；
    5. 物理峰对称性与衰退：alpha(20) > alpha(35)。
    """
    engine = DynamicTemporalAlpha()
    tau = 20.0
    sigma = 5.0

    a_0 = engine.compute_alpha(t=0.0, tau=tau, sigma=sigma)
    a_1 = engine.compute_alpha(t=1.0, tau=tau, sigma=sigma)
    a_3 = engine.compute_alpha(t=3.0, tau=tau, sigma=sigma)
    a_9 = engine.compute_alpha(t=9.0, tau=tau, sigma=sigma)
    a_20 = engine.compute_alpha(t=20.0, tau=tau, sigma=sigma)
    a_35 = engine.compute_alpha(t=35.0, tau=tau, sigma=sigma)

    # 1. 首发峰值在 0.55 左右 (0.20 + 0.35 = 0.55)
    assert abs(a_0 - 0.55) < 0.01, f"t=0 理论值应为 0.55，实际为 {a_0}"
    assert a_0 > a_1 > a_3, "情绪分量必须严格单调衰减"

    # 2. t = 9d 应处于休整谷底 (此时情绪已衰减 3 个半衰期，物理传导相距 11d 尚未到达)
    assert a_9 < a_3, "谷底阶段扩散应低于衰减初期"
    assert a_9 < 0.30, f"谷底扩散强度应回落至 0.30 以下，实际为 {a_9}"

    # 3. t = 20d (tau) 必须形成明显的物理到货共振二次峰
    assert a_20 > a_9, "tau 天物理流转到达时，网络共振必须显著超越谷底"
    assert abs(a_20 - 0.55) < 0.02, f"t=tau 理论值应接近 0.55，实际为 {a_20}"

    # 4. 超过 tau 后物理冲击退去
    assert a_20 > a_35, "共振峰过后必须回落"


def test_asymptotic_convergence_theorem():
    """定理 3：长时渐近收敛性。t -> ∞ 时，系统平滑收敛回 α_base = 0.20。"""
    engine = DynamicTemporalAlpha(alpha_base=0.20)
    tau = 20.0
    sigma = 5.0

    # 考察远期时点
    a_60 = engine.compute_alpha(t=60.0, tau=tau, sigma=sigma)
    a_100 = engine.compute_alpha(t=100.0, tau=tau, sigma=sigma)

    assert abs(a_60 - 0.20) < 0.01, "远离物理时滞后应迅速回落基线"
    assert abs(a_100 - 0.20) < 1e-4, "远期应完全收敛至 0.20 基准稳态"


def test_no_event_degradation_theorem():
    """定理 4：无突发催化事件时的退化定理。没有事件时，α 恒定退化为 α_base。"""
    engine = DynamicTemporalAlpha(alpha_base=0.20)
    
    # has_limit_up_or_event = False
    for t in [0.0, 5.0, 20.0, 50.0]:
        val = engine.compute_alpha(t=t, tau=20.0, sigma=5.0, has_limit_up_or_event=False)
        assert val == 0.20, f"无事件时应退化为 0.20，实际为 {val}"


def test_vectorized_trajectory_exact_alignment():
    """验证向量化轨迹计算与逐点标量计算的严格数值对齐 (精度 1e-12)。"""
    engine = DynamicTemporalAlpha()
    grid = np.array([0.0, 0.5, 1.0, 3.0, 7.5, 14.0, 20.0, 25.0, 40.0])
    tau = 20.0
    sigma = 5.0

    vec_res = engine.compute_alpha_trajectory(grid, tau=tau, sigma=sigma)
    scalar_res = np.array([engine.compute_alpha(float(t), tau=tau, sigma=sigma) for t in grid])

    np.testing.assert_allclose(vec_res, scalar_res, rtol=1e-12, atol=1e-12)


def test_breakdown_and_explainability():
    """可解释性白盒状态分解测试。"""
    engine = DynamicTemporalAlpha()
    tau = 20.0
    sigma = 5.0

    # 1. 检验 t = 0 (首发情绪峰)
    b0 = engine.get_alpha_breakdown(t=0.0, tau=tau, sigma=sigma)
    assert b0.is_at_sentiment_peak is True
    assert b0.is_at_physical_peak is False
    assert b0.is_in_verification_valley is False
    assert b0.f_sentiment == 0.35

    # 2. 检验 t = 9 (休整谷底)
    b9 = engine.get_alpha_breakdown(t=9.0, tau=tau, sigma=sigma)
    assert b9.is_at_sentiment_peak is False
    assert b9.is_at_physical_peak is False
    assert b9.is_in_verification_valley is True
    assert b9.alpha_clipped < 0.30

    # 3. 检验 t = 20 (物理到货峰)
    b20 = engine.get_alpha_breakdown(t=20.0, tau=tau, sigma=sigma)
    assert b20.is_at_sentiment_peak is False
    assert b20.is_at_physical_peak is True
    assert b20.is_in_verification_valley is False
    assert abs(b20.f_physical - 0.35) < 1e-5


def test_edge_and_robustness_inputs():
    """边界值与健壮性测试：负数、极大极小输入不会抛出异常。"""
    engine = DynamicTemporalAlpha()

    # 负数 t 截断至 0
    assert engine.compute_alpha(t=-5.0, tau=20.0, sigma=5.0) == engine.compute_alpha(t=0.0, tau=20.0, sigma=5.0)

    # 极小 sigma 不引发除零错误
    val_zero_sigma = engine.compute_alpha(t=20.0, tau=20.0, sigma=0.0)
    assert 0.05 <= val_zero_sigma <= 0.75

    # 极大 t 不发生溢出
    val_huge_t = engine.compute_alpha(t=10000.0, tau=20.0, sigma=5.0)
    assert val_huge_t == 0.20

    # 快捷全局函数入口
    assert compute_temporal_alpha(0.0, 20.0, 5.0) == engine.compute_alpha(0.0, 20.0, 5.0)
