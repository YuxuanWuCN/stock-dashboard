"""v2.5 策略引擎离线单元测试。

用 docs/data/kline/ 下已落盘的 K 线数据验证：
- 注册表能扫描并实例化全部策略
- 策略在真实数据上可运行且输出符合契约
- 边界输入（空/短数据）不崩溃
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.strategies.base_strategy import BaseStrategy
from src.strategies.multi_golden_cross import MultiGoldenCrossStrategy
from src.strategies.limit_up_pullback import LimitUpPullbackStrategy
from src.strategies.morning_star import MorningStarStrategy
from src.strategies.strategy_registry import get_registry

KLINE_DIR = Path(__file__).parent.parent / "docs" / "data" / "kline"


def _load_kline(code: str) -> pd.DataFrame:
    """从 docs/data/kline/{code}.json 构造标准升序 DataFrame。"""
    with open(KLINE_DIR / f"{code}.json", "r", encoding="utf-8") as f:
        d = json.load(f)
    dates = d["dates"]
    kline = d["kline"]  # [open, close, low, high]
    volume = d["volume"]
    df = pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": [r[0] for r in kline],
        "close": [r[1] for r in kline],
        "low": [r[2] for r in kline],
        "high": [r[3] for r in kline],
        "volume": volume,
    })
    return df.sort_values("date").reset_index(drop=True)


@pytest.fixture(scope="module")
def real_df():
    """真实历史数据（取贵州茅台或任意存在的第一只）。"""
    if not KLINE_DIR.exists():
        pytest.skip("docs/data/kline 不存在，跳过真实数据测试")
    files = sorted(KLINE_DIR.glob("*.json"))
    if not files:
        pytest.skip("docs/data/kline 为空，跳过真实数据测试")
    return _load_kline(files[0].stem)


def test_registry_scans_and_instantiates_all_strategies():
    """注册表能扫描并实例化全部策略。"""
    registry = get_registry()
    registry.auto_register_from_directory()
    names = registry.list_strategies()
    assert "MultiGoldenCrossStrategy" in names
    assert "LimitUpPullbackStrategy" in names
    assert "MorningStarStrategy" in names
    for name in names:
        strategy = registry.get_strategy(name)
        assert isinstance(strategy, BaseStrategy)
        assert strategy.name


def test_strategies_run_on_real_data(real_df):
    """三个策略都能在真实数据上运行且输出符合契约。"""
    registry = get_registry()
    registry.auto_register_from_directory()
    for name in registry.list_strategies():
        strategy = registry.get_strategy(name)
        signals = strategy.execute_selection(real_df, "600519", "贵州茅台")
        assert isinstance(signals, list)
        for sig in signals:
            assert "date" in sig
            assert "close" in sig
            assert "reasons" in sig
            assert isinstance(sig["reasons"], list)


def test_strategy_signal_has_required_fields(real_df):
    """命中的信号必须含 date/close/reasons。"""
    strategy = MultiGoldenCrossStrategy()
    signals = strategy.execute_selection(real_df, "600519", "贵州茅台")
    for sig in signals:
        assert sig["date"]
        assert sig["close"] > 0
        assert len(sig["reasons"]) >= 1


def test_empty_dataframe_returns_no_signals():
    """空 DataFrame 不崩溃且返回空。"""
    df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    for strategy in (MultiGoldenCrossStrategy(), LimitUpPullbackStrategy(), MorningStarStrategy()):
        assert strategy.execute_selection(df, "000001", "测试") == []


def test_short_dataframe_returns_no_signals():
    """数据不足不崩溃。"""
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-08-01", "2026-08-02"]),
        "open": [10.0, 10.1],
        "high": [10.5, 10.6],
        "low": [9.8, 9.9],
        "close": [10.2, 10.3],
        "volume": [1000, 1200],
    })
    for strategy in (MultiGoldenCrossStrategy(), LimitUpPullbackStrategy(), MorningStarStrategy()):
        assert strategy.execute_selection(df, "000001", "测试") == []


def test_st_filtered():
    """ST 股票名称被过滤。"""
    strategy = MultiGoldenCrossStrategy()
    result = strategy.execute_selection(_load_kline("600519"), "600519", "ST测试")
    # ST 在 _validate_stock_name 中已拦截，结果应为空
    assert result == []


def test_parameter_override():
    """参数覆盖生效。"""
    strategy = MultiGoldenCrossStrategy(params={"lookback_days": 5})
    assert strategy.params["lookback_days"] == 5
    assert strategy.params["ma_short_period"] == 5  # 默认值保留
