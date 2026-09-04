# -*- coding: utf-8 -*-
"""tests/test_data_adapter.py —— 统一多市场数据适配层测试套件 (Week 1)"""

import pandas as pd
import numpy as np
import pytest
from pathlib import Path

from src.data.adapter import UnifiedDataAdapter, MarketDataPacket


class _InjectedFactorProvider:
    """离线 provider fake，用于验证官方模式的路由而非网络行为。"""

    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def get_daily_factors(self, start_date, end_date):
        self.calls.append((start_date, end_date))
        return self.frame.copy()


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
        "UMD1": 0.0002,
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


def _official_factor_frame():
    return pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-01"],
            "MKT": [0.002, 0.001],
            "SMB": [0.001, 0.0005],
            "HML": [-0.001, -0.0005],
            "MOM": [0.003, 0.002],
            "rf": [0.0001, 0.0001],
        }
    )


def test_csmar_mode_routes_to_injected_provider_without_open_data_fallback(tmp_path):
    csmar = _InjectedFactorProvider(_official_factor_frame())
    adapter = UnifiedDataAdapter(
        mode="csmar", cache_db=tmp_path / "csmar_route.db", csmar_provider=csmar
    )

    result = adapter.get_market_factors("2024-01-01", "2024-01-02", market="CN")

    assert result.columns.tolist() == ["MKT", "SMB", "HML", "MOM", "rf"]
    assert result.index.strftime("%Y-%m-%d").tolist() == ["2024-01-01", "2024-01-02"]
    assert csmar.calls == [("2024-01-01", "2024-01-02")]


def test_school_scnu_mode_uses_api_provider_when_no_local_export(tmp_path):
    csmar = _InjectedFactorProvider(_official_factor_frame())
    adapter = UnifiedDataAdapter(
        mode="school_scnu",
        cache_db=tmp_path / "scnu_api.db",
        school_factor_dir=tmp_path / "missing_school_factors",
        csmar_provider=csmar,
    )

    result = adapter.get_market_factors("2024-01-01", "2024-01-02", market="CN")

    assert len(result) == 2
    assert csmar.calls == [("2024-01-01", "2024-01-02")]


def test_school_scnu_mode_prefers_injected_local_provider(tmp_path):
    school = _InjectedFactorProvider(_official_factor_frame())
    csmar = _InjectedFactorProvider(_official_factor_frame())
    adapter = UnifiedDataAdapter(
        mode="school_scnu",
        cache_db=tmp_path / "school_route.db",
        scnu_provider=school,
        csmar_provider=csmar,
    )

    adapter.get_market_factors("2024-01-01", "2024-01-02", market="CN")

    assert school.calls == [("2024-01-01", "2024-01-02")]
    assert csmar.calls == []


@pytest.mark.parametrize(
    "frame, message",
    [
        (pd.DataFrame(), "空结果"),
        (_official_factor_frame().drop(columns=["MOM"]), "缺少标准列"),
    ],
)
def test_official_mode_rejects_invalid_response_without_fallback(tmp_path, frame, message):
    provider = _InjectedFactorProvider(frame)
    adapter = UnifiedDataAdapter(
        mode="csmar", cache_db=tmp_path / "csmar_invalid.db", csmar_provider=provider
    )
    with pytest.raises(ValueError, match=message):
        adapter.get_market_factors("2024-01-01", "2024-01-02", market="CN")


def test_official_adapter_normalizes_yyyymmdd_and_rejects_intraday_duplicates(tmp_path):
    frame = _official_factor_frame()
    frame["date"] = [20240101, 20240102]
    provider = _InjectedFactorProvider(frame)
    adapter = UnifiedDataAdapter(
        mode="csmar", cache_db=tmp_path / "numeric_dates.db", csmar_provider=provider
    )
    result = adapter.get_market_factors(20240101, 20240102, market="CN")
    assert result.index.strftime("%Y-%m-%d").tolist() == ["2024-01-01", "2024-01-02"]

    duplicate = _official_factor_frame()
    duplicate["date"] = ["2024-01-01 09:30:00", "2024-01-01 18:00:00"]
    duplicate_provider = _InjectedFactorProvider(duplicate)
    duplicate_adapter = UnifiedDataAdapter(
        mode="csmar", cache_db=tmp_path / "duplicate_dates.db", csmar_provider=duplicate_provider
    )
    with pytest.raises(ValueError, match="重复日期"):
        duplicate_adapter.get_market_factors("2024-01-01", "2024-01-02", market="CN")


