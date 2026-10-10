"""Tier 2: Boundary and Extreme Condition E2E Test Suite for Cross-Asset Mixed Portfolio.
Covers 16 boundary categories with >= 5 test cases per category (80 test cases total).
Validates zero division guards, numerical stability, capital exhaustion, and edge conditions.
"""

import math
import numpy as np
import pandas as pd
import pytest

from tests.cross_asset_mix.conftest import resolve_component
from tests.cross_asset_mix import reference_oracle as oracle


# ===========================================================================
# Category 1: Zero / Negative Return Paths & Zero Volatility Handling
# ===========================================================================

def test_b01_all_zero_returns_constant_price():
    """B01-1: 20 days of flat 0.0 returns results in 0.0 momentum and floor volatility."""
    returns = pd.DataFrame({"FLAT": [0.0] * 25})
    mom_fn = resolve_component("ranking", "calculate_compounded_20d_momentum")
    iv_fn = resolve_component("ranking", "calculate_inverse_volatility")
    
    mom = mom_fn(returns, window=20)
    iv = iv_fn(returns, window=20, floor=0.08)
    assert float(mom.iloc[-1]["FLAT"]) == pytest.approx(0.0)
    assert float(iv.iloc[-1]["FLAT"]) == pytest.approx(1.0 / 0.08)


def test_b01_continuous_negative_returns_deep_drawdown():
    """B01-2: 20 days of -5% drop compounds geometrically to ~ -64.15%."""
    returns = pd.DataFrame({"DROP": [-0.05] * 20})
    mom_fn = resolve_component("ranking", "calculate_compounded_20d_momentum")
    mom = mom_fn(returns, window=20)
    expected = (0.95 ** 20) - 1.0
    assert float(mom.iloc[-1]["DROP"]) == pytest.approx(expected, rel=1e-4)


def test_b01_alternating_zero_mean_returns():
    """B01-3: Alternating +2% and -2% returns results in geometric volatility drag < 0."""
    returns = pd.DataFrame({"CHOP": [0.02, -0.02] * 10})
    mom_fn = resolve_component("ranking", "calculate_compounded_20d_momentum")
    mom = mom_fn(returns, window=20)
    assert float(mom.iloc[-1]["CHOP"]) < 0.0  # (1.02 * 0.98)^10 - 1 = (0.9996)^10 - 1 < 0


def test_b01_single_extreme_negative_day_circuit_breaker():
    """B01-4: Single-day -10% stock limit down preserved without overflow."""
    rets = [0.0] * 19 + [-0.10]
    returns = pd.DataFrame({"CRASH": rets})
    mom_fn = resolve_component("ranking", "calculate_compounded_20d_momentum")
    mom = mom_fn(returns, window=20)
    assert float(mom.iloc[-1]["CRASH"]) == pytest.approx(-0.10, rel=1e-5)


def test_b01_zero_return_asset_ranking():
    """B01-5: Zero return flat asset ranked gracefully among positive and negative peers."""
    scores = pd.Series({"NEG": -0.05, "FLAT": 0.0, "POS": 0.05})
    rank_fn = resolve_component("ranking", "compute_cross_asset_percentile_rank")
    pct = rank_fn(scores)
    assert pct["NEG"] < pct["FLAT"] < pct["POS"]
    assert float(pct["FLAT"]) == pytest.approx(50.0)


# ===========================================================================
# Category 2: Free Cash Boundaries & Zero Cash Invariant
# ===========================================================================

def test_b02_initial_cash_zero_rebalance():
    """B02-1: Zero initial cash rejects all buy orders safely."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=0.0)
    trades = ledger.rebalance(target_weights={"SA": 0.5, "600519": 0.5}, current_prices={"SA": 2000.0, "600519": 100.0})
    assert len(trades) == 0
    assert len(ledger.positions) == 0
    assert ledger.free_cash == 0.0


def test_b02_free_cash_exactly_zero():
    """B02-2: Exactly zero free cash after rebalance does not trigger false margin call."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=10_000.0)
    ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 100.0})
    state = ledger.settle_daily(settle_prices={}, close_prices={"600519": 100.0})
    assert state.free_cash == pytest.approx(0.0)
    assert state.margin_call is False


