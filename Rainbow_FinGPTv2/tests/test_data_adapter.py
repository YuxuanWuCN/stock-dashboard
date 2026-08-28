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


def test_scnu_academic_factor_provider(tmp_path):
    """测试华南师范大学/阿伯丁学院校内因子库 (CSMAR/Wind) 本地热插拔与自动清洗。"""
    from src.analysis.factor_providers import SCNUAcademicFactorProvider

    school_dir = tmp_path / "school_factors"
    school_dir.mkdir(parents=True, exist_ok=True)

    # 模拟从 CSMAR 导出的三因子/四因子 CSV 文件
    csmar_csv = school_dir / "STK_MKT_Thrfac.csv"
    dates = pd.date_range("2024-01-01", periods=10, freq="B").strftime("%Y-%m-%d")
    df_csmar = pd.DataFrame({
        "TradingDate": dates,
        "RiskPremium1": 0.0015,
        "SMB1": 0.0008,
        "HML1": -0.0004,
        "RiskFreeRate": 0.0001
    })
    df_csmar.to_csv(csmar_csv, index=False)

    # 实例化校内因子提供器
    provider = SCNUAcademicFactorProvider(data_dir=school_dir)
    factors_df = provider.get_daily_factors("2024-01-01", "2024-01-05")

    assert not factors_df.empty
    assert list(factors_df.columns) == ["date", "MKT", "SMB", "HML", "MOM", "rf"]
    assert factors_df["MKT"].iloc[0] == pytest.approx(0.0015)
    assert factors_df["SMB"].iloc[0] == pytest.approx(0.0008)

