"""涨停回马枪策略 —— 涨停后回调再次启动（移植自 KHunter）。

选股条件：
1. 近期（lookback_days 内）出现涨停（涨幅 >= limit_up_pct）
2. 涨停后回调：回调幅度不超过 pullback_max_pct
3. 当前企稳：收盘价站上 5 日均线
"""

import pandas as pd

from src.strategies.base_strategy import BaseStrategy


class LimitUpPullbackStrategy(BaseStrategy):
    """涨停回马枪策略。"""

    def __init__(self, params=None):
        default_params = {
            "limit_up_pct": 9.8,
            "pullback_days": 5,
            "pullback_max_pct": 8.0,
            "lookback_days": 10,
        }
        if params:
            default_params.update(params)
        super().__init__("涨停回马枪", default_params)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or len(df) < 2:
            return pd.DataFrame()
        result = df.copy()
        result["ma5"] = result["close"].rolling(5, min_periods=1).mean()
        result["change_pct"] = result["close"].pct_change() * 100.0
        return result

    def get_selection_criteria(self) -> list:
        p = self.params
        return [
            f"1. 近{p['lookback_days']}天内出现涨停（涨幅≥{p['limit_up_pct']}%）",
            f"2. 涨停后回调幅度≤{p['pullback_max_pct']}%",
            "3. 当前收盘价站上5日均线（企稳）",
        ]

    def select_stocks(self, df: pd.DataFrame, stock_name: str = "") -> list:
        if df.empty or len(df) < self.params["lookback_days"]:
            return []

        p = self.params
        lookback = df.tail(p["lookback_days"])
        if lookback.empty:
            return []

        latest = df.iloc[-1]
        latest_date = str(latest["date"])[:10]
        if latest["volume"] <= 0 or pd.isna(latest["close"]):
            return []

        # 条件1：lookback 内出现涨停
        limit_days = lookback[lookback["change_pct"] >= p["limit_up_pct"]]
        if limit_days.empty:
            return []

        # 条件2：从涨停日收盘算起，回调幅度不超过阈值
        limit_day_close = float(limit_days.iloc[-1]["close"])
        min_close_after = float(lookback["close"].min())
        drawdown = (limit_day_close - min_close_after) / limit_day_close * 100.0
        if drawdown > p["pullback_max_pct"]:
            return []

        # 条件3：当前站上 5 日均线
        if latest["close"] < latest["ma5"]:
            return []

        key_date = str(limit_days.iloc[-1]["date"])[:10]
        return [{
            "date": latest_date,
            "close": round(float(latest["close"]), 2),
            "key_date": key_date,
            "key_date_type": "涨停日",
            "drawdown": round(drawdown, 2),
            "reasons": ["近期涨停", "回调企稳", "站上5日均线"],
        }]