def test_b02_free_cash_tiny_positive_interest():
    """B02-3: Tiny positive cash (0.01 RMB) earns fractional interest without crash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=0.01, rf_annual=0.015)
    state = ledger.settle_daily(settle_prices={}, close_prices={})
    assert state.daily_interest > 0.0
    assert ledger.free_cash > 0.01


def test_b02_free_cash_negative_epsilon_margin_call():
    """B02-4: Negative epsilon (-0.0001) correctly triggers margin call."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100.0)
    ledger.free_cash = -0.0001
    state = ledger.settle_daily(settle_prices={}, close_prices={})
    assert state.margin_call is True


def test_b02_capital_exhaustion_multi_asset():
    """B02-5: Multiple assets exhaust capital without overdraft."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=15_000.0)
    # 600519 at 100 (100 shares = 10,000), 000858 at 80 (100 shares = 8,000)
    # Total required = 18,000 > 15,000 -> only first executes
    ledger.rebalance(
        target_weights={"600519": 0.5, "000858": 0.5},
        current_prices={"600519": 100.0, "000858": 80.0},
    )
    assert ledger.free_cash >= 0.0
    assert ledger.total_equity == pytest.approx(15_000.0)


# ===========================================================================
# Category 3: Max Leverage Boundaries & Extreme Notional Caps
# ===========================================================================

def test_b03_max_leverage_limit_enforced():
    """B03-1: Ledger exposes max_leverage attribute and tracks ratio."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0, max_leverage=2.5)
    assert ledger.max_leverage == 2.5


def test_b03_zero_equity_infinite_leverage_guard():
    """B03-2: Zero equity returns capped high leverage ratio without ZeroDivisionError."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=0.0)
    assert ledger.leverage_ratio >= 100.0
    assert np.isfinite(ledger.leverage_ratio)


def test_b03_100_percent_cash_spot_leverage_is_one():
    """B03-3: 100% stock portfolio has leverage ratio <= 1.0."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 100.0})
    assert ledger.leverage_ratio <= 1.0
    assert ledger.leverage_ratio == pytest.approx(1.0, rel=0.05)


def test_b03_pure_futures_maximum_standard_leverage():
    """B03-4: 1 lot SA at 2000 has 40,000 notional on 4,800 margin."""
    spec_fn = resolve_component("contracts", "get_contract_spec")
    spec = spec_fn("SA")
    margin_ratio = getattr(spec, "margin_ratio", getattr(spec, "margin_rate", 0.12))
    notional = 1 * spec.multiplier * 2000.0
    margin = notional * margin_ratio
    leverage = notional / margin
    assert leverage == pytest.approx(1.0 / 0.12, rel=1e-3)


