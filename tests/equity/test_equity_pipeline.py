# tests/equity/test_equity_pipeline.py
"""
Rainbow-FinGPT v4.0 A 股权益赛道核心流水线与资产配置测试
Tests for Equity Storage Runner Adapter and Fama-MacBeth Pricing.
"""

from src.assets.equity.storage_runner import EquityStorageRunnerAdapter


def test_equity_storage_adapter_universe():
    """验证 A 股存储超级周期核心标的池包含主要龙头"""
    adapter = EquityStorageRunnerAdapter()
    tickers = adapter.get_core_storage_universe()
    assert len(tickers) >= 5
    assert "001309" in tickers  # 德明利
    assert "688008" in tickers  # 澜起科技
    assert "688525" in tickers  # 佰维存储
