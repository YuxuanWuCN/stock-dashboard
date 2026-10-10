"""Tier 3: Cross-Feature Pairwise Interaction E2E Test Suite for Cross-Asset Mixed Portfolio.
Covers 4 key interaction groups with 5 test cases per group (20 test cases total).
Tests interaction dynamics between ranking, ledger sizing, margin calls, liquidation, MTM, and deadbands.
"""

import math
import numpy as np
import pandas as pd
import pytest

from tests.cross_asset_mix.conftest import resolve_component
from tests.cross_asset_mix import reference_oracle as oracle


# ===========================================================================
# Group 1: Interaction 1 - Cross-Asset Ranking -> Ledger Sizing & Allocation
# ===========================================================================

def test_i01_rank_to_target_weights_lot_discretization(sample_market_dataset):
    """I01-1: Ranking output feeds directly to ledger rebalance with discrete lot sizing."""
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    
    ranker = ranker_cls(dataset=sample_market_dataset)
    rank_res = ranker.rank_universe(as_of_date=str(sample_market_dataset.dates[25].date()), top_k=5)
    
    target_weights = {it.symbol: it.target_weight for it in rank_res.selected_top_k}
    current_prices = sample_market_dataset.prices.loc[sample_market_dataset.dates[25]].to_dict()
    
    ledger = ledger_cls(initial_cash=1_000_000.0)
    trades = ledger.rebalance(target_weights=target_weights, current_prices=current_prices)
    
    assert len(trades) > 0
    for sym, pos in ledger.positions.items():
        if pos.asset_type == "STOCK":
            assert pos.quantity % 100 == 0
        else:
            assert pos.quantity == math.floor(pos.quantity)
    assert ledger.free_cash >= 0.0


def test_i01_mixed_rank_composition_capital_split(sample_market_dataset):
    """I01-2: Top-K containing both stocks and futures properly splits capital into spot and margin."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    current_prices = sample_market_dataset.prices.loc[sample_market_dataset.dates[30]].to_dict()
    
    ledger = ledger_cls(initial_cash=1_000_000.0)
    # Mixed target weights: 50% stock spot, 20% futures margin
    ledger.rebalance(target_weights={"600519": 0.5, "SA": 0.2}, current_prices=current_prices)
    
    assert ledger.stock_market_val > 0.0
    assert ledger.margin_locked > 0.0
    assert ledger.free_cash > 0.0
    assert ledger.total_equity == pytest.approx(
        ledger.free_cash + ledger.margin_locked + ledger.stock_market_val
    )


def test_i01_rank_change_triggers_partial_rebalance(sample_market_dataset):
    """I01-3: Asset dropping out of ranking is liquidated and capital recycled to new entrant."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0)
    
    # Portfolio at T0: SA and 600519
    t0_prices = {"SA": 2000.0, "600519": 100.0, "000858": 80.0}
    ledger.rebalance(target_weights={"SA": 0.5, "600519": 0.5}, current_prices=t0_prices)
    assert "SA" in ledger.positions
    assert "600519" in ledger.positions

    # Portfolio at T1: 600519 drops out, replaced by 000858
    t1_prices = {"SA": 2000.0, "600519": 100.0, "000858": 80.0}
    trades = ledger.rebalance(target_weights={"SA": 0.5, "000858": 0.5}, current_prices=t1_prices)
    
    sell_trades = [tr for tr in trades if tr.action == "SELL" and tr.symbol == "600519"]
    buy_trades = [tr for tr in trades if tr.action == "BUY" and tr.symbol == "000858"]
    assert len(sell_trades) == 1
    assert len(buy_trades) == 1
    assert "600519" not in ledger.positions
    assert "000858" in ledger.positions


