# -*- coding: utf-8 -*-
"""tests/test_factor_providers.py —— 可插拔双市场因子数据适配器单元测试 (Spec-Kit 010)"""

from pathlib import Path
import pandas as pd
import pytest

from src.analysis.factor_providers import (
    BaseFactorProvider,
    AkshareProxyFactorProvider,
    KennethFrenchFactorProvider,
    WindCSMARStubProvider,
)
from src.analysis import factor_db


def test_akshare_proxy_provider_db_query(tmp_path):
    """测试 A 股代理因子适配器从 SQLite 查询标准因子矩阵。"""
    db_file = tmp_path / "test_factors.db"
    provider = AkshareProxyFactorProvider(db_path=db_file)

    # 导入测试因子（满足 MIN_OBS_DAYS >= 250 行要求）
    dates = pd.date_range("2024-01-01", periods=260, freq="B").strftime("%Y-%m-%d")
    df_fix = pd.DataFrame({
        "date": dates,
        "MKT": 0.001,
        "SMB": 0.0005,
        "HML": -0.0002,
        "MOM": 0.0008,
        "rf": 0.0001,
    })
    csv_file = tmp_path / "fixture.csv"
    df_fix.to_csv(csv_file, index=False)

    imported = provider.import_factors_from_csv(csv_file)
    assert imported == 260

    # 查询
    df = provider.get_daily_factors("2024-01-01", "2024-01-10")
    assert len(df) > 0
    assert list(df.columns) == ["date", "MKT", "SMB", "HML", "MOM", "rf"]
    assert df["MKT"].iloc[0] == pytest.approx(0.001)


def test_kenneth_french_provider_fallback(tmp_path):
    """测试 Kenneth French 美股因子适配器回退机制与数据结构。"""
    provider = KennethFrenchFactorProvider(cache_dir=tmp_path)
    df = provider.get_daily_factors("2025-01-01", "2025-01-10")

    assert not df.empty
    assert "date" in df.columns
    assert "MKT" in df.columns
    assert "SMB" in df.columns
    assert "HML" in df.columns
    assert "MOM" in df.columns
    assert "rf" in df.columns


def test_wind_csmar_stub_provider():
    """测试校内学术终端（Wind/CSMAR）迁移映射桩。"""
    provider = WindCSMARStubProvider(backend_type="csmar")
    assert provider.connect() is True

    provider_wind = WindCSMARStubProvider(backend_type="wind")
    # 无 Wind 环境时优雅处理
    connected = provider_wind.connect()
    assert isinstance(connected, bool)
