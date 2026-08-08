"""v2.5 狩猎场模块 —— 移植自 KHunter trading/khunter_support_calculator.py 与
khunter_buy_point_judge.py，去除数据库依赖，输出 JSON。

流程：选股结果 → 计算支撑位（ma20/关键收盘价/关键开盘价）→ 买点判断
（当前价相对支撑位的距离）→ 跟踪收益。
"""

import logging
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 支撑位计算方法映射
SUPPORT_METHODS = {
    "ma20": "_calc_ma20",
    "key_close_5": "_calc_key_close_5",
    "key_open": "_calc_key_open",
    "key_close": "_calc_key_close",
}

DEFAULT_SUPPORT_METHOD = "ma20"


class SupportCalculator:
    """支撑位计算器：4 种方法。"""

    @staticmethod
    def _calc_ma20(df: pd.DataFrame) -> Optional[float]:
        """20 日均线（最近 20 个交易日收盘均值）。"""
        if df is None or len(df) < 20:
            return None
        tail = df.tail(20)
        return float(tail["close"].mean())

    @staticmethod
    def _calc_key_close_5(df: pd.DataFrame) -> Optional[float]:
        """近 5 日关键收盘价：5 日收盘的最小值（回调支撑）。"""
        if df is None or len(df) < 5:
            return None
        return float(df["close"].tail(5).min())

    @staticmethod
    def _calc_key_open(df: pd.DataFrame) -> Optional[float]:
        """近 5 日关键开盘价：5 日开盘的最小值。"""
        if df is None or len(df) < 5:
            return None
        return float(df["open"].tail(5).min())

    @staticmethod
    def _calc_key_close(df: pd.DataFrame) -> Optional[float]:
        """关键收盘价：最近 20 日内收盘价低于均线后出现反弹的最低收盘价。"""
        if df is None or len(df) < 20:
            return None
        tail = df.tail(20)
        ma20 = tail["close"].mean()
        below_ma = tail[tail["close"] < ma20]
        if below_ma.empty:
            return float(tail["close"].min())
        return float(below_ma["close"].min())

    def calculate(self, df: pd.DataFrame, method: str = DEFAULT_SUPPORT_METHOD) -> Optional[float]:
        """按指定方法计算支撑位。"""
        func_name = SUPPORT_METHODS.get(method)
        if func_name is None:
            func_name = SUPPORT_METHODS[DEFAULT_SUPPORT_METHOD]
        return getattr(self, func_name)(df)


class BuyPointJudge:
    """买点判断：当前价相对支撑位的距离。"""

    # 买入区间：当前价在支撑位上方 0%~3% 内视为买入区间
    BUY_ZONE_PCT = 3.0

    def judge(self, current_price: float, support_price: float,
              tolerance_pct: float = 3.0) -> Dict:
        """判断当前价格与支撑位的关系。

        Returns:
            {in_buy_zone, distance_pct, support_price, current_price, action}
        """
        if support_price is None or support_price <= 0 or current_price is None or current_price <= 0:
            return {
                "in_buy_zone": False,
                "distance_pct": None,
                "support_price": support_price,
                "current_price": current_price,
                "action": "insufficient_data",
            }
        distance_pct = (current_price - support_price) / support_price * 100.0
        in_buy_zone = 0.0 <= distance_pct <= self.BUY_ZONE_PCT
        if distance_pct < 0:
            action = "below_support"      # 跌破支撑
        elif in_buy_zone:
            action = "buy_zone"           # 买入区间
        elif distance_pct <= tolerance_pct * 2:
            action = "near_support"       # 接近支撑
        else:
            action = "above_support"      # 远离支撑
        return {
            "in_buy_zone": in_buy_zone,
            "distance_pct": round(distance_pct, 2),
            "support_price": round(support_price, 2),
            "current_price": round(current_price, 2),
            "action": action,
        }


class HuntingGround:
    """狩猎场：对选股结果计算支撑位、买点并生成跟踪数据。"""

    def __init__(self, support_methods: Optional[Dict[str, str]] = None):
        """
        Args:
            support_methods: {strategy_name: support_method}，缺省用默认方法
        """
        self.support_calculator = SupportCalculator()
        self.buy_judge = BuyPointJudge()
        self.support_methods = support_methods or {}

    def _support_method_for(self, strategy_name: str) -> str:
        return self.support_methods.get(strategy_name, DEFAULT_SUPPORT_METHOD)

    def build(self, selection_result: Dict, stock_data: Dict[str, pd.DataFrame],
              current_prices: Optional[Dict[str, float]] = None) -> Dict:
        """构建狩猎场。

        Args:
            selection_result: run_strategies 的输出（results: {strategy: [signals]})
            stock_data: {code: 升序 DataFrame}
            current_prices: {code: 当前价}，缺省用最新收盘价

        Returns:
            {strategy: [{code, name, signals, support, buy_judge}]}
        """
        output = {}
        for strategy_name, items in selection_result.get("results", {}).items():
            method = self._support_method_for(strategy_name)
            entries = []
            for item in items:
                code = item["code"]
                df = stock_data.get(code)
                if df is None or df.empty:
                    continue
                support = self.support_calculator.calculate(df, method)
                price = current_prices.get(code) if current_prices else None
                if price is None:
                    price = float(df["close"].iloc[-1])
                judge = self.buy_judge.judge(price, support)
                entries.append({
                    "code": code,
                    "name": item.get("name", ""),
                    "signals": item.get("signals", []),
                    "support_method": method,
                    "support": judge["support_price"],
                    "buy_judge": judge,
                })
            output[strategy_name] = entries
        return output
