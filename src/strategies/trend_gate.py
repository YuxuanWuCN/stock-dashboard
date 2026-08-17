# -*- coding: utf-8 -*-
"""src/strategies/trend_gate.py —— 趋势门（Trend Gate）

封箱检验发现：美光 MU 下跌段集成预测命中率仅 45.2%（系统性误判），
而上升段 53.7%、震荡段 56.8%。趋势门抑制逆势信号，防止下跌段抄底。

设计：
  - 20日趋势 + 60日均线位置 → 判定趋势状态
  - 下跌趋势中，抑制/禁止看多信号（可配置权重）
  - 可单独使用，也可作为 prediction_accuracy_harness 的过滤层
"""
from typing import List, Optional, Tuple


def detect_trend(
    closes: List[float],
    window_short: int = 20,
    window_long: int = 60,
) -> Tuple[str, dict]:
    """检测趋势状态（20日方向 + 60日均线位置）。

    Args:
        closes: 收盘价序列（时间升序）
        window_short: 短周期窗口（默认20日）
        window_long: 长周期窗口（默认60日）

    Returns:
        (trend_state, metrics):
          trend_state ∈ {"uptrend", "downtrend", "neutral"}
          metrics = {
              "mom_20d": 20日涨跌幅,
              "ma60_ratio": 当前价/60日均线 - 1,
              "above_ma60": bool,
              "mom_positive": bool,
          }
    """
    n = len(closes)
    if n < window_long:
        return "neutral", {"reason": "insufficient_data"}

    curr = closes[-1]
    prev_20 = closes[-window_short] if n >= window_short else closes[0]
    ma60 = sum(closes[-window_long:]) / window_long

    mom_20d = (curr / prev_20 - 1) if prev_20 else 0.0
    ma60_ratio = (curr / ma60 - 1) if ma60 else 0.0
    above_ma60 = curr > ma60
    mom_positive = mom_20d > 0

    # 判定规则（参考师叔 claw-quant 的 Market Momentum State Regulator）
    if mom_positive and above_ma60:
        state = "uptrend"
    elif not mom_positive and not above_ma60:
        state = "downtrend"
    else:
        state = "neutral"

    metrics = {
        "mom_20d": round(mom_20d, 4),
        "ma60_ratio": round(ma60_ratio, 4),
        "above_ma60": above_ma60,
        "mom_positive": mom_positive,
    }

    return state, metrics


def apply_trend_filter(
    signal: Optional[int],
    trend_state: str,
    mode: str = "suppress_down",
) -> Optional[int]:
    """根据趋势状态过滤信号。

    Args:
        signal: 原始信号（1 看涨 / -1 看跌 / None 不表态）
        trend_state: 趋势状态（uptrend / downtrend / neutral）
        mode: 过滤模式
          - "suppress_down": 下跌趋势禁止看多（看多信号 → None）
          - "suppress_counter": 下跌趋势禁止看多，上涨趋势禁止看空
          - "weight": 保留信号但调权（下游加权，这里返回原值 + 权重建议）

    Returns:
        过滤后信号（或 None）
    """
    if signal is None:
        return None

    if mode == "suppress_down":
        # 下跌趋势中禁止看多（防止抄底）
        if trend_state == "downtrend" and signal > 0:
            return None
        return signal

    elif mode == "suppress_counter":
        # 禁止逆势（下跌禁看多、上涨禁看空）
        if trend_state == "downtrend" and signal > 0:
            return None
        if trend_state == "uptrend" and signal < 0:
            return None
        return signal

    elif mode == "weight":
        # 保留信号不动，权重建议由外部应用（此处不实现权重，仅检测）
        return signal

    else:
        return signal


def get_trend_weight(trend_state: str) -> float:
    """获取趋势调节权重（参考师叔系统的 Market Momentum State Regulator）。

    Returns:
        权重系数（uptrend: 1.5 / neutral: 1.0 / downtrend: 0.5）
    """
    if trend_state == "uptrend":
        return 1.5
    elif trend_state == "downtrend":
        return 0.5
    else:
        return 1.0
