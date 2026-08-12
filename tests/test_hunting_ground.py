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
    """主源与兜底源都失败时抛 DataNotAvailableError。"""
    def _fail():
        raise RuntimeError("network down")

    monkeypatch.setattr(ak, "stock_zh_a_spot_em", _fail)
    monkeypatch.setattr(ak, "stock_market_activity_legu", _fail)
    with pytest.raises(MarketTemperatureError):
        MarketTemperature().calculate()


def test_temperature_legu_fallback(monkeypatch):
    """东财失败时自动切换到乐咕+腾讯兜底源。"""
    def _fail():
        raise RuntimeError("network down")

    activity = pd.DataFrame({
        "item": ["上涨", "下跌", "跌停", "真实涨停", "平盘", "停牌"],
        "value": [400.0, 100.0, 0.0, 8.0, 0.0, 0.0],
    })
    monkeypatch.setattr(ak, "stock_zh_a_spot_em", _fail)
    monkeypatch.setattr(ak, "stock_market_activity_legu", lambda: activity)
    monkeypatch.setattr(MarketTemperature, "_fetch_market_amount", staticmethod(lambda: None))

    result = MarketTemperature().calculate()
    assert result["source"] == "akshare_legu+tencent"
    assert result["dimensions"]["up_count"] == 400
    assert result["dimensions"]["down_count"] == 100
    assert result["temperature"] >= 0


# ------------------------------------------------------------
# 均值回归预测因子
# ------------------------------------------------------------

def test_mean_reversion_no_history_no_damping():
    """无历史时 damping=1.0（不降仓）。"""
    d, info = MarketTemperature.mean_reversion_factor(88.0, [])
    assert d == 1.0
    assert info["note"] == "no_history"


def test_mean_reversion_normal_no_damping():
    """温度贴近近期均值时不降仓。"""
    history = [70, 72, 68, 75, 71, 69, 74, 70, 73, 71]  # 均值约 71
    d, info = MarketTemperature.mean_reversion_factor(72.0, history)
    assert d == 1.0
    assert info["note"] == "normal"


def test_mean_reversion_overheat_damps():
    """温度显著高于近期均值（>10 且当日≥65）时按偏离度降仓。"""
    history = [60, 62, 58, 61, 59, 63, 60, 62, 61, 60]  # 均值约 60.6
    d, info = MarketTemperature.mean_reversion_factor(88.0, history)
    # 偏离 27.4 → damping = 1 - 17.4*0.008 = 0.86
    assert d < 1.0
    assert 0.8 <= d <= 0.9
    assert info["note"] == "overheat"
    assert info["mean20"] > 60 and info["mean20"] < 61


def test_mean_reversion_extreme_overheat_floor():
    """极端偏离时 damping 不低于 0.6 下限。"""
    history = [50, 52, 51, 49, 53, 50, 52, 51, 50, 52]  # 均值约 51
    d, info = MarketTemperature.mean_reversion_factor(100.0, history)
    assert d >= 0.6
    assert d < 0.9


def test_mean_reversion_cold_notes_but_no_damp():
    """温度低于均值时不降仓（低温已由 6 档仓位系数处理）。"""
    history = [70, 72, 71, 73, 69, 74, 70, 71, 72, 70]  # 均值约 71
    d, info = MarketTemperature.mean_reversion_factor(50.0, history)
    assert d == 1.0
    assert info["note"] == "cold_below_mean"


def test_mean_reversion_low_mean_no_damp():
    """近期均值≤30（长期冰封市场）时不触发过热降仓。"""
    history = [20, 22, 25, 21, 24, 23, 20, 26, 22, 21]
    d, info = MarketTemperature.mean_reversion_factor(80.0, history)
    assert d == 1.0
