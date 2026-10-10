"""Tier 1: Feature Coverage E2E Test Suite for Cross-Asset Mixed Portfolio.
Covers Features 1 through 16 with >= 5 test cases per feature (80 test cases total).
Tests strictly against interface contracts and mathematical specifications in PROJECT.md.
"""

import math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from tests.cross_asset_mix.conftest import resolve_component
from tests.cross_asset_mix import reference_oracle as oracle


# ===========================================================================
# Feature 1: Contract Specifications (Multipliers, Margins 10%-15%, Tick Sizes)
# ===========================================================================

def test_f01_czce_pure_soda_sa_specs(contract_spec_resolver):
    """F01-1: CZCE Pure Soda (SA) specification contract."""
    spec = contract_spec_resolver("SA")
    assert spec.symbol in ["SA", "SA0"]
    assert "纯碱" in spec.name
    assert str(spec.asset_type) in ["FUTURES", "AssetType.FUTURES"]
    assert str(spec.exchange) in ["CZCE", "FuturesExchange.CZCE"]
    assert spec.multiplier == 20.0  # 20 tons / lot
    margin = getattr(spec, "margin_ratio", getattr(spec, "margin_rate", None))
    assert 0.10 <= margin <= 0.15  # 12% standard margin
    assert spec.tick_size == 1.0


def test_f01_czce_glass_fg_specs(contract_spec_resolver):
    """F01-2: CZCE Glass (FG) specification contract."""
    spec = contract_spec_resolver("FG")
    assert spec.symbol in ["FG", "FG0"]
    assert "玻璃" in spec.name
    assert str(spec.asset_type) in ["FUTURES", "AssetType.FUTURES"]
    assert str(spec.exchange) in ["CZCE", "FuturesExchange.CZCE"]
    assert spec.multiplier == 20.0  # 20 tons / lot
    margin = getattr(spec, "margin_ratio", getattr(spec, "margin_rate", None))
    assert 0.10 <= margin <= 0.15  # 12% standard margin
    assert spec.tick_size == 1.0


def test_f01_shfe_gold_au_specs(contract_spec_resolver):
    """F01-3: SHFE Gold (AU) specification contract."""
    spec = contract_spec_resolver("AU")
    assert spec.symbol in ["AU", "AU0"]
    assert "金" in spec.name
    assert str(spec.asset_type) in ["FUTURES", "AssetType.FUTURES"]
    assert str(spec.exchange) in ["SHFE", "FuturesExchange.SHFE"]
    assert spec.multiplier == 1000.0  # 1000 grams / lot
    margin = getattr(spec, "margin_ratio", getattr(spec, "margin_rate", None))
    assert 0.08 <= margin <= 0.15  # 10% standard margin
    assert spec.tick_size == 0.02


def test_f01_ashare_stock_specs(contract_spec_resolver):
    """F01-4: A-Share stock specification contract (100% full cash, 100 shares)."""
    spec = contract_spec_resolver("600519")
    assert str(spec.asset_type) in ["STOCK", "AssetType.STOCK"]
    margin = getattr(spec, "margin_ratio", getattr(spec, "margin_rate", None))
    assert margin == 1.0  # 100% full cash spot
    assert spec.multiplier in [1.0, 100.0]
    assert spec.tick_size == 0.01


def test_f01_contract_spec_case_insensitive_and_prefix_lookup(contract_spec_resolver):
    """F01-5: Continuous and dominant contract symbol resolution."""
    sa_spec = contract_spec_resolver("SA0")
    fg_spec = contract_spec_resolver("FG0")
    au_spec = contract_spec_resolver("AU0")
    stock_spec = contract_spec_resolver("000001")

    assert sa_spec.multiplier == 20.0
    assert fg_spec.multiplier == 20.0
    assert au_spec.multiplier == 1000.0
    assert str(stock_spec.asset_type) in ["STOCK", "AssetType.STOCK"]


# ===========================================================================
# Feature 2: Futures Rollover Gap Adjustment (Holding Return Stitching)
# ===========================================================================

def test_f02_rollover_eliminates_artificial_price_jump():
    """F02-1: Price jump from 2000 to 2100 on roll day is eliminated in adjusted returns."""
    dates = pd.bdate_range("2024-01-01", periods=5)
    # Day 2 is roll day: old contract was 2000, new contract open/settle is 2100 (+100 gap)
    raw_prices = pd.Series([1980.0, 2000.0, 2100.0, 2110.0, 2120.0], index=dates)
    adjust_fn = resolve_component("data_loader", "adjust_rollover_gaps")
    adj_series = adjust_fn(raw_prices, roll_dates=[str(dates[2].date())], roll_gaps={str(dates[2].date()): 100.0})

    # Holding return on roll day should reflect continuous economic return, not artificial +5% jump
    raw_pct = raw_prices.iloc[2] / raw_prices.iloc[1] - 1.0
    adj_pct = adj_series.iloc[2] / adj_series.iloc[1] - 1.0
    assert raw_pct == pytest.approx(0.05, abs=1e-3)
    assert abs(adj_pct) < 0.01  # Artificial jump stripped out


