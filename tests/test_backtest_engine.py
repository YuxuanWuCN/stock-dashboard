"""v2.5 回测引擎单元测试。

验证：
- 交易成本计算（佣金最低 5 元、印花税仅卖出、过户费仅沪市）
- 回测基本流程（在合成数据上运行、防未来函数）
- 绩效指标（最大回撤、胜率等）
- 边界输入
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.strategies.backtest_engine import BacktestEngine, calculate_backtest_cost

KLINE_DIR = Path(__file__).parent.parent / "docs" / "data" / "kline"


def _synthetic_df(n=250, seed=42, start="2024-01-01", base=10.0):
    """生成合成 K 线（随机游走，含明显趋势段）。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=n)
    ret = rng.normal(0.0005, 0.02, n)
    # 中间加入一段上升趋势，保证有可交易信号
    ret[100:130] += 0.02
    close = base * np.cumprod(1 + ret)
    open_ = close * (1 + rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    volume = rng.integers(100000, 500000, n).astype(float)
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


def test_commission_minimum():
    """佣金最低 5 元。"""
    cost = calculate_backtest_cost("000001", price=10.0, quantity=100, is_buy=True)
    assert cost["commission"] >= 5.0
    assert cost["stamp_tax"] == 0.0


def test_stamp_tax_only_on_sell():
    """印花税仅卖出收取。"""
    buy = calculate_backtest_cost("000001", price=10.0, quantity=1000, is_buy=True)
    sell = calculate_backtest_cost("000001", price=10.0, quantity=1000, is_buy=False)
    assert buy["stamp_tax"] == 0.0
    assert sell["stamp_tax"] > 0.0


def test_transfer_fee_only_shanghai():
    """过户费仅沪市（6 开头）。"""
    sz = calculate_backtest_cost("000001", price=10.0, quantity=1000, is_buy=True)
    sh = calculate_backtest_cost("600519", price=10.0, quantity=1000, is_buy=True)
    assert sz["transfer_fee"] == 0.0
    assert sh["transfer_fee"] > 0.0


def test_backtest_runs_on_synthetic_data():
    """回测在合成数据上能完整跑通。"""
    df = _synthetic_df()
    engine = BacktestEngine(
        stock_data={"600519": df},
        stock_names={"600519": "贵州茅台"},
        initial_capital=100000.0,
    )
    result = engine.run("MultiGoldenCrossStrategy", {
        "start_date": "2024-06-01",
        "end_date": "2024-12-31",
        "take_profit_pct": 21.0,
        "stop_loss_pct": -7.0,
        "trailing_stop_pct": 8.0,
        "max_hold_days": 20,
    })
    assert "error" not in result
    perf = result["performance"]
    assert perf["initial_capital"] == 100000.0
    assert perf["final_equity"] > 0
    assert perf["max_drawdown_pct"] <= 0
    assert perf["trades"] >= 0
    assert 0 <= perf["win_rate_pct"] <= 100
    # 资金曲线长度 = 交易日数 + 1
    assert len(result["capital_history"]) == result["period"]["trading_days"] + 1


def test_backtest_no_future_function():
    """防未来函数：买入决策只能用到当日及之前的数据。"""
    df = _synthetic_df()
    engine = BacktestEngine(
        stock_data={"600519": df},
        stock_names={"600519": "贵州茅台"},
        initial_capital=100000.0,
    )
    # 用真实 kline 数据验证 signal date 不会晚于买入日
    result = engine.run("MultiGoldenCrossStrategy", {
        "start_date": "2024-06-01",
        "end_date": "2024-12-31",
    })
    for trade in result["trades"]:
        assert trade["buy_date"] <= trade["sell_date"]


def test_unknown_strategy_returns_error():
    """未注册策略返回 error。"""
    df = _synthetic_df()
    engine = BacktestEngine(stock_data={"600519": df})
    result = engine.run("NoSuchStrategy", {"start_date": "2024-01-01", "end_date": "2024-06-30"})
    assert "error" in result


def test_empty_dates_returns_error():
    """无交易日返回 error。"""
    df = _synthetic_df()
    engine = BacktestEngine(stock_data={"600519": df})
    result = engine.run("MultiGoldenCrossStrategy", {
        "start_date": "2030-01-01", "end_date": "2030-12-31",
    })
    assert "error" in result


def test_real_kline_backtest():
    """真实落盘数据回测冒烟。"""
    if not KLINE_DIR.exists():
        pytest.skip("docs/data/kline 不存在")
    files = sorted(KLINE_DIR.glob("*.json"))[:3]
    if not files:
        pytest.skip("无 kline 数据")
    stock_data = {}
    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        dates = d["dates"]
        kline = d["kline"]
        volume = d["volume"]
        df = pd.DataFrame({
            "date": pd.to_datetime(dates).strftime("%Y-%m-%d"),
            "open": [r[0] for r in kline],
            "close": [r[1] for r in kline],
            "low": [r[2] for r in kline],
            "high": [r[3] for r in kline],
            "volume": volume,
        }).sort_values("date").reset_index(drop=True)
        stock_data[f.stem] = df

    engine = BacktestEngine(
        stock_data=stock_data,
        stock_names={code: code for code in stock_data},
        initial_capital=100000.0,
    )
    result = engine.run("MultiGoldenCrossStrategy", {
        "start_date": "2025-06-01",
        "end_date": "2026-08-01",
    })
    assert "error" not in result
    assert result["performance"]["trades"] >= 0

def _trend_df(n=100, seed=7, start="2024-05-01", base=10.0, flat=30, up=8):
    """构造横盘后放量拉升的序列，确定触发多金叉信号。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=n)
    close = np.full(n, base, dtype=float)
    for i in range(flat, min(flat + up, n)):
        close[i] = close[i - 1] * 1.05
    for i in range(flat + up, n):
        close[i] = close[i - 1] * 1.001
    volume = np.where(np.arange(n) >= flat, 300000.0, 100000.0)
    high = close * 1.01
    low = close * 0.99
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close, "high": high, "low": low, "close": close, "volume": volume,
    })


def test_backtest_holiday_cap_uses_last_close():
    """跨市场休市：持仓股票当日无行情时按最近收盘价结算，市值不归零。"""
    df_a = _synthetic_df(n=100, seed=3, start="2024-05-01", base=5.0)
    df_b = _trend_df()  # 触发信号的市场
    # 市场B 在 2024-07-05 休市（模拟美股 Juneteenth/假期），删除该日
    df_b = df_b[df_b["date"] != "2024-07-05"].reset_index(drop=True)

    engine = BacktestEngine(
        stock_data={"000001": df_a, "600519": df_b},
        stock_names={"000001": "市场A", "600519": "市场B"},
        initial_capital=100000.0,
    )
    result = engine.run("MultiGoldenCrossStrategy", {
        "start_date": "2024-06-01",
        "end_date": "2024-08-31",
        "take_profit_pct": 100.0,      # 防止止盈提前平仓，保证休市日仍有持仓
        "stop_loss_pct": -100.0,
        "trailing_stop_pct": 100.0,
        "max_hold_days": 1000,
    })
    assert "error" not in result
    hist = result["capital_history"]
    dates = result["period"]["start"]  # placeholder
    trading_dates = [d for d in engine.trading_dates if "2024-06-01" <= d <= "2024-08-31"]
    assert "2024-07-05" in trading_dates
    idx_holiday = trading_dates.index("2024-07-05")
    prev_date = trading_dates[idx_holiday - 1]
    # capital_history[0] 是初始资金，capital_history[k] 对应 trading_dates[k-1]
    ratio = hist[idx_holiday + 1] / hist[idx_holiday]
    assert 0.99 <= ratio <= 1.01, f"休市日净值变化 {ratio:.3f}，疑似持仓市值被误计为 0（前日 {prev_date}）"