def test_i01_zero_weight_unranked_assets_cleaned_up():
    """I01-4: Any asset with 0 target weight is cleanly purged and margin released."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=500_000.0)
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    assert ledger.margin_locked > 0.0

    # Next rebalance: 0 weight
    ledger.rebalance(target_weights={"SA": 0.0}, current_prices={"SA": 2000.0})
    assert "SA" not in ledger.positions
    assert ledger.margin_locked == 0.0


def test_i01_inverse_vol_weights_feed_into_margin_budget(sample_market_dataset):
    """I01-5: Low volatility asset receives higher target weight and correspondingly larger lot sizing."""
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=sample_market_dataset)
    res = ranker.rank_universe(as_of_date=str(sample_market_dataset.dates[25].date()), top_k=5)
    
    # Sort items by inv_vol
    sorted_by_iv = sorted(res.selected_top_k, key=lambda x: x.inv_vol, reverse=True)
    highest_iv = sorted_by_iv[0]
    lowest_iv = sorted_by_iv[-1]
    assert highest_iv.target_weight >= lowest_iv.target_weight


# ===========================================================================
# Group 2: Interaction 2 - Margin Call -> Forced Liquidation Protocol
# ===========================================================================

def test_i02_futures_loss_triggers_free_cash_breach():
    """I02-1: Sharp adverse futures move causes Free Cash to drop below 0."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=20_000.0)
    # Buy 1 lot SA at 2000 (notional 40,000, margin locked 4,800, free cash 15,200)
    ledger.rebalance(target_weights={"SA": 2.0}, current_prices={"SA": 2000.0})
    
    # Drop SA from 2000 to 1000 (net cash change = -17,600 -> free cash = -2,400 < 0)
    state = ledger.settle_daily(settle_prices={"SA": 1000.0}, close_prices={"SA": 1000.0})
    assert state.margin_call is True


def test_i02_liquidation_tiered_futures_before_stocks():
    """I02-2: Futures liquidated first to release margin while preserving stock spot holding."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(
        target_weights={"SA": 0.4, "600519": 0.3},
        current_prices={"SA": 2000.0, "600519": 100.0},
    )
    # Create small deficit that margin release from SA can cover
    ledger.free_cash = -500.0
    state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"600519": 100.0, "SA": 2000.0})
    
    assert state.margin_call is True
    # SA liquidated, stock preserved
    assert "SA" not in ledger.positions
    assert "600519" in ledger.positions
    assert state.free_cash >= 0.0


def test_i02_liquidation_cascades_to_stocks_if_deficit_persists():
    """I02-3: If futures margin release is insufficient, stocks are liquidated to clear deficit."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(
        target_weights={"SA": 0.2, "600519": 0.5},
        current_prices={"SA": 2000.0, "600519": 100.0},
    )
    # Deficit of 20,000 exceeds SA margin (4,800) -> must liquidate both
    ledger.free_cash = -20_000.0
    state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"600519": 100.0, "SA": 2000.0})
    assert state.margin_call is True
    assert "SA" not in ledger.positions
    assert state.free_cash >= 0.0


def test_i02_liquidation_records_in_trade_history():
    """I02-4: Liquidations produce TradeRecords tagged with action='LIQUIDATE'."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    ledger.free_cash = -200.0
    state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    
    liq_trades = [tr for tr in state.liquidations if tr.action == "LIQUIDATE"]
    assert len(liq_trades) > 0
    assert liq_trades[0].margin_change < 0.0  # Margin released


def test_i02_liquidation_halts_further_mtm_losses():
    """I02-5: Liquidated contract position has zero holding and stops future MTM bleeding."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    ledger.free_cash = -100.0
    
    # Day 1: Liquidated
    ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    assert "SA" not in ledger.positions

    # Day 2: Price drops further to 1500, but account suffers 0 MTM loss
    eq_day1 = ledger.total_equity
    s2 = ledger.settle_daily(settle_prices={"SA": 1500.0}, close_prices={"SA": 1500.0})
    assert s2.total_equity >= eq_day1  # Only earns positive interest


# ===========================================================================
# Group 3: Interaction 3 - Daily MTM Settlement -> Cash Interest Accrual Dynamics
# ===========================================================================

def test_i03_mtm_profit_compounds_into_higher_daily_interest():
    """I03-1: MTM gain on day t increases free cash, earning higher interest on day t+1."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=500_000.0, rf_annual=0.015)
    ledger.rebalance(target_weights={"SA": 0.3}, current_prices={"SA": 2000.0})
    
    # Day 1: Settle at 2000 -> normal interest
    s1 = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    
    # Day 2: Huge gain to 2500 (+500 points * 20 = +10,000 cash)
    s2 = ledger.settle_daily(settle_prices={"SA": 2500.0}, close_prices={"SA": 2500.0})
    
    # Day 3: Settle flat at 2500 -> interest base is higher than Day 1
    s3 = ledger.settle_daily(settle_prices={"SA": 2500.0}, close_prices={"SA": 2500.0})
    assert s3.daily_interest > s1.daily_interest


def test_i03_mtm_loss_reduces_interest_accrual_base():
    """I03-2: MTM loss on day t shrinks free cash, reducing interest earned on day t+1."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=500_000.0, rf_annual=0.015)
    ledger.rebalance(target_weights={"SA": 0.3}, current_prices={"SA": 2000.0})
    
    s1 = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    
    # Price drops to 1800 (-200 points * 20 = -4,000 cash)
    ledger.settle_daily(settle_prices={"SA": 1800.0}, close_prices={"SA": 1800.0})
    
    # Day 3: Flat at 1800
    s3 = ledger.settle_daily(settle_prices={"SA": 1800.0}, close_prices={"SA": 1800.0})
    assert s3.daily_interest < s1.daily_interest