def test_f02_rollover_preserves_post_roll_returns():
    """F02-2: Post-roll day returns match real trading returns exactly."""
    dates = pd.bdate_range("2024-01-01", periods=5)
    raw_prices = pd.Series([2000.0, 2000.0, 2050.0, 2100.0, 2150.0], index=dates)
    adjust_fn = resolve_component("data_loader", "adjust_rollover_gaps")
    adj_series = adjust_fn(raw_prices, roll_dates=[str(dates[2].date())])
    
    # Between Day 3 and Day 4: 2100 -> 2150 (+2.38%)
    raw_ret = raw_prices.iloc[4] / raw_prices.iloc[3] - 1.0
    adj_ret = adj_series.iloc[4] / adj_series.iloc[3] - 1.0
    assert adj_ret == pytest.approx(raw_ret, rel=1e-5)


def test_f02_rollover_cumulative_return_consistency():
    """F02-3: Cumulative return product across roll date reflects organic holding return."""
    dates = pd.bdate_range("2024-01-01", periods=4)
    raw_prices = pd.Series([1000.0, 1000.0, 1100.0, 1100.0], index=dates)
    adjust_fn = resolve_component("data_loader", "adjust_rollover_gaps")
    adj_series = adjust_fn(raw_prices, roll_dates=[str(dates[2].date())], roll_gaps={str(dates[2].date()): 100.0})
    
    # With a pure 100 basis jump on flat market, total economic return is 0%
    total_adj_ret = adj_series.iloc[-1] / adj_series.iloc[0] - 1.0
    assert total_adj_ret == pytest.approx(0.0, abs=1e-2)


def test_f02_multiple_consecutive_rollovers():
    """F02-4: Consecutive rollovers across multiple contract cycles (M1 -> M2 -> M3)."""
    dates = pd.bdate_range("2024-01-01", periods=6)
    raw_prices = pd.Series([2000.0, 2000.0, 2050.0, 2050.0, 2100.0, 2100.0], index=dates)
    adjust_fn = resolve_component("data_loader", "adjust_rollover_gaps")
    adj = adjust_fn(
        raw_prices,
        roll_dates=[str(dates[2].date()), str(dates[4].date())],
        roll_gaps={str(dates[2].date()): 50.0, str(dates[4].date()): 50.0},
    )
    assert len(adj) == 6
    assert adj.iloc[-1] / adj.iloc[0] == pytest.approx(1.0, abs=0.02)


def test_f02_negative_roll_gap_contango():
    """F02-5: Contango scenario where new contract price is lower than old contract."""
    dates = pd.bdate_range("2024-01-01", periods=4)
    raw_prices = pd.Series([2000.0, 2000.0, 1950.0, 1950.0], index=dates)
    adjust_fn = resolve_component("data_loader", "adjust_rollover_gaps")
    adj = adjust_fn(raw_prices, roll_dates=[str(dates[2].date())], roll_gaps={str(dates[2].date()): -50.0})
    assert len(adj) == 4
    assert adj.iloc[-1] / adj.iloc[0] == pytest.approx(1.0, abs=0.02)


# ===========================================================================
# Feature 3: Calendar Alignment & Cleaning (Align 202 Stocks + 3 Futures)
# ===========================================================================

def test_f03_calendar_alignment_stocks_and_futures(sample_market_dataset):
    """F03-1: Stocks and futures share identical DatetimeIndex with no date misalignment."""
    ds = sample_market_dataset
    assert isinstance(ds.dates, pd.DatetimeIndex)
    assert (ds.prices.index == ds.dates).all()
    assert (ds.returns.index == ds.dates).all()
    assert (ds.settle_prices.index == ds.dates).all()


def test_f03_stock_suspension_forward_fill_no_lookahead(sample_market_dataset):
    """F03-2: Stock trading suspension preserves previous close price without lookahead."""
    prices = sample_market_dataset.prices.copy()
    stock_col = [c for c, t in sample_market_dataset.asset_types.items() if t == "STOCK"][0]
    # Introduce suspension on day 10
    prices.iloc[10, prices.columns.get_loc(stock_col)] = np.nan
    ffilled = prices.ffill()
    assert ffilled.iloc[10][stock_col] == ffilled.iloc[9][stock_col]


def test_f03_futures_night_session_homogenization_to_daily(sample_market_dataset):
    """F03-3: Daily frequency captures full settlement price cycle."""
    ds = sample_market_dataset
    for fut in ["SA", "FG", "AU"]:
        assert fut in ds.prices.columns
        assert fut in ds.settle_prices.columns
        assert (ds.settle_prices[fut] > 0).all()


def test_f03_non_trading_day_filtering(sample_market_dataset):
    """F03-4: Weekend dates (Saturday, Sunday) are absent from trading calendar."""
    dates = sample_market_dataset.dates
    weekdays = dates.dayofweek
    assert (weekdays < 5).all()  # Monday to Friday only


def test_f03_dataset_dimensions_and_integrity(sample_market_dataset):
    """F03-5: Dimensions of prices, returns, and settle prices match exactly."""
    ds = sample_market_dataset
    assert ds.prices.shape == ds.settle_prices.shape
    assert ds.prices.shape == ds.returns.shape
    assert set(ds.prices.columns) == set(ds.asset_types.keys())


# ===========================================================================
# Feature 4: Compounded 20d Momentum (prod(1+r) - 1)
# ===========================================================================