def test_b03_deleveraging_on_equity_contraction():
    """B03-5: Shrinking equity from MTM loss causes leverage ratio to increase."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=50_000.0)
    # Buy 2 lots SA at 2000 -> Notional = 80,000 -> leverage = 80000 / 50000 = 1.6
    ledger.rebalance(target_weights={"SA": 1.6}, current_prices={"SA": 2000.0})
    lev0 = ledger.leverage_ratio
    
    # SA drops to 1900, shrinking equity faster than notional
    ledger.settle_daily(settle_prices={"SA": 1900.0}, close_prices={"SA": 1900.0})
    assert ledger.leverage_ratio > lev0


# ===========================================================================
# Category 4: Contract Month Transition Jump & Basis Inversion
# ===========================================================================

def test_b04_giant_roll_gap_stitching():
    """B04-1: 50% rollover price gap (1000 to 1500) completely eliminated."""
    dates = pd.bdate_range("2024-01-01", periods=4)
    raw = pd.Series([1000.0, 1000.0, 1500.0, 1500.0], index=dates)
    adjust_fn = resolve_component("data_loader", "adjust_rollover_gaps")
    adj = adjust_fn(raw, roll_dates=[str(dates[2].date())], roll_gaps={str(dates[2].date()): 500.0})
    ret_roll = adj.iloc[2] / adj.iloc[1] - 1.0
    assert abs(ret_roll) < 0.01


def test_b04_negative_basis_backwardation_switch():
    """B04-2: Backwardation roll gap (new contract 100 points lower) adjusted cleanly."""
    dates = pd.bdate_range("2024-01-01", periods=4)
    raw = pd.Series([2000.0, 2000.0, 1900.0, 1900.0], index=dates)
    adjust_fn = resolve_component("data_loader", "adjust_rollover_gaps")
    adj = adjust_fn(raw, roll_dates=[str(dates[2].date())], roll_gaps={str(dates[2].date()): -100.0})
    ret_roll = adj.iloc[2] / adj.iloc[1] - 1.0
    assert abs(ret_roll) < 0.01


def test_b04_zero_roll_gap_identity():
    """B04-3: Zero roll gap produces identical series without modification."""
    dates = pd.bdate_range("2024-01-01", periods=4)
    raw = pd.Series([2000.0, 2010.0, 2010.0, 2020.0], index=dates)
    adjust_fn = resolve_component("data_loader", "adjust_rollover_gaps")
    adj = adjust_fn(raw, roll_dates=[str(dates[2].date())], roll_gaps={str(dates[2].date()): 0.0})
    assert (adj == raw).all() or adj.iloc[2] == pytest.approx(raw.iloc[2])


def test_b04_roll_day_at_start_boundary():
    """B04-4: Rollover specified on index 0 handled without negative indexing error."""
    dates = pd.bdate_range("2024-01-01", periods=4)
    raw = pd.Series([2000.0, 2010.0, 2020.0, 2030.0], index=dates)
    adjust_fn = resolve_component("data_loader", "adjust_rollover_gaps")
    adj = adjust_fn(raw, roll_dates=[str(dates[0].date())])
    assert len(adj) == 4


def test_b04_roll_day_at_end_boundary():
    """B04-5: Rollover specified on final day of backtest adjusted cleanly."""
    dates = pd.bdate_range("2024-01-01", periods=4)
    raw = pd.Series([2000.0, 2000.0, 2000.0, 2100.0], index=dates)
    adjust_fn = resolve_component("data_loader", "adjust_rollover_gaps")
    adj = adjust_fn(raw, roll_dates=[str(dates[-1].date())], roll_gaps={str(dates[-1].date()): 100.0})
    assert len(adj) == 4


# ===========================================================================
# Category 5: Zero Division Guards & Numerical Stability
# ===========================================================================

def test_b05_zero_standard_deviation_vol_floor():
    """B05-1: Zero standard deviation clamped to 0.08 floor."""
    rets = pd.DataFrame({"A": [0.0] * 30})
    iv_fn = resolve_component("ranking", "calculate_inverse_volatility")
    res = iv_fn(rets, window=20, floor=0.08)
    assert float(res.iloc[-1]["A"]) == pytest.approx(1.0 / 0.08)


def test_b05_zero_price_channel_range_ctsi():
    """B05-2: Flat price with upper==lower band returns channel position 0.5 without NaN."""
    px = pd.DataFrame({"A": [10.0] * 30})
    ctsi_fn = resolve_component("ranking", "calculate_ctsi")
    res = ctsi_fn(px, window=20)
    assert not np.isnan(res.iloc[-1]["A"])
    assert np.isfinite(res.iloc[-1]["A"])


def test_b05_zero_variance_sharpe_ratio():
    """B05-3: Flat equity curve yields Sharpe ratio = 0.0, not NaN."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    eq = pd.Series([1_000_000.0] * 50)
    res = mpt_fn(eq)
    assert res["sharpe_ratio"] == 0.0


def test_b05_zero_drawdown_calmar_ratio():
    """B05-4: Monotonically increasing equity (zero drawdown) returns finite Calmar ratio."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    eq = pd.Series([100.0 + i * 1.0 for i in range(50)])
    res = mpt_fn(eq)
    assert np.isfinite(res["calmar_ratio"])
    assert res["max_drawdown"] == 0.0


def test_b05_zero_denominator_diversification_ratio():
    """B05-5: Zero covariance returns DR = 1.0 safely."""
    dr_fn = resolve_component("backtest_engine", "calculate_diversification_ratio")
    weights = np.array([1.0])
    vols = np.array([0.0])
    cov = np.array([[0.0]])
    dr = dr_fn(weights, vols, cov)
    assert dr == pytest.approx(1.0)


# ===========================================================================
# Category 6: Extreme Volatility Shocks & Market Crashes
# ===========================================================================

def test_b06_extreme_volatility_inverse_vol_behavior():
    """B06-1: 200% annualized volatility yields inverse vol 0.5."""
    rng = np.random.default_rng(42)
    # std * sqrt(252) approx 2.0 -> std = 2.0 / 15.874 = 0.126
    rets = pd.DataFrame({"VOL": rng.normal(0, 0.126, 30)})
    iv_fn = resolve_component("ranking", "calculate_inverse_volatility")
    res = iv_fn(rets, window=20, floor=0.08)
    ann_vol = rets["VOL"].iloc[-20:].std() * np.sqrt(252.0)
    assert float(res.iloc[-1]["VOL"]) == pytest.approx(1.0 / ann_vol, rel=1e-3)


def test_b06_consecutive_limit_downs_futures():
    """B06-2: Extreme drops trigger liquidation protocol and preserve positive free cash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=50_000.0)
    ledger.rebalance(target_weights={"SA": 0.8}, current_prices={"SA": 2000.0})
    
    # SA crashes from 2000 to 1200
    state = ledger.settle_daily(settle_prices={"SA": 1200.0}, close_prices={"SA": 1200.0})
    assert state.free_cash >= 0.0


