"""Universe data loading and quality gate for ETF long-history panel (2012-2026).

Implements FR-001 and FR-002:
- Loads daily close price series from ``scratch/etf_hist/<code}.json`` (read-only).
- Detects unadjusted corporate action / split jumps.
- Rejects disqualified ETFs and locks in the 10-ETF clean qualified pool.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ETF_DIR = PROJECT_ROOT / "scratch" / "etf_hist"

# The 10 ETFs verified to have zero unadjusted share split jumps
QUALIFIED_CODES = [
    "510050",  # 上证50ETF
    "510300",  # 沪深300ETF
    "159915",  # 创业板ETF (±20% limit)
    "588000",  # 科创50ETF (±20% limit)
    "512660",  # 军工ETF
    "512880",  # 证券ETF
    "515030",  # 新能源车ETF
    "515790",  # 光伏ETF
    "518880",  # 黄金ETF
    "511010",  # 国债ETF
]

# The 6 ETFs confirmed to suffer from unadjusted share consolidation/split anomalies
DISQUALIFIED_CODES = [
    "510500",  # 中证500ETF (+248.6% on 2015-04-15)
    "512010",  # 医药ETF (-73.9% on 2021-06-28)
    "512100",  # 中证1000ETF (+176.3% on 2022-09-05)
    "512690",  # 酒ETF (-48.0% on 2021-05-17, -27.1% on 2021-12-31)
    "512760",  # 半导体芯片ETF (-53.1% on 2020-09-10, -49.7% on 2026-03-27)
    "515050",  # 5G通信ETF (-65.3% on 2026-05-13)
]

# Daily price limits in A-share market
WIDE_LIMIT_CODES = {"159915", "588000"}  # 20% limit
WIDE_LIMIT_THRESHOLD = 0.21
STANDARD_LIMIT_THRESHOLD = 0.11
CLOSE_IDX = 1


def get_etf_path(code: str) -> Path:
    """Return JSON file path for given ETF code."""
    p = ETF_DIR / f"{code}.json"
    if not p.exists():
        raise FileNotFoundError(f"ETF data file not found: {p}")
    return p


def load_close(code_or_path: str | Path) -> pd.Series:
    """Load an ETF close price series, validated for monotonicity and positivity."""
    path = Path(code_or_path) if isinstance(code_or_path, Path) or "/" in str(code_or_path) or "\\" in str(code_or_path) else get_etf_path(str(code_or_path))
    data = json.loads(path.read_text(encoding="utf-8"))
    code = data.get("code", path.stem)
    dates = data["dates"]
    kline = data["kline"]

    if len(dates) != len(kline):
        raise ValueError(f"{code}: dates length ({len(dates)}) != kline length ({len(kline)})")

    close_values = [float(row[CLOSE_IDX]) for row in kline]
    index = pd.to_datetime(dates)
    series = pd.Series(close_values, index=index, name=code, dtype=float)

    if not series.index.is_monotonic_increasing:
        raise ValueError(f"{code}: DatetimeIndex is not strictly monotonically increasing")
    if series.index.has_duplicates:
        raise ValueError(f"{code}: DatetimeIndex contains duplicate dates")
    if (series <= 0).any():
        raise ValueError(f"{code}: non-positive close prices encountered")

    return series


def detect_jumps(close: pd.Series, limit: float | None = None) -> pd.Series:
    """Return outlier daily return spikes that exceed allowable price limit threshold."""
    code = str(close.name)
    if limit is None:
        limit = WIDE_LIMIT_THRESHOLD if code in WIDE_LIMIT_CODES else STANDARD_LIMIT_THRESHOLD

    daily_ret = close.pct_change().dropna()
    jumps = daily_ret[daily_ret.abs() > limit]
    return jumps


def load_universe(codes: Sequence[str] | None = None) -> pd.DataFrame:
    """Load and align daily close prices for specified universe, enforcing jump quality gate.

    Raises:
        ValueError: If any requested ETF exhibits unadjusted price jump anomalies.
    """
    target_codes = list(codes) if codes is not None else list(QUALIFIED_CODES)
    series_dict: dict[str, pd.Series] = {}

    for code in target_codes:
        s = load_close(code)
        jumps = detect_jumps(s)
        if not jumps.empty:
            jump_details = ", ".join(f"{d.date()}: {r:+.2%}" for d, r in jumps.items())
            raise ValueError(
                f"Corporate action / unadjusted price jump detected in {code}: [{jump_details}]. "
                f"Disqualified from clean defense universe."
            )
        series_dict[code] = s

    df = pd.DataFrame(series_dict)
    # Sort index chronologically
    df = df.sort_index()
    return df