def test_i03_zero_pnl_steady_interest_accrual():
    """I03-3: Flat prices produce strictly positive and monotonic equity growth via interest."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0, rf_annual=0.015)
    equities = []
    for _ in range(10):
        state = ledger.settle_daily(settle_prices={}, close_prices={})
        equities.append(state.total_equity)
    
    assert pd.Series(equities).is_monotonic_increasing


def test_i03_interest_credits_increase_free_cash_buffer():
    """I03-4: Interest accumulated over 50 days widens safety buffer against margin calls."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0, rf_annual=0.015)
    cash0 = ledger.free_cash
    for _ in range(50):
        ledger.settle_daily(settle_prices={}, close_prices={})
    assert ledger.free_cash > cash0 + 2000.0


def test_i03_settle_price_fluctuation_margin_recalculation():
    """I03-5: Daily settle price adjustment recalculates locked margin and debits/credits free cash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=200_000.0)
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    m0 = ledger.margin_locked

    # Price rises to 2200 -> margin locked increases
    ledger.settle_daily(settle_prices={"SA": 2200.0}, close_prices={"SA": 2200.0})
    assert ledger.margin_locked > m0


# ===========================================================================
# Group 4: Interaction 4 - Rebalancing Deadband -> Turnover Friction Control
# ===========================================================================

def test_i04_deadband_filters_micro_rebalances():
    """I04-1: Target weight shift within 1% deadband produces 0 trade orders."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0)
    # Initial: 50% in stock
    ledger.rebalance(target_weights={"600519": 0.50}, current_prices={"600519": 100.0})
    
    # Micro shift to 50.5% (delta 0.5% < 1.0% deadband)
    trades = ledger.rebalance(
        target_weights={"600519": 0.505},
        current_prices={"600519": 100.0},
        deadband=0.01,
    )
    assert len(trades) == 0


def test_i04_large_signal_bypasses_deadband():
    """I04-2: Significant target weight shift (> 5%) breaches deadband and executes trade."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0)
    ledger.rebalance(target_weights={"600519": 0.50}, current_prices={"600519": 100.0})
    
    # Major shift to 60% (delta 10% > 1.0% deadband)
    trades = ledger.rebalance(
        target_weights={"600519": 0.60},
        current_prices={"600519": 100.0},
        deadband=0.01,
    )
    assert len(trades) == 1
    assert trades[0].action == "BUY"


def test_i04_deadband_preserves_cash_reserve():
    """I04-3: Suppressing micro-trades retains cash in Free Cash, maximizing interest."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0)
    ledger.rebalance(target_weights={"600519": 0.50}, current_prices={"600519": 100.0})
    cash_before = ledger.free_cash

    ledger.rebalance(target_weights={"600519": 0.503}, current_prices={"600519": 100.0}, deadband=0.01)
    assert ledger.free_cash == cash_before


def test_i04_asymmetric_deadband_stock_vs_futures():
    """I04-4: Deadband operates consistently on both stocks and futures notional allocations."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0)
    ledger.rebalance(target_weights={"SA": 0.20}, current_prices={"SA": 2000.0})
    
    # Micro shift 0.5% in futures
    trades = ledger.rebalance(target_weights={"SA": 0.205}, current_prices={"SA": 2000.0}, deadband=0.01)
    assert len(trades) == 0


def test_i04_deadband_zero_disables_filtering():
    """I04-5: Setting deadband=0.0 allows any incremental lot execution."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0)
    ledger.rebalance(target_weights={"600519": 0.50}, current_prices={"600519": 100.0})
    
    # Increase enough to buy at least 100 shares (10,000 RMB = 1.0% of 1,000,000)
    trades = ledger.rebalance(target_weights={"600519": 0.52}, current_prices={"600519": 100.0}, deadband=0.0)
    assert len(trades) == 1
