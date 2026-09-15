"""同学 C CSMAR 源表适配的离线契约测试。"""

from __future__ import annotations

import pandas as pd

from src.data.factor_panel import ingest_long_source


def test_capdate_maps_to_trade_date():
    frame = pd.DataFrame(
        {
            "SecuCode": ["000591"],
            "CapDate": ["2024-01-02"],
            "MV_Total_A": [123.0],
        }
    )

    out = ingest_long_source(frame, "capitals")

    assert out.loc[0, "stock_code"] == "000591"
    assert out.loc[0, "trade_date"] == pd.Timestamp("2024-01-02")
    assert out.loc[0, "market_value"] == 123.0


def test_quarterly_source_preserves_report_and_announcement_dates():
    from src.data.factor_panel import ingest_quarterly_source

    frame = pd.DataFrame(
        {
            "Stkcd": ["000591"],
            "Accper": ["2023-09-30"],
            "DeclareDate": ["2023-10-31"],
            "F050504C": [0.12],
        }
    )

    out = ingest_quarterly_source(frame, "fin")

    assert list(out.columns) == [
        "stock_code",
        "report_date",
        "announce_date",
        "roe",
    ]
    assert out.loc[0, "report_date"] == pd.Timestamp("2023-09-30")
    assert out.loc[0, "announce_date"] == pd.Timestamp("2023-10-31")
    assert out.loc[0, "roe"] == 0.12
