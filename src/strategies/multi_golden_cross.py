"""多金叉共振策略 —— 均线、KDJ、MACD 金叉共振（移植自 KHunter，适配现有指标库）。

选股条件：
1. 均线金叉：短期均线上穿长期均线
2. KDJ 金叉：K 线上穿 D 线
3. MACD 金叉：DIF 线上穿 DEA 线
4. 共振确认：三个金叉在 lookback_days 内均出现，且最大时间差 <= resonance_days
"""

import pandas as pd

from src.strategies.base_strategy import BaseStrategy


class MultiGoldenCrossStrategy(BaseStrategy):
    """多金叉共振策略。"""

    def __init__(self, params=None):
        default_params = {
            "ma_short_period": 5,
            "ma_long_period": 20,
            "kdj_n": 9,
            "kdj_m1": 3,
            "kdj_m2": 3,
            "macd_short": 12,
            "macd_long": 26,
            "macd_signal": 9,
            "resonance_days": 3,
            "lookback_days": 10,
        }
        if params:
            default_params.update(params)
        super().__init__("多金叉共振", default_params)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or len(df) < 2:
            return pd.DataFrame()
        result = df.copy()

        close = result["close"]
        high = result["high"]
        low = result["low"]
        volume = result["volume"]

        p = self.params

        # 均线
        result["ma_short"] = close.rolling(p["ma_short_period"], min_periods=1).mean()
        result["ma_long"] = close.rolling(p["ma_long_period"], min_periods=1).mean()

        # KDJ
        lowest_low = low.rolling(p["kdj_n"], min_periods=1).min()
        highest_high = high.rolling(p["kdj_n"], min_periods=1).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low).replace(0, pd.NA) * 100
        rsv = rsv.fillna(50)
        result["K"] = rsv.ewm(alpha=1 / p["kdj_m1"], adjust=False).mean()
        result["D"] = result["K"].ewm(alpha=1 / p["kdj_m2"], adjust=False).mean()
        result["J"] = 3 * result["K"] - 2 * result["D"]

        # MACD（与 indicators.calc_macd 同口径）
        ema_short = close.ewm(span=p["macd_short"], adjust=False).mean()
        ema_long = close.ewm(span=p["macd_long"], adjust=False).mean()
        result["DIF"] = ema_short - ema_long
        result["DEA"] = result["DIF"].ewm(span=p["macd_signal"], adjust=False).mean()
        result["MACD"] = (result["DIF"] - result["DEA"]) * 2

        # 量比（5 日均量）
        result["volume_ma"] = volume.rolling(5, min_periods=1).mean()
        result["volume_ratio"] = volume / result["volume_ma"].replace(0, pd.NA)

        # 金叉信号（升序数据：当前在上方且前一日在下方）
        result["ma_cross_signal"] = (result["ma_short"] > result["ma_long"]) & (
            result["ma_short"].shift(1) <= result["ma_long"].shift(1)
        )
        result["kdj_cross_signal"] = (result["K"] > result["D"]) & (
            result["K"].shift(1) <= result["D"].shift(1)
        )
        result["macd_cross_signal"] = (result["DIF"] > result["DEA"]) & (
            result["DIF"].shift(1) <= result["DEA"].shift(1)
        )

        return result

    def get_selection_criteria(self) -> list:
        p = self.params
        return [
            f"1. 均线金叉：{p['ma_short_period']}日均线上穿{p['ma_long_period']}日均线",
            f"2. KDJ金叉：K线上穿D线（N={p['kdj_n']}）",
            f"3. MACD金叉：DIF上穿DEA（{p['macd_short']},{p['macd_long']},{p['macd_signal']}）",
            f"4. 共振：最近{p['lookback_days']}天内三个金叉最大间隔<= {p['resonance_days']}天",
        ]

    def select_stocks(self, df: pd.DataFrame, stock_name: str = "") -> list:
        if df.empty or len(df) < self.params["lookback_days"]:
            return []

        latest = df.iloc[-1]  # 升序，最新在末尾
        latest_date = str(latest["date"])[:10]

        if latest["volume"] <= 0 or pd.isna(latest["close"]):
            return []
        if latest["close"] < latest["ma_short"] or latest["close"] < latest["ma_long"]:
            return []
        if latest["volume_ratio"] < 1.0:
            return []

        lookback = df.tail(self.params["lookback_days"])
        ma_dates = lookback.loc[lookback["ma_cross_signal"], "date"]
        kdj_dates = lookback.loc[lookback["kdj_cross_signal"], "date"]
        macd_dates = lookback.loc[lookback["macd_cross_signal"], "date"]
        if ma_dates.empty or kdj_dates.empty or macd_dates.empty:
            return []

        ma_date = pd.to_datetime(ma_dates.iloc[-1])
        kdj_date = pd.to_datetime(kdj_dates.iloc[-1])
        macd_date = pd.to_datetime(macd_dates.iloc[-1])
        max_diff = abs((max(ma_date, kdj_date, macd_date) - min(ma_date, kdj_date, macd_date)).days)
        if max_diff > self.params["resonance_days"]:
            return []

        key_date = min(ma_date, kdj_date, macd_date).strftime("%Y-%m-%d")

        return [{
            "date": latest_date,
            "close": round(float(latest["close"]), 2),
            "key_date": key_date,
            "key_date_type": "多金叉共振日",
            "max_time_diff": max_diff,
            "ma_short": round(float(latest["ma_short"]), 2),
            "ma_long": round(float(latest["ma_long"]), 2),
            "volume_ratio": round(float(latest["volume_ratio"]), 2),
            "reasons": ["均线金叉", "KDJ金叉", "MACD金叉", "多指标共振"],
        }]
