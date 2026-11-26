# -*- coding: utf-8 -*-
"""DuckDB 只读接口单元测试：代码保真、只读守卫、缺文件与 provenance。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.api.types import is_string_dtype
import pytest

duckdb = pytest.importorskip("duckdb")

import duck_reader
from duck_reader import PANEL, DuckDBMarketReader, ReadOnlyViolation, open_reader


def _write_panel(root: Path, rows: int = 6) -> Path:
    path = root / PANEL
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({
        "stock_code": ["000037", "600519", "000037", "600519", "000037", "600519"][:rows],
        "trade_date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03",
                       "2024-01-04", "2024-01-04"][:rows],
        "close": [8.396, 1700.0, 8.5, 1710.0, 8.4, 1690.0][:rows],
        "volume": [12, 34, 56, 78, 90, 12][:rows],
        "ret": [None, 0.01, 0.012, 0.006, -0.012, -0.012][:rows],
    })
    frame.to_parquet(path, index=False)
    return path


@pytest.fixture
def reader(tmp_path):
    _write_panel(tmp_path)
    return DuckDBMarketReader(tmp_path)


def test_stock_codes_and_dates_stay_strings(reader):
    panel = reader.stock_panel()
    assert panel["stock_code"].tolist()[:2] == ["000037", "600519"]
    assert is_string_dtype(panel["stock_code"])
    assert is_string_dtype(panel["trade_date"])
    assert panel["trade_date"].tolist()[0] == "2024-01-02"


def test_stock_panel_is_sorted_by_date_then_code(reader):
    panel = reader.stock_panel()
    ordered = sorted(zip(panel["trade_date"], panel["stock_code"]))
    assert list(zip(panel["trade_date"], panel["stock_code"])) == ordered


def test_stock_window_filters_dates_and_codes(reader):
    window = reader.stock_window("2024-01-02", "2024-01-03", ["000037"])
    assert window["stock_code"].unique().tolist() == ["000037"]
    assert window["trade_date"].nunique() == 2
    empty = reader.stock_window("2024-01-02", "2024-01-03", ["999999"])
    assert empty.empty


def test_stock_window_treats_code_as_data_not_sql(reader):
    hostile = reader.stock_window("2024-01-02", "2024-01-04", ["'; DROP TABLE x; --"])
    assert hostile.empty
    assert not reader.stock_panel().empty


@pytest.mark.parametrize("sql", [
    "DROP TABLE x",
    "INSERT INTO x VALUES (1)",
    "UPDATE x SET a = 1",
    "CREATE TABLE x (a INT)",
    "SELECT 1; SELECT 2",
    "",
])
def test_read_only_guard_rejects_non_select(reader, sql, tmp_path):
    path = tmp_path / "whatever.parquet"
    with pytest.raises(ReadOnlyViolation):
        reader.query_frame(sql, path)


def test_missing_panel_raises_file_not_found(tmp_path):
    reader = DuckDBMarketReader(tmp_path)
    with pytest.raises(FileNotFoundError):
        reader.stock_panel()
    with pytest.raises(FileNotFoundError):
        reader.panel_provenance()


def test_missing_market_snapshot_is_reported_not_faked(reader):
    availability = reader.market_availability()
    assert set(availability) == set(duck_reader.MARKET_TABLES)
    assert not any(availability.values())
    with pytest.raises(FileNotFoundError):
        reader.etf_closes()


def test_market_csv_is_read_as_text(tmp_path):
    market = tmp_path / "snapshot"
    market.mkdir()
    (market / "etf_close.csv").write_text(
        "code,trade_date,close\n000037,2024-01-02,8.396\n", encoding="utf-8"
    )
    reader = DuckDBMarketReader(tmp_path, market)
    frame = reader.etf_closes()
    assert frame.at[0, "code"] == "000037"
    assert frame.at[0, "close"] == "8.396"
    assert reader.market_availability()["etf_close.csv"] is True


def test_panel_provenance_matches_manifest(reader, tmp_path):
    provenance = reader.panel_provenance()
    assert provenance["rows"] == 6
    assert provenance["stocks"] == 2
    assert provenance["first_date"] == "2024-01-02"
    assert provenance["last_date"] == "2024-01-04"
    assert provenance["manifest_rows"] is None
    assert provenance["rows_match_manifest"] is True

    manifest = tmp_path / duck_reader.PANEL_MANIFEST
    manifest.write_text('{"rows": 5}', encoding="utf-8")
    assert reader.panel_provenance()["rows_match_manifest"] is False


def test_open_reader_factory_contract(tmp_path):
    _write_panel(tmp_path)
    default = open_reader(tmp_path, None, None)
    assert isinstance(default, DuckDBMarketReader)
    explicit = open_reader(tmp_path, None, "duck_reader:DuckDBMarketReader")
    assert isinstance(explicit, DuckDBMarketReader)
    with pytest.raises(ValueError, match="module:factory"):
        open_reader(tmp_path, None, "bad")


def test_real_parquet_panel_is_readable_when_present(repo_root):
    """真实面板（#12 的 csmar_factor_panel_master.parquet）必须能被只读层直接取数。"""
    reader = DuckDBMarketReader(repo_root)
    try:
        provenance = reader.panel_provenance()
    except FileNotFoundError:
        pytest.skip("真实面板不在当前 checkout 中")
    assert provenance["rows"] > 100_000
    assert provenance["stocks"] > 100
    assert provenance["rows_match_manifest"] is True
    window = reader.stock_window("2026-08-01", "2026-08-28")
    assert not window.empty
    assert is_string_dtype(window["stock_code"])

def test_market_dir_env_override(tmp_path, monkeypatch):
    market = tmp_path / "custom_market"
    market.mkdir()
    (market / "actions.csv").write_text("code,trade_date,cash,ratio\n", encoding="utf-8")
    monkeypatch.setenv("RFOF_MARKET_DIR", str(market))
    reader = DuckDBMarketReader(tmp_path)
    assert reader.market_dir == market
    assert reader.market_availability()["actions.csv"] is True
    monkeypatch.setenv("RFOF_MARKET_DIR", "relative/snapshot")
    assert DuckDBMarketReader(tmp_path).market_dir == tmp_path / "relative/snapshot"


@pytest.mark.parametrize("filename, method", [
    ("etf_close.csv", "etf_closes"),
    ("fund_nav.csv", "fund_navs"),
    ("actions.csv", "actions"),
    ("futures_close.csv", "futures_closes"),
])
def test_all_market_snapshot_tables_are_readable_as_text(tmp_path, filename, method):
    """四张行情快照表都要能被只读层直接取数，代码列保持字符串。"""
    market = tmp_path / "snapshot"
    market.mkdir(exist_ok=True)
    (market / filename).write_text(
        "code,trade_date,value\n000037,2024-01-02,1.234\n", encoding="utf-8"
    )
    reader = DuckDBMarketReader(tmp_path, market)
    frame = getattr(reader, method)()
    assert frame.at[0, "code"] == "000037"
    assert frame.at[0, "value"] == "1.234"
    assert reader.market_availability()[filename] is True