def test_adapter_exposes_csmar_connection_and_query_configuration(tmp_path):
    service = object()
    query = lambda *_: _official_factor_frame()
    adapter = UnifiedDataAdapter(
        mode="csmar",
        cache_db=tmp_path / "csmar_options.db",
        csmar_service=service,
        csmar_query=query,
        csmar_service_factory=lambda: service,
        csmar_query_method="fetch_factors",
        csmar_query_params={"table_name": "STK_MKT_Thrfac"},
        csmar_connection_params={"username": "demo", "password": "secret"},
    )

    provider = adapter.csmar_provider
    assert provider.service is service
    assert provider.query is query
    assert provider.service_factory is not None
    assert provider.query_method == "fetch_factors"
    assert provider.query_params == {"table_name": "STK_MKT_Thrfac"}
    assert provider.connection_params == {"username": "demo", "password": "secret"}


def test_adapter_rejects_unknown_market(tmp_path):
    adapter = UnifiedDataAdapter(mode="csmar", cache_db=tmp_path / "market.db")
    with pytest.raises(ValueError, match="仅支持 CN 或 US"):
        adapter.get_market_factors("2024-01-01", "2024-01-02", market="EU")


def test_strict_school_provider_rejects_missing_or_duplicate_local_data(tmp_path):
    from src.analysis.factor_providers import CSMARDataError, SCNUAcademicFactorProvider

    missing = SCNUAcademicFactorProvider(
        data_dir=tmp_path / "missing_school_factors", strict=True
    )
    with pytest.raises(CSMARDataError, match="未在|覆盖"):
        missing.get_daily_factors("2024-01-01", "2024-01-02")

    school_dir = tmp_path / "duplicate_school_factors"
    school_dir.mkdir()
    duplicate = _official_factor_frame()
    duplicate.loc[1, "date"] = duplicate.loc[0, "date"]
    duplicate.to_csv(school_dir / "factors.csv", index=False)
    provider = SCNUAcademicFactorProvider(data_dir=school_dir, strict=True)
    with pytest.raises(CSMARDataError, match="重复日期"):
        provider.get_daily_factors("2024-01-01", "2024-01-02")


def test_official_adapter_applies_explicit_trading_calendar_to_injected_provider(tmp_path):
    partial = _InjectedFactorProvider(_official_factor_frame().iloc[:1])
    adapter = UnifiedDataAdapter(
        mode="csmar",
        cache_db=tmp_path / "calendar_route.db",
        csmar_provider=partial,
        csmar_expected_trading_dates=["2024-01-01", "2024-01-02"],
    )
    with pytest.raises(ValueError, match="缺失日期"):
        adapter.get_market_factors("2024-01-01", "2024-01-02", market="CN")


def test_adapter_factor_cache_reutilization(tmp_path):
    """测试同一日期范围重复请求时直接命中内存缓存，提升批量吞吐量。"""
    provider = _InjectedFactorProvider(_official_factor_frame())
    adapter = UnifiedDataAdapter(
        mode="csmar",
        cache_db=tmp_path / "cache_test.db",
        csmar_provider=provider,
    )
    res1 = adapter.get_market_factors("2024-01-01", "2024-01-02", market="CN")
    assert len(adapter._factor_cache) == 1

    # 替换 provider 中的数据，再次请求
    provider.frame = pd.DataFrame()
    # 命中缓存，返回相同数据而非空
    res2 = adapter.get_market_factors("2024-01-01", "2024-01-02", market="CN")
    assert res1.equals(res2)

