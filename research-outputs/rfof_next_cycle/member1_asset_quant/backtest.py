
"""Point-in-time defense, equity, futures and accumulation accounting."""
from __future__ import annotations

import numpy as np
import pandas as pd

from market import CASH, ETF_CODES, FUTURES
from src.data.return_basis import compute_return_basis
from stability_methods import vol_target_scale, weights_a0, weights_hrp, weights_hrp_vt, weights_lw_minvar
from stability_walkforward import BEAR_WINDOWS

ANN = 252
BASE_ETFS = ("511010", "510050", "510300")
METHODS = ("A0", "A1", "A2", "A3", "A4")


def drawdown(returns: pd.Series) -> pd.Series:
    wealth = (1 + returns).cumprod()
    return wealth / wealth.cummax().clip(lower=1.0) - 1.0


def metrics(returns: pd.Series, cash: pd.Series) -> dict:
    if len(returns) < 2 or not np.isfinite(returns).all() or (returns <= -1).any():
        raise ValueError("metrics require at least two finite returns greater than -100%")
    excess = returns - cash.reindex(returns.index)
    if not np.isfinite(excess).all():
        raise ValueError("metrics require aligned cash rates")
    growth = float(np.log1p(returns).sum())
    vol = float(returns.std() * np.sqrt(ANN))
    excess_std = excess.std()
    cagr = np.expm1(growth * ANN / len(returns))
    dd = drawdown(returns).min()
    return {
        "start_date": returns.index[0].date().isoformat(),
        "end_date": returns.index[-1].date().isoformat(),
        "n_days": len(returns),
        "total_ret_pct": 100 * np.expm1(growth),
        "ann_ret_pct": 100 * cagr,
        "ann_vol_pct": 100 * vol,
        "max_dd_pct": 100 * dd,
        "sharpe": np.sqrt(ANN) * excess.mean() / excess_std if excess_std > 1e-12 else np.nan,
        "calmar": cagr / abs(dd) if dd < -1e-12 else np.nan,
    }


def _defense_target(history: pd.DataFrame, method: str, target_vol: float, min_history: int) -> pd.Series:
    baseline = history[list(BASE_ETFS)].dropna()
    if method == "A0":
        return weights_a0(baseline)
    if method == "A3":
        base = weights_a0(baseline)
        scale = vol_target_scale(baseline @ base, target_vol)
        target = base * scale
        target[CASH] = 1.0 - scale
        return target
    if method not in METHODS:
        raise ValueError(f"unknown defense method: {method}")
    available = history[list(ETF_CODES)]
    mature = available.columns[available.count().ge(min_history) & available.std().gt(1e-12)]
    risk = available[mature].dropna()
    if len(risk) < min_history or risk.shape[1] < 3:
        raise ValueError("insufficient common history for mature ETF allocation")
    if method == "A1":
        result = weights_lw_minvar(risk)
        # Keep the cap even on the legacy solver's exceptional fallback path.
        if result.max() > 0.4 + 1e-9:
            return pd.Series(1.0 / len(mature), index=mature)
        return result
    if method == "A2":
        return weights_hrp(risk)
    return weights_hrp_vt(risk, CASH, target_vol=target_vol)


def defense_ledger(
    returns: pd.DataFrame,
    method: str,
    *,
    cost_bps: float = 30,
    lookback: int = 756,
    target_vol: float = 0.08,
    min_history: int = 252,
) -> pd.DataFrame:
    """Rebalance at quarter entry from t-1 information and track passive drift."""
    if lookback < min_history or min_history < 10:
        raise ValueError("invalid defense lookback")
    columns = [*ETF_CODES, CASH]
    returns = returns.loc[:, columns]
    complete_core = returns[[*BASE_ETFS, CASH]].notna().all(axis=1)
    if complete_core.sum() <= min_history:
        raise ValueError("too few aligned baseline ETF and cash returns")
    opening = complete_core[complete_core].index[min_history]
    evaluation = returns.loc[opening:]
    if not complete_core.loc[opening:].all():
        raise ValueError("missing core ETF or cash data in defense sample")
    weights = pd.Series(0.0, index=columns)
    weights[CASH] = 1.0
    period = None
    nav = 1.0
    rows = []
    for day, daily in evaluation.iterrows():
        ongoing = day.to_period("Q")
        turnover = 0.0
        if period != ongoing:
            old = weights
            end = returns.index.get_loc(day)
            history = returns.iloc[max(0, end - lookback):end]
            weights = _defense_target(history, method, target_vol, min_history).reindex(columns, fill_value=0.0)
            turnover = float((weights - old).abs().sum() / 2)
            period = ongoing
        if daily[weights > 0].isna().any():
            raise ValueError(f"missing held ETF return on {day.date()}")
        daily = daily.fillna(0.0)
        cost = turnover * cost_bps / 10_000
        growth = weights * (1.0 + daily)
        gross_factor = float(growth.sum())
        net = gross_factor * (1.0 - cost) - 1.0
        nav *= 1.0 + net
        rows.append((net, nav, turnover, cost, *weights.to_numpy()))
        weights = growth / gross_factor
    return pd.DataFrame(
        rows, index=evaluation.index,
        columns=["net_return", "nav", "turnover", "trade_cost", *(f"w_{c}" for c in columns)],
    )