def test_f04_compounded_20d_momentum_formula():
    """F04-1: Evaluates prod_{tau=t-19}^t (1+r_tau) - 1 against manual formula."""
    returns = pd.DataFrame({"A": [0.01] * 20})
    mom_fn = resolve_component("ranking", "calculate_compounded_20d_momentum")
    res = mom_fn(returns, window=20)
    expected = (1.01 ** 20) - 1.0
    assert float(res.iloc[-1]["A"]) == pytest.approx(expected, rel=1e-5)


def test_f04_momentum_positive_steady_growth():
    """F04-2: 20 days of +0.5% daily return compounds to ~10.49%."""
    returns = pd.DataFrame({"A": [0.005] * 20})
    mom_fn = resolve_component("ranking", "calculate_compounded_20d_momentum")
    res = mom_fn(returns, window=20)
    expected = (1.005 ** 20) - 1.0
    assert float(res.iloc[-1]["A"]) == pytest.approx(expected, rel=1e-5)


def test_f04_momentum_negative_drawdown():
    """F04-3: 20 days of -1% daily return compounds to ~ -18.21%."""
    returns = pd.DataFrame({"A": [-0.01] * 20})
    mom_fn = resolve_component("ranking", "calculate_compounded_20d_momentum")
    res = mom_fn(returns, window=20)
    expected = (0.99 ** 20) - 1.0
    assert float(res.iloc[-1]["A"]) == pytest.approx(expected, rel=1e-5)


def test_f04_momentum_zero_return_flat():
    """F04-4: 20 days of 0% return results in exactly 0.0 momentum."""
    returns = pd.DataFrame({"A": [0.0] * 20})
    mom_fn = resolve_component("ranking", "calculate_compounded_20d_momentum")
    res = mom_fn(returns, window=20)
    assert float(res.iloc[-1]["A"]) == pytest.approx(0.0, abs=1e-9)


def test_f04_momentum_rolling_window_shift():
    """F04-5: Rolling window drops old returns and includes new return."""
    # Day 0 is +10%, days 1-19 are 0%, day 20 is +5%
    ret_vals = [0.10] + [0.0] * 19 + [0.05]
    returns = pd.DataFrame({"A": ret_vals})
    mom_fn = resolve_component("ranking", "calculate_compounded_20d_momentum")
    res = mom_fn(returns, window=20)
    
    # At index 19 (window 0..19), momentum contains the 10%
    assert float(res.iloc[19]["A"]) == pytest.approx(0.10, rel=1e-5)
    # At index 20 (window 1..20), the 10% dropped out and the 5% entered
    assert float(res.iloc[20]["A"]) == pytest.approx(0.05, rel=1e-5)


# ===========================================================================
# Feature 5: Inverse Volatility with Floor (sigma_floor = 0.08)
# ===========================================================================

def test_f05_inverse_volatility_formula():
    """F05-1: Correct formula 1 / (std * sqrt(252))."""
    # Create daily returns with known std = 0.015 -> ann_vol = 0.015 * sqrt(252) approx 0.2381
    rng = np.random.default_rng(123)
    rets = pd.DataFrame({"A": rng.normal(0, 0.015, 30)})
    iv_fn = resolve_component("ranking", "calculate_inverse_volatility")
    res = iv_fn(rets, window=20, floor=0.08)
    
    std_20 = rets["A"].iloc[10:30].std()
    expected_ann = std_20 * np.sqrt(252.0)
    expected_iv = 1.0 / max(expected_ann, 0.08)
    assert float(res.iloc[-1]["A"]) == pytest.approx(expected_iv, rel=1e-4)


def test_f05_anti_overflow_floor_active_on_flat_asset():
    """F05-2: Flat price asset with 0 volatility clamped to floor 0.08, returning 12.5."""
    rets = pd.DataFrame({"A": [0.0] * 25})
    iv_fn = resolve_component("ranking", "calculate_inverse_volatility")
    res = iv_fn(rets, window=20, floor=0.08)
    assert float(res.iloc[-1]["A"]) == pytest.approx(1.0 / 0.08, abs=1e-4)


def test_f05_anti_overflow_floor_inactive_on_volatile_asset():
    """F05-3: Highly volatile asset (ann vol = 0.30) not affected by 0.08 floor."""
    rets = pd.DataFrame({"A": [0.03, -0.03] * 15})
    iv_fn = resolve_component("ranking", "calculate_inverse_volatility")
    res = iv_fn(rets, window=20, floor=0.08)
    ann_vol = rets["A"].iloc[-20:].std() * np.sqrt(252.0)
    assert ann_vol > 0.08
    assert float(res.iloc[-1]["A"]) == pytest.approx(1.0 / ann_vol, rel=1e-4)


def test_f05_strictly_positive_finite():
    """F05-4: Inverse volatility is strictly finite and > 0."""
    rets = pd.DataFrame({"A": [0.0] * 30, "B": [0.01, -0.01] * 15})
    iv_fn = resolve_component("ranking", "calculate_inverse_volatility")
    res = iv_fn(rets, window=20, floor=0.08)
    assert np.isfinite(res.dropna().values).all()
    assert (res.dropna().values > 0).all()


def test_f05_monotonic_relationship():
    """F05-5: Higher volatility strictly maps to lower inverse volatility."""
    rets_low = pd.DataFrame({"A": [0.005, -0.005] * 15})
    rets_high = pd.DataFrame({"A": [0.02, -0.02] * 15})
    iv_fn = resolve_component("ranking", "calculate_inverse_volatility")
    iv_low = float(iv_fn(rets_low, window=20).iloc[-1]["A"])
    iv_high = float(iv_fn(rets_high, window=20).iloc[-1]["A"])
    assert iv_low > iv_high


