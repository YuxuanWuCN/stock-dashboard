"""v2.5 市场温度模块 —— 移植自 KHunter utils/market_temperature.py，适配 akshare。

四维度市场温度：涨跌家数比 35% + 跌停家数 35% + 昨日涨停表现 20% + 成交额位置 10%。
状态阈值与仓位系数沿用 KHunter（活跃/正常/偏冷/寒冷/冰封/极端）。
"""

import logging
import time
import traceback
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
        """计算当日市场温度（优先东财实时全市场行情，失败时用乐咕+腾讯兜底）。"""
        spot = self._try_fetch_spot_em()
        if spot is None or spot.empty:
            logger.warning("东财全市场行情不可用，切换乐咕+腾讯兜底源")
            return self._calculate_legu_fallback()
        return self._calculate_from_spot(spot)

    @staticmethod
    def _try_fetch_spot_em() -> Optional[pd.DataFrame]:
        """东财全市场实时行情（失败返回 None，最多重试 2 次）。"""
        for attempt in range(3):
            try:
                spot = ak.stock_zh_a_spot_em()
                if spot is not None and not spot.empty:
                    return spot
            except Exception:
                logger.warning("东财全市场行情第 %d 次获取失败: %s", attempt + 1, traceback.format_exc().splitlines()[-1] if traceback.format_exc().splitlines() else "")
                if attempt < 2:
                    time.sleep(1)
        return None

    def _calculate_from_spot(self, spot: pd.DataFrame) -> Dict:
        """基于东财全市场快照计算四维度温度。"""
        up_count = int((spot["涨跌幅"] > 0).sum())
        down_count = int((spot["涨跌幅"] < 0).sum())
        total = up_count + down_count
        up_down_ratio = up_count / total if total > 0 else 0.5
        # 0.3~1.0 映射到 0~100：涨跌比 7:3 时 57 分，1:0 才到 100（避免普涨天顶格）
        ratio_score = max(0.0, min(100.0, (up_down_ratio - 0.3) / 0.7 * 100.0))

        # 跌停家数（权重 35%）：跌停越多温度越低
        limit_down_count = int((spot["涨跌幅"] <= -9.8).sum())
        limit_down_score = max(0.0, 100.0 - limit_down_count * 10.0)

        # 成交额位置（权重 10%）：当日总成交额，2 万亿封顶（避免放量天顶格）
        amount = float(spot["成交额"].sum())
        volume_score = max(0.0, min(100.0, amount / 2.0e12 * 100.0))

        # 昨日涨停表现（权重 20%）：当日涨幅靠前股票的强度近似，8% 封顶
        top_gainers = spot.nlargest(20, "涨跌幅")["涨跌幅"].mean()
        limit_up_perf_score = max(0.0, min(100.0, 50.0 + float(top_gainers) * 6.25))

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

    def _calculate_legu_fallback(self) -> Dict:
        """乐咕市场活跃度 + 腾讯指数成交额 兜底计算（东财不可用时）。"""
        try:
            activity = ak.stock_market_activity_legu()
        except Exception as exc:
            raise DataNotAvailableError(f"乐咕市场活跃度获取失败: {exc}") from exc
        if activity is None or activity.empty:
            raise DataNotAvailableError("乐咕市场活跃度为空")

        def _value(name: str) -> float:
            row = activity[activity["item"] == name]
            if row.empty:
                return 0.0
            try:
                return float(row.iloc[0]["value"])
            except (TypeError, ValueError):
                return 0.0

        up_count = int(_value("上涨"))
        down_count = int(_value("下跌"))
        limit_down_count = int(_value("跌停"))
        limit_up_count = int(_value("真实涨停"))
        total = up_count + down_count
        up_down_ratio = up_count / total if total > 0 else 0.5
        ratio_score = max(0.0, min(100.0, (up_down_ratio - 0.3) / 0.7 * 100.0))
        limit_down_score = max(0.0, 100.0 - limit_down_count * 10.0)

        amount_yuan = self._fetch_market_amount()
        if amount_yuan is None:
            volume_score = 50.0  # 无成交额时给中性分
        else:
            volume_score = max(0.0, min(100.0, amount_yuan / 2.0e12 * 100.0))

        # 用真实涨停家数近似“涨停表现”强度，40 家封顶
        limit_up_perf_score = max(0.0, min(100.0, 50.0 + limit_up_count * 1.25))

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
                "top_gainers_avg": round(limit_up_count * 0.12, 2),
                "total_amount_yi": round(amount_yuan / 1.0e8, 0) if amount_yuan else None,
            },
            "source": "akshare_legu+tencent",
        }

    @staticmethod
    def _fetch_market_amount() -> Optional[float]:
        """腾讯行情接口获取沪深两市成交额（元）；失败返回 None。"""
        try:
            import requests
            resp = requests.get(
                "https://qt.gtimg.cn/q=sh000001,sz399001",
                timeout=10,
            )
            resp.raise_for_status()
            total = 0.0
            for line in resp.text.strip().split(";"):
                if "=" not in line:
                    continue
                parts = line.split("~")
                if len(parts) <= 35:
                    continue
                tail = parts[35].split("/")
                if len(tail) >= 3:
                    total += float(tail[2])
            return total if total > 0 else None
        except Exception:
            logger.warning("腾讯指数成交额获取失败: %s", traceback.format_exc().splitlines()[-1] if traceback.format_exc().splitlines() else "")
            return None

    @staticmethod
    def _status_for(temperature: float):
        """按温度阈值返回 (状态, 仓位系数)。"""
        for threshold, status, ratio in MarketTemperature.STATUS_THRESHOLDS:
            if temperature >= threshold:
                return status, ratio
        return MarketTemperature.STATUS_THRESHOLDS[-1][1], MarketTemperature.STATUS_THRESHOLDS[-1][2]

    @staticmethod
    def mean_reversion_factor(temperature: float, history: list) -> tuple:
        """均值回归预测因子：温度相对近 20 日均值的偏离度。

        理念：今天的狂热不预测明天的狂热。当日温度显著高于近期均值
        （>10 度且当日≥65）时，按偏离度线性降仓（最多降 40%），
        避免在情绪顶部满仓追高；趋势延续（偏离小）不降仓。

        返回 (damping, info)；history 为空或均值≤30 时 damping=1.0（不降）。
        """
        if temperature is None or not history:
            return 1.0, {"mean20": None, "overheat": 0.0, "percentile": None, "note": "no_history"}
        vals = [float(h) for h in history if h is not None]
        if not vals:
            return 1.0, {"mean20": None, "overheat": 0.0, "percentile": None, "note": "no_history"}
        mean20 = sum(vals) / len(vals)
        overheat = temperature - mean20
        percentile = sum(1 for v in vals if v <= temperature) / len(vals) * 100.0

        damping = 1.0
        note = "normal"
        if mean20 > 30 and temperature >= 65 and overheat > 10:
            damping = max(0.6, 1.0 - (overheat - 10.0) * 0.008)
            note = "overheat" if percentile >= 90 else "hot_above_mean"
        elif mean20 > 30 and temperature < mean20 - 10:
            note = "cold_below_mean"
        return round(damping, 3), {
            "mean20": round(mean20, 1),
            "overheat": round(overheat, 1),
            "percentile": round(percentile, 1),
            "note": note,
        }