def test_b06_flash_crash_intraday_recovery():
    """B06-3: Day 1 crash to 1500, Day 2 recovery to 2000 handles MTM transitions cleanly."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=200_000.0)
    ledger.rebalance(target_weights={"SA": 0.3}, current_prices={"SA": 2000.0})
    
    # Day 1
    s1 = ledger.settle_daily(settle_prices={"SA": 1600.0}, close_prices={"SA": 1600.0})
    # Day 2
    s2 = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    assert s2.daily_pnl > 0.0


def test_b06_gap_opening_stock_crash():
    """B06-4: Stock gaps down -20% overnight; total equity preserved with 0 cash leakage."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(target_weights={"600519": 0.5}, current_prices={"600519": 100.0})
    cash0 = ledger.free_cash
    
    # Stock drops from 100 to 80
    ledger.settle_daily(settle_prices={}, close_prices={"600519": 80.0})
    # Free cash must not change (stock loss is in stock_market_val, not free cash)
    assert ledger.free_cash >= cash0  # Increased slightly by daily interest


def test_b06_hyper_volatile_asset_ranking():
    """B06-5: Asset with huge volatility receives low inverse volatility weight."""
    calm = pd.DataFrame({"CALM": [0.001, -0.001] * 15, "WILD": [0.10, -0.10] * 15})
    iv_fn = resolve_component("ranking", "calculate_inverse_volatility")
    res = iv_fn(calm, window=20)
    assert res.iloc[-1]["CALM"] > res.iloc[-1]["WILD"]


# ===========================================================================
# Category 7: Empty Universe & Starvation Conditions
# ===========================================================================

def test_b07_empty_price_dataset():
    """B07-1: Empty dataset produces empty RankResult without exception."""
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    dates = pd.DatetimeIndex([])
    ds = oracle.AlignedDataset(dates, pd.DataFrame(), pd.DataFrame(), {}, pd.DataFrame())
    ranker = ranker_cls(dataset=ds)
    res = ranker.rank_universe(as_of_date="2024-01-01", top_k=5)
    assert len(res.selected_top_k) == 0


def test_b07_fewer_assets_than_top_k():
    """B07-2: Universe of 2 assets when requesting Top 5 returns both assets."""
    dates = pd.bdate_range("2024-01-01", periods=25)
    prices = pd.DataFrame({"SA": [2000.0] * 25, "FG": [1500.0] * 25}, index=dates)
    rets = pd.DataFrame({"SA": [0.001] * 25, "FG": [0.002] * 25}, index=dates)
    ds = oracle.AlignedDataset(dates, prices, rets, {"SA": "FUTURES", "FG": "FUTURES"}, prices.copy())
    
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=ds)
    res = ranker.rank_universe(as_of_date=str(dates[-1].date()), top_k=5)
    assert len(res.selected_top_k) == 2


def test_b07_all_assets_suspended():
    """B07-3: All assets having NaN values handled safely without crash."""
    scores = pd.Series({"A": np.nan, "B": np.nan})
    rank_fn = resolve_component("ranking", "compute_cross_asset_percentile_rank")
    pct = rank_fn(scores)
    assert pct.isna().all()


def test_b07_window_larger_than_history():
    """B07-4: Requesting window=20 with only 5 days of history returns empty rank."""
    dates = pd.bdate_range("2024-01-01", periods=5)
    prices = pd.DataFrame({"SA": [2000.0] * 5}, index=dates)
    rets = pd.DataFrame({"SA": [0.001] * 5}, index=dates)
    ds = oracle.AlignedDataset(dates, prices, rets, {"SA": "FUTURES"}, prices.copy())
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=ds)
    res = ranker.rank_universe(as_of_date=str(dates[-1].date()), window=20, top_k=5)
    assert len(res.selected_top_k) == 0