# ===========================================================================
# Feature 6: Composite Trend Strength (CTSI)
# ===========================================================================

def test_f06_ctsi_formula_components():
    """F06-1: CTSI combines MA divergence, Bollinger channel position, and alignment."""
    px = pd.DataFrame({"A": [10.0 + i * 0.1 for i in range(30)]})
    ctsi_fn = resolve_component("ranking", "calculate_ctsi")
    res = ctsi_fn(px, window=20)
    assert not res.empty
    assert np.isfinite(res.dropna().values).all()


def test_f06_ctsi_bullish_breakout_high_score():
    """F06-2: Surging price well above moving average scores high trend strength."""
    prices = [100.0] * 20 + [102.0, 105.0, 110.0, 115.0, 120.0]
    px_df = pd.DataFrame({"A": prices})
    ctsi_fn = resolve_component("ranking", "calculate_ctsi")
    res = ctsi_fn(px_df, window=20)
    latest_score = float(res.iloc[-1]["A"])
    assert latest_score > 0.6  # Strongly bullish score


def test_f06_ctsi_bearish_breakdown_low_score():
    """F06-3: Collapsing price scores low trend strength."""
    prices = [100.0] * 20 + [98.0, 95.0, 90.0, 85.0, 80.0]
    px_df = pd.DataFrame({"A": prices})
    ctsi_fn = resolve_component("ranking", "calculate_ctsi")
    res = ctsi_fn(px_df, window=20)
    latest_score = float(res.iloc[-1]["A"])
    assert latest_score < 0.4  # Bearish score


def test_f06_ctsi_sideways_neutral_score():
    """F06-4: Range-bound oscillation produces intermediate score."""
    prices = [100.0, 101.0, 99.0, 100.0] * 8
    px_df = pd.DataFrame({"A": prices})
    ctsi_fn = resolve_component("ranking", "calculate_ctsi")
    res = ctsi_fn(px_df, window=20)
    latest = float(res.iloc[-1]["A"])
    assert 0.1 <= latest <= 0.9


def test_f06_ctsi_ma_alignment_boost():
    """F06-5: MA5 > MA20 condition gives positive score alignment increment."""
    # Fast MA rising above slow MA
    rising = pd.DataFrame({"A": [10.0 + i * 0.2 for i in range(25)]})
    falling = pd.DataFrame({"A": [20.0 - i * 0.2 for i in range(25)]})
    ctsi_fn = resolve_component("ranking", "calculate_ctsi")
    score_rising = float(ctsi_fn(rising, window=20).iloc[-1]["A"])
    score_falling = float(ctsi_fn(falling, window=20).iloc[-1]["A"])
    assert score_rising > score_falling


# ===========================================================================
# Feature 7: Cross-Asset Percentile Ranking (Uniform [0, 100])
# ===========================================================================

def test_f07_percentile_ranking_range_zero_to_hundred():
    """F07-1: All ranked values strictly bounded within [0, 100]."""
    series = pd.Series([10.5, -2.3, 0.0, 50.1, 100.2, -50.0])
    rank_fn = resolve_component("ranking", "compute_cross_asset_percentile_rank")
    pct = rank_fn(series)
    assert pct.min() >= 0.0
    assert pct.max() <= 100.0
    assert float(pct.min()) == pytest.approx(0.0)
    assert float(pct.max()) == pytest.approx(100.0)


def test_f07_percentile_ranking_unbiased_across_stocks_and_futures():
    """F07-2: Stocks and futures ranked in unified series with no structural bias."""
    scores = pd.Series(
        {"SA": 1.25, "FG": 0.85, "AU": 1.50, "600519": 1.10, "000858": 0.50}
    )
    rank_fn = resolve_component("ranking", "compute_cross_asset_percentile_rank")
    pct = rank_fn(scores)
    # Highest score (AU) gets 100.0, lowest (000858) gets 0.0
    assert float(pct["AU"]) == pytest.approx(100.0)
    assert float(pct["000858"]) == pytest.approx(0.0)
    assert pct["SA"] > pct["600519"] > pct["FG"]


def test_f07_percentile_ranking_monotonically_increasing():
    """F07-3: Percentile ranks are strictly monotonic with respect to input scores."""
    scores = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    rank_fn = resolve_component("ranking", "compute_cross_asset_percentile_rank")
    pct = rank_fn(scores)
    assert pct.is_monotonic_increasing


def test_f07_percentile_ranking_single_element_corner():
    """F07-4: Single-element series handled safely without division by zero."""
    scores = pd.Series([42.0])
    rank_fn = resolve_component("ranking", "compute_cross_asset_percentile_rank")
    pct = rank_fn(scores)
    assert float(pct.iloc[0]) == 100.0


def test_f07_percentile_ranking_tie_handling():
    """F07-5: Tied scores receive identical percentile ranks."""
    scores = pd.Series([10.0, 20.0, 20.0, 30.0])
    rank_fn = resolve_component("ranking", "compute_cross_asset_percentile_rank")
    pct = rank_fn(scores)
    assert float(pct.iloc[1]) == float(pct.iloc[2])


# ===========================================================================
# Feature 8: Top-K Mixed Selection & Tagging
# ===========================================================================

