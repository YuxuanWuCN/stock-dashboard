# -*- coding: utf-8 -*-
"""src/analysis/bet_type_classifier.py —— 赌注类型数据化分类器

封箱检验证据：
  - 立新能源（妖股）：择时 +163% vs 持有 +85% → 择时有效
  - 美光 MU（趋势股）：择时 +161% vs 持有 +423% → 择时跑输

设计：用统计特征判定标的类型，自动切换策略逻辑。
参考：师叔 claw-quant 的 SFM 层（因子流形：IC、半衰期、拥挤度）。
"""
import math
from typing import List, Tuple, Optional


def calculate_volatility(returns: List[float], window: int = 20) -> float:
    """计算波动率（收益标准差，年化）。

    Args:
        returns: 日收益序列
        window: 窗口期（默认20日）

    Returns:
        年化波动率（252 个交易日）
    """
    if len(returns) < window:
        return 0.0
    recent = returns[-window:]
    valid = [r for r in recent if not math.isnan(r)]
    if len(valid) < 5:
        return 0.0
    mean = sum(valid) / len(valid)
    variance = sum((r - mean) ** 2 for r in valid) / len(valid)
    std_daily = math.sqrt(variance)
    return std_daily * math.sqrt(252)  # 年化


def calculate_momentum_half_life(closes: List[float], lookback: int = 60) -> Optional[float]:
    """估算动量半衰期（简化版：用自相关衰减速度）。

    动量半衰期：收益率自相关降到 0.5 所需的滞后期数。
    短半衰期 → 快速反转（妖股）；长半衰期 → 趋势持续（趋势股）。

    Args:
        closes: 收盘价序列
        lookback: 回溯窗口（默认60日）

    Returns:
        半衰期（单位：天），None 表示无法计算
    """
    if len(closes) < lookback + 10:
        return None
    
    # 计算收益序列
    rets = []
    for i in range(1, len(closes)):
        if closes[i - 1] and closes[i - 1] != 0:
            rets.append(closes[i] / closes[i - 1] - 1)
        else:
            rets.append(0.0)
    
    if len(rets) < lookback:
        return None
    
    recent_rets = rets[-lookback:]
    
    # 计算 lag-1 到 lag-10 的自相关
    autocorrs = []
    for lag in range(1, min(11, len(recent_rets) // 2)):
        x = recent_rets[:-lag]
        y = recent_rets[lag:]
        if len(x) < 10:
            break
        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)
        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x))) / len(x)
        std_x = math.sqrt(sum((v - mean_x) ** 2 for v in x) / len(x))
        std_y = math.sqrt(sum((v - mean_y) ** 2 for v in y) / len(y))
        if std_x > 0 and std_y > 0:
            autocorrs.append(cov / (std_x * std_y))
        else:
            autocorrs.append(0.0)
    
    if not autocorrs or autocorrs[0] <= 0:
        return None
    
    # 估算半衰期：找到自相关降到初始值 0.5 倍的滞后期
    half = autocorrs[0] * 0.5
    for i, ac in enumerate(autocorrs):
        if ac <= half:
            return float(i + 1)
    
    return float(len(autocorrs))  # 超过观测窗口 → 长半衰期


def calculate_atr_ratio(closes: List[float], highs: List[float], lows: List[float], window: int = 14) -> float:
    """计算 ATR 相对值（ATR / 当前价格）。

    Args:
        closes, highs, lows: 收盘价、最高价、最低价序列
        window: ATR 窗口（默认14日）

    Returns:
        ATR 占价格的比例
    """
    if len(closes) < window + 1:
        return 0.0
    
    trs = []
    for i in range(1, len(closes)):
        h = highs[i] if i < len(highs) else closes[i]
        l = lows[i] if i < len(lows) else closes[i]
        c_prev = closes[i - 1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
    
    if len(trs) < window:
        return 0.0
    
    atr = sum(trs[-window:]) / window
    curr = closes[-1]
    return atr / curr if curr else 0.0


def classify_bet_type(
    closes: List[float],
    highs: Optional[List[float]] = None,
    lows: Optional[List[float]] = None,
) -> Tuple[str, dict]:
    """数据化分类标的类型（趋势型/妖股型/震荡型）。

    Args:
        closes: 收盘价序列（至少60日）
        highs, lows: 最高价、最低价（用于 ATR，可选）

    Returns:
        (bet_type, metrics):
          bet_type ∈ {"trend", "volatile", "range_bound"}
          metrics = {
              "volatility_annual": 年化波动率,
              "momentum_half_life": 动量半衰期（天）,
              "atr_ratio": ATR/价格,
          }
    """
    if len(closes) < 60:
        return "range_bound", {"reason": "insufficient_data"}
    
    # 计算收益
    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] and closes[i - 1] != 0:
            returns.append(closes[i] / closes[i - 1] - 1)
        else:
            returns.append(0.0)
    
    vol = calculate_volatility(returns)
    half_life = calculate_momentum_half_life(closes)
    atr_ratio = calculate_atr_ratio(closes, highs or closes, lows or closes)
    
    metrics = {
        "volatility_annual": round(vol, 4),
        "momentum_half_life": round(half_life, 2) if half_life else None,
        "atr_ratio": round(atr_ratio, 4),
    }
    
    # 分类规则（阈值可调）
    # 趋势股：低波动（<0.4）+ 长半衰期（>5）
    # 妖股：高波动（>0.6）或 短半衰期（<3）或 高 ATR（>0.05）
    # 震荡：其余
    
    # 修正规则：
    # 强趋势型（如大牛股）：动量不衰减（自相关持续高）或 半衰期 > 5 天
    # 妖股型（如题材炒作）：半衰期极短（< 3 天，冲高快速回落）且 日内波动极大（ATR > 10%）
    # 震荡型：其余
    
    is_persistent_trend = (half_life is None) or (half_life is not None and half_life >= 4.0)
    is_flash_speculation = (half_life is not None and half_life <= 2.5) and (atr_ratio > 0.08)
    
    if is_flash_speculation:
        return "volatile", metrics
    elif is_persistent_trend and vol > 0.3:
        return "trend", metrics
    else:
        return "range_bound", metrics


def get_strategy_recommendation(bet_type: str) -> dict:
    """根据赌注类型推荐策略参数。

    Returns:
        {
            "holding_period": 建议持仓周期（天）,
            "trade_frequency": 交易频率（"high" / "medium" / "low"）,
            "signal_weight": 短线信号权重（0-1）,
            "description": 策略描述,
        }
    """
    if bet_type == "trend":
        return {
            "holding_period": 60,  # 2-3 月
            "trade_frequency": "low",
            "signal_weight": 0.3,  # 低权重：主要靠持有
            "description": "趋势股：拿住不动，少交易，避免频繁进出损害复利",
        }
    elif bet_type == "volatile":
        return {
            "holding_period": 5,  # 1 周
            "trade_frequency": "high",
            "signal_weight": 1.0,  # 高权重：紧跟信号
            "description": "妖股：短线择时有效，及时止盈止损，不扛单",
        }
    else:  # range_bound
        return {
            "holding_period": 20,  # 1 月
            "trade_frequency": "medium",
            "signal_weight": 0.5,
            "description": "震荡股：均值回归或观望，避免追涨杀跌",
        }
