# -*- coding: utf-8 -*-
"""tests/test_factor_providers.py —— 可插拔双市场因子数据适配器单元测试 (Spec-Kit 010)"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.analysis.factor_providers import (
    BaseFactorProvider,
    AkshareProxyFactorProvider,
    KennethFrenchFactorProvider,
    WindCSMARStubProvider,
    CSMARConnectionError,
    CSMARDataError,
    CSMARFactorProvider,
    CSMARQueryError,
    SCNUAcademicFactorProvider,
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
    """CSMAR 迁移桩不得把没有实际 SDK 的状态报告为已连接。"""
    provider = WindCSMARStubProvider(backend_type="csmar")
    assert provider.connect() is False

    provider_wind = WindCSMARStubProvider(backend_type="wind")
    # 无 Wind 环境时优雅处理
    connected = provider_wind.connect()
    assert isinstance(connected, bool)


def _valid_csmar_rows():
    return [
        {
            "TradingDate": "2024-01-01",
            "RiskPremium1": 0.001,
            "SMB1": 0.0005,
            "HML1": -0.0005,
            "UMD1": 0.002,
            "RiskFreeRate": 0.0001,
        },
        {
            "TradingDate": "2024-01-02",
            "RiskPremium1": 0.002,
            "SMB1": 0.001,
            "HML1": -0.001,
            "UMD1": 0.003,
            "RiskFreeRate": 0.0001,
        },
    ]


class _FakeCsmarService:
    def __init__(self, response=None, *, connected=True, error=None):
        self.response = response if response is not None else _valid_csmar_rows()
        self.connected = connected
        self.error = error
        self.calls = []

    def connect(self):
        self.calls.append("connect")
        return self.connected

    def query(self, start_date, end_date):
        self.calls.append((start_date, end_date))
        if self.error is not None:
            raise self.error
        return self.response


def test_csmar_provider_normalizes_service_response_and_preserves_metadata():
    service = _FakeCsmarService()
    provider = CSMARFactorProvider(
        service=service, query_method="query", source="CSMAR", version="offline-fixture"
    )

    result = provider.get_daily_factors("2024-01-01", "2024-01-02")

    assert result.columns.tolist() == ["date", "MKT", "SMB", "HML", "MOM", "rf"]
    assert result["date"].tolist() == ["2024-01-01", "2024-01-02"]
    assert result["MKT"].tolist() == pytest.approx([0.001, 0.002])
    assert result.attrs == {"source": "CSMAR", "version": "offline-fixture"}
    assert service.calls == ["connect", ("2024-01-01", "2024-01-02")]


def test_csmar_provider_supports_tuple_rows_and_numpy_column_envelopes():
    tuple_provider = CSMARFactorProvider(query=lambda *_: tuple(_valid_csmar_rows()))
    tuple_result = tuple_provider.get_daily_factors("2024-01-01", "2024-01-02")
    assert len(tuple_result) == 2

    columns = np.array(
        ["TradingDate", "RiskPremium1", "SMB1", "HML1", "UMD1", "sz_rf_rate"]
    )
    rows = np.array(
        [
            [20240101, 0.001, 0.0005, -0.0005, 0.002, 0.0001],
            [20240102, 0.002, 0.001, -0.001, 0.003, 0.0001],
        ],
        dtype=object,
    )
    envelope_provider = CSMARFactorProvider(
        query=lambda *_: {"columns": columns, "rows": rows}
    )
    result = envelope_provider.get_daily_factors(20240101, 20240102)
    assert result["date"].tolist() == ["2024-01-01", "2024-01-02"]
    assert result["rf"].tolist() == pytest.approx([0.0001, 0.0001])


def test_csmar_provider_wraps_malformed_columnar_response():
    provider = CSMARFactorProvider(
        query=lambda *_: {
            "TradingDate": [20240101, 20240102],
            "RiskPremium1": [0.001],
        }
    )
    with pytest.raises(CSMARDataError, match="缺少标准列|长度不一致"):
        provider.get_daily_factors("2024-01-01", "2024-01-02")


def test_csmar_provider_uses_task_package_query_signature_without_leaking_credentials():
    seen = {}

    def query(table_name, start_date, end_date, fields):
        seen["query"] = {
            "table_name": table_name,
            "start_date": start_date,
            "end_date": end_date,
            "fields": fields,
        }
        return _valid_csmar_rows()

    provider = CSMARFactorProvider(
        query=query,
        connection_params={"username": "demo", "password": "secret"},
        query_params={
            "table_name": "STK_MKT_Thrfac",
            "fields": [
                "TradingDate",
                "RiskPremium1",
                "SMB1",
                "HML1",
                "UMD1",
                "RiskFreeRate",
            ],
        },
    )

    provider.get_daily_factors("2024-01-01", "2024-01-02")

    assert seen["query"] == {
        "table_name": "STK_MKT_Thrfac",
        "start_date": "2024-01-01",
        "end_date": "2024-01-02",
        "fields": [
            "TradingDate",
            "RiskPremium1",
            "SMB1",
            "HML1",
            "UMD1",
            "RiskFreeRate",
        ],
    }


def test_csmar_provider_service_factory_receives_connection_params_once():
    seen = {}

    class FactoryService:
        connected = True

        def connect(self):
            return True

        def query(self, start_date, end_date):
            seen["query"] = (start_date, end_date)
            return _valid_csmar_rows()

    def factory(username, password):
        seen["credentials"] = (username, password)
        return FactoryService()

    provider = CSMARFactorProvider(
        service_factory=factory,
        connection_params={"username": "demo", "password": "secret"},
    )
    result = provider.get_daily_factors("2024-01-01", "2024-01-02")

    assert len(result) == 2
    assert seen["credentials"] == ("demo", "secret")
    assert seen["query"] == ("2024-01-01", "2024-01-02")


def test_csmar_provider_rejects_unconnected_service_and_query_failure():
    disconnected = CSMARFactorProvider(
        service=_FakeCsmarService(connected=False), query_method="query"
    )
    with pytest.raises(CSMARConnectionError, match="连接"):
        disconnected.get_daily_factors("2024-01-01", "2024-01-02")

    failed = CSMARFactorProvider(
        service=_FakeCsmarService(error=RuntimeError("offline")), query_method="query"
    )
    with pytest.raises(CSMARQueryError, match="查询"):
        failed.get_daily_factors("2024-01-01", "2024-01-02")


@pytest.mark.parametrize(
    "response, message",
    [
        ([], "空结果"),
        ([{"TradingDate": "2024-01-01", "RiskPremium1": 0.1}], "缺少标准列"),
        ([{**_valid_csmar_rows()[0], "TradingDate": "not-a-date"}], "非法日期"),
        ([{**_valid_csmar_rows()[0], "RiskPremium1": "not-a-number"}], "非法数值"),
    ],
)
def test_csmar_provider_rejects_invalid_response_contract(response, message):
    provider = CSMARFactorProvider(query=lambda *_: response)
    with pytest.raises(CSMARDataError, match=message):
        provider.get_daily_factors("2024-01-01", "2024-01-02")


def test_csmar_provider_rejects_duplicate_normalized_dates_and_bad_bound():
    rows = _valid_csmar_rows()
    rows[1]["TradingDate"] = "2024-01-01 18:00:00"
    provider = CSMARFactorProvider(query=lambda *_: rows)
    with pytest.raises(CSMARDataError, match="重复日期"):
        provider.get_daily_factors("2024-01-01", "2024-01-02")

    valid_provider = CSMARFactorProvider(query=lambda *_: _valid_csmar_rows())
    with pytest.raises(CSMARDataError, match="合法日期"):
        valid_provider.get_daily_factors(202401, 20240102)


def test_csmar_provider_enforces_explicit_trading_calendar():
    partial = _valid_csmar_rows()[:1]
    provider = CSMARFactorProvider(
        query=lambda *_: partial,
        expected_trading_dates=["2024-01-01", "2024-01-02"],
    )
    with pytest.raises(CSMARDataError, match="缺失日期"):
        provider.get_daily_factors("2024-01-01", "2024-01-02")

    extra = _valid_csmar_rows() + [
        {
            "TradingDate": "2024-01-03",
            "RiskPremium1": 0.003,
            "SMB1": 0.001,
            "HML1": -0.001,
            "UMD1": 0.003,
            "RiskFreeRate": 0.0001,
        }
    ]
    provider = CSMARFactorProvider(
        query=lambda *_: extra,
        expected_trading_dates=["2024-01-01"],
    )
    with pytest.raises(CSMARDataError, match="多余日期"):
        provider.get_daily_factors("2024-01-01", "2024-01-02")

    with pytest.raises(CSMARDataError, match="重复日期"):
        CSMARFactorProvider(
            query=lambda *_: _valid_csmar_rows(),
            expected_trading_dates=["2024-01-01", "2024-01-01"],
        ).get_daily_factors("2024-01-01", "2024-01-02")


def test_csmar_provider_prefers_keyword_call_for_variadic_query():
    seen = {}

    def query(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return _valid_csmar_rows()

    provider = CSMARFactorProvider(
        query=query,
        query_params={"table_name": "STK_MKT_Thrfac", "fields": ["TradingDate"]},
    )
    provider.get_daily_factors("2024-01-01", "2024-01-02")
    assert seen["args"] == ()
    assert seen["kwargs"]["table_name"] == "STK_MKT_Thrfac"
    assert seen["kwargs"]["start_date"] == "2024-01-01"
    assert seen["kwargs"]["end_date"] == "2024-01-02"


def test_csmar_provider_rejects_unknown_legacy_parameters():
    with pytest.raises(TypeError, match="connection_params"):
        CSMARFactorProvider(query=lambda *_: _valid_csmar_rows(), username="demo")
    with pytest.raises(ValueError, match="connection_params"):
        CSMARFactorProvider(
            query=lambda *_: _valid_csmar_rows(),
            query_params={"password": "secret"},
        )


def test_scnu_provider_enforces_explicit_trading_calendar_even_without_strict_mode(tmp_path):
    class PartialProvider:
        def get_daily_factors(self, start_date, end_date):
            return pd.DataFrame(_valid_csmar_rows()[:1])

    provider = SCNUAcademicFactorProvider(
        data_dir=tmp_path / "missing",
        api_provider=PartialProvider(),
        expected_trading_dates=["2024-01-01", "2024-01-02"],
    )
    with pytest.raises(CSMARDataError, match="缺失日期"):
        provider.get_daily_factors("2024-01-01", "2024-01-02")


def test_scnu_strict_mode_requires_explicit_trading_calendar(tmp_path):
    frame = pd.DataFrame(_valid_csmar_rows())
    frame.to_csv(tmp_path / "factors.csv", index=False)
    provider = SCNUAcademicFactorProvider(data_dir=tmp_path, strict=True)
    with pytest.raises(CSMARDataError, match="expected_trading_dates"):
        provider.get_daily_factors("2024-01-01", "2024-01-02")


def test_eastmoney_miaoxiang_provider(tmp_path):
    """测试东方财富妙想技能套件与多因子资金流适配器。"""
    from src.analysis.factor_providers import EastMoneyMiaoXiangProvider
    from src.skills.eastmoney_miaoxiang_skill import EastMoneyMiaoXiangSkill

    db_path = tmp_path / "eastmoney_test.db"
    provider = EastMoneyMiaoXiangProvider(db_path=db_path)
    
    # 1. 因子与资金流测试
    df = provider.get_factors_with_flows("2025-01-01", "2025-01-10")
    assert not df.empty
    assert "LARGE_ORDER_INFLOW" in df.columns
    assert "NORTHBOUND_DELTA" in df.columns
    assert "INST_SEAT_RATIO" in df.columns
    assert "MKT" in df.columns

    # 2. 产业链图谱测试 (德明利 001309)
    skill = EastMoneyMiaoXiangSkill(cache_db=db_path)
    onto = skill.get_supply_chain_ontology("001309")
    assert onto is not None
    assert onto.target_name == "德明利"
    assert len(onto.upstream_suppliers) > 0

    # 3. 市场情绪快照测试
    breadth = skill.get_market_breadth_snapshot("2025-01-10")
    assert breadth.temperature_score >= 0.0
    assert breadth.total_turnover_cny > 0