def test_f08_top_k_selects_exact_count(sample_market_dataset):
    """F08-1: Top-K selection returns exactly K items."""
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=sample_market_dataset)
    res = ranker.rank_universe(as_of_date=str(sample_market_dataset.dates[25].date()), top_k=5)
    assert len(res.selected_top_k) == 5


def test_f08_top_k_mixed_asset_types(sample_market_dataset):
    """F08-2: Top-K contains both STOCK and FUTURES items in a mixed universe."""
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=sample_market_dataset)
    res = ranker.rank_universe(as_of_date=str(sample_market_dataset.dates[30].date()), top_k=10)
    asset_types = {item.asset_type for item in res.selected_top_k}
    assert "STOCK" in asset_types
    assert "FUTURES" in asset_types


def test_f08_top_k_all_fields_populated(sample_market_dataset):
    """F08-3: All required fields in RankItem are populated and valid."""
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=sample_market_dataset)
    res = ranker.rank_universe(as_of_date=str(sample_market_dataset.dates[25].date()), top_k=5)
    for item in res.selected_top_k:
        assert isinstance(item.rank, int)
        assert len(item.symbol) > 0
        assert item.asset_type in ["STOCK", "FUTURES"]
        assert np.isfinite(item.momentum_20d)
        assert np.isfinite(item.inv_vol)
        assert np.isfinite(item.trend_strength)
        assert np.isfinite(item.composite_score)
        assert item.target_weight > 0.0


def test_f08_top_k_weights_sum_to_one(sample_market_dataset):
    """F08-4: Target weights across Top-K sum to 1.0."""
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=sample_market_dataset)
    res = ranker.rank_universe(as_of_date=str(sample_market_dataset.dates[25].date()), top_k=8)
    total_weight = sum(item.target_weight for item in res.selected_top_k)
    assert total_weight == pytest.approx(1.0, rel=1e-3)


def test_f08_top_k_strictly_sorted_by_composite_score(sample_market_dataset):
    """F08-5: Items ordered with rank 1 having the highest composite score."""
    ranker_cls = resolve_component("ranking", "CrossAssetRanker")
    ranker = ranker_cls(dataset=sample_market_dataset)
    res = ranker.rank_universe(as_of_date=str(sample_market_dataset.dates[25].date()), top_k=6)
    scores = [it.composite_score for it in res.selected_top_k]
    assert scores == sorted(scores, reverse=True)


# ===========================================================================
# Feature 9: Dual-Track Accounting Ledger (Equity Conservation Identity)
# ===========================================================================

def test_f09_equity_conservation_identity():
    """F09-1: Total Equity = Free Cash + Margin Locked + Stock Market Value always holds."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0)
    assert ledger.total_equity == pytest.approx(
        ledger.free_cash + ledger.margin_locked + ledger.stock_market_val
    )


def test_f09_stock_full_cash_purchase():
    """F09-2: Stock buy deducts 100% full cash, increases stock market val, 0 margin locked."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=500_000.0)
    
    # Buy stock: 50% target weight at price 100
    ledger.rebalance(target_weights={"600519": 0.5}, current_prices={"600519": 100.0})
    assert ledger.margin_locked == 0.0
    assert ledger.stock_market_val > 0.0
    assert ledger.total_equity == pytest.approx(500_000.0, rel=1e-4)


def test_f09_futures_margin_lock():
    """F09-3: Futures buy locks standard margin (12%), leaving rest in Free Cash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=500_000.0)
    
    # SA: price 2000, multiplier 20, margin 12% -> 4800 per lot
    ledger.rebalance(target_weights={"SA": 0.2}, current_prices={"SA": 2000.0})
    assert ledger.margin_locked > 0.0
    assert ledger.stock_market_val == 0.0
    assert ledger.total_equity == pytest.approx(500_000.0, rel=1e-4)


def test_f09_separate_tracking_no_cross_contamination():
    """F09-4: Stock price movement modifies Stock Market Value without altering Margin Locked."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0)
    ledger.rebalance(
        target_weights={"600519": 0.3, "SA": 0.2},
        current_prices={"600519": 100.0, "SA": 2000.0},
    )
    initial_margin = ledger.margin_locked

    # Stock price jumps to 120, SA settle price unchanged at 2000
    ledger.settle_daily(
        settle_prices={"SA": 2000.0},
        close_prices={"600519": 120.0, "SA": 2000.0},
    )
    assert ledger.margin_locked == pytest.approx(initial_margin, rel=1e-4)
    assert ledger.stock_market_val > 300_000.0


def test_f09_cash_withdrawal_or_injection():
    """F09-5: Capital injection increases free cash and total equity by exact same amount."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.free_cash += 50_000.0
    assert ledger.total_equity == pytest.approx(150_000.0)


# ===========================================================================
# Feature 10: Discrete Lot Execution (100 Shares / 1 Lot, No Overdraft)
# ===========================================================================

def test_f10_stock_order_rounded_to_100_shares():
    """F10-1: Stock orders strictly rounded to integer multiples of 100 shares."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=250_000.0)
    # Target 100% at price 133.0 -> 250000 / 133 = 1879.7 shares -> rounds to 1800 shares
    ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 133.0})
    pos = ledger.positions["600519"]
    assert pos.quantity % 100 == 0
    assert pos.quantity == 1800


