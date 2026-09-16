"""同学 C CSMAR Filling 真实交易日过滤测试。"""

from __future__ import annotations

import json

import pandas as pd

from scripts.filter_csmar_panel_to_real_days import main


def test_filter_keeps_only_csmar_filling_zero_days(tmp_path):
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    rows = []
    for code in ("000001", "600036"):
        for date in dates:
            rows.append(
                {
                    "stock_code": code,
                    "trade_date": date,
                    "close": 1.0,
                    "volume": 1.0,
                    "turnover_rate": 0.1,
                    "market_value": 10.0,
                    "pe_ttm": 2.0,
                    "pb": 1.0,
                    "roe": 0.1,
                }
            )
    panel_path = tmp_path / "panel.parquet"
    pd.DataFrame(rows).to_parquet(panel_path, index=False)
    calendar_path = tmp_path / "calendar.csv"
    pd.DataFrame(
        {"TradingDate": dates.strftime("%Y-%m-%d"), "Filling": ["0", "2", "0"]}
    ).to_csv(calendar_path, index=False)

    out_parquet = tmp_path / "filtered.parquet"
    out_csv = tmp_path / "filtered.csv"
    manifest = tmp_path / "manifest.json"
    result = main(
        [
            "--csmar-panel",
            str(panel_path),
            "--filling-calendar",
            str(calendar_path),
            "--out-parquet",
            str(out_parquet),
            "--out-csv",
            str(out_csv),
            "--manifest",
            str(manifest),
        ]
    )

    assert result == 0
    filtered = pd.read_parquet(out_parquet)
    assert filtered["trade_date"].dt.strftime("%Y-%m-%d").unique().tolist() == [
        "2024-01-02",
        "2024-01-04",
    ]
    assert len(filtered) == 4
    assert json.loads(manifest.read_text(encoding="utf-8"))["non_trading_fill_days_removed"] == 1
