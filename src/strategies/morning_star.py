"""启明星策略 —— 三根 K 线底部反转形态（移植自 KHunter）。

形态定义（在下跌趋势后）：
1. 第一根：大阴线（跌幅 <= -2%）
2. 第二根：小实体/十字星（实体占比小，开盘收盘接近）
3. 第三根：阳线，收盘进入第一根实体上半部分
"""

import pandas as pd

from src.strategies.base_strategy import BaseStrategy


class MorningStarStrategy(BaseStrategy):
    """启明星策略。"""

    def __init__(self, params=None):
        default_params = {
            "lookback_days": 30,
            "decline_threshold": -10.0,   # 形态出现前累计跌幅
            "big_negative_pct": -2.0,     # 第一根阴线跌幅
            "small_body_pct": 0.5,        # 第二根实体占价格比例上限（%）
        }
        if params:
            default_params.update(params)
        super().__init__("启明星", default_params)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or len(df) < 4:
            return pd.DataFrame()
        result = df.copy()
        result["change_pct"] = result["close"].pct_change() * 100.0
        result["body_pct"] = (result["close"] - result["open"]).abs() / result["close"] * 100.0
        return result

    def get_selection_criteria(self) -> list:
        return [
            "1. 形态前 30 日累计跌幅 ≥ 10%（超跌背景）",
            "2. 第一根：大阴线（跌幅≥2%）",
            "3. 第二根：小实体十字星",
            "4. 第三根：阳线收复第一根实体一半以上",
        ]

    def select_stocks(self, df: pd.DataFrame, stock_name: str = "") -> list:
        p = self.params
        if df.empty or len(df) < p["lookback_days"]:
            return []

        lookback = df.tail(p["lookback_days"])
        latest = df.iloc[-1]
        latest_date = str(latest["date"])[:10]
        if latest["volume"] <= 0 or pd.isna(latest["close"]):
            return []

        # 背景：lookback 内累计跌幅超阈值（从高点算）
        peak = float(lookback["high"].max())
        drawdown = (float(latest["close"]) - peak) / peak * 100.0
        if drawdown > p["decline_threshold"]:  # drawdown 为负，> -10 说明跌得不够
            return []

        # 最近三根 K 线构成启明星
        if len(df) < 3:
            return []
        d1, d2, d3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]

        if d1["change_pct"] > p["big_negative_pct"]:      # 第一根需为大阴线
            return []
        if d2["body_pct"] > p["small_body_pct"]:          # 第二根需为小实体
            return []
        if d3["close"] <= d3["open"]:                     # 第三根需为阳线
            return []

        # 第三根收盘进入第一根实体上半部分
        first_open, first_close = float(d1["open"]), float(d1["close"])
        upper_half = first_open - (first_open - first_close) / 2.0
        if float(d3["close"]) < upper_half:
            return []

        key_date = str(d1["date"])[:10]
        return [{
            "date": latest_date,
            "close": round(float(latest["close"]), 2),
            "key_date": key_date,
            "key_date_type": "启明星第一日",
            "drawdown": round(drawdown, 2),
            "reasons": ["超跌背景", "大阴线", "十字星", "阳线确认"],
        }]