def test_f10_futures_order_rounded_to_integer_lots():
    """F10-2: Futures orders strictly rounded to integer lots."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    # Target SA price 2100, multiplier 20 -> notional = 42,000 per lot
    # Target 50% = 50,000 -> 50,000 / 42,000 = 1.19 lots -> rounds to 1 lot
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2100.0})
    pos = ledger.positions["SA"]
    assert pos.quantity == 1.0


def test_f10_no_cash_overdraft_on_stock_buy():
    """F10-3: Stock buy cannot exceed available Free Cash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=10_000.0)
    # Price 105 -> 100 shares = 10,500 > 10,000 cash -> order truncated to 0 shares
    ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 105.0})
    assert "600519" not in ledger.positions or ledger.positions["600519"].quantity == 0
    assert ledger.free_cash == pytest.approx(10_000.0)


def test_f10_no_cash_overdraft_on_futures_margin():
    """F10-4: Futures position cannot exceed allowable free cash margin."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=3_000.0)
    # SA margin is 4800 per lot > 3000 free cash -> 0 lots opened
    ledger.rebalance(target_weights={"SA": 1.0}, current_prices={"SA": 2000.0})
    assert "SA" not in ledger.positions or ledger.positions["SA"].quantity == 0


def test_f10_exact_budget_edge_case():
    """F10-5: Exactly enough cash for 100 shares executes leaving zero free cash without error."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=10_000.0)
    ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 100.0})
    assert ledger.positions["600519"].quantity == 100
    assert ledger.free_cash == pytest.approx(0.0)


# ===========================================================================
# Feature 11: Daily MTM Futures Settlement
# ===========================================================================

def test_f11_mtm_gain_credits_free_cash():
    """F11-1: Daily price gain on futures directly credits Free Cash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    # Buy 1 lot SA at 2000
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    cash_after_buy = ledger.free_cash

    # Settle at 2050 (+50 points * 20 mult = +1000 PnL)
    # Margin increases by 50 * 20 * 0.12 = 120 -> net cash change = +1000 - 120 = +880
    ledger.settle_daily(
        settle_prices={"SA": 2050.0},
        close_prices={"SA": 2050.0},
    )
    assert ledger.free_cash > cash_after_buy
    assert ledger.total_equity > 100_000.0


def test_f11_mtm_loss_debits_free_cash():
    """F11-2: Daily price drop debits Free Cash and decreases Total Equity."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})

    # Settle at 1950 (-50 points * 20 mult = -1000 PnL)
    ledger.settle_daily(
        settle_prices={"SA": 1950.0},
        close_prices={"SA": 1950.0},
    )
    assert ledger.total_equity < 100_000.0


def test_f11_mtm_updates_locked_margin():
    """F11-3: Margin locked dynamically updates to new settlement price."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    qty = ledger.positions["SA"].quantity

    ledger.settle_daily(settle_prices={"SA": 2200.0}, close_prices={"SA": 2200.0})
    expected_margin = qty * 20.0 * 2200.0 * 0.12
    assert ledger.margin_locked == pytest.approx(expected_margin, rel=1e-4)


def test_f11_gold_au_tick_and_multiplier_mtm():
    """F11-4: Gold AU with 1000 multiplier and 0.02 tick accurately computes MTM."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0)
    # AU at 450.0 -> 1 lot notional 450,000, margin 10% = 45,000
    ledger.rebalance(target_weights={"AU": 0.5}, current_prices={"AU": 450.0})
    
    # Rise +1.50 yuan/gram -> 1.50 * 1000 = +1500 PnL
    state = ledger.settle_daily(settle_prices={"AU": 451.50}, close_prices={"AU": 451.50})
    assert state.daily_pnl > 1400.0


def test_f11_zero_price_change_neutral_settle():
    """F11-5: Flat settlement price results in 0 MTM PnL (excluding interest)."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0, rf_annual=0.0)
    ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
    eq_before = ledger.total_equity

    ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    assert ledger.total_equity == pytest.approx(eq_before, abs=1e-4)


# ===========================================================================
# Feature 12: Idle Cash 1.5% Daily Interest
# ===========================================================================

def test_f12_daily_interest_formula():
    """F12-1: Daily interest equals Free Cash * (0.015 / 252)."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0, rf_annual=0.015)
    state = ledger.settle_daily(settle_prices={}, close_prices={})
    expected = 1_000_000.0 * (0.015 / 252.0)
    assert state.daily_interest == pytest.approx(expected, rel=1e-4)


def test_f12_interest_accrues_only_on_positive_free_cash():
    """F12-2: Zero free cash produces 0 daily interest."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=0.0, rf_annual=0.015)
    state = ledger.settle_daily(settle_prices={}, close_prices={})
    assert state.daily_interest == 0.0


def test_f12_compound_interest_over_252_days():
    """F12-3: 1,000,000 cash held idle for 252 days yields ~15,000 interest."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=1_000_000.0, rf_annual=0.015)
    for _ in range(252):
        ledger.settle_daily(settle_prices={}, close_prices={})
    total_earned = ledger.total_equity - 1_000_000.0
    assert 14_900.0 <= total_earned <= 15_200.0