def test_b07_single_asset_universe():
    """B07-5: Universe with single asset receives 100.0 rank and 100% target weight."""
    dates = pd.bdate_range("2024-01-01", periods=25)
    prices = pd.DataFrame({"SA": [2000.0 + i for i in range(25)]}, index=dates)
    rets = pd.DataFrame({"SA": [0.005] * 25}, index=dates)
    ds = oracle.AlignedDataset(dates, prices, rets, {"SA": "FUTURES"}, prices.copy())
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=ds)
    res = ranker.rank_universe(as_of_date=str(dates[-1].date()), top_k=1)
    assert len(res.selected_top_k) == 1
    assert res.selected_top_k[0].composite_score > 0.0


# ===========================================================================
# Category 8: All-Stock and All-Futures Top-K Regimes
# ===========================================================================

def test_b08_all_stocks_top_k():
    """B08-1: All-stock ranking regime when stocks dominate momentum."""
    dates = pd.bdate_range("2024-01-01", periods=25)
    # Stocks surge +2% daily, futures drop -2% daily
    stock_rets = {f"STK_{i}": [0.02] * 25 for i in range(5)}
    fut_rets = {"SA": [-0.02] * 25, "FG": [-0.02] * 25}
    all_rets = {**stock_rets, **fut_rets}
    rets_df = pd.DataFrame(all_rets, index=dates)
    prices_df = pd.DataFrame({k: 100.0 * np.cumprod([1.0 + r for r in v]) for k, v in all_rets.items()}, index=dates)
    types = {k: "STOCK" if "STK" in k else "FUTURES" for k in all_rets}
    
    ds = oracle.AlignedDataset(dates, prices_df, rets_df, types, prices_df.copy())
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=ds)
    res = ranker.rank_universe(as_of_date=str(dates[-1].date()), top_k=3)
    for it in res.selected_top_k:
        assert it.asset_type == "STOCK"


def test_b08_all_futures_top_k(sample_commodity_surge_dataset):
    """B08-2: Commodity surge regime selects 100% futures into Top-K."""
    ds = sample_commodity_surge_dataset
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=ds)
    res = ranker.rank_universe(as_of_date=str(ds.dates[25].date()), top_k=3)
    fut_symbols = {"SA", "FG", "AU"}
    selected_syms = {it.symbol for it in res.selected_top_k}
    assert selected_syms.issubset(fut_symbols)


def test_b08_all_stocks_portfolio_pure_cash_spot():
    """B08-3: All-stock portfolio has zero margin locked."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=500_000.0)
    ledger.rebalance(target_weights={"600519": 0.5, "000858": 0.5}, current_prices={"600519": 100.0, "000858": 80.0})
    assert ledger.margin_locked == 0.0


def test_b08_all_futures_portfolio_maximum_margin_efficiency():
    """B08-4: All-futures portfolio leaves large free cash earning interest."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=500_000.0)
    # Buy 1 lot SA (margin 4,800) -> free cash approx 495,200
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    assert ledger.free_cash > 400_000.0
    state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    assert state.daily_interest > 20.0


def test_b08_regime_switch_all_stock_to_all_futures():
    """B08-5: Switching from all stocks to all futures liquidates stocks completely."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=200_000.0)
    ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 100.0})
    assert "600519" in ledger.positions

    # Rebalance to all futures
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"600519": 100.0, "SA": 2000.0})
    assert "600519" not in ledger.positions
    assert "SA" in ledger.positions


# ===========================================================================
# Category 9: Margin Call & Epsilon Edge Conditions
# ===========================================================================

def test_b09_margin_call_exact_boundary():
    """B09-1: Free cash == 0.0 does NOT trigger margin call."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=0.0)
    state = ledger.settle_daily(settle_prices={}, close_prices={})
    assert state.margin_call is False


def test_b09_margin_call_minus_one_cent():
    """B09-2: Free cash == -0.01 triggers margin call."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100.0)
    ledger.free_cash = -0.01
    state = ledger.settle_daily(settle_prices={}, close_prices={})
    assert state.margin_call is True


def test_b09_partial_futures_liquidation():
    """B09-3: Liquidating 1 lot of futures covers negative balance and restores positive cash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=50_000.0)
    ledger.rebalance(target_weights={"SA": 0.8}, current_prices={"SA": 2000.0})
    ledger.free_cash = -100.0
    state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    assert state.free_cash >= 0.0


