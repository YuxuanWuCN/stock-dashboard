"""Authoritative Reference Specification Oracle for Cross-Asset Mixed Portfolio.
Implements the exact mathematical requirements and interface contracts defined in
PROJECT.md and ORIGINAL_REQUEST.md. Used as the authoritative oracle for test verification.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Feature 1: Contract Specifications
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    name: str
    asset_type: str  # 'STOCK' | 'FUTURES'
    exchange: str
    multiplier: float
    margin_rate: float
    tick_size: float
    lot_size: int  # 100 for stocks, 1 for futures


FUTURES_SPECS: Dict[str, ContractSpec] = {
    "SA": ContractSpec(
        symbol="SA",
        name="纯碱主力连续",
        asset_type="FUTURES",
        exchange="CZCE",
        multiplier=20.0,
        margin_rate=0.12,
        tick_size=1.0,
        lot_size=1,
    ),
    "FG": ContractSpec(
        symbol="FG",
        name="玻璃主力连续",
        asset_type="FUTURES",
        exchange="CZCE",
        multiplier=20.0,
        margin_rate=0.12,
        tick_size=1.0,
        lot_size=1,
    ),
    "AU": ContractSpec(
        symbol="AU",
        name="沪金主力连续",
        asset_type="FUTURES",
        exchange="SHFE",
        multiplier=1000.0,
        margin_rate=0.10,
        tick_size=0.02,
        lot_size=1,
    ),
}

DEFAULT_STOCK_SPEC = ContractSpec(
    symbol="",
    name="A股标的",
    asset_type="STOCK",
    exchange="SSE_SZSE",
    multiplier=1.0,
    margin_rate=1.0,
    tick_size=0.01,
    lot_size=100,
)


def get_contract_spec(symbol: str) -> ContractSpec:
    clean_sym = symbol.strip().upper()
    if clean_sym in FUTURES_SPECS:
        return FUTURES_SPECS[clean_sym]
    for k, v in FUTURES_SPECS.items():
        if clean_sym.startswith(k):
            return v
    # Stock symbol fallback
    return ContractSpec(
        symbol=symbol,
        name=f"Stock_{symbol}",
        asset_type="STOCK",
        exchange="SH" if symbol.startswith("6") else "SZ",
        multiplier=1.0,
        margin_rate=1.0,
        tick_size=0.01,
        lot_size=100,
    )


# ---------------------------------------------------------------------------
# Feature 2 & 3: Futures Rollover Gap Adjustment & Calendar Alignment
# ---------------------------------------------------------------------------

def adjust_rollover_gaps(
    raw_prices: pd.Series,
    roll_dates: List[str],
    roll_gaps: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """Eliminates artificial rollover price jumps in continuous futures contracts.
    
    Returns an adjusted continuous price series where holding returns on roll dates
    reflect pure asset return without roll basis jumps.
    """
    adj_series = raw_prices.copy().astype(float)
    dates_idx = [pd.to_datetime(d) for d in roll_dates]
    
    # Backward ratio or difference adjustment
    for dt in dates_idx:
        if dt in adj_series.index:
            loc = adj_series.index.get_loc(dt)
            if loc > 0:
                p_prev = adj_series.iloc[loc - 1]
                p_curr = adj_series.iloc[loc]
                if roll_gaps and str(dt.date()) in roll_gaps:
                    gap = roll_gaps[str(dt.date())]
                else:
                    gap = p_curr - p_prev
                # Adjust all previous prices by the ratio to preserve returns
                ratio = (p_curr - gap) / p_curr if p_curr != 0 else 1.0
                if ratio > 0:
                    adj_series.iloc[:loc] = adj_series.iloc[:loc] * (p_curr / (p_prev if p_prev != 0 else 1.0))
    return adj_series


@dataclass
class AlignedDataset:
    dates: pd.DatetimeIndex
    prices: pd.DataFrame
    returns: pd.DataFrame
    asset_types: Dict[str, str]
    settle_prices: pd.DataFrame


class DataLoader:
    """Homogenizes stock and commodity futures ticker feeds into aligned daily data."""
    
    def __init__(self, sample_data: Optional[Dict[str, Any]] = None):
        self._sample_data = sample_data

    def load_aligned_market_data(
        self, start_date: str, end_date: str
    ) -> AlignedDataset:
        dates = pd.bdate_range(start=start_date, end=end_date)
        if self._sample_data is not None:
            prices = self._sample_data.get("prices", pd.DataFrame(index=dates))
            returns = self._sample_data.get("returns", pd.DataFrame(index=dates))
            asset_types = self._sample_data.get("asset_types", {})
            settle_prices = self._sample_data.get("settle_prices", prices.copy())
            return AlignedDataset(
                dates=dates,
                prices=prices,
                returns=returns,
                asset_types=asset_types,
                settle_prices=settle_prices,
            )
        # Default empty aligned dataset
        return AlignedDataset(
            dates=dates,
            prices=pd.DataFrame(index=dates),
            returns=pd.DataFrame(index=dates),
            asset_types={},
            settle_prices=pd.DataFrame(index=dates),
        )


# ---------------------------------------------------------------------------
# Features 4-8: Momentum, Inverse Vol, CTSI, Ranking, Top-K
# ---------------------------------------------------------------------------

def calculate_compounded_20d_momentum(returns_df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Calculates compounded 20-day momentum: prod_{tau=t-19}^t (1 + r_tau) - 1."""
    gross_returns = 1.0 + returns_df.fillna(0.0)
    rolling_prod = gross_returns.rolling(window=window, min_periods=window).apply(np.prod, raw=True)
    return rolling_prod - 1.0