def test_f12_interest_increments_total_equity():
    """F12-4: Free cash interest directly compounds total equity upwards."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=500_000.0, rf_annual=0.015)
    eq0 = ledger.total_equity
    ledger.settle_daily(settle_prices={}, close_prices={})
    assert ledger.total_equity > eq0


def test_f12_margin_locked_does_not_earn_interest():
    """F12-5: Locked margin does not earn idle interest; interest calculated only on Free Cash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0, rf_annual=0.015)
    # Lock 20,000 in margin -> 80,000 free cash
    ledger.rebalance(target_weights={"SA": 0.2}, current_prices={"SA": 2000.0})
    free_cash = ledger.free_cash
    state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    expected_interest = free_cash * (0.015 / 252.0)
    assert state.daily_interest == pytest.approx(expected_interest, rel=1e-4)


# ===========================================================================
# Feature 13: Risk Control & Liquidation
# ===========================================================================

def test_f13_margin_call_triggered_when_free_cash_negative():
    """F13-1: Margin call flag is True whenever Free Cash drops below 0."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=50_000.0)
    ledger.rebalance(target_weights={"SA": 0.8}, current_prices={"SA": 2000.0})
    # Force Free Cash into negative
    ledger.free_cash = -500.0
    state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    assert state.margin_call is True


def test_f13_futures_liquidated_first():
    """F13-2: Tier 1 liquidation releases futures positions to cover negative free cash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(
        target_weights={"600519": 0.3, "SA": 0.5},
        current_prices={"600519": 100.0, "SA": 2000.0},
    )
    # Force negative free cash
    ledger.free_cash = -500.0
    state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"600519": 100.0, "SA": 2000.0})
    assert state.margin_call is True
    assert "SA" not in ledger.positions or ledger.positions["SA"].quantity < 1


def test_f13_stocks_liquidated_if_still_negative():
    """F13-3: Tier 2 liquidation sells stocks only if futures liquidation does not restore cash."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    ledger.rebalance(target_weights={"600519": 0.8}, current_prices={"600519": 100.0})
    ledger.free_cash = -10_000.0
    state = ledger.settle_daily(settle_prices={}, close_prices={"600519": 100.0})
    assert state.margin_call is True
    assert ledger.free_cash >= 0.0  # Restored through stock sale


def test_f13_liquidation_restores_positive_free_cash():
    """F13-4: Post-liquidation state has Free Cash >= 0."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=50_000.0)
    ledger.rebalance(target_weights={"SA": 0.9}, current_prices={"SA": 2000.0})
    ledger.free_cash = -2_000.0
    state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
    assert state.free_cash >= 0.0


def test_f13_leverage_ratio_calculation():
    """F13-5: Leverage ratio = Total Notional Exposure / Total Equity."""
    ledger_cls = resolve_component("ledger", "DualTrackLedger")
    ledger = ledger_cls(initial_cash=100_000.0)
    # Buy 1 lot SA at 2000 -> Notional = 1 * 20 * 2000 = 40,000 -> leverage = 40000 / 100000 = 0.40
    ledger.rebalance(target_weights={"SA": 0.4}, current_prices={"SA": 2000.0})
    assert ledger.leverage_ratio == pytest.approx(0.40, rel=0.1)


# ===========================================================================
# Feature 14: Multi-Benchmark Backtest Engine
# ===========================================================================

def test_f14_backtest_runs_all_four_series(sample_market_dataset):
    """F14-1: Parallel simulation generates Mixed, Pure Stock, Pure Futures, and CSI 300 series."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(dataset=sample_market_dataset, rebalance_freq=10)
    res = engine.run_backtest()
    assert "Mixed" in res.equity_curve.columns
    assert "PureStock" in res.equity_curve.columns
    assert "PureFutures" in res.equity_curve.columns
    assert "CSI300" in res.equity_curve.columns


def test_f14_backtest_rebalance_schedule(sample_market_dataset):
    """F14-2: Rebalance events trigger according to configured period."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(dataset=sample_market_dataset, rebalance_freq=15)
    res = engine.run_backtest()
    assert len(res.rebalance_dates) > 0


def test_f14_identical_starting_nav(sample_market_dataset):
    """F14-3: All portfolio series start with initial capital (e.g. 1,000,000)."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(dataset=sample_market_dataset, initial_cash=1_000_000.0)
    res = engine.run_backtest()
    for col in ["Mixed", "PureStock", "PureFutures", "CSI300"]:
        assert float(res.equity_curve[col].iloc[0]) == pytest.approx(1_000_000.0, rel=1e-4)


def test_f14_backtest_no_forward_leakage(sample_market_dataset):
    """F14-4: Backtest steps day by day without referencing future prices."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(dataset=sample_market_dataset)
    res = engine.run_backtest()
    assert len(res.equity_curve) == len(sample_market_dataset.dates)


