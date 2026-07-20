# analysis/indicators.py —— 全部技术指标计算
#
# 要求：
# - 仅依赖 pandas/numpy，不装 TA-Lib
# - 统一处理 NaN、停牌、窗口不足
# - 所有函数接收 pandas Series / DataFrame，返回同长度 Series

from typing import Optional, Tuple

import numpy as np
import pandas as pd


# ============================================================
# 1. 移动均线
# ============================================================

def calc_ma(series: pd.Series, window: int) -> pd.Series:
    """简单移动平均。窗口不足处为 NaN。"""
    return series.rolling(window=window, min_periods=window).mean()


def calc_mas(
    close: pd.Series, windows: list = None
) -> dict:
    """一次性返回多个均线 dict。"""
    if windows is None:
        windows = [5, 10, 20, 60]
    return {f"ma{w}": calc_ma(close, w) for w in windows}


# ============================================================
# 2. RSI
# ============================================================

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI（Wilder averaging）。不足 period+1 处为 NaN。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period + 1, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period + 1, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # 当 avg_loss == 0 时（连续上涨无跌幅），RSI = 100
    rsi = rsi.fillna(100.0)
    # 当 avg_gain == 0 时（连续下跌无涨幅），RSI = 0
    mask_no_gain = (avg_gain == 0) & (avg_loss > 0)
    rsi[mask_no_gain] = 0.0

    return rsi


# ============================================================
# 3. MACD
# ============================================================

def calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """
    返回 DataFrame 含 dif, dea, hist 三列。
    使用 EMA。不足 slow 处为 NaN。
    """
    ema_fast = close.ewm(span=fast, min_periods=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, min_periods=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, min_periods=signal, adjust=False).mean()
    hist = 2.0 * (dif - dea)
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": hist}, index=close.index)


# ============================================================
# 4. ATR
# ============================================================

def calc_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """ATR（Wilder）。返回同 index Series。小于 period+1 为 NaN。"""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1, skipna=False)
    atr = tr.ewm(alpha=1 / period, min_periods=period + 1, adjust=False).mean()
    return atr


