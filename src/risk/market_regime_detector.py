# -*- coding: utf-8 -*-
"""src/risk/market_regime_detector.py —— 市场状态机检测器

核心功能：
1. 三状态检测（BULL / BEAR / SIDEWAYS）
2. 基于动量（MA20/MA60 交叉）+ 波动率（ATR）的综合判断
3. 状态转换逻辑（带滞后防抖，防止状态频繁切换）

设计原则：
- 零前视偏差：detect_regime 只使用截至调用日期的历史数据
- 参数可配置：所有阈值通过 config dataclass 暴露，支持调优
- 与现有 rolling_direction_calibration.py 风格一致

参考：
- 《Gemini任务包_系统优化.md》市场状态机设计章节
- specs/contest-2026/spec.md §2.3 Trend Gate 风控机制增强
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("market_regime_detector")


class RegimeType(Enum):
    """市场状态枚举。"""
    BULL = "BULL"           # 牛市：动量向上 + 低波动
    BEAR = "BEAR"           # 熊市：动量向下 + 低波动
    SIDEWAYS = "SIDEWAYS"   # 震荡市：动量不明确或高波动

    def __str__(self) -> str:
        return self.value


@dataclass
class RegimeDetectorConfig:
    """市场状态机检测器配置参数。

    所有阈值均为可调参数，支持通过配置对象注入。
    """
    # MA 周期参数
    ma_fast: int = 20
    ma_slow: int = 60

    # ATR 计算周期
    atr_period: int = 14

    # 动量阈值（归一化 MA 差值比例）
    momentum_threshold_bull: float = 0.02    # 动量 > 2% → 偏牛
    momentum_threshold_bear: float = -0.02   # 动量 < -2% → 偏熊

    # 波动率阈值（ATR/Close 比例）
    # 高波动市场（> 此阈值）统一归为 SIDEWAYS
    volatility_threshold_high: float = 0.04  # ATR/Close > 4% → 高波动

    # 滞后防抖参数
    # 状态切换必须满足：新状态连续出现 min_duration 天，才真正切换
    min_duration: int = 3
    hysteresis_min_duration: Optional[int] = None

    # 二级判断参数（动量极强时覆盖高波动判断）
    # 若动量绝对值 > 此阈值，即使高波动也判定为趋势
    momentum_override_threshold: float = 0.05

    def __post_init__(self):
        if self.hysteresis_min_duration is not None:
            self.min_duration = self.hysteresis_min_duration
        else:
            self.hysteresis_min_duration = self.min_duration

    def validate(self) -> None:
        """参数合理性检查。"""
        assert 5 <= self.ma_fast <= 50, "ma_fast 应在 5-50 范围"
        assert 20 <= self.ma_slow <= 250, "ma_slow 应在 20-250 范围"
        assert self.ma_fast < self.ma_slow, "ma_fast 必须小于 ma_slow"
        assert 5 <= self.atr_period <= 50, "atr_period 应在 5-50 范围"
        assert 0.0 < self.momentum_threshold_bull <= 0.10, "momentum_threshold_bull 应在 (0, 0.10]"
        assert -0.10 <= self.momentum_threshold_bear < 0.0, "momentum_threshold_bear 应在 [-0.10, 0)"
        assert 0.01 <= self.volatility_threshold_high <= 0.15, "volatility_threshold_high 应在 0.01-0.15 范围"
        assert 1 <= self.min_duration <= 10, "min_duration 应在 1-10 范围"
        assert 1 <= self.hysteresis_min_duration <= 10, "hysteresis_min_duration 应在 1-10 范围"


# 默认配置
DEFAULT_REGIME_CONFIG = RegimeDetectorConfig()

# 激进配置（更灵敏，更容易识别趋势）
AGGRESSIVE_REGIME_CONFIG = RegimeDetectorConfig(
    ma_fast=10,
    ma_slow=30,
    momentum_threshold_bull=0.015,
    momentum_threshold_bear=-0.015,
    min_duration=2,
)

# 保守配置（更稳定，不易受毛刺干扰）
CONSERVATIVE_REGIME_CONFIG = RegimeDetectorConfig(
    ma_fast=30,
    ma_slow=90,
    momentum_threshold_bull=0.03,
    momentum_threshold_bear=-0.03,
    min_duration=5,
    volatility_threshold_high=0.035,
)


def _calculate_atr(prices: pd.DataFrame, period: int = 14) -> pd.Series:
    """计算真实波幅均值（ATR）。

    严格遵循无前视原则：使用 rolling 计算。

    Parameters
    ----------
    prices : pd.DataFrame
        包含 'high', 'low', 'close' 列的行情 DataFrame
    period : int
        ATR 周期（默认 14）

    Returns
    -------
    pd.Series
        ATR 序列
    """
    high = prices["high"]
    low = prices["low"]
    close = prices["close"]

    # TR = max(H-L, abs(H - C_prev), abs(L - C_prev))
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    return atr


def _apply_hysteresis(
    regimes: pd.Series,
    min_duration: int = 3,
) -> pd.Series:
    """对状态序列应用滞后防抖。

    规则：序列长度小于 min_duration 时返回原序列；
    新状态必须连续出现 >= min_duration 天，才切换到新状态；
    否则保持前一状态。

    Parameters
    ----------
    regimes : pd.Series
        未防抖的状态序列（RegimeType 枚举）
    min_duration : int
        最小持续天数

    Returns
    -------
    pd.Series
        防抖后的状态序列
    """
    if len(regimes) <= min_duration:
        return regimes.copy()

    result = regimes.copy()
    current_regime = regimes.iloc[0]
    candidate_regime = current_regime
    candidate_count = 0

    for i in range(len(regimes)):
        raw_regime = regimes.iloc[i]

        if raw_regime == current_regime:
            # 状态未变，重置候选
            candidate_regime = current_regime
            candidate_count = 0
            result.iloc[i] = current_regime
        else:
            # 出现新状态
            if raw_regime == candidate_regime:
                candidate_count += 1
            else:
                candidate_regime = raw_regime
                candidate_count = 1

            if candidate_count >= min_duration:
                # 满足持续天数，切换状态
                logger.info(f"市场状态切换确认: {current_regime} -> {candidate_regime} (持续 {candidate_count} 天)")
                current_regime = candidate_regime
                candidate_count = 0
                result.iloc[i] = current_regime
            else:
                # 不满足持续天数，保持原状态
                result.iloc[i] = current_regime

    return result


class MarketRegimeDetector:
    """市场状态机检测器。

    基于动量（MA 交叉）和波动率（ATR）的综合市场状态判断，
    带滞后防抖以防止状态频繁切换。
    """

    def __init__(self, config: Optional[RegimeDetectorConfig] = None):
        """
        Parameters
        ----------
        config : Optional[RegimeDetectorConfig]
            检测器配置参数（若未提供则使用 DEFAULT_REGIME_CONFIG）
        """
        self.config = config or DEFAULT_REGIME_CONFIG
        self.config.validate()

        # 内部状态记录（用于统计和调试）
        self._last_raw_regime: pd.Series = pd.Series(dtype=object)
        self._last_hysteresis_applied: pd.Series = pd.Series(dtype=object)

    def detect_regime(self, prices: pd.DataFrame) -> pd.Series:
        """检测市场状态序列。

        对输入的价格数据，逐日计算市场状态。

        Parameters
        ----------
        prices : pd.DataFrame
            DataFrame with columns ['close', 'high', 'low']
            index: DatetimeIndex

        Returns
        -------
        pd.Series
            RegimeType 枚举值序列（与 prices index 对齐）
        """
        cfg = self.config
        close = prices["close"]
        high = prices["high"]
        low = prices["low"]

        # 1. 计算技术指标
        ma_fast = close.rolling(window=cfg.ma_fast, min_periods=cfg.ma_fast).mean()
        ma_slow = close.rolling(window=cfg.ma_slow, min_periods=cfg.ma_slow).mean()
        atr = _calculate_atr(prices, period=cfg.atr_period)

        # 2. 动量信号（归一化 MA 差值）
        momentum = (ma_fast - ma_slow) / ma_slow.replace(0, np.nan)

        # 3. 波动率信号（ATR / Close）
        volatility = atr / close

        # 4. 逐日状态判断
        regimes = []
        for i in range(len(prices)):
            mom = momentum.iloc[i]
            vol = volatility.iloc[i]

            if pd.isna(mom) or pd.isna(vol):
                # 数据不足时默认震荡市
                regimes.append(RegimeType.SIDEWAYS)
                continue

            # 二级判断：高波动但动量极强时，仍保留趋势判断
            if abs(mom) > cfg.momentum_override_threshold:
                if mom > 0:
                    regimes.append(RegimeType.BULL)
                else:
                    regimes.append(RegimeType.BEAR)
                continue

            # 标准判断逻辑
            if vol > cfg.volatility_threshold_high:
                # 高波动 → 震荡市（市场方向不明确）
                regimes.append(RegimeType.SIDEWAYS)
            elif mom > cfg.momentum_threshold_bull:
                regimes.append(RegimeType.BULL)
            elif mom < cfg.momentum_threshold_bear:
                regimes.append(RegimeType.BEAR)
            else:
                # 动量不明确 → 震荡市
                regimes.append(RegimeType.SIDEWAYS)

        raw_series = pd.Series(regimes, index=prices.index)
        self._last_raw_regime = raw_series

        # 5. 应用滞后防抖
        final_series = _apply_hysteresis(raw_series, min_duration=cfg.min_duration)
        self._last_hysteresis_applied = final_series

        return final_series

    def get_regime_statistics(
        self,
        prices: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """获取市场状态统计信息（分布比例、切换次数、平均持续天数等）。

        Parameters
        ----------
        prices : Optional[pd.DataFrame]
            行情数据（若为 None 则使用最近一次 detect_regime 结果）

        Returns
        -------
        Dict[str, Any]
            包含各状态天数、占比、平均持续天数等统计信息
        """
        if len(self._last_hysteresis_applied) > 0 and prices is None:
            regimes = self._last_hysteresis_applied
        elif prices is not None:
            regimes = self.detect_regime(prices)
        else:
            return {
                "total_days": 0,
                "bull_days": 0,
                "bear_days": 0,
                "sideways_days": 0,
                "bull_pct": 0.0,
                "bear_pct": 0.0,
                "sideways_pct": 0.0,
                "regime_distribution": {"bull_days": 0, "bear_days": 0, "sideways_days": 0},
                "regime_percentages": {"bull_pct": 0.0, "bear_pct": 0.0, "sideways_pct": 0.0},
                "transition_matrix": np.zeros((3, 3), dtype=int),
                "regime_labels": ["BULL", "BEAR", "SIDEWAYS"],
                "switch_count": 0,
                "avg_duration_days": {"bull": 0.0, "bear": 0.0, "sideways": 0.0},
            }

        total_days = len(regimes)

        if total_days == 0:
            return {
                "total_days": 0,
                "bull_days": 0,
                "bear_days": 0,
                "sideways_days": 0,
                "bull_pct": 0.0,
                "bear_pct": 0.0,
                "sideways_pct": 0.0,
                "regime_distribution": {"bull_days": 0, "bear_days": 0, "sideways_days": 0},
                "regime_percentages": {"bull_pct": 0.0, "bear_pct": 0.0, "sideways_pct": 0.0},
                "transition_matrix": np.zeros((3, 3), dtype=int),
                "regime_labels": ["BULL", "BEAR", "SIDEWAYS"],
                "switch_count": 0,
                "avg_duration_days": {"bull": 0.0, "bear": 0.0, "sideways": 0.0},
            }

        # 状态分布
        counts = regimes.value_counts()
        dist: Dict[str, int] = {
            "bull_days": int(counts.get(RegimeType.BULL, 0)),
            "bear_days": int(counts.get(RegimeType.BEAR, 0)),
            "sideways_days": int(counts.get(RegimeType.SIDEWAYS, 0)),
        }
        pcts: Dict[str, float] = {
            k.replace("_days", "_pct"): round(v / total_days, 4)
            for k, v in dist.items()
        }

        # 转移矩阵
        regime_labels = ["BULL", "BEAR", "SIDEWAYS"]
        label_map = {RegimeType.BULL: 0, RegimeType.BEAR: 1, RegimeType.SIDEWAYS: 2}
        trans_mat = np.zeros((3, 3), dtype=int)
        for i in range(len(regimes) - 1):
            c_r = regimes.iloc[i]
            n_r = regimes.iloc[i + 1]
            if c_r in label_map and n_r in label_map:
                trans_mat[label_map[c_r], label_map[n_r]] += 1

        # 切换次数
        switches = int((regimes != regimes.shift(1)).sum()) - 1
        switches = max(0, switches)

        # 各状态平均持续天数
        avg_durations = self._calculate_avg_durations(regimes)

        return {
            "total_days": total_days,
            "bull_days": dist["bull_days"],
            "bear_days": dist["bear_days"],
            "sideways_days": dist["sideways_days"],
            "bull_pct": pcts["bull_pct"],
            "bear_pct": pcts["bear_pct"],
            "sideways_pct": pcts["sideways_pct"],
            "regime_distribution": dist,
            "regime_percentages": pcts,
            "transition_matrix": trans_mat,
            "regime_labels": regime_labels,
            "switch_count": switches,
            "avg_duration_days": avg_durations,
        }

    @staticmethod
    def _calculate_avg_durations(regimes: pd.Series) -> Dict[str, float]:
        """计算各状态的平均持续天数。"""
        if len(regimes) == 0:
            return {"bull": 0.0, "bear": 0.0, "sideways": 0.0}

        # 找出每个连续段的长度
        durations: Dict[str, List[int]] = {
            "bull": [],
            "bear": [],
            "sideways": [],
        }

        current_regime = regimes.iloc[0]
        current_len = 1

        for i in range(1, len(regimes)):
            if regimes.iloc[i] == current_regime:
                current_len += 1
            else:
                key = current_regime.value.lower()
                durations[key].append(current_len)
                current_regime = regimes.iloc[i]
                current_len = 1

        # 记录最后一段
        key = current_regime.value.lower()
        durations[key].append(current_len)

        return {
            k: round(float(np.mean(v)), 1) if len(v) > 0 else 0.0
            for k, v in durations.items()
        }
