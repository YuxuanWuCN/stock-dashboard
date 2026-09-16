"""CSMAR 下载脚本的离线 SDK 夹具测试。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from src.analysis.factor_providers import CSMARDataError


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "download_csmar_carhart_factors.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("download_csmar_carhart_factors_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_download_script_writes_validated_standard_csv_from_task_template(tmp_path, monkeypatch):
    seen = {}

    class FakeService:
        def query(self, **kwargs):
            seen.update(kwargs)
            return pd.DataFrame(
                {
                    "TradingDate": [20240101, 20240102],
                    "RiskPremium1": [0.001, 0.002],
                    "SMB1": [0.0005, 0.001],
                    "HML1": [-0.0005, -0.001],
                    "UMD1": [0.002, 0.003],
                    "RiskFreeRate": [0.0001, 0.0001],
                }
            )

    package = types.ModuleType("csmarapi")
    service_module = types.ModuleType("csmarapi.CsmarService")
    service_module.CsmarService = FakeService
    monkeypatch.setitem(sys.modules, "csmarapi", package)
    monkeypatch.setitem(sys.modules, "csmarapi.CsmarService", service_module)
    module = _load_script_module()
    output = tmp_path / "factors.csv"
    args = module.parse_args(
        [
            "--start-date", "2024-01-01",
            "--end-date", "2024-01-02",
            "--min-rows", "2",
            "--output", str(output),
        ]
    )

    assert module.download_factors(args) == 0
    assert seen["table_name"] == "STK_MKT_Thrfac"
    assert seen["start_date"] == "2024-01-01"
    assert seen["end_date"] == "2024-01-02"
    assert seen["fields"] == module.DEFAULT_FIELDS
    result = pd.read_csv(output)
    assert result.columns.tolist() == ["date", "MKT", "SMB", "HML", "MOM", "rf"]
    assert result["date"].astype(str).tolist() == ["2024-01-01", "2024-01-02"]


def test_download_script_returns_failure_without_sdk_and_does_not_write(tmp_path, monkeypatch):
    package = types.ModuleType("csmarapi")
    monkeypatch.setitem(sys.modules, "csmarapi", package)
    monkeypatch.delitem(sys.modules, "csmarapi.CsmarService", raising=False)
    module = _load_script_module()
    output = tmp_path / "missing-sdk.csv"

    result = module.main(["--output", str(output)])

    assert result == 2
    assert not output.exists()


def test_download_script_checks_supplied_trading_calendar(tmp_path, monkeypatch):
    class FakeService:
        def query(self, **kwargs):
            return pd.DataFrame(
                {
                    "TradingDate": [20240101, 20240102],
                    "RiskPremium1": [0.001, 0.002],
                    "SMB1": [0.0005, 0.001],
                    "HML1": [-0.0005, -0.001],
                    "UMD1": [0.002, 0.003],
                    "RiskFreeRate": [0.0001, 0.0001],
                }
            )

    package = types.ModuleType("csmarapi")
    service_module = types.ModuleType("csmarapi.CsmarService")
    service_module.CsmarService = FakeService
    monkeypatch.setitem(sys.modules, "csmarapi", package)
    monkeypatch.setitem(sys.modules, "csmarapi.CsmarService", service_module)
    module = _load_script_module()

    calendar = tmp_path / "calendar.csv"
    pd.DataFrame({"TradingDate": [20240101, 20240102]}).to_csv(calendar, index=False)
    output = tmp_path / "verified.csv"
    args = module.parse_args(
        [
            "--start-date", "2024-01-01",
            "--end-date", "2024-01-02",
            "--min-rows", "2",
            "--trading-calendar", str(calendar),
            "--output", str(output),
        ]
    )
    assert module.download_factors(args) == 0
    assert output.exists()


def test_download_script_rejects_partial_response_against_calendar(tmp_path, monkeypatch):
    class FakeService:
        def query(self, **kwargs):
            return pd.DataFrame(
                {
                    "TradingDate": [20240101],
                    "RiskPremium1": [0.001],
                    "SMB1": [0.0005],
                    "HML1": [-0.0005],
                    "UMD1": [0.002],
                    "RiskFreeRate": [0.0001],
                }
            )

    package = types.ModuleType("csmarapi")
    service_module = types.ModuleType("csmarapi.CsmarService")
    service_module.CsmarService = FakeService
    monkeypatch.setitem(sys.modules, "csmarapi", package)
    monkeypatch.setitem(sys.modules, "csmarapi.CsmarService", service_module)
    module = _load_script_module()

    calendar = tmp_path / "calendar.csv"
    pd.DataFrame({"date": ["2024-01-01", "2024-01-02"]}).to_csv(calendar, index=False)
    output = tmp_path / "partial.csv"
    args = module.parse_args(
        [
            "--start-date", "2024-01-01",
            "--end-date", "2024-01-02",
            "--min-rows", "1",
            "--trading-calendar", str(calendar),
            "--output", str(output),
        ]
    )
    with pytest.raises(CSMARDataError, match="缺失日期"):
        module.download_factors(args)
    assert not output.exists()


def test_download_script_rejects_missing_calendar_dates(tmp_path):
    module = _load_script_module()
    calendar = tmp_path / "calendar.csv"
    pd.DataFrame({"date": ["2024-01-01", None]}).to_csv(calendar, index=False)
    with pytest.raises(CSMARDataError, match="缺失日期"):
        module._read_trading_calendar(calendar)


def test_download_script_returns_failure_for_missing_calendar_file(tmp_path):
    module = _load_script_module()
    output = tmp_path / "missing-calendar.csv"
    result = module.main(
        [
            "--trading-calendar",
            str(tmp_path / "does-not-exist.csv"),
            "--output",
            str(output),
            "--allow-unverified-coverage",
        ]
    )
    assert result == 2
    assert not output.exists()


def test_download_script_can_require_calendar_before_connecting(tmp_path):
    module = _load_script_module()
    output = tmp_path / "must-have-calendar.csv"
    args = module.parse_args(
        [
            "--start-date", "2024-01-01",
            "--end-date", "2024-01-02",
            "--min-rows", "1",
            "--require-coverage",
            "--output", str(output),
        ]
    )
    with pytest.raises(CSMARDataError, match="trading-calendar|交易日历"):
        module.download_factors(args)
    assert not output.exists()