def calculate_inverse_volatility(
    returns_df: pd.DataFrame, window: int = 20, floor: float = 0.08
) -> pd.DataFrame:
    """Annualized daily volatility with floor to prevent division overflow."""
    daily_vol = returns_df.rolling(window=window, min_periods=window).std()
    ann_vol = daily_vol * np.sqrt(252.0)
    clamped_vol = np.maximum(ann_vol, floor)
    return 1.0 / clamped_vol


def calculate_ctsi(prices_df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Composite Trend Strength Indicator combining MA divergence and channel position."""
    ma20 = prices_df.rolling(window=window, min_periods=5).mean()
    ma5 = prices_df.rolling(window=5, min_periods=2).mean()
    std20 = prices_df.rolling(window=window, min_periods=5).std().replace(0.0, np.nan)
    
    # MA divergence: (Price - MA20) / MA20
    ma_div = (prices_df - ma20) / ma20.replace(0.0, np.nan)
    # Bollinger channel position: (Price - Lower) / (Upper - Lower)
    upper = ma20 + 2.0 * std20
    lower = ma20 - 2.0 * std20
    channel_range = (upper - lower).replace(0.0, np.nan)
    channel_pos = (prices_df - lower) / channel_range
    channel_pos = channel_pos.clip(0.0, 1.0)
    
    # MA alignment: MA5 > MA20
    alignment = (ma5 > ma20).astype(float)
    
    ctsi = 0.4 * ma_div.fillna(0.0) + 0.4 * channel_pos.fillna(0.5) + 0.2 * alignment
    return ctsi


def compute_cross_asset_percentile_rank(series: pd.Series) -> pd.Series:
    """Maps scores non-parametrically to uniform percentile range [0, 100]."""
    valid = series.dropna()
    if len(valid) == 0:
        return series
    if len(valid) == 1:
        res = series.copy()
        res.loc[valid.index] = 100.0
        return res
    ranks = valid.rank(ascending=True, method="average")
    percentiles = (ranks - 1.0) / (len(valid) - 1.0) * 100.0
    res = series.copy()
    res.loc[valid.index] = percentiles
    return res


@dataclass
class RankItem:
    rank: int
    symbol: str
    name: str
    asset_type: str
    momentum_20d: float
    inv_vol: float
    trend_strength: float
    composite_score: float
    target_weight: float


@dataclass
class RankResult:
    as_of_date: str
    ranked_df: pd.DataFrame
    selected_top_k: List[RankItem]


class CrossAssetRanker:
    """Cross-asset momentum, risk, and trend strength ranking engine."""

    def __init__(
        self,
        dataset: AlignedDataset,
        momentum_weight: float = 0.5,
        inv_vol_weight: float = 0.3,
        trend_weight: float = 0.2,
        vol_floor: float = 0.08,
    ):
        self.dataset = dataset
        self.momentum_weight = momentum_weight
        self.inv_vol_weight = inv_vol_weight
        self.trend_weight = trend_weight
        self.vol_floor = vol_floor

    def rank_universe(
        self, as_of_date: str, window: int = 20, top_k: int = 10
    ) -> RankResult:
        dt = pd.to_datetime(as_of_date)
        hist_returns = self.dataset.returns.loc[:dt]
        hist_prices = self.dataset.prices.loc[:dt]
        
        if len(hist_returns) < window:
            empty_df = pd.DataFrame(
                columns=[
                    "rank", "symbol", "name", "asset_type",
                    "momentum_20d", "inv_vol", "trend_strength",
                    "composite_score", "target_weight"
                ]
            )
            return RankResult(as_of_date=as_of_date, ranked_df=empty_df, selected_top_k=[])

        mom_df = calculate_compounded_20d_momentum(hist_returns, window=window)
        iv_df = calculate_inverse_volatility(hist_returns, window=window, floor=self.vol_floor)
        ctsi_df = calculate_ctsi(hist_prices, window=window)

        mom_latest = mom_df.iloc[-1]
        iv_latest = iv_df.iloc[-1]
        ctsi_latest = ctsi_df.iloc[-1]

        mom_pct = compute_cross_asset_percentile_rank(mom_latest)
        iv_pct = compute_cross_asset_percentile_rank(iv_latest)
        ctsi_pct = compute_cross_asset_percentile_rank(ctsi_latest)

        composite = (
            self.momentum_weight * mom_pct
            + self.inv_vol_weight * iv_pct
            + self.trend_weight * ctsi_pct
        )

        sorted_symbols = composite.sort_values(ascending=False).index.tolist()
        
        items: List[RankItem] = []
        ranked_rows = []
        selected_symbols = sorted_symbols[:top_k]

        # Inverse-vol or equal weighting on Top-K
        selected_iv = [iv_latest.get(sym, 1.0) for sym in selected_symbols]
        sum_iv = sum(selected_iv) if sum(selected_iv) > 0 else len(selected_symbols)
        
        for idx, sym in enumerate(sorted_symbols):
            spec = get_contract_spec(sym)
            score = float(composite.get(sym, 0.0))
            is_top_k = sym in selected_symbols
            weight = (float(iv_latest.get(sym, 1.0)) / sum_iv) if is_top_k and sum_iv > 0 else 0.0
            
            item = RankItem(
                rank=idx + 1,
                symbol=sym,
                name=spec.name,
                asset_type=spec.asset_type,
                momentum_20d=float(mom_latest.get(sym, 0.0)),
                inv_vol=float(iv_latest.get(sym, 0.0)),
                trend_strength=float(ctsi_latest.get(sym, 0.0)),
                composite_score=score,
                target_weight=round(weight, 6),
            )
            ranked_rows.append(item.__dict__)
            if is_top_k:
                items.append(item)

        ranked_df = pd.DataFrame(ranked_rows)
        return RankResult(as_of_date=as_of_date, ranked_df=ranked_df, selected_top_k=items)


# ---------------------------------------------------------------------------
# Features 9-13: Dual-Track Accounting Ledger, Discrete Lots, MTM, Cash Interest, Risk Control
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    symbol: str
    asset_type: str
    action: str  # 'BUY' | 'SELL' | 'LIQUIDATE'
    quantity: float  # shares for stock, lots for futures
    price: float
    cash_flow: float
    margin_change: float
    fee: float = 0.0


@dataclass
class Position:
    symbol: str
    asset_type: str
    quantity: float  # shares or lots
    avg_price: float
    current_price: float
    settle_price: float
    margin_locked: float = 0.0


@dataclass
class DailyLedgerState:
    date: str
    total_equity: float
    free_cash: float
    margin_locked: float
    stock_market_val: float
    leverage_ratio: float
    daily_interest: float
    daily_pnl: float
    margin_call: bool = False
    liquidations: List[TradeRecord] = field(default_factory=list)


class DualTrackLedger:
    """Dual-track cash spot and margin leverage accounting ledger."""

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        rf_annual: float = 0.015,
        max_leverage: float = 3.0,
    ):
        self.initial_cash = float(initial_cash)
        self.free_cash = float(initial_cash)
        self.rf_annual = float(rf_annual)
        self.max_leverage = float(max_leverage)
        self.positions: Dict[str, Position] = {}
        self.history: List[DailyLedgerState] = []
        self.trades: List[TradeRecord] = []
        self._last_settle_prices: Dict[str, float] = {}

    @property
    def margin_locked(self) -> float:
        return sum(pos.margin_locked for pos in self.positions.values() if pos.asset_type == "FUTURES")

    @property
    def stock_market_val(self) -> float:
        return sum(pos.quantity * pos.current_price for pos in self.positions.values() if pos.asset_type == "STOCK")

    @property
    def total_equity(self) -> float:
        return self.free_cash + self.margin_locked + self.stock_market_val

    @property
    def total_notional_exposure(self) -> float:
        exposure = 0.0
        for pos in self.positions.values():
            spec = get_contract_spec(pos.symbol)
            exposure += pos.quantity * spec.multiplier * pos.current_price
        return exposure

    @property
    def leverage_ratio(self) -> float:
        equity = self.total_equity
        if equity <= 0:
            return 999.0
        return self.total_notional_exposure / equity

    def rebalance(
        self,
        target_weights: Dict[str, float],
        current_prices: Dict[str, float],
        deadband: float = 0.01,
    ) -> List[TradeRecord]:
        """Discretizes lot sizing and updates positions with equity conservation."""
        executed_trades: List[TradeRecord] = []
        equity = self.total_equity
        if equity <= 0:
            return executed_trades

        # First, liquidate positions not in target weights
        for sym in list(self.positions.keys()):
            if sym not in target_weights or target_weights[sym] <= 0:
                pos = self.positions[sym]
                spec = get_contract_spec(sym)
                px = current_prices.get(sym, pos.current_price)
                if pos.asset_type == "STOCK":
                    cash_back = pos.quantity * px
                    self.free_cash += cash_back
                    tr = TradeRecord(
                        symbol=sym,
                        asset_type="STOCK",
                        action="SELL",
                        quantity=pos.quantity,
                        price=px,
                        cash_flow=cash_back,
                        margin_change=0.0,
                    )
                else:  # FUTURES
                    # Release margin, settle final day PnL if any
                    margin_released = pos.margin_locked
                    pnl = pos.quantity * spec.multiplier * (px - pos.settle_price)
                    self.free_cash += (margin_released + pnl)
                    tr = TradeRecord(
                        symbol=sym,
                        asset_type="FUTURES",
                        action="SELL",
                        quantity=pos.quantity,
                        price=px,
                        cash_flow=margin_released + pnl,
                        margin_change=-margin_released,
                    )
                executed_trades.append(tr)
                del self.positions[sym]

        for sym, weight in target_weights.items():
            if weight <= 0:
                continue
            spec = get_contract_spec(sym)
            px = current_prices.get(sym, 0.0)
            if px is None or np.isnan(px) or px <= 0:
                continue

            target_val = equity * weight
            current_pos = self.positions.get(sym)
            current_qty = current_pos.quantity if current_pos else 0.0

            if spec.asset_type == "STOCK":
                # Discrete 100 shares
                raw_shares = target_val / px
                target_shares = math.floor(raw_shares / spec.lot_size) * spec.lot_size
                delta_shares = target_shares - current_qty
                
                # Check deadband
                if abs(delta_shares * px) < equity * deadband:
                    continue

                if delta_shares > 0:
                    cost = delta_shares * px
                    if cost > self.free_cash:
                        # Truncate to available free cash
                        target_shares = math.floor(self.free_cash / (px * spec.lot_size)) * spec.lot_size
                        delta_shares = target_shares - current_qty
                        cost = delta_shares * px
                    if delta_shares > 0 and cost <= self.free_cash:
                        self.free_cash -= cost
                        self.positions[sym] = Position(
                            symbol=sym,
                            asset_type="STOCK",
                            quantity=target_shares,
                            avg_price=px,
                            current_price=px,
                            settle_price=px,
                        )
                        executed_trades.append(
                            TradeRecord(sym, "STOCK", "BUY", delta_shares, px, -cost, 0.0)
                        )
                elif delta_shares < 0:
                    cash_back = abs(delta_shares) * px
                    self.free_cash += cash_back
                    if target_shares > 0:
                        self.positions[sym] = Position(
                            symbol=sym,
                            asset_type="STOCK",
                            quantity=target_shares,
                            avg_price=px,
                            current_price=px,
                            settle_price=px,
                        )
                    else:
                        del self.positions[sym]
                    executed_trades.append(
                        TradeRecord(sym, "STOCK", "SELL", abs(delta_shares), px, cash_back, 0.0)
                    )

            else:  # FUTURES
                notional_per_lot = spec.multiplier * px
                margin_per_lot = notional_per_lot * spec.margin_rate
                # Discrete 1 lot based on notional exposure
                raw_lots = target_val / notional_per_lot if notional_per_lot > 0 else 0
                target_lots = math.floor(raw_lots / spec.lot_size) * spec.lot_size
                delta_lots = target_lots - current_qty

                if abs(delta_lots * margin_per_lot) < equity * deadband:
                    continue

                if delta_lots > 0:
                    req_margin = delta_lots * margin_per_lot
                    if req_margin > self.free_cash:
                        target_lots = math.floor(self.free_cash / (margin_per_lot * spec.lot_size)) * spec.lot_size
                        delta_lots = target_lots - current_qty
                        req_margin = delta_lots * margin_per_lot
                    if delta_lots > 0 and req_margin <= self.free_cash:
                        self.free_cash -= req_margin
                        total_locked = target_lots * margin_per_lot
                        self.positions[sym] = Position(
                            symbol=sym,
                            asset_type="FUTURES",
                            quantity=target_lots,
                            avg_price=px,
                            current_price=px,
                            settle_price=px,
                            margin_locked=total_locked,
                        )
                        executed_trades.append(
                            TradeRecord(sym, "FUTURES", "BUY", delta_lots, px, -req_margin, req_margin)
                        )
                elif delta_lots < 0:
                    released_margin = abs(delta_lots) * margin_per_lot
                    self.free_cash += released_margin
                    if target_lots > 0:
                        total_locked = target_lots * margin_per_lot
                        self.positions[sym] = Position(
                            symbol=sym,
                            asset_type="FUTURES",
                            quantity=target_lots,
                            avg_price=px,
                            current_price=px,
                            settle_price=px,
                            margin_locked=total_locked,
                        )
                    else:
                        del self.positions[sym]
                    executed_trades.append(
                        TradeRecord(sym, "FUTURES", "SELL", abs(delta_lots), px, released_margin, -released_margin)
                    )

        self.trades.extend(executed_trades)
        return executed_trades

    def settle_daily(
        self,
        settle_prices: Dict[str, float],
        close_prices: Dict[str, float],
        date_str: str = "",
    ) -> DailyLedgerState:
        """Executes daily MTM futures settlement, idle cash interest accrual, and margin check."""
        prev_equity = self.total_equity

        # 1. Idle cash interest accrual (1.5% annual / 252)
        daily_interest = 0.0
        if self.free_cash > 0:
            daily_interest = self.free_cash * (self.rf_annual / 252.0)
            self.free_cash += daily_interest

        # 2. Daily futures MTM settlement
        for sym, pos in list(self.positions.items()):
            if pos.asset_type == "FUTURES":
                spec = get_contract_spec(sym)
                st_px = settle_prices.get(sym, pos.settle_price)
                cl_px = close_prices.get(sym, pos.current_price)
                prev_st = self._last_settle_prices.get(sym, pos.settle_price)
                
                # Daily MTM PnL = lots * multiplier * (settle_today - settle_yesterday)
                mtm_pnl = pos.quantity * spec.multiplier * (st_px - prev_st)
                self.free_cash += mtm_pnl

                # Recompute locked margin based on today's settle price
                new_margin = pos.quantity * spec.multiplier * st_px * spec.margin_rate
                margin_diff = new_margin - pos.margin_locked
                pos.margin_locked = new_margin
                self.free_cash -= margin_diff

                pos.settle_price = st_px
                pos.current_price = cl_px
                self._last_settle_prices[sym] = st_px
            else:
                # Update stock close price
                cl_px = close_prices.get(sym, pos.current_price)
                pos.current_price = cl_px

        # 3. Margin Call & Tiered Liquidation Protocol
        margin_call_triggered = False
        liquidations: List[TradeRecord] = []
        if self.free_cash < 0:
            margin_call_triggered = True
            # Tier 1: Liquidate futures positions to free locked margin
            for sym in list(self.positions.keys()):
                if self.free_cash >= 0:
                    break
                pos = self.positions[sym]
                if pos.asset_type == "FUTURES":
                    spec = get_contract_spec(sym)
                    margin_released = pos.margin_locked
                    self.free_cash += margin_released
                    tr = TradeRecord(
                        symbol=sym,
                        asset_type="FUTURES",
                        action="LIQUIDATE",
                        quantity=pos.quantity,
                        price=pos.current_price,
                        cash_flow=margin_released,
                        margin_change=-margin_released,
                    )
                    liquidations.append(tr)
                    del self.positions[sym]

            # Tier 2: Liquidate stocks if still negative
            if self.free_cash < 0:
                for sym in list(self.positions.keys()):
                    if self.free_cash >= 0:
                        break
                    pos = self.positions[sym]
                    if pos.asset_type == "STOCK":
                        cash_back = pos.quantity * pos.current_price
                        self.free_cash += cash_back
                        tr = TradeRecord(
                            symbol=sym,
                            asset_type="STOCK",
                            action="LIQUIDATE",
                            quantity=pos.quantity,
                            price=pos.current_price,
                            cash_flow=cash_back,
                            margin_change=0.0,
                        )
                        liquidations.append(tr)
                        del self.positions[sym]

        curr_equity = self.total_equity
        daily_pnl = curr_equity - prev_equity

        state = DailyLedgerState(
            date=date_str,
            total_equity=curr_equity,
            free_cash=self.free_cash,
            margin_locked=self.margin_locked,
            stock_market_val=self.stock_market_val,
            leverage_ratio=self.leverage_ratio,
            daily_interest=daily_interest,
            daily_pnl=daily_pnl,
            margin_call=margin_call_triggered,
            liquidations=liquidations,
        )
        self.history.append(state)
        self.trades.extend(liquidations)
        return state


# ---------------------------------------------------------------------------
# Feature 14 & 15: Multi-Benchmark Backtest Engine & MPT / DR Metrics
# ---------------------------------------------------------------------------

def calculate_diversification_ratio(
    weights: np.ndarray,
    asset_volatilities: np.ndarray,
    cov_matrix: np.ndarray,
) -> float:
    """Choueifaty and Coignard (2008) Diversification Ratio DR(w) = w^T sigma / sqrt(w^T Sigma w)."""
    w = np.asarray(weights, dtype=float)
    sigma = np.asarray(asset_volatilities, dtype=float)
    cov = np.asarray(cov_matrix, dtype=float)

    weighted_vol = np.sum(w * sigma)
    port_var = np.dot(w, np.dot(cov, w))
    port_vol = np.sqrt(max(port_var, 1e-12))
    if port_vol == 0 or weighted_vol == 0:
        return 1.0
    return float(weighted_vol / port_vol)


def calculate_mpt_metrics(
    equity_series: pd.Series, rf_annual: float = 0.015
) -> Dict[str, float]:
    """Calculates Sharpe, Max Drawdown, Calmar Ratio, and Annualized Return."""
    returns = equity_series.pct_change().dropna()
    if len(returns) == 0:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "calmar_ratio": 0.0,
        }

    total_ret = (equity_series.iloc[-1] / equity_series.iloc[0]) - 1.0
    n_days = len(equity_series)
    ann_factor = 252.0 / max(n_days, 1)
    ann_ret = (1.0 + total_ret) ** ann_factor - 1.0 if total_ret > -1.0 else -1.0

    daily_rf = rf_annual / 252.0
    excess_ret = returns - daily_rf
    std_ret = returns.std()
    sharpe = float((excess_ret.mean() / std_ret) * np.sqrt(252.0)) if std_ret > 0 else 0.0

    cum_max = equity_series.cummax()
    drawdown = (cum_max - equity_series) / cum_max.replace(0.0, np.nan)
    max_dd = float(drawdown.max()) if len(drawdown) > 0 else 0.0

    calmar = float(ann_ret / max_dd) if max_dd > 1e-6 else 0.0

    return {
        "total_return": round(float(total_ret), 4),
        "annual_return": round(float(ann_ret), 4),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "calmar_ratio": round(calmar, 4),
    }


@dataclass
class BacktestResult:
    mixed_portfolio: Dict[str, Any]
    pure_stock: Dict[str, Any]
    pure_futures: Dict[str, Any]
    csi_300: Dict[str, Any]
    diversification_ratio: float
    equity_curve: pd.DataFrame
    rebalance_dates: List[str]


class CrossAssetBacktestEngine:
    """Executes multi-benchmark parallel backtest across stocks and commodity futures."""

    def __init__(
        self,
        dataset: AlignedDataset,
        initial_cash: float = 1_000_000.0,
        rebalance_freq: int = 10,
        top_k: int = 10,
        rf_annual: float = 0.015,
    ):
        self.dataset = dataset
        self.initial_cash = initial_cash
        self.rebalance_freq = rebalance_freq
        self.top_k = top_k
        self.rf_annual = rf_annual
        self.ranker = CrossAssetRanker(dataset=dataset)

    def run_backtest(self) -> BacktestResult:
        dates = self.dataset.dates
        mixed_ledger = DualTrackLedger(initial_cash=self.initial_cash, rf_annual=self.rf_annual)
        stock_ledger = DualTrackLedger(initial_cash=self.initial_cash, rf_annual=self.rf_annual)
        fut_ledger = DualTrackLedger(initial_cash=self.initial_cash, rf_annual=self.rf_annual)

        mixed_equities = []
        stock_equities = []
        fut_equities = []
        rebalance_dates = []

        for i, dt in enumerate(dates):
            date_str = str(dt.date())
            # Current prices & settle prices
            close_px = self.dataset.prices.loc[dt].to_dict()
            settle_px = self.dataset.settle_prices.loc[dt].to_dict()

            # Rebalance trigger
            if i >= 20 and (i % self.rebalance_freq == 0):
                rebalance_dates.append(date_str)
                rank_res = self.ranker.rank_universe(as_of_date=date_str, top_k=self.top_k)
                
                # Mixed target weights
                mixed_weights = {item.symbol: item.target_weight for item in rank_res.selected_top_k}
                mixed_ledger.rebalance(mixed_weights, close_px)

                # Pure Stock target weights
                stock_items = [it for it in rank_res.selected_top_k if it.asset_type == "STOCK"]
                if stock_items:
                    w = 1.0 / len(stock_items)
                    stock_weights = {it.symbol: w for it in stock_items}
                    stock_ledger.rebalance(stock_weights, close_px)

                # Pure Futures target weights
                fut_items = [it for it in rank_res.selected_top_k if it.asset_type == "FUTURES"]
                if fut_items:
                    w = 1.0 / len(fut_items)
                    fut_weights = {it.symbol: w for it in fut_items}
                    fut_ledger.rebalance(fut_weights, close_px)

            # Daily settlement
            m_state = mixed_ledger.settle_daily(settle_px, close_px, date_str)
            s_state = stock_ledger.settle_daily(settle_px, close_px, date_str)
            f_state = fut_ledger.settle_daily(settle_px, close_px, date_str)

            mixed_equities.append(m_state.total_equity)
            stock_equities.append(s_state.total_equity)
            fut_equities.append(f_state.total_equity)

        equity_df = pd.DataFrame(
            {
                "Mixed": mixed_equities,
                "PureStock": stock_equities,
                "PureFutures": fut_equities,
            },
            index=dates,
        )

        # Baseline CSI 300 buy & hold simulation
        if "000300" in self.dataset.prices.columns:
            csi_series = self.dataset.prices["000300"]
            csi_equity = self.initial_cash * (csi_series / csi_series.iloc[0])
        else:
            # Synthetic CSI 300 proxy using equal weight of stocks
            stock_cols = [c for c in self.dataset.prices.columns if get_contract_spec(c).asset_type == "STOCK"]
            if stock_cols:
                mean_px = self.dataset.prices[stock_cols].mean(axis=1)
                csi_equity = self.initial_cash * (mean_px / mean_px.iloc[0])
            else:
                csi_equity = pd.Series(self.initial_cash, index=dates)
        equity_df["CSI300"] = csi_equity

        # Compute diversification ratio for mixed portfolio
        n_assets = len(self.dataset.prices.columns)
        eq_weights = np.ones(n_assets) / n_assets
        daily_cov = self.dataset.returns.cov().fillna(0.0).values
        daily_vols = self.dataset.returns.std().fillna(0.0).values
        dr = calculate_diversification_ratio(eq_weights, daily_vols, daily_cov)

        mixed_metrics = calculate_mpt_metrics(equity_df["Mixed"], self.rf_annual)
        stock_metrics = calculate_mpt_metrics(equity_df["PureStock"], self.rf_annual)
        fut_metrics = calculate_mpt_metrics(equity_df["PureFutures"], self.rf_annual)
        csi_metrics = calculate_mpt_metrics(equity_df["CSI300"], self.rf_annual)

        return BacktestResult(
            mixed_portfolio=mixed_metrics,
            pure_stock=stock_metrics,
            pure_futures=fut_metrics,
            csi_300=csi_metrics,
            diversification_ratio=round(dr, 4),
            equity_curve=equity_df,
            rebalance_dates=rebalance_dates,
        )


# ---------------------------------------------------------------------------
# Feature 16: JSON & Markdown Reporting
# ---------------------------------------------------------------------------

def run_cross_asset_pipeline(
    dataset: AlignedDataset,
    output_json_path: Union[str, Path] = "docs/data/paper/backtest_cross_asset_mix.json",
    output_report_path: Union[str, Path] = "reports/tables/backtest_cross_asset_mix_report.md",
) -> BacktestResult:
    """Executes the complete pipeline and writes JSON and Markdown report artifacts."""
    engine = CrossAssetBacktestEngine(dataset=dataset)
    res = engine.run_backtest()

    out_json = Path(output_json_path)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    json_data = {
        "metadata": {
            "strategy": "Cross-Asset Mixed Portfolio",
            "assets": list(dataset.prices.columns),
            "start_date": str(dataset.dates[0].date()),
            "end_date": str(dataset.dates[-1].date()),
            "rebalance_count": len(res.rebalance_dates),
        },
        "metrics": {
            "mixed_portfolio": res.mixed_portfolio,
            "pure_stock": res.pure_stock,
            "pure_futures": res.pure_futures,
            "csi_300": res.csi_300,
            "diversification_ratio": res.diversification_ratio,
        },
        "nav_summary": {
            "initial_nav": 1.0,
            "final_nav": round(float(res.equity_curve["Mixed"].iloc[-1] / res.equity_curve["Mixed"].iloc[0]), 4),
        },
    }
    out_json.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")

    out_report = Path(output_report_path)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    md_content = f"""# 跨资产混合投资组合 (Cross-Asset Mixed Portfolio) 回测报告

## 1. 核心表现指标对比

| 资产配置模式 | 累计收益率 | 年化收益率 | 年化夏普比率 | 最大回撤 | 卡尔玛比率 |
|---|---|---|---|---|---|
| **混合池优选产品 (Mixed)** | {res.mixed_portfolio['total_return']:.2%} | {res.mixed_portfolio['annual_return']:.2%} | {res.mixed_portfolio['sharpe_ratio']:.2f} | {res.mixed_portfolio['max_drawdown']:.2%} | {res.mixed_portfolio['calmar_ratio']:.2f} |
| **纯股票 202 组合 (Pure Stock)** | {res.pure_stock['total_return']:.2%} | {res.pure_stock['annual_return']:.2%} | {res.pure_stock['sharpe_ratio']:.2f} | {res.pure_stock['max_drawdown']:.2%} | {res.pure_stock['calmar_ratio']:.2f} |
| **纯商品期货组合 (Pure Futures)** | {res.pure_futures['total_return']:.2%} | {res.pure_futures['annual_return']:.2%} | {res.pure_futures['sharpe_ratio']:.2f} | {res.pure_futures['max_drawdown']:.2%} | {res.pure_futures['calmar_ratio']:.2f} |
| **沪深 300 基准 (CSI 300)** | {res.csi_300['total_return']:.2%} | {res.csi_300['annual_return']:.2%} | {res.csi_300['sharpe_ratio']:.2f} | {res.csi_300['max_drawdown']:.2%} | {res.csi_300['calmar_ratio']:.2f} |

## 2. 分散化增益 (Diversification Gain)
- **跨资产分散化比率 (DR)**: `{res.diversification_ratio:.4f}`
- **资产池配置**: 股票现货 (100% 现金全额建仓) + 大宗商品期货 (10%~15% 标准保证金杠杆建仓)
- **货币计息**: 闲置现金计提 1.5% 年化收益
"""
    out_report.write_text(md_content, encoding="utf-8")
    return res