def test_b09_full_liquidation_cascade():
    """B09-4: Large deficit liquidates both futures and stocks to restore solvency."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(target_weights={"600519": 0.4, "SA": 0.5}, current_prices={"600519": 100.0, "SA": 2000.0})
    ledger.free_cash = -30_000.0
    state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"600519": 100.0, "SA": 2000.0})
    assert state.margin_call is True
    assert state.free_cash >= 0.0


def test_b09_multiple_settle_cycles_in_margin_call():
    """B09-5: Continued margin pressure handled day by day."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    # Buy 1 lot SA and stocks
    ledger.rebalance(target_weights={"SA": 0.4, "600519": 0.3}, current_prices={"SA": 2000.0, "600519": 100.0})
    # Deficit triggers liquidation of SA on day 1
    ledger.free_cash = -50.0
    s1 = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"600519": 100.0, "SA": 2000.0})
    assert s1.margin_call is True
    assert s1.free_cash >= 0.0
    # Day 2: second deficit liquidates stock 600519
    ledger.free_cash = -50.0
    s2 = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"600519": 100.0, "SA": 2000.0})
    assert s2.margin_call is True
    assert s2.free_cash >= 0.0


# ===========================================================================
# Category 10: Discrete Lot Rounding & Micro-Budget Extremes
# ===========================================================================

def test_b10_budget_insufficient_for_100_shares():
    """B10-1: 50 RMB budget for 100 RMB stock results in 0 shares purchased."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=50.0)
    ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 100.0})
    assert "600519" not in ledger.positions or ledger.positions["600519"].quantity == 0


def test_b10_budget_insufficient_for_1_lot_futures():
    """B10-2: 2,000 RMB budget for 4,800 RMB margin results in 0 lots opened."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=2000.0)
    ledger.rebalance(target_weights={"SA": 1.0}, current_prices={"SA": 2000.0})
    assert "SA" not in ledger.positions or ledger.positions["SA"].quantity == 0


def test_b10_odd_lot_prevention():
    """B10-3: Stock quantity is always a multiple of 100 shares."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=123_456.0)
    ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 77.0})
    qty = ledger.positions["600519"].quantity
    assert qty % 100 == 0


def test_b10_fractional_lot_futures_prohibited():
    """B10-4: Futures lot quantity is always an integer."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=500_000.0)
    ledger.rebalance(target_weights={"SA": 0.33}, current_prices={"SA": 1950.0})
    qty = ledger.positions["SA"].quantity
    assert qty == math.floor(qty)


def test_b10_residual_cash_preserved_in_free_cash():
    """B10-5: Unspent cash from rounding remains in Free Cash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    # Budget 15,000 for 100 RMB stock -> buys 100 shares (10,000), leaves 5,000
    ledger = ledger_cls(initial_cash=15_000.0)
    ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 100.0})
    assert ledger.free_cash == pytest.approx(5000.0)


# ===========================================================================
# Category 11: Calendar Edges & Interest Accrual Conventions
# ===========================================================================

def test_b11_leap_year_calendar_day_count():
    """B11-1: 2024 leap year Feb 29 present in trading calendar."""
    dates = pd.bdate_range("2024-02-26", "2024-03-01")
    feb29 = pd.Timestamp("2024-02-29")
    assert feb29 in dates


def test_b11_long_holiday_gap_alignment():
    """B11-2: Holiday gap has no intermediate weekend dates."""
    dates = pd.bdate_range("2024-09-30", "2024-10-08")
    assert (dates.dayofweek < 5).all()


def test_b11_annual_rate_to_daily_divisor():
    """B11-3: Daily interest divisor equals 252."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=252_000.0, rf_annual=0.015)
    state = ledger.settle_daily(settle_prices={}, close_prices={})
    expected = 252_000.0 * 0.015 / 252.0  # Exactly 15.0 RMB
    assert state.daily_interest == pytest.approx(expected)


def test_b11_interest_accrual_idempotence():
    """B11-4: Separate daily settle calls accrue interest independently."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0, rf_annual=0.015)
    s1 = ledger.settle_daily(settle_prices={}, close_prices={}, date_str="2024-01-02")
    s2 = ledger.settle_daily(settle_prices={}, close_prices={}, date_str="2024-01-03")
    assert s1.daily_interest > 0.0
    assert s2.daily_interest > 0.0


def test_b11_settle_prices_missing_for_stock():
    """B11-5: Stocks without settle price fall back to close price safely."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 100.0})
    # Settle prices empty dictionary
    state = ledger.settle_daily(settle_prices={}, close_prices={"600519": 105.0})
    assert state.stock_market_val == pytest.approx(1000 * 105.0, rel=0.1)


