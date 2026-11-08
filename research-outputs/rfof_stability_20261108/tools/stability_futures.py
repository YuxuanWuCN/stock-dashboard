"""Futures sleeve realism and sensitivity engine (FR-005, US2).

Implements:
- B0: Baseline reproduction (zero-error match with precomputed_core_returns.csv)
- B1: Roll cost drag grid (0, 5, 10, 20 bps * rolls per year)
- B2: Margin financing & cash yield compensation (10%, 15%, 100%)
- B3: Moving average lookback sensitivity (MA 10, 20, 40, 60)
- B4: Holiday alignment sensitivity (ffill vs true calendar cash yield)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "Rainbow_FinGPTv2" / "data" / "raw"
PRECOMPUTED_CSV = (
    PROJECT_ROOT
    / "R-FOF"
    / "reports"
    / "personal_lifecycle_backtest"
    / "precomputed_core_returns.csv"
)

FUTURES_WEIGHTS = {"AU": 0.50, "M": 0.25, "CU": 0.25}
ANN_FACTOR = 252.0


def _load_csv_raw(path: Path, use_iloc: bool) -> pd.Series:
    """Robust CSV loader handling UTF-8 and GBK encodings."""
    try:
        df = pd.read_csv(path, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="gbk")

    if use_iloc:
        date_col = df.iloc[:, 0]
        close_col = pd.to_numeric(df.iloc[:, 4], errors="coerce")
    else:
        lowered = {str(c).strip().lower(): c for c in df.columns}
        date_col = df[lowered["date"]]
        close_col = pd.to_numeric(df[lowered["close"]], errors="coerce")

    idx = pd.to_datetime(date_col)
    series = pd.Series(close_col.to_numpy(), index=idx, dtype=float)
    series = series.where(series > 0).dropna()
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series


def load_precomputed_baseline_futures() -> pd.Series:
    """Load canonical r_futures_hedge series from precomputed_core_returns.csv."""
    df = pd.read_csv(PRECOMPUTED_CSV, index_col=0, parse_dates=True)
    return df["r_futures_hedge"]


def compute_futures_variant(
    roll_cost_bps: float = 0.0,
    rolls_per_year: int = 6,
    margin_pct: float = 1.0,
    ma_window: int = 20,
    holiday_mode: str = "ffill",
) -> pd.Series:
    """Compute customized daily return series for the futures sleeve under realism adjustments."""
    precomputed = pd.read_csv(PRECOMPUTED_CSV, index_col=0, parse_dates=True)
    panel_index = precomputed.index
    risk_free = precomputed["r_rf"]

    # Load raw continuous futures
    sources = [
        ("AU", DATA_ROOT / "shfe_au_futures_daily_raw.csv", True),
        ("M", DATA_ROOT / "commodity_futures" / "m_futures_daily_raw.csv", False),
        ("CU", DATA_ROOT / "commodity_futures" / "cu_futures_daily_raw.csv", False),
    ]

    total_sleeve = pd.Series(0.0, index=panel_index, dtype=float)

    # Annual roll cost drag converted to daily drag
    ann_roll_drag = (rolls_per_year * roll_cost_bps) / 10000.0
    daily_roll_drag = ann_roll_drag / ANN_FACTOR

    for label, path, use_iloc in sources:
        full_close = _load_csv_raw(path, use_iloc=use_iloc)
        # Compute trend signal on full history before reindexing
        full_ma = full_close.rolling(ma_window, min_periods=ma_window).mean()
        trend_full = (full_close > full_ma).astype(float)

        # Align to equity panel
        trend_panel = trend_full.reindex(panel_index, method="ffill").fillna(0.0).astype(bool)
        close_panel = full_close.reindex(panel_index, method="ffill")

        # Daily percentage change (without look-ahead, fill_method=None)
        pct_change = close_panel.pct_change(fill_method=None)
        above_ma = trend_panel.shift(1, fill_value=False).astype(bool)

        # When trend is active:
        # If margin_pct < 1.0: margin is posted for futures return, unencumbered (1 - margin_pct) gets risk_free
        # When trend is inactive: full sleeve sits in risk_free
        if margin_pct < 1.0:
            futures_active_ret = (pct_change * 1.0) + ((1.0 - margin_pct) * risk_free) - daily_roll_drag
        else:
            futures_active_ret = pct_change - daily_roll_drag

        if holiday_mode == "calendar":
            # Identify days where futures exchange was closed (pct_change == 0 or NaN)
            was_closed = pct_change.isna() | (pct_change == 0.0)
            # If closed, allocate to risk_free for that day
            futures_active_ret = futures_active_ret.where(~was_closed, risk_free)

        leg_return = futures_active_ret.where(above_ma, risk_free)
        weight = FUTURES_WEIGHTS[label]
        total_sleeve = total_sleeve.add(weight * leg_return.fillna(0.0), fill_value=0.0)

    return total_sleeve.rename(f"r_fut_w{ma_window}_c{int(roll_cost_bps)}")


def compute_futures_sensitivity_grid() -> pd.DataFrame:
    """Generate sensitivity grid across costs, margins, and MA windows."""
    precomputed = pd.read_csv(PRECOMPUTED_CSV, index_col=0, parse_dates=True)
    rf_pct = 2.4

    scenarios = [
        # Variant, roll_cost_bps, rolls_per_year, margin_pct, ma_window, holiday_mode
        ("B0_Baseline", 0.0, 6, 1.0, 20, "ffill"),
        ("B1_RollCost_5bps", 5.0, 6, 1.0, 20, "ffill"),
        ("B1_RollCost_10bps", 10.0, 6, 1.0, 20, "ffill"),
        ("B1_RollCost_20bps", 20.0, 6, 1.0, 20, "ffill"),
        ("B2_Margin_15pct", 5.0, 6, 0.15, 20, "ffill"),
        ("B2_Margin_10pct", 5.0, 6, 0.10, 20, "ffill"),
        ("B3_MA_10", 5.0, 6, 1.0, 10, "ffill"),
        ("B3_MA_40", 5.0, 6, 1.0, 40, "ffill"),
        ("B3_MA_60", 5.0, 6, 1.0, 60, "ffill"),
        ("B4_TrueCalendar", 5.0, 6, 1.0, 20, "calendar"),
    ]

    records: list[dict[str, Any]] = []
    for var_name, cost, rolls, margin, ma, hol in scenarios:
        s = compute_futures_variant(
            roll_cost_bps=cost,
            rolls_per_year=rolls,
            margin_pct=margin,
            ma_window=ma,
            holiday_mode=hol,
        )
        wealth = (1.0 + s).cumprod()
        n = len(s)
        ann_ret = float((wealth.iloc[-1] ** (ANN_FACTOR / n) - 1.0) * 100.0)
        ann_vol = float(s.std() * np.sqrt(ANN_FACTOR) * 100.0)
        max_dd = float((wealth / wealth.cummax() - 1.0).min() * 100.0)
        sharpe = (ann_ret - rf_pct) / max(ann_vol, 1e-4)

        records.append({
            "variant": var_name,
            "roll_cost_bps": cost,
            "rolls_per_year": rolls,
            "margin_pct": margin * 100.0,
            "ma_window": ma,
            "holiday_mode": hol,
            "ann_ret_pct": round(ann_ret, 2),
            "ann_vol_pct": round(ann_vol, 2),
            "max_dd_pct": round(max_dd, 2),
            "sharpe": round(sharpe, 3),
        })

    return pd.DataFrame(records)
