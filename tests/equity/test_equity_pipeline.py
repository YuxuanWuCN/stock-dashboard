# tests/equity/test_equity_pipeline.py
"""
Rainbow-FinGPT v4.0 A 股权益赛道核心流水线与资产配置测试
Tests for Equity Storage Runner Adapter, Fama-MacBeth Pricing, and Silver Allocator.
"""

import pytest
from src.assets.equity.storage_runner import EquityStorageRunnerAdapter
from src.assets.wealth.silver_allocation import SilverWealthAllocator


def test_equity_storage_adapter_universe():
    """验证 A 股存储超级周期核心标的池包含主要龙头"""
    adapter = EquityStorageRunnerAdapter()
    tickers = adapter.get_core_storage_universe()
    assert len(tickers) >= 5
    assert "001309" in tickers  # 德明利
    assert "688008" in tickers  # 澜起科技
    assert "688525" in tickers  # 佰维存储


def test_silver_wealth_allocation_conservation():
    """验证银发普惠资产配置比例守恒 (和为 100%) 与防焦虑回撤指标"""
    allocator = SilverWealthAllocator(target_cash_buffer=36.0)
    
    # 正常温度 65℃
    prof_norm = allocator.compute_allocation(market_temperature=65.0)
    assert prof_norm.cash_ratio_pct + prof_norm.fixed_income_ratio_pct + prof_norm.hedged_equity_ratio_pct == pytest.approx(100.0)
    assert prof_norm.cash_ratio_pct >= 30.0
    assert "AAA" in prof_norm.safety_rating
    
    # 过热温度 85℃ 触发被动加大防御垫
    prof_hot = allocator.compute_allocation(market_temperature=85.0)
    assert prof_hot.cash_ratio_pct > prof_norm.cash_ratio_pct
    assert prof_hot.cash_ratio_pct + prof_hot.fixed_income_ratio_pct + prof_hot.hedged_equity_ratio_pct == pytest.approx(100.0)
