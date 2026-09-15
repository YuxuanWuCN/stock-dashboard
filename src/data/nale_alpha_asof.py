"""Point-in-time revision selection for NALE inputs and historical network edges."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Sequence

import pandas as pd


_TIMEZONE_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")


class AsOfError(ValueError):
    """Input cannot support a defensible decision-time snapshot."""


def _date_only(value: object, field: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise AsOfError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AsOfError(f"{field} is invalid") from exc


def _aware_time(value: object, field: str) -> pd.Timestamp:
    if not isinstance(value, str) or _TIMEZONE_SUFFIX.search(value) is None:
        raise AsOfError(f"{field} must have an explicit timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AsOfError(f"{field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AsOfError(f"{field} must have an explicit timezone")
    return pd.Timestamp(parsed).tz_convert("UTC")


def select_asof_revision(
    frame: pd.DataFrame,
    *,
    signal_date: str,
    decision_cutoff: str,
    keys: Sequence[str],
    available_at_column: str = "available_at",
    date_column: str | None = "date",
    effective_from_column: str | None = None,
    effective_to_column: str | None = None,
) -> pd.DataFrame:
    """Return the latest known revision per key, never backfilling a future publication."""
    day = _date_only(signal_date, "signal_date")
    cutoff = _aware_time(decision_cutoff, "decision_cutoff")
    if not keys or len(set(keys)) != len(keys):
        raise AsOfError("keys must be a nonempty unique sequence")
    if (effective_from_column is None) != (effective_to_column is None):
        raise AsOfError("effective_from and effective_to must be supplied together")
    required = set(keys) | {available_at_column}
    if date_column is not None:
        required.add(date_column)
    if effective_from_column is not None:
        required.update((effective_from_column, effective_to_column))
    missing = sorted(required - set(frame.columns))
    if missing:
        raise AsOfError(f"required columns missing: {', '.join(missing)}")
    if frame[list(keys)].isna().any().any():
        raise AsOfError("revision keys contain null values")
    if frame.empty:
        return frame.copy()
    known_at = frame[available_at_column].map(lambda value: _aware_time(value, available_at_column))
    mask = known_at.le(cutoff)
    if date_column is not None:
        dates = frame[date_column].map(lambda value: _date_only(value, date_column))
        mask &= dates.eq(day)
    if effective_from_column is not None:
        starts = frame[effective_from_column].map(
            lambda value: _date_only(value, effective_from_column)
        )
        ends = frame[effective_to_column].map(
            lambda value: None if pd.isna(value) else _date_only(value, effective_to_column)
        )
        for start, end in zip(starts, ends):
            if end is not None and end < start:
                raise AsOfError("effective interval ends before it starts")
        mask &= starts.le(day) & ends.map(lambda end: end is None or day <= end)
    eligible = frame.loc[mask].copy()
    if eligible.empty:
        return eligible
    eligible["_nale_known_at"] = known_at.loc[mask]
    latest = eligible.groupby(list(keys), dropna=False)["_nale_known_at"].transform("max")
    selected = eligible.loc[eligible["_nale_known_at"].eq(latest)].copy()
    if selected.duplicated(subset=list(keys), keep=False).any():
        raise AsOfError("duplicate latest revision for a decision-time key")
    return selected.drop(columns="_nale_known_at").sort_values(list(keys), kind="mergesort").reset_index(drop=True)
