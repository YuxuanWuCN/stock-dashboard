"""Hand-checkable price fixtures; they are not observed A-share returns."""

import numpy as np
import pandas as pd
import pytest

from src.data.nale_alpha_labels import build_excess_return_labels, validate_price_bars


def _fixture():
    dates = tuple(pd.bdate_range("2024-06-03", periods=8).strftime("%Y-%m-%d"))
    rows = []
    for day in dates:
        for code in ("000001", "000300.SH"):
            rows.append({
                "date": day,
                "code": code,
                "close": 100.0 if code == "000001" else 1000.0,
                "available_at": day + "T18:00:00+08:00",
                "source_id": "math-fixture-" + day + "-" + code,
                "adjustment_method": "unadjusted" if code == "000001" else "index_close",
                "trade_status": "trading",
                "volume": 1000.0,
                "limit_up": False,
                "limit_down": False,
                "is_observed": False,
            })
    prices = pd.DataFrame(rows)
    prices.loc[(prices["date"] == dates[6]) & (prices["code"] == "000001"), "close"] = 110.0
    prices.loc[(prices["date"] == dates[6]) & (prices["code"] == "000300.SH"), "close"] = 1050.0
    signals = pd.DataFrame([{
        "date": dates[0], "code": "000001",
        "signal_at": dates[0] + "T15:10:00+08:00",
    }])
    return signals, prices, dates


def test_five_day_proxy_math_and_label_availability():
    signals, prices, dates = _fixture()
    built = build_excess_return_labels(signals, prices, dates, allow_fixture=True)
    assert built.horizon_days == 5
    assert built.excluded.empty
    assert len(built.labels) == 1
    row = built.labels.iloc[0]
    assert row["code"] == "000001"
    assert row["entry_date"] == dates[1]
    assert row["exit_date"] == dates[6]
    assert row["asset_return"] == pytest.approx(0.10)
    assert row["benchmark_return"] == pytest.approx(0.05)
    assert row["y_excess"] == pytest.approx(0.05)
    assert row["label_available_at"] == pd.Timestamp(dates[6] + "T18:00:00+08:00")
    assert row["evidence_class"] == "engineering_fixture"
    assert row["price_source_id"].startswith("price-bars-")


def test_fixture_is_rejected_by_default_and_delayed_bar_delays_label():
    signals, prices, dates = _fixture()
    with pytest.raises(ValueError, match="non-observed"):
        build_excess_return_labels(signals, prices, dates)
    delayed = prices.copy()
    delayed.loc[(delayed["date"] == dates[6]) & (delayed["code"] == "000001"), "available_at"] = dates[7] + "T10:00:00+08:00"
    result = build_excess_return_labels(signals, delayed, dates, allow_fixture=True)
    assert result.labels.iloc[0]["label_available_at"] == pd.Timestamp(dates[7] + "T10:00:00+08:00")


def test_missing_or_untradeable_bars_are_excluded_without_forward_fill():
    signals, prices, dates = _fixture()
    missing = prices.loc[~((prices["date"] == dates[1]) & (prices["code"] == "000001"))]
    result = build_excess_return_labels(signals, missing, dates, allow_fixture=True)
    assert result.labels.empty
    assert result.excluded.iloc[0]["reason"] == "missing_asset_entry_bar"

    limit = prices.copy()
    limit.loc[(limit["date"] == dates[1]) & (limit["code"] == "000001"), "limit_up"] = True
    result = build_excess_return_labels(signals, limit, dates, allow_fixture=True)
    assert result.excluded.iloc[0]["reason"] == "asset_entry_not_tradeable"

    suspended = prices.copy()
    suspended.loc[(suspended["date"] == dates[6]) & (suspended["code"] == "000001"), "trade_status"] = "suspended"
    result = build_excess_return_labels(signals, suspended, dates, allow_fixture=True)
    assert result.excluded.iloc[0]["reason"] == "asset_exit_not_tradeable"


def test_unmatured_tail_and_invalid_calendar_fail_closed():
    signals, prices, dates = _fixture()
    last = signals.copy()
    last.loc[0, "date"] = dates[-1]
    last.loc[0, "signal_at"] = dates[-1] + "T15:10:00+08:00"
    result = build_excess_return_labels(last, prices, dates, allow_fixture=True)
    assert result.labels.empty
    assert result.excluded.iloc[0]["reason"] == "horizon_not_matured"
    with pytest.raises(ValueError, match="sorted and unique"):
        build_excess_return_labels(signals, prices, tuple(reversed(dates)), allow_fixture=True)


def test_price_table_rejects_duplicates_bad_values_and_times():
    _, prices, _ = _fixture()
    with pytest.raises(ValueError, match="duplicate"):
        validate_price_bars(pd.concat([prices, prices.iloc[[0]]], ignore_index=True), allow_fixture=True)
    bad = prices.copy()
    bad.loc[0, "close"] = 0.0
    with pytest.raises(ValueError, match="positive"):
        validate_price_bars(bad, allow_fixture=True)
    bad = prices.copy()
    bad.loc[0, "volume"] = np.inf
    with pytest.raises(ValueError, match="NaN or Inf"):
        validate_price_bars(bad, allow_fixture=True)
    bad = prices.copy()
    bad.loc[0, "available_at"] = bad.loc[0, "date"] + "T14:59:00+08:00"
    with pytest.raises(ValueError, match="before its close"):
        validate_price_bars(bad, allow_fixture=True)
    bad = prices.copy()
    bad.loc[0, "available_at"] = bad.loc[0, "date"] + "T18:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_price_bars(bad, allow_fixture=True)
