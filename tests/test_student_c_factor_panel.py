"""同学 C 标准面板的离线契约测试。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.build_student_c_factor_panel as cscript
from src.data.factor_panel import (
    STANDARD_COLUMNS,
    SourceSchemaError,
    fill_within_stock,
    normalize_stock_code,
    read_source,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = PROJECT_ROOT / "data" / "task_split" / "student_C_finance_consumer_100.csv"


def _tiny_panel() -> pd.DataFrame:
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])
    rows = [("600036", d, v) for d, v in zip(dates, [30.0, np.nan, 36.0, np.nan])]
    rows += [("000001", d, v) for d, v in zip(dates, [np.nan, 20.0, np.nan, 24.0])]
    frame = pd.DataFrame(rows, columns=["stock_code", "trade_date", "close"])
    for column in STANDARD_COLUMNS[3:]:
        frame[column] = np.nan
    return frame[list(STANDARD_COLUMNS)]


def test_c_task_file_has_100_unique_six_digit_codes_and_two_subindustries():
    frame = read_source(TASK_FILE, source_label="student_C_task")
    codes = [normalize_stock_code(value) for value in frame["code"]]
    assert len(codes) == 100
    assert len(set(codes)) == 100
    assert all(len(code) == 6 and code.isdigit() for code in codes)
    assert frame["sub_industry"].value_counts().to_dict() == {
        "大金融与央国企": 50,
        "核心消费与医药生物": 50,
    }
    assert {"000001", "000002", "000858"}.issubset(codes)


def test_fill_isolated_per_stock_and_preserves_leading_zero():
    filled, stats = fill_within_stock(_tiny_panel(), ["close"], method="ffill")
    assert filled["stock_code"].str.fullmatch(r"\d{6}").all()
    assert filled.loc[filled.stock_code == "600036", "close"].tolist() == [30.0, 30.0, 36.0, 36.0]
    values = filled.loc[filled.stock_code == "000001", "close"].tolist()
    assert np.isnan(values[0])
    assert values[1:] == [20.0, 20.0, 24.0]
    assert stats["600036"]["close"] == 2
    assert stats["000001"]["close"] == 1


def test_leading_zero_normalization_does_not_merge_different_codes():
    assert normalize_stock_code("1") == "000001"
    assert normalize_stock_code("000001") == "000001"
    assert normalize_stock_code("600036") == "600036"


def test_synthetic_backtest_source_is_rejected():
    synthetic = PROJECT_ROOT / "data" / "raw" / "backtest_paper_2024_2026_300stocks" / "market_prices.csv"
    with pytest.raises(SourceSchemaError, match="随机数生成"):
        cscript._guard_against_synthetic(synthetic, "--raw-file")


def test_no_source_does_not_write_a_fake_panel(tmp_path):
    result = cscript.main(["--quiet", "--out-dir", str(tmp_path)])
    assert result == 2
    assert not list(tmp_path.iterdir())