def defense_windows(ledgers: dict, cash: pd.Series) -> pd.DataFrame:
    records = []
    for (method, param, bps), ledger in ledgers.items():
        series = ledger["net_return"]
        complete_windows = [
            (name, series.loc[start:end]) for name, (start, end) in BEAR_WINDOWS.items()
            if series.index[0] <= pd.Timestamp(start) and series.index[-1] >= pd.Timestamp(end)
        ]
        for window, segment in [("FullSample", series), *complete_windows]:
            if len(segment) < 2:
                continue
            part = ledger.loc[segment.index]
            records.append({
                "method": method, "param_id": param, "cost_bps_round_trip": bps, "window": window,
                **metrics(segment, cash), "turnover": part["turnover"].sum(),
                "cost_drag_pct": 100 * (1 - (1 - part["trade_cost"]).prod()),
            })
    return pd.DataFrame(records)


def stock_ledger(panel: pd.DataFrame, declarations: pd.DataFrame, cost_bps: float = 30) -> tuple[pd.DataFrame, dict]:
    # The prior declared data basis controls returns. A future full-sample
    # diagnosis must not be used as a historical filter on individual names.
    declared_only = pd.DataFrame(columns=["stock_code", "verdict"])
    basis = compute_return_basis(panel, declarations, verification=declared_only)
    grid = basis.pivot(index="trade_date", columns="stock_code", values="basis_return")
    volume = panel.pivot(index="trade_date", columns="stock_code", values="volume").reindex_like(grid)
    grid.index = pd.DatetimeIndex(grid.index, name="trade_date")
    usable = grid.to_numpy(dtype=float)
    if np.isinf(usable).any() or (usable <= -1).any():
        raise ValueError("stock total return out of domain")
    observed = volume.to_numpy(dtype=float) > 0
    weights = np.zeros(grid.shape[1])
    nav = 1.0
    current_month = None
    rows = []
    for pos, day in enumerate(grid.index[1:], start=1):
        month = day.to_period("M")
        turnover = 0.0
        if month != current_month:
            can_trade = observed[pos - 1]
            if not can_trade.any():
                raise ValueError(f"no tradeable stocks as of {grid.index[pos - 1]}")
            frozen = weights[~can_trade].sum()
            desired = weights.copy()
            desired[can_trade] = (1 - frozen) / can_trade.sum()
            turnover = (np.abs(desired - weights).sum() + abs(desired.sum() - weights.sum())) / 2
            weights = desired
            current_month = month
        values = usable[pos]
        locked = float(weights[np.isnan(values)].sum())
        after_move = weights * (1.0 + np.nan_to_num(values, nan=0.0))
        gross_factor = float(after_move.sum())
        cost = turnover * cost_bps / 10_000
        net = gross_factor * (1 - cost) - 1
        nav *= 1.0 + net
        rows.append((net, nav, turnover, cost, locked, int(np.count_nonzero(weights))))
        weights = after_move / gross_factor
    stats = {
        "rows": len(panel), "stocks": len(grid.columns), "sessions": len(grid.index),
        "first_date": grid.index[0].date().isoformat(), "last_date": grid.index[-1].date().isoformat(),
        "missing_stock_date_rows": int(grid.size - len(panel)),
        "return_basis_rows": {str(k): int(v) for k, v in basis["basis_source"].value_counts().items()},
        "cohort_stocks": {
            str(k): int(v) for k, v in declarations.loc[
                declarations["stock_code"].isin(grid.columns), "cohort"
            ].value_counts().items()
        },
    }
    return pd.DataFrame(
        rows, index=grid.index[1:],
        columns=["net_return", "nav", "turnover", "trade_cost", "unmarked_weight", "held_stocks"],
    ), stats


