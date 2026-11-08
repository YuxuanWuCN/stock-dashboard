"""Step 1 of the 2026-11 stability study: audit the 17-ETF long-history panel.

Reads ``scratch/etf_hist/*.json`` (read-only), reports coverage, gaps, outliers and
price-only caveats (e.g. money-market ETF 511880 distributes monthly, so a qfq close
series does NOT capture its yield). Writes one CSV into the study output directory.

kline row layout in the source JSON is ECharts-style: [open, close, low, high].
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ETF_DIR = PROJECT_ROOT / "scratch" / "etf_hist"
OUT_DIR = PROJECT_ROOT / "R-FOF" / "reports" / "stability_20261108" / "tables"

OUTLIER_ABS_RET = 0.11   # |daily ret| above this is flagged (ETF price limit is 10%)
GAP_DAYS = 10            # calendar-day gap above this is flagged (CNY/National Day ~9d)
CLOSE_IDX = 1


def load_close(path: Path) -> pd.Series:
    """Load one ETF JSON into a date-indexed close series (validates alignment)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    dates, kline = d["dates"], d["kline"]
    if len(dates) != len(kline):
        raise ValueError(f"{path.name}: dates/kline length mismatch")
    s = pd.Series([row[CLOSE_IDX] for row in kline],
                  index=pd.to_datetime(dates), name=d["code"], dtype=float)
    if not s.index.is_monotonic_increasing or s.index.has_duplicates:
        raise ValueError(f"{path.name}: index not strictly increasing")
    return s


def audit_one(path: Path) -> dict:
    """Return coverage / quality statistics for a single ETF."""
    meta = json.loads(path.read_text(encoding="utf-8"))
    s = load_close(path)
    r = s.pct_change().dropna()
    gaps = s.index.to_series().diff().dt.days.dropna()
    years = (s.index[-1] - s.index[0]).days / 365.25
    return {
        "code": meta["code"], "name": meta["name"],
        "start": s.index[0].date(), "end": s.index[-1].date(), "n_days": len(s),
        "n_nan": int(s.isna().sum()), "n_nonpos": int((s <= 0).sum()),
        "n_gap_gt10d": int((gaps > GAP_DAYS).sum()),
        "n_outlier_ret": int((r.abs() > OUTLIER_ABS_RET).sum()),
        "max_abs_ret": float(r.abs().max()),
        "price_cagr_pct": float((s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1) * 100,
        "ann_vol_pct": float(r.std() * np.sqrt(252)) * 100,
        "max_dd_pct": float((s / s.cummax() - 1).min()) * 100,
    }


def main() -> pd.DataFrame:
    rows = [audit_one(p) for p in sorted(ETF_DIR.glob("*.json"))]
    df = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / "etf_data_audit.csv", index=False, encoding="utf-8-sig")
    return df


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    print(main().round(2).to_string(index=False))