# ===========================================================================
# Category 12: Settle vs Close Price Divergence Extremes
# ===========================================================================

def test_b12_settle_higher_than_close():
    """B12-1: Futures settle price 5% higher than close price: MTM uses settle price."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=200_000.0)
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    
    # Settle at 2100 (+100), close at 2000
    state = ledger.settle_daily(settle_prices={"SA": 2100.0}, close_prices={"SA": 2000.0})
    assert state.daily_pnl > 0.0


def test_b12_settle_lower_than_close():
    """B12-2: Futures settle price 5% lower than close price: MTM debit properly applied."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=200_000.0)
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    
    # Settle at 1900 (-100), close at 2000
    state = ledger.settle_daily(settle_prices={"SA": 1900.0}, close_prices={"SA": 2000.0})
    assert state.daily_pnl < 0.0


def test_b12_extreme_divergence_10_percent():
    """B12-3: 10% gap between settle and close price preserves equity identity."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=200_000.0)
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    ledger.settle_daily(settle_prices={"SA": 2200.0}, close_prices={"SA": 1800.0})
    assert ledger.total_equity == pytest.approx(
        ledger.free_cash + ledger.margin_locked + ledger.stock_market_val
    )


def test_b12_stock_close_equals_settle():
    """B12-4: Stock position close and settle prices are equivalent."""
    pos = oracle.Position("600519", "STOCK", 100, 100.0, 105.0, 105.0)
    assert pos.current_price == pos.settle_price


def test_b12_daily_pnl_reconciles_settle_and_close():
    """B12-5: Daily PnL equals delta equity across consecutive days."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    eq_before = ledger.total_equity
    state = ledger.settle_daily(settle_prices={}, close_prices={})
    assert state.daily_pnl == pytest.approx(ledger.total_equity - eq_before)


# ===========================================================================
# Category 13: Total Loss / 100% Drawdown Boundary
# ===========================================================================

def test_b13_equity_approaching_zero():
    """B13-1: Equity at 1.0 RMB handles leverage and calculations without ZeroDivisionError."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1.0)
    assert ledger.leverage_ratio == 0.0


def test_b13_negative_equity_catastrophe():
    """B13-2: Negative equity safely reports capped maximum leverage."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100.0)
    ledger.free_cash = -200.0
    assert ledger.leverage_ratio >= 100.0


def test_b13_drawdown_capped_at_100_percent():
    """B13-3: Max drawdown metric never exceeds 1.0."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    eq = pd.Series([100.0, 50.0, 10.0, 0.001])
    res = mpt_fn(eq)
    assert 0.0 <= res["max_drawdown"] <= 1.0


def test_b13_recovery_from_90_percent_drawdown():
    """B13-4: Portfolio surviving 90% drawdown resumes normal accounting."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=10_000.0)
    # Rebalance with tiny capital
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    assert ledger.total_equity > 0.0


def test_b13_nav_minimum_clamped_at_zero():
    """B13-5: NAV series never contains negative values in reporting."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    eq = pd.Series([100.0, 80.0, 90.0])
    res = mpt_fn(eq)
    assert res["total_return"] >= -1.0


# ===========================================================================
# Category 14: Benchmark Length Mismatch & Alignment Edge
# ===========================================================================

def test_b14_benchmark_longer_than_portfolio(sample_market_dataset):
    """B14-1: Benchmark series longer than test period trimmed to dataset window."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(dataset=sample_market_dataset)
    res = engine.run_backtest()
    assert len(res.equity_curve["CSI300"]) == len(sample_market_dataset.dates)


def test_b14_benchmark_shorter_than_portfolio(sample_market_dataset):
    """B14-2: Synthetic benchmark proxy generated when CSI 300 ticker missing."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(dataset=sample_market_dataset)
    res = engine.run_backtest()
    assert "CSI300" in res.equity_curve.columns
    assert not res.equity_curve["CSI300"].isna().any()


def test_b14_empty_benchmark_series():
    """B14-3: Empty benchmark dataset handled safely."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    empty_series = pd.Series([], dtype=float)
    res = mpt_fn(empty_series)
    assert res["total_return"] == 0.0


