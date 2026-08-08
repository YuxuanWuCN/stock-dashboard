"""v2.5 狩猎场与市场温度单元测试。

- 支撑位 4 种计算方法（可手算小样本复核）
- 买点判断（买入区间/跌破/远离）
- 狩猎场构建
- 市场温度（mock 行情数据 + 阈值映射）
"""

import json
from pathlib import Path

import akshare as ak
import pandas as pd
import pytest

from src.strategies.hunting_ground import BuyPointJudge, HuntingGround, SupportCalculator
from src.strategies.market_temperature import MarketTemperature, MarketTemperatureError


def _make_df(closes, opens=None):
    n = len(closes)
    opens = opens or [c * 0.99 for c in closes]
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n).strftime("%Y-%m-%d"),
        "open": opens,
        "high": [max(o, c) * 1.01 for o, c in zip(opens, closes)],
        "low": [min(o, c) * 0.99 for o, c in zip(opens, closes)],
        "close": closes,
        "volume": [100000] * n,
    })


# ------------------------------------------------------------
# 支撑位计算（手算复核）
# ------------------------------------------------------------

def test_support_ma20():
    """ma20 = 最近 20 日收盘均值。"""
    closes = list(range(1, 31))  # 1..30
    df = _make_df([float(c) for c in closes])
    support = SupportCalculator().calculate(df, "ma20")
    # 最近 20 日 = 11..30，均值 = 20.5
    assert support is not None
    assert abs(support - 20.5) < 1e-9


def test_support_key_close_5():
    """key_close_5 = 近 5 日收盘最小值。"""
    closes = [10.0, 9.5, 9.2, 9.8, 10.5, 11.0, 10.8]
    df = _make_df(closes)
    support = SupportCalculator().calculate(df, "key_close_5")
    assert support == 9.2  # 最近 5 日 [9.2, 9.8, 10.5, 11.0, 10.8] 的最小值


def test_support_key_open():
    """key_open = 近 5 日开盘最小值。"""
    closes = [10.0] * 7
    opens = [10.0, 9.8, 9.5, 9.7, 10.0, 10.1, 10.2]
    df = _make_df(closes, opens)
    support = SupportCalculator().calculate(df, "key_open")
    assert support == 9.5  # 最近 5 日开盘 [9.5, 9.7, 10.0, 10.1, 10.2] 的最小值


def test_support_insufficient_data():
    """数据不足返回 None。"""
    df = _make_df([10.0, 10.5])
    assert SupportCalculator().calculate(df, "ma20") is None
    assert SupportCalculator().calculate(df, "key_close_5") is None


def test_unknown_method_falls_back_to_ma20():
    """未知方法回退 ma20。"""
    closes = [float(c) for c in range(1, 26)]
    df = _make_df(closes)
    assert SupportCalculator().calculate(df, "no_such_method") is not None


# ------------------------------------------------------------
# 买点判断
# ------------------------------------------------------------

def test_buy_zone():
    """当前价在支撑位上方 0~3% 为买入区间。"""
    judge = BuyPointJudge().judge(10.2, 10.0)
    assert judge["in_buy_zone"] is True
    assert judge["action"] == "buy_zone"
    assert judge["distance_pct"] == 2.0


def test_above_support():
    """远离支撑位。"""
    judge = BuyPointJudge().judge(12.0, 10.0)
    assert judge["in_buy_zone"] is False
    assert judge["action"] == "above_support"


def test_below_support():
    """跌破支撑位。"""
    judge = BuyPointJudge().judge(9.5, 10.0)
    assert judge["in_buy_zone"] is False
    assert judge["action"] == "below_support"


def test_near_support():
    """接近支撑位（3~6%）。"""
    judge = BuyPointJudge().judge(10.5, 10.0)
    assert judge["action"] == "near_support"


def test_insufficient_data():
    """无效价格返回 insufficient_data。"""
    judge = BuyPointJudge().judge(0.0, 10.0)
    assert judge["action"] == "insufficient_data"


# ------------------------------------------------------------
# 狩猎场
# ------------------------------------------------------------

def test_hunting_ground_build():
    """狩猎场构建：选股结果 + 支撑位 + 买点。"""
    df = _make_df([float(c) for c in range(1, 31)])
    selection = {
        "results": {
            "MultiGoldenCrossStrategy": [
                {"code": "600519", "name": "茅台", "signals": [{"date": "2026-01-30", "close": 30.0}]},
            ]
        }
    }
    hg = HuntingGround()
    out = hg.build(selection, {"600519": df}, current_prices={"600519": 20.5})
    entries = out["MultiGoldenCrossStrategy"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["support"] == 20.5  # ma20 = (11+...+30)/20 = 20.5
    assert entry["buy_judge"]["in_buy_zone"] is True


# ------------------------------------------------------------
# 市场温度
# ------------------------------------------------------------

class _FakeSpot:
    def __init__(self, df):
        self.df = df

    def __getitem__(self, key):
        return self.df[key]


def test_temperature_thresholds():
    """阈值映射：80+ 活跃 / 65+ 正常 / 50+ 偏冷 / 30+ 寒冷 / 15+ 冰封。"""
    mt = MarketTemperature()
    assert mt._status_for(85) == ("活跃", 1.0)
    assert mt._status_for(70) == ("正常", 0.8)
    assert mt._status_for(55) == ("偏冷", 0.5)
    assert mt._status_for(35) == ("寒冷", 0.25)
    assert mt._status_for(20) == ("冰封", 0.1)
    assert mt._status_for(5) == ("极端", 0.0)


def test_temperature_hot_market(monkeypatch):
    """大涨行情 → 温度高。"""
    n = 500
    import numpy as np
    df = pd.DataFrame({
        "涨跌幅": np.concatenate([np.full(400, 2.5), np.full(100, -1.0)]),
        "成交额": np.full(n, 3.0e8),  # 合计 1.5 万亿
    })
    monkeypatch.setattr(ak, "stock_zh_a_spot_em", lambda: df)
    result = MarketTemperature().calculate()
    # 涨跌比 80%、无跌停、成交额 1.5 万亿 → 温度应较高
    assert result["temperature"] >= 60
    assert result["status"] in ("活跃", "正常")
    assert result["dimensions"]["up_count"] == 400


def test_temperature_cold_market(monkeypatch):
    """大跌行情 → 温度低。"""
    n = 500
    import numpy as np
    df = pd.DataFrame({
        "涨跌幅": np.concatenate([np.full(50, 1.0), np.full(450, -3.5)]),
        "成交额": np.full(n, 1.0e8),  # 合计 0.5 万亿
    })
    monkeypatch.setattr(ak, "stock_zh_a_spot_em", lambda: df)
    result = MarketTemperature().calculate()
    # 跌多涨少 + 成交额低 → 温度应明显低于中性（50），且低于大涨场景
    assert result["temperature"] < 50
    assert result["status"] in ("寒冷", "冰封", "极端", "偏冷")
    assert result["dimensions"]["down_count"] == 450


def test_temperature_api_error(monkeypatch):
    """API 失败抛 DataNotAvailableError。"""
    def _fail():
        raise RuntimeError("network down")

    monkeypatch.setattr(ak, "stock_zh_a_spot_em", _fail)
    with pytest.raises(MarketTemperatureError):
        MarketTemperature().calculate()
