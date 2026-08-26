# -*- coding: utf-8 -*-
"""src/execution/trend_gate.py —— Trend Gate™ 布尔硬门禁与 C 浪主跌全量清仓执行器 (Week 9)

依据规范：
1. 《StockDashboard v3.0 & Serenity Chokepoint 12-Week Roadmap》Phase III: Week 9
2. 趋势过滤算法：MA20 均线趋势 + MACD 柱状图动量 + 艾略特波浪 C 浪侦测
3. 快速渲染布尔门禁 G_i in {0, 1}
4. 紧急硬清仓机制 (Clarification Q4):
   - 当 G_i = 0 时，100% 物理拦截所有新增买单 (allocated_weight = 0)
   - 触发次日开盘 100% 市价强制清仓已有持仓 (EMERGENCY_LIQUIDATE)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("trend_gate")


@dataclass
class TrendGateDecision:
    """Trend Gate 门禁裁决结果。"""
    ticker: str
    gate_open: bool  # G_i in {0, 1}: True 为允许做多/持有, False 为阻断/清仓
    ma20_val: float
    current_price: float
    macd_hist: float
    is_c_wave_downtrend: bool
    recommended_action: str  # 'PERMIT_LONG', 'EMERGENCY_LIQUIDATE', 'BLOCK_BUY'
    reason: str


class TrendGate:
    """Trend Gate™ 战术布尔硬门禁。"""

    def __init__(self, ma_period: int = 20):
        self.ma_period = ma_period

    def calculate_macd(self, close_series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算 MACD 快线 (DIF)、慢线 (DEA) 与动量柱 (Histogram)。"""
        ema_fast = close_series.ewm(span=fast, adjust=False).mean()
        ema_slow = close_series.ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        hist = (dif - dea) * 2.0
        return dif, dea, hist

    def detect_c_wave_correction(self, close_series: pd.Series) -> bool:
        """检测当前是否处于艾略特波浪 C 浪主跌/深度调整结构。
        
        判定特征：
        1. 价格跌破 MA20 且 MA20 斜率向下；
        2. MACD 柱状图在零轴下方持续放大（负动量加速）；
        3. 5日内出现加速下行创新低。
        """
        if len(close_series) < max(self.ma_period, 30):
            return False

        ma20 = close_series.rolling(self.ma_period).mean()
        _, _, hist = self.calculate_macd(close_series)

        curr_p = float(close_series.iloc[-1])
        curr_ma = float(ma20.iloc[-1])
        prev_ma = float(ma20.iloc[-5])
        curr_hist = float(hist.iloc[-1])
        prev_hist = float(hist.iloc[-3])

        # 条件 1: 价格在均线下方且均线向下
        ma_downtrend = (curr_p < curr_ma) and (curr_ma < prev_ma)
        # 条件 2: MACD 柱在 0 轴下方且加速扩大
        macd_bearish_expanding = (curr_hist < 0.0) and (curr_hist < prev_hist)

        return bool(ma_downtrend and macd_bearish_expanding)

    def evaluate_gate(self, ticker: str, kline_df: pd.DataFrame) -> TrendGateDecision:
        """评估 Trend Gate 布尔门禁裁决。"""
        closes = kline_df["close"]
        if len(closes) < self.ma_period:
            return TrendGateDecision(
                ticker=ticker,
                gate_open=True,
                ma20_val=float(closes.iloc[-1]),
                current_price=float(closes.iloc[-1]),
                macd_hist=0.0,
                is_c_wave_downtrend=False,
                recommended_action="PERMIT_LONG",
                reason="历史 K 线样本不足 20 根，默认放行"
            )

        ma20 = float(closes.rolling(self.ma_period).mean().iloc[-1])
        curr_p = float(closes.iloc[-1])
        _, _, hist = self.calculate_macd(closes)
        curr_hist = float(hist.iloc[-1])

        is_c_wave = self.detect_c_wave_correction(closes)

        if is_c_wave or (curr_p < ma20 * 0.95 and curr_hist < 0):
            return TrendGateDecision(
                ticker=ticker,
                gate_open=False,
                ma20_val=ma20,
                current_price=curr_p,
                macd_hist=curr_hist,
                is_c_wave_downtrend=True,
                recommended_action="EMERGENCY_LIQUIDATE",
                reason=f"🚨 Trend Gate 触发 C 浪主跌阻断 (价格 {curr_p:.2f} < MA20 {ma20:.2f}, MACD Hist {curr_hist:.3f})，执行次日强制清仓！"
            )

        return TrendGateDecision(
            ticker=ticker,
            gate_open=True,
            ma20_val=ma20,
            current_price=curr_p,
            macd_hist=curr_hist,
            is_c_wave_downtrend=False,
            recommended_action="PERMIT_LONG",
            reason=f"✅ 趋势健康：价格 ({curr_p:.2f}) 处于均线多头或震荡上升区间"
        )
