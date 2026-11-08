"""Walk-forward backtest framework and bear market stress windows.

Implements FR-003, FR-004:
- Rolling walk-forward evaluation (default 3-year train window, quarterly rebalance).
- Strictly point-in-time (t-1 close information set, no look-ahead bias).
- Rebalance transaction cost deduction (default 15 bps round-trip, test 0 & 30 bps).
- 4 Historical bear market stress window metrics extraction.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from stability_methods import (
    vol_target_scale,
    weights_a0,
    weights_hrp,
    weights_lw_minvar,
)

ANN_FACTOR = 252.0
DAILY_CASH_RET = 0.024 / ANN_FACTOR  # 2.4% p.a. risk-free rate

# The 4 Historical Bear Market Regimes in A-Share History
BEAR_WINDOWS = {
    "Bear2015": ("2015-06-12", "2016-02-29"),  # 杠杆牛崩塌与去杠杆熔断
    "Bear2018": ("2018-01-29", "2018-12-28"),  # 中美贸易争端与信用紧缩
    "Bear2022": ("2021-12-13", "2022-10-31"),  # 核心资产均值回归与美联储加息
    "Bear2026": ("2025-09-22", "2026-10-26"),  # 2026年真实持续熊市深调（报告同源）
}


def compute_drawdown_series(daily_ret: pd.Series) -> pd.Series:
    """Compute underwater drawdown percentage series from daily simple returns."""
    wealth = (1.0 + daily_ret).cumprod()
    peak = wealth.cummax()
    dd = (wealth / peak - 1.0) * 100.0
    return dd


def compute_metrics(daily_ret: pd.Series, turnover: float = 0.0, cost_drag_pct: float = 0.0) -> dict[str, float]:
    """Compute annualized metrics (MaxDD, Vol, CAGR, Sharpe, Calmar) for a return series."""
    clean = daily_ret.dropna()
    n = len(clean)
    if n < 5:
        return {
            "n_days": n,
            "ann_ret_pct": 0.0,
            "ann_vol_pct": 0.0,
            "max_dd_pct": 0.0,
            "sharpe": 0.0,
            "calmar": 0.0,
            "turnover": turnover,
            "cost_drag_pct": cost_drag_pct,
        }

    wealth = (1.0 + clean).cumprod()
    total_ret = float(wealth.iloc[-1] - 1.0)
    years = n / ANN_FACTOR
    ann_ret = float((wealth.iloc[-1] ** (1.0 / max(years, 1e-4)) - 1.0) * 100.0)
    ann_vol = float(clean.std() * np.sqrt(ANN_FACTOR) * 100.0)

    dd_series = compute_drawdown_series(clean)
    max_dd = float(dd_series.min())

    rf_pct = 2.4
    sharpe = float((ann_ret - rf_pct) / max(ann_vol, 1e-4))
    calmar = float(ann_ret / abs(max_dd)) if abs(max_dd) > 1e-4 else 0.0

    return {
        "n_days": n,
        "ann_ret_pct": round(ann_ret, 2),
        "ann_vol_pct": round(ann_vol, 2),
        "max_dd_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 3),
        "calmar": round(calmar, 3),
        "turnover": round(turnover, 2),
        "cost_drag_pct": round(cost_drag_pct, 4),
    }


def compute_window_metrics(
    daily_net_ret: pd.Series,
    windows: Mapping[str, tuple[str, str]] | None = None,
) -> pd.DataFrame:
    """Extract performance metrics across all specified historical stress windows."""
    target_windows = dict(windows) if windows is not None else dict(BEAR_WINDOWS)
    rows: list[dict[str, Any]] = []

    # Full Sample Metrics
    full_m = compute_metrics(daily_net_ret)
    full_m["window"] = "FullSample"
    rows.append(full_m)

    # Individual Bear Window Metrics
    for name, (start_dt, end_dt) in target_windows.items():
        slice_ret = daily_net_ret.loc[start_dt:end_dt]
        w_m = compute_metrics(slice_ret)
        w_m["window"] = name
        rows.append(w_m)

    df = pd.DataFrame(rows).set_index("window")
    return df


def run_walkforward(
    prices: pd.DataFrame,
    method: str = "A0",
    train_days: int = 756,
    rebalance_freq: str = "Q",
    cost_bps: float = 15.0,
    cap: float = 0.40,
    vol_target: float = 0.08,
) -> dict[str, Any]:
    """Execute out-of-sample walk-forward backtest for a portfolio method.

    Parameters:
        prices: Date-indexed price DataFrame for candidate assets.
        method: One of ['A0', 'A1', 'A2', 'A3'].
        train_days: Lookback estimation window (e.g. 756 days ~ 3 years).
        rebalance_freq: 'Q' (quarterly), 'M' (monthly), or 'A' (annual).
        cost_bps: Round-trip transaction cost in basis points (15 bps default).
        cap: Maximum asset weight constraint for A1.
        vol_target: Target annualized volatility for A3.

    Returns:
        Dict with keys: 'daily_net_ret', 'weights', 'turnover', 'cost_drag_pct', 'nav'.
    """
    daily_asset_rets = prices.pct_change().dropna(how="all").fillna(0.0)
    dates = daily_asset_rets.index
    n_days = len(dates)

    if n_days <= train_days:
        raise ValueError(f"Total days ({n_days}) must be greater than train_days ({train_days})")

    # Determine rebalance dates: first trading day of each quarter/month
    period_series = dates.to_period(rebalance_freq)
    is_new_period = period_series != period_series.shift(1)
    # Only rebalance after the initial training window has elapsed
    is_rebal_day = is_new_period & (np.arange(n_days) >= train_days)

    assets = list(prices.columns)
    # Weights include candidate assets plus synthetic 'CASH'
    all_assets = assets + ["CASH"]

    curr_weights = pd.Series(0.0, index=all_assets, dtype=float)
    # Seed initial weight with A0 baseline before first dynamic rebalance
    init_a0 = weights_a0(daily_asset_rets.iloc[:train_days])
    for a, w in init_a0.items():
        if a in curr_weights:
            curr_weights[a] = w
    if curr_weights.sum() > 0:
        curr_weights = curr_weights / curr_weights.sum()
    else:
        curr_weights["CASH"] = 1.0

    weight_records: list[pd.Series] = []
    daily_net_returns: list[float] = []
    total_turnover = 0.0
    total_friction_drag = 0.0

    for i in range(train_days, n_days):
        dt = dates[i]
        rebal_today = is_rebal_day[i]

        if rebal_today:
            # Strictly point-in-time: use data up to day i-1
            train_slice = daily_asset_rets.iloc[i - train_days : i]
            # Exclude assets not yet listed / traded during this training window
            valid_cols = [c for c in assets if (prices[c].iloc[i - train_days : i] > 0).sum() > 60]
            slice_valid = train_slice[valid_cols].dropna(how="any")

            if method == "A0":
                target_w = weights_a0(slice_valid)
            elif method == "A1":
                target_w = weights_lw_minvar(slice_valid, cap=cap)
            elif method == "A2":
                target_w = weights_hrp(slice_valid)
            elif method == "A3":
                # A3 base is A0, scaled by realized volatility
                base_w = weights_a0(slice_valid)
                # Compute realized portfolio return of base_w over recent 60 days
                recent_rets = slice_valid.dot(base_w.reindex(slice_valid.columns).fillna(0.0))
                scale = vol_target_scale(recent_rets, target_vol=vol_target, window=60)
                target_w = base_w * scale
                target_w["CASH"] = target_w.get("CASH", 0.0) + (1.0 - scale)
            else:
                raise ValueError(f"Unknown method: {method}")

            # Expand to full asset universe including CASH
            new_weights = pd.Series(0.0, index=all_assets, dtype=float)
            for col, w in target_w.items():
                if col in new_weights:
                    new_weights[col] = w
            if new_weights.sum() > 0:
                new_weights = new_weights / new_weights.sum()

            # Turnover calculation
            # Drifted weights at start of day i
            turnover_step = float(0.5 * (new_weights - curr_weights).abs().sum())
            friction = turnover_step * (cost_bps / 10000.0)
            total_turnover += turnover_step
            total_friction_drag += friction
            curr_weights = new_weights
        else:
            friction = 0.0

        weight_records.append(curr_weights.copy())

        # Day i simple return: asset rets + CASH ret
        day_rets = daily_asset_rets.iloc[i]
        asset_gain = sum(curr_weights.get(c, 0.0) * day_rets.get(c, 0.0) for c in assets)
        cash_gain = curr_weights.get("CASH", 0.0) * DAILY_CASH_RET
        gross_ret = asset_gain + cash_gain
        net_ret = gross_ret - friction
        daily_net_returns.append(net_ret)

        # Passive asset drift until next rebalance
        drifted = {}
        for c in assets:
            drifted[c] = curr_weights.get(c, 0.0) * (1.0 + day_rets.get(c, 0.0))
        drifted["CASH"] = curr_weights.get("CASH", 0.0) * (1.0 + DAILY_CASH_RET)
        sum_drift = sum(drifted.values())
        if sum_drift > 0:
            for k in all_assets:
                curr_weights[k] = drifted[k] / sum_drift

    out_dates = dates[train_days:]
    net_ret_series = pd.Series(daily_net_returns, index=out_dates, name=f"{method}_net_ret")
    weights_df = pd.DataFrame(weight_records, index=out_dates)
    nav_series = (1.0 + net_ret_series).cumprod()

    return {
        "daily_net_ret": net_ret_series,
        "weights": weights_df,
        "turnover": total_turnover,
        "cost_drag_pct": total_friction_drag * 100.0,
        "nav": nav_series,
    }
