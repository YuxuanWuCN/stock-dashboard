"""Dual-Track Ledger and Margin Accounting Module.

This module implements the unified dual-track accounting mechanism for cross-asset
portfolios combining cash-spot equities (100% full cash, discrete 100-share lots)
and commodity futures (standard exchange margin 10%~15%, discrete 1-lot sizing,
daily MTM mark-to-market settlement, idle cash interest accrual, and tiered liquidation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
import numpy as np

try:
    from .contracts import (
        AssetType,
        ContractSpec,
        get_contract_spec,
    )
except ImportError:
    from src.assets.cross_asset_mix.contracts import (
        AssetType,
        ContractSpec,
        get_contract_spec,
    )


def _is_stock(asset_type: Any) -> bool:
    """Helper to reliably detect stock asset types regardless of enum/string representation."""
    val = getattr(asset_type, "value", asset_type)
    return str(val).upper().endswith("STOCK")


@dataclass
class TradeRecord:
    """Record of an executed portfolio trade or liquidation.

    Attributes:
        symbol: Ticker symbol of traded asset.
        asset_type: 'STOCK' or 'FUTURES'.
        action: 'BUY', 'SELL', or 'LIQUIDATE'.
        quantity: Traded quantity (shares for stocks, lots for futures).
        price: Execution fill price.
        cash_flow: Net cash impact (+ for cash inflow/receipt, - for cash outflow/payment).
        margin_change: Change in locked margin balance (+ for lock, - for release).
        fee: Explicit commission or transaction fee incurred.
    """
    symbol: str
    asset_type: str
    action: str
    quantity: float
    price: float
    cash_flow: float
    margin_change: float
    fee: float = 0.0


@dataclass
class Position:
    """Position tracking object for an individual stock or futures holding.

    Attributes:
        symbol: Ticker symbol.
        asset_type: 'STOCK' or 'FUTURES'.
        quantity: Held quantity (discrete shares for stock, discrete lots for futures).
        avg_price: Volume-weighted entry price.
        current_price: Latest mark or close price.
        settle_price: Latest settlement price (used for futures MTM).
        margin_locked: Current margin collateral locked by this position.
    """
    symbol: str
    asset_type: str
    quantity: float
    avg_price: float
    current_price: float
    settle_price: float
    margin_locked: float = 0.0


@dataclass
class DailyLedgerState:
    """Snapshot of portfolio accounting status at the end of a trading day.

    Attributes:
        date: Date string (e.g. '2024-01-02').
        total_equity: Total portfolio equity (Free Cash + Margin Locked + Stock Market Value).
        free_cash: Unencumbered cash available for deployment or interest accrual.
        margin_locked: Total margin collateral locked in open futures contracts.
        stock_market_val: Aggregate market value of held equities.
        leverage_ratio: Total notional exposure / total equity.
        daily_interest: Cash interest credited today (Free Cash * rf_annual / 252).
        daily_pnl: Portfolio daily PnL compared to previous day's equity.
        margin_call: True if free cash dipped below zero before liquidation.
        liquidations: List of forced liquidation trade records executed today.
    """
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
    """Dual-track cash spot and margin leverage accounting ledger.

    Enforces the fundamental accounting identity:
        Total Equity = Free Cash + Margin Locked + Stock Market Value

    Key features:
    1. Spot equities: 100% full cash, discrete 100-share lots, zero overdraft.
    2. Futures: Standard exchange margin (SA/FG 12%, AU 10%), discrete 1-lot sizing.
    3. Daily MTM settlement: Futures daily PnL credited/debited to Free Cash using settle prices.
    4. Idle cash interest: Accrues max(0, Free Cash) * (0.015 / 252) daily into free cash.
    5. Tiered forced liquidation: Futures liquidated first (releasing margin), then stocks.
    """

    def __init__(
        self,
        initial_cash: float = 10_000_000.0,
        rf_annual: float = 0.015,
        min_free_cash_buffer: float = 0.0,
        max_leverage: float = 3.0,
        enable_fees: bool = False,
        commission_rate: float = 0.00015,
        stamp_duty_rate: float = 0.001,
        min_commission: float = 5.0,
        futures_fee_rate: float = 0.00005,
    ):
        self.initial_cash = float(initial_cash)
        self.free_cash = float(initial_cash)
        self.rf_annual = float(rf_annual)
        self.min_free_cash_buffer = float(min_free_cash_buffer)
        self.max_leverage = float(max_leverage)
        self.enable_fees = bool(enable_fees)
        self.commission_rate = float(commission_rate)
        self.stamp_duty_rate = float(stamp_duty_rate)
        self.min_commission = float(min_commission)
        self.futures_fee_rate = float(futures_fee_rate)

        self.positions: Dict[str, Position] = {}
        self.history: List[DailyLedgerState] = []
        self.trades: List[TradeRecord] = []
        self._last_settle_prices: Dict[str, float] = {}

    @property
    def margin_locked(self) -> float:
        """Total margin locked in open futures positions."""
        return sum(
            pos.margin_locked
            for pos in self.positions.values()
            if not _is_stock(pos.asset_type)
        )

    @property
    def stock_market_val(self) -> float:
        """Total market value of held equities."""
        return sum(
            pos.quantity * pos.current_price
            for pos in self.positions.values()
            if _is_stock(pos.asset_type)
        )

    @property
    def total_equity(self) -> float:
        """Total portfolio equity: Free Cash + Margin Locked + Stock Market Value."""
        return self.free_cash + self.margin_locked + self.stock_market_val

    @property
    def total_notional_exposure(self) -> float:
        """Gross notional exposure of the combined portfolio."""
        exposure = 0.0
        for pos in self.positions.values():
            if _is_stock(pos.asset_type):
                exposure += pos.quantity * pos.current_price
            else:
                spec = get_contract_spec(pos.symbol)
                exposure += abs(pos.quantity) * spec.multiplier * pos.current_price
        return exposure

    @property
    def leverage_ratio(self) -> float:
        """Effective portfolio leverage: Gross Notional Exposure / Total Equity."""
        equity = self.total_equity
        if equity <= 0:
            return 999.0
        return self.total_notional_exposure / equity

    def accrue_daily_interest(self) -> float:
        """Accrues interest on unencumbered positive free cash: max(0, Free Cash) * (rf_annual / 252)."""
        daily_interest = 0.0
        if self.free_cash > 0:
            daily_interest = self.free_cash * (self.rf_annual / 252.0)
            self.free_cash += daily_interest
        return daily_interest

    def check_margin_call(self) -> bool:
        """Check whether free cash has breached margin call threshold (Free Cash < 0)."""
        return self.free_cash < 0

    def _calc_stock_fee(self, value: float, is_sell: bool = False) -> float:
        """Calculate commission and stamp duty for equities."""
        if not self.enable_fees or value <= 0:
            return 0.0
        comm = max(self.min_commission, value * self.commission_rate)
        if is_sell:
            comm += value * self.stamp_duty_rate
        return comm

    def _calc_futures_fee(self, notional: float) -> float:
        """Calculate transaction fee for futures."""
        if not self.enable_fees or notional <= 0:
            return 0.0
        return notional * self.futures_fee_rate

    def liquidate_positions(self, amount_needed: Optional[float] = None) -> List[TradeRecord]:
        """Tiered forced liquidation protocol.

        Hierarchy:
        1. Tier 1: Liquidate futures positions first, which immediately releases locked margin
           and halts further MTM losses.
        2. Tier 2: If Free Cash remains negative after all futures are closed, liquidate stocks.
        """
        liquidations: List[TradeRecord] = []
        if self.free_cash >= 0 and (amount_needed is None or amount_needed <= 0):
            return liquidations

        # Tier 1: Liquidate futures to release locked margin
        for sym in list(self.positions.keys()):
            if self.free_cash >= 0:
                break
            pos = self.positions.get(sym)
            if pos is None:
                continue
            if not _is_stock(pos.asset_type):
                spec = get_contract_spec(sym)
                margin_released = pos.margin_locked
                notional = abs(pos.quantity) * spec.multiplier * pos.current_price
                fee = self._calc_futures_fee(notional)
                net_cash = margin_released - fee
                self.free_cash += net_cash
                tr = TradeRecord(
                    symbol=sym,
                    asset_type="FUTURES",
                    action="LIQUIDATE",
                    quantity=abs(pos.quantity),
                    price=pos.current_price,
                    cash_flow=net_cash,
                    margin_change=-margin_released,
                    fee=fee,
                )
                liquidations.append(tr)
                del self.positions[sym]

        # Tier 2: Liquidate stocks if free cash remains negative
        if self.free_cash < 0:
            for sym in list(self.positions.keys()):
                if self.free_cash >= 0:
                    break
                pos = self.positions.get(sym)
                if pos is None:
                    continue
                if _is_stock(pos.asset_type):
                    gross_cash = pos.quantity * pos.current_price
                    fee = self._calc_stock_fee(gross_cash, is_sell=True)
                    net_cash = gross_cash - fee
                    self.free_cash += net_cash
                    tr = TradeRecord(
                        symbol=sym,
                        asset_type="STOCK",
                        action="LIQUIDATE",
                        quantity=pos.quantity,
                        price=pos.current_price,
                        cash_flow=net_cash,
                        margin_change=0.0,
                        fee=fee,
                    )
                    liquidations.append(tr)
                    del self.positions[sym]

        self.trades.extend(liquidations)
        return liquidations

    def rebalance(
        self,
        target_weights: Dict[str, float],
        current_prices: Dict[str, float],
        deadband: float = 0.01,
    ) -> List[TradeRecord]:
        """Discretizes lot sizing and updates portfolio positions with zero cash overdraft.

        Execution ordering:
        1. Closes positions that are dropped from target_weights (or have weight <= 0).
        2. Adjusts existing positions and opens new positions according to target weights.
        """
        executed_trades: List[TradeRecord] = []
        equity = self.total_equity
        if equity <= 0:
            return executed_trades

        # 1. Close positions for dropped assets or assets reversing direction
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            is_stock_asset = _is_stock(pos.asset_type)
            should_close = False
            if is_stock_asset:
                if sym not in target_weights or target_weights[sym] <= 0:
                    should_close = True
            else:
                if sym not in target_weights or abs(target_weights.get(sym, 0.0)) < 1e-6:
                    should_close = True
                elif (pos.quantity > 0 and target_weights[sym] < 0) or (pos.quantity < 0 and target_weights[sym] > 0):
                    should_close = True

            if should_close:
                spec = get_contract_spec(sym)
                px = current_prices.get(sym, pos.current_price)
                if is_stock_asset:
                    gross_cash = pos.quantity * px
                    fee = self._calc_stock_fee(gross_cash, is_sell=True)
                    net_cash = gross_cash - fee
                    self.free_cash += net_cash
                    tr = TradeRecord(
                        symbol=sym,
                        asset_type="STOCK",
                        action="SELL",
                        quantity=pos.quantity,
                        price=px,
                        cash_flow=net_cash,
                        margin_change=0.0,
                        fee=fee,
                    )
                else:  # FUTURES
                    margin_released = pos.margin_locked
                    pnl = pos.quantity * spec.multiplier * (px - pos.settle_price)
                    notional = abs(pos.quantity) * spec.multiplier * px
                    fee = self._calc_futures_fee(notional)
                    net_cash = margin_released + pnl - fee
                    self.free_cash += net_cash
                    action_name = "COVER" if pos.quantity < 0 else "SELL"
                    tr = TradeRecord(
                        symbol=sym,
                        asset_type="FUTURES",
                        action=action_name,
                        quantity=abs(pos.quantity),
                        price=px,
                        cash_flow=net_cash,
                        margin_change=-margin_released,
                        fee=fee,
                    )
                executed_trades.append(tr)
                del self.positions[sym]

        # 2. Adjust existing and enter new positions
        target_equity = equity * (1.0 - self.min_free_cash_buffer) if self.min_free_cash_buffer > 0 else equity
        for sym, weight in target_weights.items():
            if abs(weight) < 1e-6:
                continue
            spec = get_contract_spec(sym)
            px = current_prices.get(sym, 0.0)
            if px is None or not np.isfinite(px) or px <= 0:
                continue

            is_stock_asset = _is_stock(spec.asset_type)
            if is_stock_asset and weight <= 0:
                continue

            target_val = target_equity * weight
            current_pos = self.positions.get(sym)
            current_qty = current_pos.quantity if current_pos else 0.0

            if is_stock_asset:
                # Discrete 100 shares lot sizing for equities
                raw_shares = target_val / px
                target_shares = math.floor(raw_shares / 100) * 100
                delta_shares = target_shares - current_qty

                # Deadband threshold check
                if abs(delta_shares * px) < equity * deadband:
                    continue

                if delta_shares > 0:
                    cost = delta_shares * px
                    if cost > self.free_cash:
                        target_shares = current_qty + math.floor(max(0.0, self.free_cash) / (px * 100)) * 100
                        delta_shares = target_shares - current_qty
                        cost = delta_shares * px
                    if delta_shares > 0 and cost <= self.free_cash:
                        fee = self._calc_stock_fee(cost, is_sell=False)
                        if cost + fee <= self.free_cash:
                            self.free_cash -= (cost + fee)
                            if current_pos:
                                new_avg = (current_pos.avg_price * current_pos.quantity + px * delta_shares) / target_shares
                                current_pos.quantity = target_shares
                                current_pos.avg_price = new_avg
                                current_pos.current_price = px
                                current_pos.settle_price = px
                            else:
                                self.positions[sym] = Position(
                                    symbol=sym,
                                    asset_type="STOCK",
                                    quantity=target_shares,
                                    avg_price=px,
                                    current_price=px,
                                    settle_price=px,
                                )
                            tr = TradeRecord(sym, "STOCK", "BUY", delta_shares, px, -(cost + fee), 0.0, fee)
                            executed_trades.append(tr)
                elif delta_shares < 0:
                    sell_shares = abs(delta_shares)
                    gross_cash = sell_shares * px
                    fee = self._calc_stock_fee(gross_cash, is_sell=True)
                    net_cash = gross_cash - fee
                    self.free_cash += net_cash
                    if target_shares > 0:
                        current_pos.quantity = target_shares
                        current_pos.current_price = px
                        current_pos.settle_price = px
                    else:
                        del self.positions[sym]
                    tr = TradeRecord(sym, "STOCK", "SELL", sell_shares, px, net_cash, 0.0, fee)
                    executed_trades.append(tr)

            else:  # FUTURES (Both Long and Short)
                notional_per_lot = spec.multiplier * px
                margin_per_lot = notional_per_lot * spec.margin_rate
                if notional_per_lot <= 0:
                    continue

                if weight > 0:
                    raw_lots = target_val / notional_per_lot
                    target_lots = math.floor(raw_lots)
                else:
                    raw_lots = abs(target_val) / notional_per_lot
                    target_lots = -math.floor(raw_lots)

                delta_lots = target_lots - current_qty

                # Deadband threshold check
                if abs(delta_lots * notional_per_lot) < equity * deadband:
                    continue

                if current_pos:
                    unrealized_pnl = current_pos.quantity * spec.multiplier * (px - current_pos.settle_price)
                    self.free_cash += unrealized_pnl
                    new_m_exist = abs(current_pos.quantity) * notional_per_lot * spec.margin_rate
                    margin_diff = new_m_exist - current_pos.margin_locked
                    current_pos.margin_locked = new_m_exist
                    self.free_cash -= margin_diff
                    current_pos.settle_price = px
                    self._last_settle_prices[sym] = px

                # Increasing position (more long or more short)
                if (target_lots > 0 and delta_lots > 0) or (target_lots < 0 and delta_lots < 0):
                    lots_to_add = abs(target_lots) - abs(current_qty)
                    req_margin = lots_to_add * margin_per_lot
                    if req_margin > self.free_cash:
                        max_afford_lots = math.floor(max(0.0, self.free_cash) / margin_per_lot)
                        lots_to_add = max_afford_lots
                        if target_lots > 0:
                            target_lots = current_qty + lots_to_add
                        else:
                            target_lots = current_qty - lots_to_add
                        delta_lots = target_lots - current_qty
                        req_margin = lots_to_add * margin_per_lot

                    if lots_to_add > 0 and req_margin <= self.free_cash:
                        notional_added = lots_to_add * notional_per_lot
                        fee = self._calc_futures_fee(notional_added)
                        if req_margin + fee <= self.free_cash:
                            self.free_cash -= (req_margin + fee)
                            total_locked = abs(target_lots) * margin_per_lot
                            action_name = "BUY" if target_lots > 0 else "SHORT"
                            if current_pos:
                                new_avg = (current_pos.avg_price * abs(current_pos.quantity) + px * lots_to_add) / abs(target_lots)
                                current_pos.quantity = target_lots
                                current_pos.avg_price = new_avg
                                current_pos.current_price = px
                                current_pos.settle_price = px
                                current_pos.margin_locked = total_locked
                            else:
                                self.positions[sym] = Position(
                                    symbol=sym,
                                    asset_type="FUTURES",
                                    quantity=target_lots,
                                    avg_price=px,
                                    current_price=px,
                                    settle_price=px,
                                    margin_locked=total_locked,
                                )
                            self._last_settle_prices[sym] = px
                            tr = TradeRecord(sym, "FUTURES", action_name, lots_to_add, px, -(req_margin + fee), req_margin, fee)
                            executed_trades.append(tr)
                elif (target_lots >= 0 and current_qty > 0 and delta_lots < 0) or (target_lots <= 0 and current_qty < 0 and delta_lots > 0):
                    # Reducing position (long or short)
                    lots_to_close = abs(current_qty) - abs(target_lots)
                    released_margin = lots_to_close * margin_per_lot
                    fee = self._calc_futures_fee(lots_to_close * notional_per_lot)
                    net_cash = released_margin - fee
                    self.free_cash += net_cash
                    total_locked = abs(target_lots) * margin_per_lot
                    action_name = "SELL" if current_qty > 0 else "COVER"
                    if abs(target_lots) > 0:
                        current_pos.quantity = target_lots
                        current_pos.current_price = px
                        current_pos.settle_price = px
                        current_pos.margin_locked = total_locked
                    else:
                        del self.positions[sym]
                    tr = TradeRecord(sym, "FUTURES", action_name, lots_to_close, px, net_cash, -released_margin, fee)
                    executed_trades.append(tr)

        self.trades.extend(executed_trades)
        return executed_trades

    def settle_daily(
        self,
        settle_prices: Dict[str, float],
        close_prices: Dict[str, float],
        date_str: str = "",
    ) -> DailyLedgerState:
        """Executes daily MTM futures settlement, idle cash interest accrual, and margin check.

        1. Accrues idle interest on unencumbered positive Free Cash.
        2. Applies Mark-to-Market (MTM) PnL for futures directly to Free Cash using settle_prices.
        3. Dynamically updates locked margin based on current day's settlement price.
        4. Updates close prices for equities.
        5. Performs margin call check and tiered liquidation if Free Cash < 0.
        """
        prev_equity = self.total_equity

        # 1. Idle cash interest accrual
        daily_interest = self.accrue_daily_interest()

        # 2. Daily futures MTM settlement
        for sym, pos in list(self.positions.items()):
            if not _is_stock(pos.asset_type):
                spec = get_contract_spec(sym)
                st_px = settle_prices.get(sym, pos.settle_price)
                cl_px = close_prices.get(sym, pos.current_price)
                prev_st = self._last_settle_prices.get(sym, pos.settle_price)

                # Daily MTM PnL = lots * multiplier * (settle_today - settle_yesterday)
                mtm_pnl = pos.quantity * spec.multiplier * (st_px - prev_st)
                self.free_cash += mtm_pnl

                # Recompute locked margin based on today's settle price
                new_margin = abs(pos.quantity) * spec.multiplier * st_px * spec.margin_rate
                margin_diff = new_margin - pos.margin_locked
                pos.margin_locked = new_margin
                self.free_cash -= margin_diff

                pos.settle_price = st_px
                pos.current_price = cl_px
                self._last_settle_prices[sym] = st_px
            else:
                # Update stock close and settle price
                cl_px = close_prices.get(sym, pos.current_price)
                pos.current_price = cl_px
                pos.settle_price = cl_px

        # 3. Margin Call & Tiered Forced Liquidation Protocol
        margin_call_triggered = self.check_margin_call()
        liquidations: List[TradeRecord] = []
        if margin_call_triggered:
            liquidations = self.liquidate_positions(amount_needed=abs(self.free_cash))

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
        return state