def futures_ledger(
    prices: pd.DataFrame, cash: pd.Series, *, ma_days: int = 20, roll_bps: int = 20,
    rolls_per_year: int = 6, margin: float = 0.15,
) -> pd.DataFrame:
    """Continuous-price proxy with B0, B1 and a margin-carry B2 stacked on B1."""
    moves, active = {}, {}
    for code in FUTURES:
        close = prices[code].dropna()
        moves[code] = close.pct_change(fill_method=None).reindex(cash.index)
        ma = close.rolling(ma_days).mean()
        active[code] = close.gt(ma).where(ma.notna()).shift(1).reindex(cash.index)
    moves, active = pd.DataFrame(moves), pd.DataFrame(active)
    if moves.isna().any().any() or active.isna().any().any():
        raise ValueError("missing futures observations or insufficient MA warm-up on lifecycle dates")
    if cash.isna().any() or not 0 <= margin <= 1:
        raise ValueError("missing cash observations or invalid margin ratio")
    active = active.astype(float)
    exposure = active @ pd.Series(FUTURES)
    trend_pnl = moves.mul(active) @ pd.Series(FUTURES)
    b0 = trend_pnl + (1 - exposure) * cash
    roll_cost = exposure * (roll_bps * rolls_per_year / 10_000 / ANN)
    collateral_yield = exposure * (1 - margin) * cash
    return pd.DataFrame({
        "B0": b0, "B1": b0 - roll_cost, "B2": b0 - roll_cost + collateral_yield,
        "roll_cost": roll_cost, "collateral_yield": collateral_yield,
        "futures_active_notional": exposure,
    })


def lifecycle_weights(age: float) -> np.ndarray:
    """Research ledger allocation. Archive reports give the hump but lack the full parameter set."""
    width = 10 if age <= 35 else 12
    growth = 0.20 + 0.50 * np.exp(-0.5 * ((age - 35) / width) ** 2)
    return np.array([1 - growth, 0.8 * growth, 0.2 * growth])


def lifecycle_ledger(
    defense: pd.DataFrame, stocks: pd.DataFrame, futures: pd.DataFrame, variant: str,
    *, start_age: int = 35, bps: float = 30, wrapper_fee: float = 0.005,
) -> pd.DataFrame:
    """R-FOF research ledger with an auditable quarterly one-way profit ratchet."""
    dates = stocks.index
    legs = pd.DataFrame({
        "defense": defense["net_return"], "equity": stocks["net_return"], "futures": futures[variant],
    }).reindex(dates)
    if not np.isfinite(legs).all().all() or (legs <= -1).any().any():
        raise ValueError("missing or invalid lifecycle input")
    holdings = lifecycle_weights(start_age)
    anchor = holdings[1:].sum()
    period = dates[0].to_period("Q")
    rows = []
    for pos, (day, returns) in enumerate(legs.iterrows()):
        prior = float(holdings.sum())
        weights_before = holdings / prior
        age = start_age + (day - dates[0]).days / 365.2425
        this_period = day.to_period("Q")
        sweep = 0.0
        shift = 0.0
        if this_period != period:
            attack = holdings[1:].sum()
            sweep = 0.50 * max(attack - anchor * 1.06, 0.0)
            limit = lifecycle_weights(age)[1:].sum() * prior
            shift = max(sweep, attack - limit, 0.0)
            core = attack - shift
            holdings = np.array([holdings[0] + shift, 0.8 * core, 0.2 * core])
            anchor = core
            period = this_period
        weights = holdings / prior
        turnover = 1.0 if pos == 0 else float(np.abs(weights - weights_before).sum() / 2)
        trade_cost = turnover * bps / 10_000
        fee = wrapper_fee / ANN
        holdings = holdings * (1 - trade_cost) * (1 - fee) * (1 + returns.to_numpy())
        nav = float(holdings.sum())
        rows.append((nav / prior - 1, nav, age, *weights, *returns, turnover, trade_cost, fee,
                     sweep, shift - sweep, holdings[0], holdings[1] + holdings[2]))
    ledger = pd.DataFrame(rows, index=dates, columns=[
        "net_return", "nav", "age", "w_defense", "w_equity", "w_futures",
        "defense_return", "equity_return", "futures_return", "turnover", "portfolio_trade_cost",
        "wrapper_fee", "ratchet_transfer_nav", "glide_transfer_nav", "defense_nav", "growth_nav",
    ])
    ledger["defense_trade_cost"] = defense["trade_cost"].reindex(dates)
    ledger["equity_trade_cost"] = stocks["trade_cost"]
    ledger["futures_roll_cost"] = futures["roll_cost"] if variant in ("B1", "B2") else 0.0
    ledger["futures_collateral_yield"] = futures["collateral_yield"] if variant == "B2" else 0.0
    return ledger
