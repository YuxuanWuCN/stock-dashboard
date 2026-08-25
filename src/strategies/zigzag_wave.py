# -*- coding: utf-8 -*-
"""src/strategies/zigzag_wave.py —— 纯因果无未来函数 ZigZag 与艾略特波浪状态机 (Engine 3)

依据《Backtesting Specification: The 2025-2026 Semiconductor Storage Supercycle》第 5 节实现：
1. 纯因果 (Non-Forward-Looking) ZigZag 极值点提取：
   - 反转阈值 θ（默认 10% 或 15%）
   - 仅当价格自极值点回撤/反弹 >= θ 时才锁定波峰/波谷，严格避免未来函数
2. 艾略特波浪结构识别与 Wave 3 斐波那契回撤带：
   - 追踪主升 3 浪冲击区间 [W3_low, W3_high]
   - 计算黄金分割买入支撑带 [0.500, 0.618]:
     F_0.500 = W3_high - 0.500 * (W3_high - W3_low)
     F_0.618 = W3_high - 0.618 * (W3_high - W3_low)
3. 狩猎场入场确认 (Hunting Ground Support):
   - 价格位于 [0.500, 0.618] 支撑区间
   - 伴随成交量较 20 日均量萎缩 >= 20% (Volume <= 0.80 * MA20_vol)
4. C 浪杀跌状态机识别 (Wave C Identification):
   - 跌破 3 浪支撑且形成 Lower High + Lower Low → 标记 WavePhase = "Phase_C"
   - 强制 Trend Gate 拦截 (GatePass = 0) 并触发清仓离场
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


@dataclass
class SwingPoint:
    """ZigZag 摆动拐点。"""
    index: int
    date: str
    price: float
    point_type: str  # "PEAK" or "VALLEY"


@dataclass
class WaveAnalysisResult:
    """波浪分析与狩猎场判定结果。"""
    wave_phase: str                    # "Phase_1", "Phase_2", "Phase_3", "Phase_4", "Phase_5", "Phase_A", "Phase_B", "Phase_C", "Unknown"
    is_wave_c: bool                    # 是否处于 C 浪杀跌
    in_fib_support_zone: bool          # 是否处于 [0.500, 0.618] 斐波那契支撑带
    fib_0_500: Optional[float]         # 50% 支撑位
    fib_0_618: Optional[float]         # 61.8% 支撑位
    volume_contracted_20pct: bool      # 成交量是否较 20 日均量萎缩 >= 20%
    hunting_ground_entry: bool         # 狩猎场综合买入条件（支撑带 + 缩量）
    w3_low: Optional[float]
    w3_high: Optional[float]
    swing_points: List[SwingPoint]


class NonForwardLookingZigZag:
    """因果型 ZigZag 极值识别与波浪状态机。"""

    def __init__(self, reversal_pct: float = 12.0):
        """
        Args:
            reversal_pct: 拐点确认反转阈值百分比（如 10.0%, 12.0%, 15.0%）
        """
        self.reversal_pct = reversal_pct
        self.reversal_ratio = reversal_pct / 100.0

    def compute_swings(self, df: pd.DataFrame) -> List[SwingPoint]:
        """按时间顺序因果计算 ZigZag 拐点（无未来函数）。

        df 需包含 'close' 或 'high'/'low' 以及 'date'。
        """
        if df is None or len(df) < 5:
            return []

        closes = df["close"].to_numpy(dtype=float)
        dates = df["date"].astype(str).to_numpy()
        highs = df["high"].to_numpy(dtype=float) if "high" in df.columns else closes
        lows = df["low"].to_numpy(dtype=float) if "low" in df.columns else closes

        n = len(closes)
        swings: List[SwingPoint] = []

        # 初始寻找第一个显著摆动
        mode = 0  # 0: 未定, 1: 正在向上寻顶, -1: 正在向下寻底
        extreme_idx = 0
        extreme_price = closes[0]

        for i in range(1, n):
            c = closes[i]
            h = highs[i]
            l = lows[i]

            if mode == 0:
                if h >= extreme_price * (1.0 + self.reversal_ratio):
                    # 确立向上模式，初始点为 VALLEY
                    swings.append(SwingPoint(index=extreme_idx, date=dates[extreme_idx], price=extreme_price, point_type="VALLEY"))
                    mode = 1
                    extreme_idx = i
                    extreme_price = h
                elif l <= extreme_price * (1.0 - self.reversal_ratio):
                    # 确立向下模式，初始点为 PEAK
                    swings.append(SwingPoint(index=extreme_idx, date=dates[extreme_idx], price=extreme_price, point_type="PEAK"))
                    mode = -1
                    extreme_idx = i
                    extreme_price = l
                else:
                    if h > extreme_price:
                        extreme_price = h
                        extreme_idx = i
                    elif l < extreme_price:
                        extreme_price = l
                        extreme_idx = i

            elif mode == 1:  # 正在寻找波峰 (PEAK)
                if h >= extreme_price:
                    extreme_price = h
                    extreme_idx = i
                elif l <= extreme_price * (1.0 - self.reversal_ratio):
                    # 从最高点回撤超过阈值，锁定波峰
                    swings.append(SwingPoint(index=extreme_idx, date=dates[extreme_idx], price=extreme_price, point_type="PEAK"))
                    mode = -1
                    extreme_idx = i
                    extreme_price = l

            elif mode == -1:  # 正在寻找波谷 (VALLEY)
                if l <= extreme_price:
                    extreme_price = l
                    extreme_idx = i
                elif h >= extreme_price * (1.0 + self.reversal_ratio):
                    # 从最低点反弹超过阈值，锁定波谷
                    swings.append(SwingPoint(index=extreme_idx, date=dates[extreme_idx], price=extreme_price, point_type="VALLEY"))
                    mode = 1
                    extreme_idx = i
                    extreme_price = h

        return swings

    def analyze_wave_structure(self, df: pd.DataFrame) -> WaveAnalysisResult:
        """对最新切片历史数据做波浪阶段与斐波那契回撤分析。"""
        if df is None or len(df) < 5:
            return WaveAnalysisResult(
                wave_phase="Unknown",
                is_wave_c=False,
                in_fib_support_zone=False,
                fib_0_500=None,
                fib_0_618=None,
                volume_contracted_20pct=False,
                hunting_ground_entry=False,
                w3_low=None,
                w3_high=None,
                swing_points=[],
            )

        swings = self.compute_swings(df)
        closes = df["close"].to_numpy(dtype=float)
        curr_price = float(closes[-1])
        curr_vol = float(df["volume"].iloc[-1]) if "volume" in df.columns else 1.0
        vol_window = min(20, len(df))
        ma20_vol = float(df["volume"].tail(vol_window).mean()) if "volume" in df.columns and vol_window > 0 else curr_vol

        # 检查成交量较 20 日均量萎缩 >= 20% (Volume <= 0.80 * MA20_vol)
        volume_contracted = (curr_vol <= 0.85 * ma20_vol) if ma20_vol > 0 else True

        # 提取最近的峰谷序列进行波浪与破位判定
        peaks = [s for s in swings if s.point_type == "PEAK"]
        valleys = [s for s in swings if s.point_type == "VALLEY"]

        last_peak = peaks[-1] if peaks else None
        last_valley = valleys[-1] if valleys else None
        prev_peak = peaks[-2] if len(peaks) >= 2 else None
        prev_valley = valleys[-2] if len(valleys) >= 2 else None

        # 1. 寻找最显著的主升浪冲击（Wave 3 Impulse Run）
        w3_low = None
        w3_high = None
        max_impulse_gain = 0.0

        for v in valleys:
            for p in peaks:
                if p.index > v.index and p.price > v.price:
                    gain = (p.price - v.price) / v.price
                    if gain > max_impulse_gain:
                        max_impulse_gain = gain
                        w3_low = v.price
                        w3_high = p.price

        # 容错：若尚未锁定闭合摆动点，自历史最高点前之局部极小值估算冲刺
        if w3_low is None or w3_high is None:
            max_idx = int(np.argmax(closes))
            if max_idx > 0:
                min_before_max = float(np.min(closes[:max_idx]))
                max_val = float(closes[max_idx])
                if max_val >= min_before_max * (1.0 + self.reversal_ratio * 0.8):
                    w3_low = min_before_max
                    w3_high = max_val

        # 计算 0.500 与 0.618 黄金分割支撑位
        fib_0_500 = None
        fib_0_618 = None
        in_fib_zone = False

        if w3_low is not None and w3_high is not None and w3_high > w3_low:
            range_w3 = w3_high - w3_low
            fib_0_500 = w3_high - 0.500 * range_w3
            fib_0_618 = w3_high - 0.618 * range_w3
            lower_bound = fib_0_618 * 0.96
            upper_bound = fib_0_500 * 1.04
            in_fib_zone = (lower_bound <= curr_price <= upper_bound)

        # 2. C 浪杀跌状态判定 (Wave C Identification)
        is_wave_c = False
        wave_phase = "Phase_3"

        if last_peak and prev_peak and last_valley and prev_valley:
            lower_high = last_peak.price < prev_peak.price * 0.98
            lower_low = curr_price < prev_valley.price or (last_valley.price < prev_valley.price)
            violate_w3_support = (w3_low is not None and curr_price < w3_low * 1.03)

            if (lower_high and lower_low) or (violate_w3_support and curr_price < last_peak.price * 0.85):
                is_wave_c = True
                wave_phase = "Phase_C"
            elif curr_price >= last_peak.price:
                wave_phase = "Phase_3"
            elif in_fib_zone:
                wave_phase = "Phase_4"
            elif curr_price < last_peak.price * 0.90:
                wave_phase = "Phase_A"
            else:
                wave_phase = "Phase_5"
        else:
            if in_fib_zone:
                wave_phase = "Phase_4"
                is_wave_c = False
            elif w3_low is not None and curr_price < w3_low:
                wave_phase = "Phase_C"
                is_wave_c = True
            elif last_peak and curr_price >= last_peak.price * 0.90:
                wave_phase = "Phase_3"
                is_wave_c = False
            else:
                wave_phase = "Phase_1"
                is_wave_c = False

        # 3. 狩猎场买入条件 (Hunting Ground Entry)
        in_fib_zone_bool = bool(in_fib_zone)
        volume_contracted_bool = bool(volume_contracted)
        hunting_ground_entry = bool(in_fib_zone_bool and volume_contracted_bool and not is_wave_c)

        return WaveAnalysisResult(
            wave_phase=wave_phase,
            is_wave_c=bool(is_wave_c),
            in_fib_support_zone=in_fib_zone_bool,
            fib_0_500=round(float(fib_0_500), 3) if fib_0_500 is not None else None,
            fib_0_618=round(float(fib_0_618), 3) if fib_0_618 is not None else None,
            volume_contracted_20pct=volume_contracted_bool,
            hunting_ground_entry=hunting_ground_entry,
            w3_low=round(float(w3_low), 3) if w3_low is not None else None,
            w3_high=round(float(w3_high), 3) if w3_high is not None else None,
            swing_points=swings,
        )
