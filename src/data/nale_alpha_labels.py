"""Matured excess-return labels from auditable point-in-time daily bars.

The t+1 close / t+1+h close convention is a research proxy, not an executable
order fill. Source declarations are not a substitute for independent auditing.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
import pandas as pd


PRICE_COLUMNS = (
    "date", "code", "close", "available_at", "source_id",
    "adjustment_method", "trade_status", "volume", "limit_up",
    "limit_down", "is_observed",
)
ADJUSTMENT_METHODS = {
    "unadjusted", "qfq_asof", "hfq_asof", "total_return_asof", "index_close",
}


def _timestamp(value: object, name: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return stamp.tz_convert("UTC")


def _calendar_dates(values: Sequence[str]) -> tuple[str, ...]:
    dates = tuple(values)
    if not dates or any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) for value in dates):
        raise ValueError("trading_dates must contain ISO calendar dates")
    try:
        for value in dates:
            date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("trading_dates contains an invalid calendar date") from exc
    if tuple(sorted(set(dates))) != dates:
        raise ValueError("trading_dates must be sorted and unique")
    return dates


def validate_price_bars(prices: pd.DataFrame, *, allow_fixture: bool = False) -> pd.DataFrame:
    """Reject incomplete or undeclared price bars before building any label."""
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        raise ValueError("prices must be a nonempty DataFrame")
    missing = set(PRICE_COLUMNS) - set(prices.columns)
    if missing:
        raise ValueError(f"missing price columns: {sorted(missing)}")
    bars = prices.copy()
    if any(not isinstance(value, str) or not re.fullmatch(r"(?:[0-9]{6}|[0-9]{6}\.[A-Z]{2})", value) for value in bars["code"]):
        raise ValueError("price code must preserve its six-digit identifier")
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) for value in bars["date"]):
        raise ValueError("price date must be an ISO calendar date")
    try:
        dates = [date.fromisoformat(value) for value in bars["date"]]
    except ValueError as exc:
        raise ValueError("price date is not a valid calendar date") from exc
    if bars.duplicated(["date", "code"]).any():
        raise ValueError("duplicate price date/code key")
    for column in ("source_id", "adjustment_method", "trade_status"):
        if any(not isinstance(value, str) or not value.strip() for value in bars[column]):
            raise ValueError(f"{column} must be nonempty")
    if not set(bars["adjustment_method"]).issubset(ADJUSTMENT_METHODS):
        raise ValueError("unknown price adjustment_method")
    if not set(bars["trade_status"]).issubset({"trading", "suspended"}):
        raise ValueError("trade_status must be trading or suspended")
    for column in ("limit_up", "limit_down", "is_observed"):
        if any(not isinstance(value, (bool, np.bool_)) for value in bars[column]):
            raise ValueError(f"{column} must contain booleans")
    if not allow_fixture and not bars["is_observed"].all():
        raise ValueError("non-observed price bars require explicit engineering-fixture mode")
    for column in ("close", "volume"):
        try:
            bars[column] = pd.to_numeric(bars[column], errors="raise").astype(np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{column} must be numeric") from exc
        if not np.isfinite(bars[column].to_numpy()).all():
            raise ValueError(f"{column} contains NaN or Inf")
    if (bars["close"] <= 0).any() or (bars["volume"] < 0).any():
        raise ValueError("close must be positive and volume nonnegative")
    bars["available_at"] = pd.DatetimeIndex([_timestamp(value, "price available_at") for value in bars["available_at"]])
    for available, bar_day in zip(bars["available_at"], dates):
        close_at = pd.Timestamp(f"{bar_day.isoformat()}T15:00:00+08:00").tz_convert("UTC")
        if available < close_at:
            raise ValueError("a closing price cannot be available before its close")
    for _, group in bars.groupby("code", sort=False):
        if group["adjustment_method"].nunique() != 1:
            raise ValueError("adjustment_method changes within a price series")
    return bars


def _validate_signals(signals: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(signals, pd.DataFrame) or signals.empty:
        raise ValueError("signals must be a nonempty DataFrame")
    if not {"date", "code", "signal_at"}.issubset(signals.columns):
        raise ValueError("signals require date, code, and signal_at")
    result = signals.loc[:, ["date", "code", "signal_at"]].copy()
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}", value) for value in result["code"]):
        raise ValueError("signal code must be a six-digit string")
    if result.duplicated(["date", "code"]).any():
        raise ValueError("duplicate signal date/code key")
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) for value in result["date"]):
        raise ValueError("signal date must be an ISO calendar date")
    result["signal_at"] = pd.DatetimeIndex([_timestamp(value, "signal_at") for value in result["signal_at"]])
    for signal_at, day in zip(result["signal_at"], result["date"]):
        local = signal_at.tz_convert("Asia/Shanghai")
        if local.date() != date.fromisoformat(day) or local.hour < 15:
            raise ValueError("signal_at must be after the close on its signal date")
    return result


@dataclass(frozen=True)
class LabelBuildResult:
    labels: pd.DataFrame
    excluded: pd.DataFrame
    horizon_days: int
    entry_proxy: str = "t+1 close"
    exit_proxy: str = "t+1+h close"
    label_definition: str = "asset price return minus same-period benchmark price return"


def build_excess_return_labels(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    trading_dates: Sequence[str],
    *,
    horizon_days: int = 5,
    benchmark_code: str = "000300.SH",
    allow_fixture: bool = False,
) -> LabelBuildResult:
    """Build eligible research labels and explicit exclusions without forward fill."""
    if not isinstance(horizon_days, int) or horizon_days < 1:
        raise ValueError("horizon_days must be a positive integer")
    if not isinstance(benchmark_code, str) or not re.fullmatch(r"[0-9]{6}\.[A-Z]{2}", benchmark_code):
        raise ValueError("benchmark_code must be a six-digit exchange index")
    calendar = _calendar_dates(trading_dates)
    signal_rows = _validate_signals(signals)
    bars = validate_price_bars(prices, allow_fixture=allow_fixture)
    by_date = {day: index for index, day in enumerate(calendar)}
    by_key = bars.set_index(["date", "code"], drop=False)
    labels: list[dict] = []
    excluded: list[dict] = []

    for signal in signal_rows.itertuples(index=False):
        day, code, signal_at = signal

        def reject(reason: str) -> None:
            excluded.append({"date": day, "code": code, "reason": reason})

        index = by_date.get(day)
        if index is None:
            reject("signal_date_not_in_calendar")
            continue
        if index + 1 + horizon_days >= len(calendar):
            reject("horizon_not_matured")
            continue
        entry_day = calendar[index + 1]
        exit_day = calendar[index + 1 + horizon_days]
        keys = (
            (entry_day, code), (exit_day, code),
            (entry_day, benchmark_code), (exit_day, benchmark_code),
        )
        missing = [name for name, key in zip(
            ("asset_entry", "asset_exit", "benchmark_entry", "benchmark_exit"), keys,
        ) if key not in by_key.index]
        if missing:
            reject("missing_" + "_and_".join(missing) + "_bar")
            continue
        asset_entry, asset_exit, benchmark_entry, benchmark_exit = (by_key.loc[key] for key in keys)
        if asset_entry["trade_status"] != "trading" or asset_entry["volume"] <= 0 or asset_entry["limit_up"]:
            reject("asset_entry_not_tradeable")
            continue
        if asset_exit["trade_status"] != "trading" or asset_exit["volume"] <= 0 or asset_exit["limit_down"]:
            reject("asset_exit_not_tradeable")
            continue
        if benchmark_entry["trade_status"] != "trading" or benchmark_exit["trade_status"] != "trading":
            reject("benchmark_not_available")
            continue
        price_rows = (asset_entry, asset_exit, benchmark_entry, benchmark_exit)
        label_available_at = max(row["available_at"] for row in price_rows)
        if label_available_at <= signal_at:
            raise ValueError("label availability cannot precede its signal")
        asset_return = float(asset_exit["close"] / asset_entry["close"] - 1.0)
        benchmark_return = float(benchmark_exit["close"] / benchmark_entry["close"] - 1.0)
        evidence = [f"{row['date']}:{row['code']}:{row['source_id']}" for row in price_rows]
        source_hash = hashlib.sha256(json.dumps(evidence, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        labels.append({
            "date": day,
            "code": code,
            "entry_date": entry_day,
            "exit_date": exit_day,
            "entry_at": pd.Timestamp(f"{entry_day}T15:00:00+08:00"),
            "exit_at": pd.Timestamp(f"{exit_day}T15:00:00+08:00"),
            "entry_price": float(asset_entry["close"]),
            "exit_price": float(asset_exit["close"]),
            "benchmark_entry_price": float(benchmark_entry["close"]),
            "benchmark_exit_price": float(benchmark_exit["close"]),
            "asset_return": asset_return,
            "benchmark_return": benchmark_return,
            "y_excess": asset_return - benchmark_return,
            "label_available_at": label_available_at,
            "price_source_id": "price-bars-" + source_hash,
            "asset_entry_source_id": asset_entry["source_id"],
            "asset_exit_source_id": asset_exit["source_id"],
            "benchmark_entry_source_id": benchmark_entry["source_id"],
            "benchmark_exit_source_id": benchmark_exit["source_id"],
            "asset_adjustment_method": asset_entry["adjustment_method"],
            "benchmark_adjustment_method": benchmark_entry["adjustment_method"],
            "evidence_class": (
                "observed_claim" if all(row["is_observed"] for row in price_rows)
                else "engineering_fixture"
            ),
        })
    return LabelBuildResult(
        labels=pd.DataFrame(labels), excluded=pd.DataFrame(excluded), horizon_days=horizon_days,
    )
