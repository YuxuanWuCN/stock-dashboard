# -*- coding: utf-8 -*-
"""tests/test_data_adapter.py —— 统一多市场数据适配层测试套件 (Week 1)"""

import pandas as pd
import numpy as np
import pytest
from pathlib import Path

from src.data.adapter import UnifiedDataAdapter, MarketDataPacket


def test_unified_data_adapter_factors(tmp_path):
    """测试多市场因子数据获取与列规范对齐。"""
    cache_db = tmp_path / "test_adapter.db"
    adapter = UnifiedDataAdapter(mode="dual_track", cache_db=cache_db)

    # 1. A 股 7 因子获取
    df_cn = adapter.get_market_factors("2024-01-01", "2024-01-20", market="CN", include_micro_flows=True)
    assert not df_cn.empty
    assert "MKT" in df_cn.columns
    assert "SMB" in df_cn.columns
    assert "HML" in df_cn.columns
    assert "MOM" in df_cn.columns
    assert "rf" in df_cn.columns
    assert "LARGE_ORDER_INFLOW" in df_cn.columns
    assert "NORTHBOUND_DELTA" in df_cn.columns

    # 2. 美股 4 因子获取
    df_us = adapter.get_market_factors("2024-01-01", "2024-01-20", market="US")
    assert not df_us.empty
    assert "MKT" in df_us.columns
    assert "SMB" in df_us.columns


def test_market_data_packet_assembly(tmp_path):
    """测试 MarketDataPacket 标的数据封包装配与时序交集对齐。"""
    cache_db = tmp_path / "test_adapter_packet.db"
    adapter = UnifiedDataAdapter(mode="dual_track", cache_db=cache_db)

    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    prices = [10.0, 10.5, 10.2, 10.8, 11.0, 11.2, 10.9, 11.5, 11.8, 12.0]
    kline_df = pd.DataFrame({
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": [10000] * 10,
        "amount": [100000] * 10
    }, index=dates)

    packet = adapter.assemble_market_packet(
        ticker="001309",
        kline_df=kline_df,
        market="CN",
        cash_flow_indicators={"prepayment_yoy": 0.45, "capex_yoy": 0.38}
    )

    assert isinstance(packet, MarketDataPacket)
    assert packet.ticker == "001309"
    assert len(packet.dates) == 10
    assert len(packet.returns) == 10
    assert not packet.factors.empty
    assert packet.cash_flow_indicators["prepayment_yoy"] == 0.45
