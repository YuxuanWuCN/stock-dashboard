"""v2.5 市场温度模块 —— 移植自 KHunter utils/market_temperature.py，适配 akshare。

四维度市场温度：涨跌家数比 35% + 跌停家数 35% + 昨日涨停表现 20% + 成交额位置 10%。
状态阈值与仓位系数沿用 KHunter（活跃/正常/偏冷/寒冷/冰封/极端）。
"""

import logging
from typing import Dict, Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


class MarketTemperatureError(Exception):
    """市场温度计算异常。"""


class DataNotAvailableError(MarketTemperatureError):
    """数据不可用异常（非交易日或 API 无数据）。"""


class MarketTemperature:
    """市场温度计算器（A 股，akshare 东财实时行情）。"""

    # 权重
    WEIGHT_UP_DOWN_RATIO = 0.35
    WEIGHT_LIMIT_DOWN = 0.35
    WEIGHT_LIMIT_UP_PERFORMANCE = 0.20
    WEIGHT_VOLUME = 0.10

    # 温度 → 状态/仓位系数
    STATUS_THRESHOLDS = [
        (80, "活跃", 1.0),
        (65, "正常", 0.8),
        (50, "偏冷", 0.5),
        (30, "寒冷", 0.25),
        (15, "冰封", 0.1),
        (0, "极端", 0.0),
    ]

    def calculate(self) -> Dict:
        """计算当日市场温度（基于东财实时全市场行情）。"""
        try:
            spot = ak.stock_zh_a_spot_em()
        except Exception as exc:
            raise DataNotAvailableError(f"获取全市场行情失败: {exc}") from exc

        if spot is None or spot.empty:
            raise DataNotAvailableError("全市场行情为空")

        # 涨跌家数比（权重 35%）
        up_count = int((spot["涨跌幅"] > 0).sum())
        down_count = int((spot["涨跌幅"] < 0).sum())
        total = up_count + down_count
        up_down_ratio = up_count / total if total > 0 else 0.5
        # 0.3~0.7 映射到 0~100
        ratio_score = max(0.0, min(100.0, (up_down_ratio - 0.3) / 0.4 * 100.0))

        # 跌停家数（权重 35%）：跌停越多温度越低
        limit_down_count = int((spot["涨跌幅"] <= -9.8).sum())
        limit_down_score = max(0.0, 100.0 - limit_down_count * 10.0)

        # 成交额位置（权重 10%）：当日总成交额
        amount = float(spot["成交额"].sum())
        # 用 1 万亿元作为中性参考（A 股常态区间 0.6~1.5 万亿）
        volume_score = max(0.0, min(100.0, amount / 1.0e12 * 100.0))

        # 昨日涨停表现（权重 20%）：当日涨幅靠前股票的强度近似
        top_gainers = spot.nlargest(20, "涨跌幅")["涨跌幅"].mean()
        limit_up_perf_score = max(0.0, min(100.0, 50.0 + float(top_gainers) * 5.0))

        temperature = (
            self.WEIGHT_UP_DOWN_RATIO * ratio_score
            + self.WEIGHT_LIMIT_DOWN * limit_down_score
            + self.WEIGHT_LIMIT_UP_PERFORMANCE * limit_up_perf_score
            + self.WEIGHT_VOLUME * volume_score
        )

        status, position_ratio = self._status_for(temperature)

        return {
            "temperature": round(temperature, 1),
            "status": status,
            "position_ratio": position_ratio,
            "dimensions": {
                "up_down_ratio": round(up_down_ratio, 4),
                "up_count": up_count,
                "down_count": down_count,
                "limit_down_count": limit_down_count,
                "top_gainers_avg": round(float(top_gainers), 2),
                "total_amount_yi": round(amount / 1.0e8, 0),
            },
            "source": "akshare_stock_zh_a_spot_em",
        }

    @staticmethod
    def _status_for(temperature: float):
        """按温度阈值返回 (状态, 仓位系数)。"""
        for threshold, status, ratio in MarketTemperature.STATUS_THRESHOLDS:
            if temperature >= threshold:
                return status, ratio
        return MarketTemperature.STATUS_THRESHOLDS[-1][1], MarketTemperature.STATUS_THRESHOLDS[-1][2]
