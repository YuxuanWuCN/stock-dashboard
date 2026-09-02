# -*- coding: utf-8 -*-
"""tests/test_dynamic_position_sizer.py —— 动态仓位管理器单元测试

覆盖：
1. 各市场状态（BULL/BEAR/SIDEWAYS）的仓位计算
2. 回撤惩罚机制（阈值内无惩罚、超出后线性/指数衰减）
3. 波动率调整（高/低/正常波动率）
4. 仓位边界限制（min_position/max_position）
5. 未知状态处理
6. 配置验证
7. 历史记录功能
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytest

from src.risk.dynamic_position_sizer import (
    DynamicPositionSizer,
    PositionSizerConfig,
    DEFAULT_POSITION_CONFIG,
    AGGRESSIVE_POSITION_CONFIG,
    CONSERVATIVE_POSITION_CONFIG,
)


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def sizer_default() -> DynamicPositionSizer:
    """默认配置的仓位管理器。"""
    return DynamicPositionSizer()


@pytest.fixture
def sizer_conservative() -> DynamicPositionSizer:
    """保守配置的仓位管理器。"""
    return DynamicPositionSizer(CONSERVATIVE_POSITION_CONFIG)


@pytest.fixture
def sizer_aggressive() -> DynamicPositionSizer:
    """激进配置的仓位管理器。"""
    return DynamicPositionSizer(AGGRESSIVE_POSITION_CONFIG)


# ============================================================
# 单元测试：基础仓位（市场状态）
# ============================================================

class TestBasePosition:
    """测试不同市场状态的基础仓位计算。"""

    def test_bull_position(self, sizer_default):
        """牛市状态：仓位应 > base_position。"""
        pos = sizer_default.calculate_position(
            regime="BULL",
            current_drawdown=0.0,
            volatility=0.025,
        )
        # base=1.0 * bull_mult=1.2 = 1.2
        expected = 1.0 * 1.2
        assert pos == pytest.approx(expected, rel=0.01), f"BULL 仓位期望 {expected}，实际 {pos}"

    def test_bear_position(self, sizer_default):
        """熊市状态：仓位应 < base_position。"""
        pos = sizer_default.calculate_position(
            regime="BEAR",
            current_drawdown=0.0,
            volatility=0.025,
        )
        # base=1.0 * bear_mult=0.6 = 0.6
        expected = 1.0 * 0.6
        assert pos == pytest.approx(expected, rel=0.01), f"BEAR 仓位期望 {expected}，实际 {pos}"

    def test_sideways_position(self, sizer_default):
        """震荡市状态：仓位应接近 base_position。"""
        pos = sizer_default.calculate_position(
            regime="SIDEWAYS",
            current_drawdown=0.0,
            volatility=0.025,
        )
        # base=1.0 * sideways_mult=0.9 = 0.9
        expected = 1.0 * 0.9
        assert pos == pytest.approx(expected, rel=0.01), f"SIDEWAYS 仓位期望 {expected}，实际 {pos}"

    def test_case_insensitive_regime(self, sizer_default):
        """状态字符串应大小写不敏感。"""
        pos1 = sizer_default.calculate_position("bull", 0.0, 0.025)
        pos2 = sizer_default.calculate_position("BULL", 0.0, 0.025)
        pos3 = sizer_default.calculate_position("Bull", 0.0, 0.025)
        assert pos1 == pos2 == pos3

    def test_unknown_regime(self, sizer_default):
        """未知状态应使用 SIDEWAYS 默认值。"""
        pos = sizer_default.calculate_position("UNKNOWN", 0.0, 0.025)
        expected = 1.0 * 0.9  # SIDEWAYS multiplier
        assert pos == pytest.approx(expected, rel=0.01)


# ============================================================
# 单元测试：回撤惩罚
# ============================================================

class TestDrawdownPenalty:
    """测试回撤惩罚机制。"""

    def test_no_penalty_below_threshold(self, sizer_default):
        """回撤低于阈值时应无惩罚。"""
        pos_no_dd = sizer_default.calculate_position("BULL", 0.0, 0.025)
        pos_small_dd = sizer_default.calculate_position("BULL", 0.05, 0.025)
        # 回撤 5% < 阈值 10%，应无惩罚
        assert pos_small_dd == pytest.approx(pos_no_dd, rel=0.01)

    def test_linear_penalty_at_threshold(self, sizer_default):
        """回撤刚好等于阈值时应无惩罚。"""
        pos = sizer_default.calculate_position("BULL", 0.10, 0.025)
        expected = 1.0 * 1.2  # 无惩罚
        assert pos == pytest.approx(expected, rel=0.01)

    def test_linear_penalty_above_threshold(self, sizer_default):
        """回撤超过阈值时应线性衰减。"""
        # 回撤 15%，阈值 10%，factor=2.0
        # penalty = 1 - 2.0 * (0.15 - 0.10) = 0.90
        # position = 1.2 * 0.90 * 1.0 = 1.08
        pos = sizer_default.calculate_position("BULL", 0.15, 0.025)
        expected = 1.0 * 1.2 * 0.90
        assert pos == pytest.approx(expected, rel=0.01)

    def test_linear_penalty_clipped(self, sizer_default):
        """回撤过大时 penalty 不应低于 min。"""
        # 回撤 50%，penalty_min=0.5
        # penalty = 1 - 2.0 * (0.50 - 0.10) = 0.20 → clipped to 0.5
        pos = sizer_default.calculate_position("BULL", 0.50, 0.025)
        expected = 1.0 * 1.2 * 0.5
        assert pos == pytest.approx(expected, rel=0.01)

    def test_exponential_penalty(self):
        """指数衰减回撤惩罚应比线性更平滑。"""
        cfg = PositionSizerConfig(
            use_exponential_drawdown=True,
            exponential_drawdown_k=3.0,
        )
        sizer = DynamicPositionSizer(cfg)

        # 回撤 15%（超过 5%）
        # exp(-3.0 * 0.05) = 0.8607
        pos = sizer.calculate_position("BULL", 0.15, 0.025)
        expected = 1.0 * 1.2 * np.exp(-3.0 * 0.05)
        assert pos == pytest.approx(expected, rel=0.01)

        # 回撤 30%（超过 20%）  
        # exp(-3.0 * 0.20) = 0.5488
        pos2 = sizer.calculate_position("BULL", 0.30, 0.025)
        expected2 = 1.0 * 1.2 * np.exp(-3.0 * 0.20)
        assert pos2 == pytest.approx(expected2, rel=0.01)

        # 验证指数衰减使极端回撤惩罚更合理（不会过早 clip）
        assert pos2 > 0.5  # 不应触发 clip


# ============================================================
# 单元测试：波动率调整
# ============================================================

class TestVolatilityAdjustment:
    """测试波动率调整机制。"""

    def test_normal_volatility(self, sizer_default):
        """正常波动率（0.02-0.05）应无调整。"""
        pos = sizer_default.calculate_position("BULL", 0.0, 0.03)
        expected = 1.0 * 1.2
        assert pos == pytest.approx(expected, rel=0.01)

    def test_high_volatility(self, sizer_default):
        """高波动率（>0.05）应降仓。"""
        pos = sizer_default.calculate_position("BULL", 0.0, 0.06)
        expected = 1.0 * 1.2 * 0.8  # high_vol_adj=0.8
        assert pos == pytest.approx(expected, rel=0.01)

    def test_low_volatility(self, sizer_default):
        """低波动率（<0.02）应加仓。"""
        pos = sizer_default.calculate_position("BULL", 0.0, 0.01)
        expected = 1.0 * 1.2 * 1.1  # low_vol_adj=1.1
        assert pos == pytest.approx(expected, rel=0.01)

    @pytest.mark.parametrize("vol,expected_adj", [
        (0.0, 1.1),      # 极低波动 → 1.1
        (0.01, 1.1),     # 低波动 → 1.1
        (0.02, 1.0),     # 阈值边界（正常）
        (0.03, 1.0),     # 正常波动
        (0.05, 0.8),     # 阈值边界（高波动）
        (0.10, 0.8),     # 高波动 → 0.8
    ])
    def test_volatility_threshold_boundaries(self, vol, expected_adj):
        """波动率阈值边界条件测试。"""
        sizer = DynamicPositionSizer()
        # 使用 BEAR 状态使基准清晰（0.6）
        pos = sizer.calculate_position("BEAR", 0.0, vol)
        expected = 1.0 * 0.6 * expected_adj
        assert pos == pytest.approx(expected, rel=0.01)


# ============================================================
# 单元测试：仓位边界限制
# ============================================================

class TestPositionBounds:
    """测试仓位边界限制。"""

    def test_min_position_clip(self):
        """仓位不应低于 min_position。"""
        cfg = PositionSizerConfig(
            base_position=0.5,
            bear_multiplier=0.3,
            min_position=0.3,
        )
        sizer = DynamicPositionSizer(cfg)
        pos = sizer.calculate_position("BEAR", 0.0, 0.025)
        # 0.5 * 0.3 = 0.15 → clipped to 0.3
        assert pos == 0.3

    def test_max_position_clip(self):
        """仓位不应高于 max_position。"""
        cfg = PositionSizerConfig(
            base_position=2.0,
            bull_multiplier=1.5,
            max_position=2.0,
        )
        sizer = DynamicPositionSizer(cfg)
        pos = sizer.calculate_position("BULL", 0.0, 0.025)
        # 2.0 * 1.5 = 3.0 → clipped to 2.0
        assert pos == 2.0

    def test_combined_effects_clip(self):
        """多因子组合后超出限制应正确 clip。"""
        cfg = PositionSizerConfig(
            base_position=1.5,
            bull_multiplier=1.5,
            volatility_low_adj=1.2,
            max_position=2.0,
        )
        sizer = DynamicPositionSizer(cfg)
        # 1.5 * 1.5 * 1.2 = 2.7 → clipped to 2.0
        pos = sizer.calculate_position("BULL", 0.0, 0.01)
        assert pos == 2.0


# ============================================================
# 单元测试：EMA 平滑
# ============================================================

class TestSmoothing:
    """测试 EMA 平滑功能。"""

    def test_smoothing_effect(self):
        """平滑应使仓位变化更平缓。"""
        cfg = PositionSizerConfig(smoothing_alpha=0.3)
        sizer = DynamicPositionSizer(cfg)

        # 第一次调用：无历史，应直接返回计算值
        pos1 = sizer.calculate_position("BULL", 0.0, 0.025)
        expected1 = 1.0 * 1.2
        assert pos1 == pytest.approx(expected1, rel=0.01)

        # 第二次调用：应用平滑
        pos2 = sizer.calculate_position("BEAR", 0.0, 0.025)
        # 0.3 * 0.6 + 0.7 * 1.2 = 0.18 + 0.84 = 1.02
        expected2 = 0.3 * 0.6 + 0.7 * 1.2
        assert pos2 == pytest.approx(expected2, rel=0.01)

    def test_no_smoothing_by_default(self, sizer_default):
        """默认配置（smoothing_alpha=0）不应平滑。"""
        pos1 = sizer_default.calculate_position("BULL", 0.0, 0.025)
        pos2 = sizer_default.calculate_position("BEAR", 0.0, 0.025)
        assert pos2 == pytest.approx(0.6, rel=0.01)  # 直接切换


# ============================================================
# 单元测试：历史记录
# ============================================================

class TestPositionHistory:
    """测试仓位历史记录功能。"""

    def test_get_history_empty(self, sizer_default):
        """未调用 calculate_position 时应返回空 DataFrame。"""
        df = sizer_default.get_position_history()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_get_history_after_calls(self, sizer_default):
        """调用后应正确记录历史。"""
        sizer_default.calculate_position("BULL", 0.0, 0.025)
        sizer_default.calculate_position("BEAR", 0.05, 0.03)

        df = sizer_default.get_position_history()
        assert len(df) == 2
        assert "regime" in df.columns
        assert "final_position" in df.columns
        assert df["regime"].iloc[0] == "BULL"
        assert df["regime"].iloc[1] == "BEAR"

    def test_reset(self, sizer_default):
        """reset 应清空历史记录。"""
        sizer_default.calculate_position("BULL", 0.0, 0.025)
        sizer_default.reset()
        df = sizer_default.get_position_history()
        assert len(df) == 0


# ============================================================
# 单元测试：配置验证
# ============================================================

class TestConfigValidation:
    """测试配置验证。"""

    def test_default_config_valid(self):
        """默认配置应通过验证。"""
        cfg = PositionSizerConfig()
        cfg.validate()  # 不应抛出异常

    def test_invalid_base_position(self):
        """base_position 超出范围应抛出异常。"""
        with pytest.raises(AssertionError):
            PositionSizerConfig(base_position=5.0).validate()

    def test_invalid_min_max(self):
        """min_position >= max_position 应抛出异常。"""
        with pytest.raises(AssertionError):
            PositionSizerConfig(min_position=1.0, max_position=0.5).validate()

    def test_invalid_volatility_adj(self):
        """volatility_high_adj <= 0 应抛出异常。"""
        with pytest.raises(AssertionError):
            PositionSizerConfig(volatility_high_adj=0.0).validate()

    @pytest.mark.parametrize("cfg_kwargs", [
        {"bull_multiplier": -0.1},
        {"drawdown_threshold": 0.60},
        {"drawdown_penalty_min": -0.1},
        {"smoothing_alpha": 1.0},
    ])
    def test_invalid_params(self, cfg_kwargs):
        """各种无效参数应抛出异常。"""
        with pytest.raises(AssertionError):
            PositionSizerConfig(**cfg_kwargs).validate()


# ============================================================
# 单元测试：集成与组合场景
# ============================================================

class TestIntegration:
    """集成测试：多因子组合场景。"""

    def test_bull_low_dd_low_vol(self, sizer_aggressive):
        """牛市 + 低回撤 + 低波动 → 最高仓位。"""
        pos = sizer_aggressive.calculate_position("BULL", 0.0, 0.01)
        # 激进配置：1.0 * 1.4 * 1.0 * 1.1 = 1.54
        assert pos > 1.0
        assert pos <= 2.5  # 不超过 max

    def test_bear_high_dd_high_vol(self, sizer_conservative):
        """熊市 + 高回撤 + 高波动 → 最低仓位。"""
        pos = sizer_conservative.calculate_position("BEAR", 0.25, 0.08)
        # 保守配置下应接近 min_position
        assert pos <= 0.8

    def test_sideways_moderate_dd_normal_vol(self, sizer_default):
        """震荡市 + 中等回撤 + 正常波动 → 中等仓位。"""
        pos = sizer_default.calculate_position("SIDEWAYS", 0.08, 0.03)
        # 0.9 * 1.0 * 1.0 = 0.9
        assert 0.5 <= pos <= 1.5

    def test_config_presets_valid(self):
        """预设配置应都是有效的。"""
        for cfg in [DEFAULT_POSITION_CONFIG, AGGRESSIVE_POSITION_CONFIG, CONSERVATIVE_POSITION_CONFIG]:
            cfg.validate()  # 不应抛出异常
            sizer = DynamicPositionSizer(cfg)
            pos = sizer.calculate_position("BULL", 0.05, 0.025)
            assert cfg.min_position <= pos <= cfg.max_position


# ============================================================
# 运行入口
# ============================================================

if __name__ == "__main__":
    pytest.main(["-v", __file__])