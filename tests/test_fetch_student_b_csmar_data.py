"""同学 B CSMAR SDK 拉取层的纯离线契约测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pandas as pd

from src.data.factor_panel import normalize_stock_codes


try:
    fetch = importlib.import_module("scripts.fetch_student_b_csmar_data")
except ModuleNotFoundError:
    fetch = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = PROJECT_ROOT / "data" / "task_split" / "student_B_energy_materials_100.csv"


class FakeCSMARService:
    def __init__(self, authenticated: bool = True):
        self.authenticated = authenticated
        self.calls: list[tuple[list[str], str, str, str, str]] = []

    def getListDbs(self):
        return [{"database": "fixture"}] if self.authenticated else None

    def query(self, columns, condition, table_name, start_date, end_date):
        self.calls.append((list(columns), condition, table_name, start_date, end_date))
        codes = [part.strip(" '") for part in condition.split("(", 1)[1].rstrip(")").split(",")]
        if table_name == "TRD_FwardQuotation":
            return [
                {
                    "Symbol": code,
                    "TradingDate": date,
                    "ClosePrice": 10.0,
                    "Volume": 100000.0,
                    "TurnoverRate1": 1.5,
                    "MarketValue": 1000000.0,
                }
                for code in codes
                for date in ("2024-01-02", "2024-01-03")
            ]
        if table_name == "FI_T10":
            return [
                {
                    "Stkcd": code,
                    "Accper": date,
                    "F100103C": 12.0,
                    "F100401A": 1.4,
                }
                for code in codes
                for date in ("2024-01-02", "2024-01-03")
            ]
        if table_name == "FI_T5":
            return [
                {
                    "Stkcd": code,
                    "Accper": "2022-12-31",
                    "F050504C": 0.12,
                }
                for code in codes
            ]
        if table_name == "AIQ_AccInfoDisTimeY":
            return [
                {
                    "Symbol": code,
                    "EndDate": "2022-12-31",
                    "DeclareDate": "2023-03-31",
                }
                for code in codes
            ]
        raise AssertionError(f"unexpected table: {table_name}")


def test_fetch_module_exists_and_exposes_query_contract():
    assert fetch is not None
    assert hasattr(fetch, "query_csmar_table")
    assert hasattr(fetch, "fetch_and_build")


def test_query_csmar_table_uses_official_positional_contract():
    assert fetch is not None
    service = FakeCSMARService()
    spec = fetch.TABLE_SPECS["trade"]

    frame = fetch.query_csmar_table(
        service,
        spec,
        ["000591", "600900"],
        "2024-01-02",
        "2026-08-28",
    )

    assert service.calls[0] == (
        list(spec.columns),
        "Symbol in ('000591','600900')",
        spec.table,
        "2024-01-02",
        "2026-08-28",
    )
    assert set(frame["Symbol"].astype(str)) == {"000591", "600900"}


def test_query_rejects_empty_response_without_fabrication():
    assert fetch is not None

    class EmptyService(FakeCSMARService):
        def query(self, *args):
            self.calls.append(args)
            return []

    with __import__("pytest").raises(fetch.CSMARDataError, match="空"):
        fetch.query_csmar_table(
            EmptyService(),
            fetch.TABLE_SPECS["trade"],
            ["000591"],
            "2024-01-02",
            "2024-01-03",
        )


def test_fetch_rejects_auth_failure_without_writing_final_outputs(tmp_path):
    assert fetch is not None
    sdk_cwd = tmp_path / "sdk"
    sdk_cwd.mkdir()
    (sdk_cwd / "token.txt").write_text("fixture-token\n0\n0", encoding="utf-8")
    out_dir = tmp_path / "csmar"
    raw_dir = tmp_path / "sources" / "csmar_raw"
    args = fetch.parse_args(
        [
            "--task-file",
            str(TASK_FILE),
            "--start-date",
            "2024-01-02",
            "--end-date",
            "2024-01-03",
            "--sdk-cwd",
            str(sdk_cwd),
            "--out-dir",
            str(out_dir),
            "--raw-dir",
            str(raw_dir),
        ]
    )

    result = fetch.fetch_and_build(
        args,
        service_factory=lambda: FakeCSMARService(authenticated=False),
    )

    assert result == 2
    assert not list(out_dir.glob("student_b_csmar_factor_panel*"))
    assert not list(raw_dir.glob("*.csv"))


def test_fetch_writes_raw_sources_and_standard_outputs(tmp_path):
    assert fetch is not None
    sdk_cwd = tmp_path / "sdk"
    sdk_cwd.mkdir()
    (sdk_cwd / "token.txt").write_text("fixture-token\n0\n0", encoding="utf-8")
    out_dir = tmp_path / "csmar"
    raw_dir = tmp_path / "sources" / "csmar_raw"
    args = fetch.parse_args(
        [
            "--task-file",
            str(TASK_FILE),
            "--start-date",
            "2024-01-02",
            "--end-date",
            "2024-01-03",
            "--sdk-cwd",
            str(sdk_cwd),
            "--out-dir",
            str(out_dir),
            "--raw-dir",
            str(raw_dir),
            "--overwrite",
        ]
    )

    result = fetch.fetch_and_build(
        args,
        service_factory=lambda: FakeCSMARService(authenticated=True),
    )

    assert result == 0
    assert {p.name for p in raw_dir.glob("*.csv")} == {
        "trd_fward_quotation.csv",
        "fi_t10.csv",
        "fi_t5.csv",
        "aiq_acc_info_dis_time_y.csv",
        "stk_fin_analysis.csv",
    }
    csv_path = out_dir / "student_b_csmar_factor_panel.csv"
    parquet_path = out_dir / "student_b_csmar_factor_panel.parquet"
    manifest_path = out_dir / "student_b_csmar_factor_panel_manifest.json"
    assert csv_path.exists()
    assert parquet_path.exists()
    assert manifest_path.exists()

    csv = pd.read_csv(csv_path, dtype={"stock_code": "string"})
    parquet = pd.read_parquet(parquet_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(csv) == 200
    assert len(parquet) == len(csv)
    assert csv["stock_code"].str.fullmatch(r"\d{6}").all()
    assert csv["stock_code"].nunique() == 100
    assert csv[["stock_code", "trade_date"]].duplicated().sum() == 0
    assert manifest["coverage_status"] == "complete"