def calc_atr_pct(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ATR / 收盘价 × 100。"""
    atr = calc_atr(high, low, close, period)
    return (atr / close.replace(0, np.nan)) * 100.0


# ============================================================
# 5. 布林带
# ============================================================

def calc_bollinger(
    close: pd.Series, window: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    """
    返回 DataFrame 含 upper, middle, lower, position, width_pct。
    position = (close - lower) / (upper - lower)，0~1。
    """
    middle = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    boll_range = upper - lower
    position = (close - lower) / boll_range.replace(0, np.nan)
    width_pct = (boll_range / middle.replace(0, np.nan)) * 100.0
    return pd.DataFrame(
        {"upper": upper, "middle": middle, "lower": lower,
         "position": position, "width_pct": width_pct},
        index=close.index,
    )


# ============================================================
# 6. 收益 (N 日)
# ============================================================

def calc_return(close: pd.Series, window: int) -> pd.Series:
    """N 日涨跌幅（%）。不足 window 处为 NaN。"""
    return close.pct_change(periods=window) * 100.0


def calc_returns(close: pd.Series, windows: list = None) -> dict:
    if windows is None:
        windows = [5, 20, 60]
    return {f"return_{w}d": calc_return(close, w) for w in windows}


# ============================================================
# 7. 量比
# ============================================================

def calc_volume_ratio(
    volume: pd.Series, short_window: int = 5, long_window: int = 20
) -> pd.Series:
    """短期均量 / 长期均量。"""
    avg_short = volume.rolling(window=short_window, min_periods=short_window).mean()
    avg_long = volume.rolling(window=long_window, min_periods=long_window).mean()
    return avg_short / avg_long.replace(0, np.nan)


# ============================================================
# 8. 年化波动率
# ============================================================

def calc_volatility(
    close: pd.Series, window: int = 20, trading_days: int = 242
) -> pd.Series:
    """N 日年化波动率（%），默认 20 日 / 242 个交易日年化。"""
    returns = close.pct_change()
    std = returns.rolling(window=window, min_periods=window).std(ddof=1)
    return std * np.sqrt(trading_days) * 100.0


# ============================================================
# 9. 最大回撤
# ============================================================

def calc_max_drawdown(close: pd.Series, window: int = 60) -> pd.Series:
    """滚动 N 日最大回撤（%，负数表示跌幅）。"""
    rolling_max = close.rolling(window=window, min_periods=1).max()
    drawdown = (close - rolling_max) / rolling_max.replace(0, np.nan) * 100.0
    # 取窗口期内最深的回撤
    result = pd.Series(np.nan, index=close.index, dtype=float)
    for i in range(window - 1, len(close)):
        start = i - window + 1
        window_close = close.iloc[start : i + 1]
        peak = window_close.expanding().max()
        dd = (window_close - peak) / peak.replace(0, np.nan) * 100.0
        result.iloc[i] = dd.min()
    return result


# ============================================================
# 10. 相对强度
# ============================================================

def calc_relative_strength(
    stock_close: pd.Series, benchmark_close: pd.Series, window: int = 20
) -> pd.Series:
    """
    计算个股相对基准的 N 日超额收益（百分点）。
    正数表示跑赢基准。
    """
    stock_ret = stock_close.pct_change(periods=window) * 100.0
    bench_ret = benchmark_close.pct_change(periods=window) * 100.0
    return stock_ret - bench_ret


# ============================================================
# 11. 判断趋势
# ============================================================

def determine_trend(
    close: pd.Series,
    ma20: pd.Series,
    ma60: pd.Series,
    rsi14: pd.Series,
) -> str:
    """
    根据最新数据点判断趋势方向。
    返回: strong_uptrend / uptrend / range / rebound / downtrend / insufficient
    """
    last_close = close.iloc[-1]
    last_ma20 = ma20.iloc[-1]
    last_ma60 = ma60.iloc[-1]
    last_rsi14 = rsi14.iloc[-1]

    if pd.isna(last_ma20) or pd.isna(last_ma60) or pd.isna(last_rsi14):
        return "insufficient"

    # 检查 MA 斜率（用最近 5 日 MA 值的变化方向）
    if len(ma20) >= 6:
        ma20_5d_ago = ma20.iloc[-6]
        ma20_rising = pd.notna(ma20_5d_ago) and last_ma20 > ma20_5d_ago
    else:
        ma20_rising = False

    price_above_ma20 = last_close > last_ma20
    price_above_ma60 = last_close > last_ma60
    ma20_above_ma60 = last_ma20 > last_ma60

    if price_above_ma20 and price_above_ma60 and ma20_above_ma60 and ma20_rising:
        if last_rsi14 > 65:
            return "strong_uptrend"
        return "uptrend"
    elif price_above_ma20 and price_above_ma60 and ma20_above_ma60 and not ma20_rising:
        return "uptrend"
    elif not price_above_ma20 and price_above_ma60:
        return "rebound"
    elif price_above_ma20 and not price_above_ma60 and ma20_rising:
        return "rebound"
    elif price_above_ma20 or price_above_ma60:
        return "range"
    elif last_close < last_ma20 and last_close < last_ma60 and not ma20_above_ma60:
        return "downtrend"
    else:
        return "range"


# ============================================================
# 12. 综合计算（一键算完所有指标）
# ============================================================

def compute_all_indicators(
    df: pd.DataFrame,
    industry_close: Optional[pd.Series] = None,
    market_close: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    输入 DataFrame 必须含: date, open, high, low, close, volume。
    返回同一 DataFrame，附加所有指标列。

    如果提供 industry_close 和 market_close（与 df 同 index），
    则同时计算行业相对强度。
    """
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    n = len(df)

    # --- 均线 ---
    mas = calc_mas(close)
    for k, v in mas.items():
        df[k] = v

    # --- 收益 ---
    returns = calc_returns(close)
    for k, v in returns.items():
        df[k] = v

    # --- RSI ---
    df["rsi14"] = calc_rsi(close, 14)

    # --- MACD ---
    macd = calc_macd(close)
    df["macd_dif"] = macd["dif"]
    df["macd_dea"] = macd["dea"]
    df["macd_hist"] = macd["hist"]

    # --- ATR ---
    df["atr14"] = calc_atr(high, low, close, 14)
    df["atr14_pct"] = calc_atr_pct(high, low, close, 14)

    # --- 布林带 ---
    boll = calc_bollinger(close)
    df["boll_upper"] = boll["upper"]
    df["boll_middle"] = boll["middle"]
    df["boll_lower"] = boll["lower"]
    df["boll_position"] = boll["position"]

    # --- 量比 ---
    df["volume_ratio_5d"] = calc_volume_ratio(volume, 5, 20)

    # --- 波动率 ---
    df["volatility_20d"] = calc_volatility(close, 20)

    # --- 最大回撤 ---
    df["max_drawdown_60d"] = calc_max_drawdown(close, 60)

    # --- 相对强度 ---
    if industry_close is not None:
        df["industry_rs_20d"] = calc_relative_strength(close, industry_close, 20)
    if market_close is not None:
        df["market_rs_20d"] = calc_relative_strength(close, market_close, 20)

    # --- 趋势 ---
    df["trend"] = None
    if n >= 60:
        trend = determine_trend(close, mas["ma20"], mas["ma60"], df["rsi14"])
        df["trend"] = trend  # 最后一行为判断值，其余 NaN（会在主流程按需处理）

    return df


# ============================================================
# 13. 辅助：获取最近有效值
# ============================================================

def get_latest_value(series: pd.Series) -> Optional[float]:
    """获取 series 中最后一个非 NaN 值。"""
    valid = series.dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])