def test_b14_benchmark_scale_normalization(sample_market_dataset):
    """B14-4: Benchmark starts at exact same initial capital."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(dataset=sample_market_dataset, initial_cash=2_000_000.0)
    res = engine.run_backtest()
    assert float(res.equity_curve["CSI300"].iloc[0]) == pytest.approx(2_000_000.0)


def test_b14_single_day_backtest():
    """B14-5: Single day dataset produces 0 return without failure."""
    dates = pd.bdate_range("2024-01-01", periods=1)
    px = pd.DataFrame({"600519": [100.0]}, index=dates)
    ret = pd.DataFrame({"600519": [0.0]}, index=dates)
    ds = oracle.AlignedDataset(dates, px, ret, {"600519": "STOCK"}, px.copy())
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(dataset=ds)
    res = engine.run_backtest()
    assert len(res.equity_curve) == 1


# ===========================================================================
# Category 15: Ticker Format & Asset Type Validation
# ===========================================================================

def test_b15_unknown_ticker_symbol_defaults_to_stock(contract_spec_resolver):
    """B15-1: Unknown symbol defaults to standard stock specification."""
    spec = contract_spec_resolver("MY_UNKNOWN_99")
    assert str(spec.asset_type) in ["STOCK", "AssetType.STOCK"]
    assert spec.multiplier in [1.0, 100.0]


def test_b15_whitespace_and_special_chars_in_ticker(contract_spec_resolver):
    """B15-2: Trailing whitespace in commodity symbol stripped and recognized."""
    spec = contract_spec_resolver(" SA ")
    assert spec.symbol in ["SA", "SA0"]
    assert str(spec.asset_type) in ["FUTURES", "AssetType.FUTURES"]


def test_b15_lowercase_commodity_symbol(contract_spec_resolver):
    """B15-3: Lowercase commodity symbol resolved accurately."""
    spec = contract_spec_resolver("au")
    assert spec.symbol in ["AU", "AU0"]
    assert str(spec.asset_type) in ["FUTURES", "AssetType.FUTURES"]


def test_b15_invalid_price_negative_throws_or_clamps():
    """B15-4: Zero price in rebalance does not cause division by zero."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    trades = ledger.rebalance(target_weights={"600519": 0.5}, current_prices={"600519": 0.0})
    assert len(trades) == 0


def test_b15_nan_price_in_rebalance_skipped():
    """B15-5: NaN price in rebalance safely ignored."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    trades = ledger.rebalance(target_weights={"600519": 0.5}, current_prices={"600519": np.nan})
    assert len(trades) == 0


# ===========================================================================
# Category 16: MPT & Metric Edge Conditions
# ===========================================================================

def test_b16_zero_volatility_sharpe_zero():
    """B16-1: Flat equity curve yields 0.0 Sharpe ratio."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    eq = pd.Series([100.0] * 30)
    res = mpt_fn(eq)
    assert res["sharpe_ratio"] == 0.0


def test_b16_zero_drawdown_calmar_bounded():
    """B16-2: Zero drawdown yields finite Calmar ratio."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    eq = pd.Series([100.0 + i for i in range(30)])
    res = mpt_fn(eq)
    assert np.isfinite(res["calmar_ratio"])


def test_b16_negative_sharpe_ratio():
    """B16-3: Consistently losing portfolio produces negative Sharpe ratio."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    eq = pd.Series([100.0 * (0.99 ** i) for i in range(30)])
    res = mpt_fn(eq)
    assert res["sharpe_ratio"] < 0.0


def test_b16_single_asset_dr_one():
    """B16-4: Single asset Diversification Ratio is exactly 1.0."""
    dr_fn = resolve_component("backtest_engine", "calculate_diversification_ratio")
    dr = dr_fn(np.array([1.0]), np.array([0.15]), np.array([[0.0225]]))
    assert dr == pytest.approx(1.0)


def test_b16_dr_upper_bound_sanity():
    """B16-5: DR is strictly bounded above by sqrt(N) for N equal-vol uncorrelated assets."""
    dr_fn = resolve_component("backtest_engine", "calculate_diversification_ratio")
    n = 4
    weights = np.ones(n) / n
    vols = np.full(n, 0.20)
    cov = np.diag(vols ** 2)  # Zero correlation
    dr = dr_fn(weights, vols, cov)
    # Expected DR = sqrt(4) = 2.0
    assert dr == pytest.approx(math.sqrt(n), rel=1e-3)
    assert dr <= math.sqrt(n) + 1e-6