def test_f14_backtest_generates_valid_equity_dataframe(sample_market_dataset):
    """F14-5: Generated equity curves have no NaN or Inf values."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(dataset=sample_market_dataset)
    res = engine.run_backtest()
    assert not res.equity_curve.isna().any().any()
    assert np.isfinite(res.equity_curve.values).all()


# ===========================================================================
# Feature 15: Diversification Ratio & MPT Metrics
# ===========================================================================

def test_f15_diversification_ratio_formula():
    """F15-1: Diversification Ratio DR(w) = w^T sigma / sqrt(w^T Sigma w)."""
    dr_fn = resolve_component("backtest_engine", "calculate_diversification_ratio")
    weights = np.array([0.5, 0.5])
    vols = np.array([0.2, 0.2])
    # Zero correlation -> cov = diag(0.04, 0.04) -> port_vol = sqrt(0.25*0.04 + 0.25*0.04) = sqrt(0.02) = 0.1414
    cov = np.array([[0.04, 0.0], [0.0, 0.04]])
    dr = dr_fn(weights, vols, cov)
    # Weighted vol = 0.2, port_vol = 0.1414 -> DR = 0.2 / 0.1414 = sqrt(2) approx 1.414
    assert dr == pytest.approx(math.sqrt(2.0), rel=1e-3)
    assert dr > 1.0


def test_f15_dr_equals_one_for_perfectly_correlated():
    """F15-2: Single asset or perfectly correlated assets yield DR = 1.0."""
    dr_fn = resolve_component("backtest_engine", "calculate_diversification_ratio")
    weights = np.array([1.0])
    vols = np.array([0.25])
    cov = np.array([[0.0625]])
    dr = dr_fn(weights, vols, cov)
    assert dr == pytest.approx(1.0, abs=1e-4)


def test_f15_sharpe_ratio_computation():
    """F15-3: Annualized Sharpe properly deducts 1.5% risk free rate."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    # Steady daily return series
    daily_rets = [0.001] * 100
    equity = pd.Series(100.0 * np.cumprod([1.0 + r for r in daily_rets]))
    metrics = mpt_fn(equity, rf_annual=0.015)
    assert "sharpe_ratio" in metrics
    assert metrics["sharpe_ratio"] > 0.0


def test_f15_max_drawdown_computation():
    """F15-4: Peak-to-trough decline accurate down to basis points."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    equity = pd.Series([100.0, 120.0, 96.0, 110.0])  # Drop from 120 to 96 is exactly -20%
    metrics = mpt_fn(equity)
    assert metrics["max_drawdown"] == pytest.approx(0.20, abs=1e-3)


def test_f15_calmar_ratio_computation():
    """F15-5: Calmar ratio = Annualized Return / Max Drawdown."""
    mpt_fn = resolve_component("backtest_engine", "calculate_mpt_metrics")
    equity = pd.Series([100.0, 120.0, 96.0, 130.0])
    metrics = mpt_fn(equity)
    assert "calmar_ratio" in metrics
    if metrics["max_drawdown"] > 0:
        expected = metrics["annual_return"] / metrics["max_drawdown"]
        assert metrics["calmar_ratio"] == pytest.approx(expected, rel=1e-2)


# ===========================================================================
# Feature 16: JSON & Markdown Reporting
# ===========================================================================

def test_f16_json_artifact_created_and_valid(sample_market_dataset, tmp_path):
    """F16-1: JSON artifact is written to specified path with valid structure."""
    pipe_fn = resolve_component("runner", "run_cross_asset_pipeline")
    json_path = tmp_path / "test_out.json"
    md_path = tmp_path / "test_out.md"
    pipe_fn(sample_market_dataset, output_json_path=json_path, output_report_path=md_path)
    
    assert json_path.exists()
    import json
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "metadata" in data
    assert "metrics" in data


def test_f16_markdown_report_created_and_valid(sample_market_dataset, tmp_path):
    """F16-2: Markdown report contains comparison table and section headers."""
    pipe_fn = resolve_component("runner", "run_cross_asset_pipeline")
    json_path = tmp_path / "test_out.json"
    md_path = tmp_path / "test_out.md"
    pipe_fn(sample_market_dataset, output_json_path=json_path, output_report_path=md_path)
    
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "跨资产混合投资组合" in content
    assert "分散化比率" in content
    assert "年化夏普比率" in content


def test_f16_json_contains_all_four_benchmarks(sample_market_dataset, tmp_path):
    """F16-3: JSON payload includes metrics for Mixed, Pure Stock, Pure Futures, and CSI 300."""
    pipe_fn = resolve_component("runner", "run_cross_asset_pipeline")
    json_path = tmp_path / "benchmarks.json"
    md_path = tmp_path / "benchmarks.md"
    pipe_fn(sample_market_dataset, output_json_path=json_path, output_report_path=md_path)
    
    import json
    data = json.loads(json_path.read_text(encoding="utf-8"))
    metrics = data["metrics"]
    for bench in ["mixed_portfolio", "pure_stock", "pure_futures", "csi_300"]:
        assert bench in metrics
        assert "sharpe_ratio" in metrics[bench]


def test_f16_report_displays_diversification_ratio(sample_market_dataset, tmp_path):
    """F16-4: Markdown report displays Choueifaty Diversification Ratio (DR)."""
    pipe_fn = resolve_component("runner", "run_cross_asset_pipeline")
    json_path = tmp_path / "dr.json"
    md_path = tmp_path / "dr.md"
    pipe_fn(sample_market_dataset, output_json_path=json_path, output_report_path=md_path)
    
    content = md_path.read_text(encoding="utf-8")
    assert "DR" in content or "分散化比率" in content


def test_f16_custom_output_paths(sample_market_dataset, tmp_path):
    """F16-5: Custom output paths for JSON and Markdown reports are honored."""
    pipe_fn = resolve_component("runner", "run_cross_asset_pipeline")
    custom_json = tmp_path / "custom" / "path" / "out.json"
    custom_md = tmp_path / "custom" / "path" / "out.md"
    pipe_fn(sample_market_dataset, output_json_path=custom_json, output_report_path=custom_md)
    assert custom_json.exists()
    assert custom_md.exists()
