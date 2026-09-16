# -*- coding: utf-8 -*-
"""tests/test_market_regime_detector.py —— 市场状态机检测器单元测试

覆盖：
1. 正常 BULL/BEAR/SIDEWAYS 状态判断正确性
2. 边界条件（数据不足、动量刚好等于阈值）
3. 防抖逻辑（状态频繁切换时保持稳定）
4. 高波动覆盖（volatility > threshold 时归为 SIDEWAYS）
5. 动量覆盖（abs(momentum) > override_threshold 时强制判断）
6. 统计信息方法
7. 空数据/NaN 处理
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytest

from src.risk.market_regime_detector import (
    MarketRegimeDetector,
    RegimeDetectorConfig,
    RegimeType,
    _apply_hysteresis,
    _calculate_atr,
)


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def bull_market_prices() -> pd.DataFrame:
    """生成牛市价格序列：持续上涨（每日+0.5%），低波动。"""
    n = 100
    np.random.seed(42)
    close = 100.0 * np.cumprod(1 + np.random.normal(0.005, 0.01, n))
    high = close * (1 + np.abs(np.random.normal(0, 0.005, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n)))
    return pd.DataFrame({
        "close": close,
        "high": high,
        "low": low,
    }, index=pd.date_range("2025-01-01", periods=n))


@pytest.fixture
def bear_market_prices() -> pd.DataFrame:
    """生成熊市价格序列：持续下跌（每日-0.5%），低波动。"""
    n = 100
    np.random.seed(42)
    close = 100.0 * np.cumprod(1 + np.random.normal(-0.005, 0.01, n))
    high = close * (1 + np.abs(np.random.normal(0, 0.005, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n)))
    return pd.DataFrame({
        "close": close,
        "high": high,
        "low": low,
    }, index=pd.date_range("2025-01-01", periods=n))


@pytest.fixture
def sideways_market_prices() -> pd.DataFrame:
    """生成震荡市价格序列：价格在窄幅区间波动，无明显趋势。"""
    n = 100
    np.random.seed(42)
    close = 100.0 + np.random.normal(0, 0.5, n).cumsum()
    close = 100.0 + (close - close.mean()) * 0.3  # 压缩波动
    high = close + np.abs(np.random.normal(0, 0.2, n))
    low = close - np.abs(np.random.normal(0, 0.2, n))
    return pd.DataFrame({
        "close": close,
        "high": high,
        "low": low,
    }, index=pd.date_range("2025-01-01", periods=n))


@pytest.fixture
def high_volatility_prices() -> pd.DataFrame:
    """生成高波动价格序列：大幅震荡，无明显趋势。"""
    n = 100
    np.random.seed(42)
    close = 100.0 * np.cumprod(1 + np.random.normal(0, 0.04, n))
    high = close * (1 + np.abs(np.random.normal(0, 0.02, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.02, n)))
    return pd.DataFrame({
        "close": close,
        "high": high,
        "low": low,
    }, index=pd.date_range("2025-01-01", periods=n))


@pytest.fixture
def short_prices() -> pd.DataFrame:
    """短数据序列（少于 MA 周期，用于测试边界条件）。"""
    return pd.DataFrame({
        "close": [100, 101, 102],
        "high": [101, 102, 103],
        "low": [99, 100, 101],
    }, index=pd.date_range("2025-01-01", periods=3))


# ============================================================
# 单元测试：_calculate_atr
# ============================================================

class TestCalculateATR:
    """测试 ATR 计算函数。"""

    def test_basic_atr(self):
        """基本 ATR 计算验证。"""
        prices = pd.DataFrame({
            "high": [101, 102, 103, 104, 105],
            "low": [99, 100, 101, 102, 103],
            "close": [100, 101, 102, 103, 104],
        })
        atr = _calculate_atr(prices, period=3)
        assert len(atr) == 5
        # 前 2 天应为 NaN（period=3 需要至少 3 个数据点）
        assert pd.isna(atr.iloc[0])
        assert pd.isna(atr.iloc[1])
        # 第 3 天起应有值
        assert not pd.isna(atr.iloc[2])
        assert atr.iloc[2] > 0

    def test_atr_constant_range(self):
        """恒定波幅：ATR 应等于波幅。"""
        prices = pd.DataFrame({
            "high": [102] * 10,
            "low": [98] * 10,
            "close": [100] * 10,
        })
        atr = _calculate_atr(prices, period=5)
        # 有效值应为 4.0（high-low=4）
        assert not pd.isna(atr.iloc[4])
        assert abs(atr.iloc[4] - 4.0) < 0.01

    def test_atr_empty_data(self):
        """空数据应返回空 Series。"""
        prices = pd.DataFrame({"high": [], "low": [], "close": []})
        atr = _calculate_atr(prices, period=5)
        assert len(atr) == 0


# ============================================================
# 单元测试：_apply_hysteresis
# ============================================================

class TestApplyHysteresis:
    """测试防抖逻辑。"""

    def test_basic_hysteresis(self):
        """基本防抖：状态切换时保持稳定。"""
        series = pd.Series(
            [RegimeType.BULL, RegimeType.BULL, RegimeType.BEAR,
             RegimeType.BULL, RegimeType.BULL, RegimeType.BULL],
        )
        result = _apply_hysteresis(series, min_duration=3)
        # 第 2 天（index=2）的 BEAR 应被防抖为 BULL
        assert result.iloc[2] == RegimeType.BULL
        # 前 2 天保持原样
        assert result.iloc[0] == RegimeType.BULL
        assert result.iloc[1] == RegimeType.BULL

    def test_no_change_if_stable(self):
        """如果状态稳定，防抖不应改变任何值。"""
        series = pd.Series([RegimeType.BULL] * 10)
        result = _apply_hysteresis(series, min_duration=3)
        assert all(r == RegimeType.BULL for r in result)

    def test_short_series(self):
        """短序列（< min_duration）应原样返回。"""
        series = pd.Series([RegimeType.BULL, RegimeType.BEAR])
        result = _apply_hysteresis(series, min_duration=3)
        assert result.iloc[0] == RegimeType.BULL
        assert result.iloc[1] == RegimeType.BEAR

    def test_min_duration_1(self):
        """min_duration=1 时不应防抖（每个状态都持续1天）。"""
        series = pd.Series(
            [RegimeType.BULL, RegimeType.BEAR, RegimeType.BULL,
             RegimeType.BEAR, RegimeType.BULL],
        )
        result = _apply_hysteresis(series, min_duration=1)
        # 所有切换都应保留
        assert result.iloc[1] == RegimeType.BEAR
        assert result.iloc[2] == RegimeType.BULL


# ============================================================
# 单元测试：MarketRegimeDetector
# ============================================================

class TestMarketRegimeDetector:
    """市场状态机检测器集成测试。"""

    def test_bull_market_detection(self, bull_market_prices):
        """牛市数据应检测为 BULL 状态。"""
        detector = MarketRegimeDetector()
        regime = detector.detect_regime(bull_market_prices)
        # 最后 20 天应该大部分是 BULL
        last_20 = regime.iloc[-20:]
        bull_ratio = (last_20 == RegimeType.BULL).mean()
        assert bull_ratio >= 0.5, f"牛市检测率仅 {bull_ratio:.2%}"

    def test_bear_market_detection(self, bear_market_prices):
        """熊市数据应检测为 BEAR 状态。"""
        detector = MarketRegimeDetector()
        regime = detector.detect_regime(bear_market_prices)
        last_20 = regime.iloc[-20:]
        bear_ratio = (last_20 == RegimeType.BEAR).mean()
        # 熊市检测可能比牛市稍弱，但仍应有一定比例
        assert bear_ratio >= 0.3, f"熊市检测率仅 {bear_ratio:.2%}"

    def test_sideways_detection(self, sideways_market_prices):
        """震荡市数据应检测为 SIDEWAYS 状态。"""
        detector = MarketRegimeDetector()
        regime = detector.detect_regime(sideways_market_prices)
        last_30 = regime.iloc[-30:]
        sideways_ratio = (last_30 == RegimeType.SIDEWAYS).mean()
        assert sideways_ratio >= 0.4, f"震荡市检测率仅 {sideways_ratio:.2%}"

    def test_high_volatility_sideways(self, high_volatility_prices):
        """高波动数据应归为 SIDEWAYS（市场方向不明确）。"""
        detector = MarketRegimeDetector()
        regime = detector.detect_regime(high_volatility_prices)
        last_30 = regime.iloc[-30:]
        sideways_ratio = (last_30 == RegimeType.SIDEWAYS).mean()
        assert sideways_ratio >= 0.3, f"高波动震荡市检测率仅 {sideways_ratio:.2%}"

    def test_short_data_returns_sideways(self, short_prices):
        """数据不足时默认返回 SIDEWAYS。"""
        detector = MarketRegimeDetector()
        regime = detector.detect_regime(short_prices)
        # 所有数据都应返回 SIDEWAYS（数据不足无法计算 MA/ATR）
        assert all(r == RegimeType.SIDEWAYS for r in regime)

    def test_hysteresis_effect(self):
        """防抖逻辑应减少状态切换次数。"""
        # 创建每日切换的数据
        n = 50
        np.random.seed(42)
        close = 100.0 + np.sin(np.linspace(0, 10, n)) * 5
        high = close + 1
        low = close - 1
        prices = pd.DataFrame({
            "close": close,
            "high": high,
            "low": low,
        }, index=pd.date_range("2025-01-01", periods=n))

        # 使用较短的防抖
        detector = MarketRegimeDetector(
            RegimeDetectorConfig(hysteresis_min_duration=2)
        )
        regime = detector.detect_regime(prices)

        # 检查切换次数（不应超过 n/2 次）
        switches = (regime != regime.shift(1)).sum()
        assert switches <= n / 2, f"切换次数过多: {switches}"

    def test_momentum_override(self):
        """动量超过 override_threshold 时应强制判断趋势。"""
        # 创建强趋势 + 高波动数据
        n = 80
        np.random.seed(42)
        trend = np.linspace(0, 20, n)  # 强上升趋势
        noise = np.random.normal(0, 2, n)  # 高波动噪声
        close = 100 + trend + noise
        high = close + np.abs(np.random.normal(0, 1, n))
        low = close - np.abs(np.random.normal(0, 1, n))

        prices = pd.DataFrame({
            "close": close,
            "high": high,
            "low": low,
        }, index=pd.date_range("2025-01-01", periods=n))

        # 使用低 override 阈值确保覆盖
        detector = MarketRegimeDetector(
            RegimeDetectorConfig(
                momentum_override_threshold=0.03,
                hysteresis_min_duration=2,
            )
        )
        regime = detector.detect_regime(prices)
        # 最后的强趋势应该被检测到
        last_10 = regime.iloc[-10:]
        bull_ratio = (last_10 == RegimeType.BULL).mean()
        assert bull_ratio > 0, f"动量覆盖后 BULL 检测率 {bull_ratio:.2%}"

    def test_get_regime_statistics(self, bull_market_prices):
        """统计信息方法应返回正确结构。"""
        detector = MarketRegimeDetector()
        detector.detect_regime(bull_market_prices)
        stats = detector.get_regime_statistics()

        assert "bull_days" in stats
        assert "bear_days" in stats
        assert "sideways_days" in stats
        assert "transition_matrix" in stats
        assert "regime_labels" in stats
        assert stats["bull_days"] + stats["bear_days"] + stats["sideways_days"] > 0
        assert stats["transition_matrix"].shape == (3, 3)

    def test_get_regime_statistics_empty(self):
        """未调用 detect_regime 时返回空统计。"""
        detector = MarketRegimeDetector()
        stats = detector.get_regime_statistics()
        assert stats["bull_days"] == 0
        assert stats["bear_days"] == 0
        assert stats["sideways_days"] == 0

    def test_config_validation(self):
        """无效配置应抛出异常。"""
        with pytest.raises(AssertionError):
            MarketRegimeDetector(RegimeDetectorConfig(ma_fast=100, ma_slow=50))
        with pytest.raises(AssertionError):
            MarketRegimeDetector(RegimeDetectorConfig(hysteresis_min_duration=0))

    @pytest.mark.parametrize("bad_data", [
        pd.DataFrame({"close": [], "high": [], "low": []}),
        pd.DataFrame({"close": [np.nan], "high": [np.nan], "low": [np.nan]}),
    ])
    def test_edge_case_empty_or_nan(self, bad_data):
        """空数据或全 NaN 数据应优雅处理。"""
        detector = MarketRegimeDetector()
        regime = detector.detect_regime(bad_data)
        assert len(regime) == len(bad_data)
        assert all(r == RegimeType.SIDEWAYS for r in regime)


# ============================================================
# 运行入口
# ============================================================

if __name__ == "__main__":
    pytest.main(["-v", __file__])