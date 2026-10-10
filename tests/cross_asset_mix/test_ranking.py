"""Unit tests for Milestone 2: Cross-Asset Momentum & Risk Ranking Engine.

Validates:
- 20-day Compounded Geometric Momentum
- Inverse Volatility with Anti-Overflow Floor (sigma_floor = 0.08)
- Composite Trend Strength Indicator (CTSI)
- Empirical Percentile Ranking Non-Parametric Mapping [0, 100]
- Top-K Selection and Weight Normalization (inverse-vol & equal)
- CrossAssetRanker with heterogeneous asset universes (equities + commodity futures)
- Boundary and starvation scenarios
"""

import math
import numpy as np
import pandas as pd
import pytest

from src.assets.cross_asset_mix.ranking import (
    CrossAssetRanker,
    RankItem,
    RankResult,
    calc_compounded_momentum,
    calc_inverse_volatility,
    calc_trend_strength_ctsi,
    calculate_compounded_20d_momentum,
    calculate_ctsi,
    calculate_inverse_volatility,
    compute_cross_asset_percentile_rank,
    rank_cross_asset_universe,
    select_top_k,
)
from src.assets.cross_asset_mix.data_loader import AlignedDataset


# ===========================================================================
# 1. Compounded Geometric Momentum Tests
# ===========================================================================

def test_compounded_momentum_scalar_positive():
    """Validates compounding formula prod(1 + r) - 1 on scalar series."""
    returns = [0.01] * 20
    score = calc_compounded_momentum(returns, window=20)
    expected = (1.01 ** 20) - 1.0
    assert score == pytest.approx(expected, rel=1e-5)


def test_compounded_momentum_scalar_negative():
    """20 days of -2% return compounds geometrically to ~ -33.24%."""
    returns = [-0.02] * 20
    score = calc_compounded_momentum(returns, window=20)
    expected = (0.98 ** 20) - 1.0
    assert score == pytest.approx(expected, rel=1e-5)


def test_compounded_momentum_zero_flat():
    """Flat returns produce exactly 0.0 momentum."""
    returns = [0.0] * 20
    assert calc_compounded_momentum(returns, window=20) == pytest.approx(0.0, abs=1e-9)


def test_compounded_momentum_volatility_drag():
    """Alternating +3% and -3% return demonstrates volatility drag (prod < 1.0)."""
    returns = [0.03, -0.03] * 10
    score = calc_compounded_momentum(returns, window=20)
    # (1.03 * 0.97)^10 - 1 = (0.9991)^10 - 1 < 0
    assert score < 0.0
    assert score == pytest.approx((0.9991 ** 10) - 1.0, rel=1e-5)


def test_compounded_momentum_dataframe_rolling():
    """Rolling DataFrame momentum drops earliest day and includes latest day."""
    ret_vals = [0.10] + [0.0] * 19 + [0.05]
    df = pd.DataFrame({"SYM": ret_vals})
    res = calculate_compounded_20d_momentum(df, window=20)
    assert pd.isna(res.iloc[18]["SYM"])
    assert float(res.iloc[19]["SYM"]) == pytest.approx(0.10, rel=1e-5)
    assert float(res.iloc[20]["SYM"]) == pytest.approx(0.05, rel=1e-5)


def test_compounded_momentum_nan_handling():
    """NaN returns in array are treated as 0.0 neutral returns."""
    returns = [0.01] * 10 + [np.nan] * 5 + [0.01] * 5
    score = calc_compounded_momentum(returns, window=20)
    expected = (1.01 ** 15) - 1.0
    assert score == pytest.approx(expected, rel=1e-5)


def test_compounded_momentum_empty_input():
    """Empty returns sequence safely returns 0.0."""
    assert calc_compounded_momentum([], window=20) == 0.0


# ===========================================================================
# 2. Inverse Volatility Tests
# ===========================================================================

def test_inverse_volatility_sample_std_formula():
    """Validates sample std (ddof=1) scaled by sqrt(252)."""
    rng = np.random.default_rng(42)
    daily_rets = rng.normal(0, 0.02, 20)
    iv = calc_inverse_volatility(daily_rets, window=20, floor=0.08, trading_days=252)
    sample_std = float(np.std(daily_rets, ddof=1))
    ann_vol = sample_std * np.sqrt(252.0)
    expected = 1.0 / max(ann_vol, 0.08)
    assert iv == pytest.approx(expected, rel=1e-5)


def test_inverse_volatility_floor_clamp():
    """Flat returns with 0 std clamped by floor 0.08 returning 12.5."""
    returns = [0.0] * 25
    iv = calc_inverse_volatility(returns, window=20, floor=0.08)
    assert iv == pytest.approx(1.0 / 0.08, abs=1e-6)


def test_inverse_volatility_custom_floor():
    """Custom floor parameter 0.05 returns 20.0 on zero-volatility asset."""
    returns = [0.0] * 25
    iv = calc_inverse_volatility(returns, window=20, floor=0.05)
    assert iv == pytest.approx(1.0 / 0.05, abs=1e-6)


def test_inverse_volatility_strictly_positive_finite():
    """Inverse volatility is strictly positive and finite for any input."""
    df = pd.DataFrame({
        "ZERO": [0.0] * 30,
        "LOW": [0.001, -0.001] * 15,
        "HIGH": [0.08, -0.08] * 15,
    })
    res = calculate_inverse_volatility(df, window=20, floor=0.08)
    valid_vals = res.dropna().values
    assert (valid_vals > 0).all()
    assert np.isfinite(valid_vals).all()


def test_inverse_volatility_monotonicity():
    """Lower volatility strictly maps to higher inverse volatility score."""
    low_vol = [0.002, -0.002] * 10
    high_vol = [0.03, -0.03] * 10
    iv_low = calc_inverse_volatility(low_vol, window=20)
    iv_high = calc_inverse_volatility(high_vol, window=20)
    assert iv_low > iv_high


def test_inverse_volatility_short_history_fallback():
    """Insufficient history (<2 observations) safely falls back to floor."""
    assert calc_inverse_volatility([0.01], window=20, floor=0.08) == pytest.approx(1.0 / 0.08)


# ===========================================================================
# 3. Composite Trend Strength Indicator (CTSI) Tests
# ===========================================================================

def test_ctsi_bullish_breakout():
    """Strong uptrend with surging price produces high CTSI (> 0.6)."""
    prices = [100.0] * 20 + [103.0, 107.0, 112.0, 118.0, 125.0]
    score = calc_trend_strength_ctsi(prices, window=20)
    assert score > 0.6


def test_ctsi_bearish_breakdown():
    """Collapsing price below MA20 produces low CTSI (< 0.4)."""
    prices = [100.0] * 20 + [97.0, 93.0, 88.0, 82.0, 75.0]
    score = calc_trend_strength_ctsi(prices, window=20)
    assert score < 0.4


def test_ctsi_sideways_neutral():
    """Oscillating range-bound price yields intermediate score in [0.1, 0.9]."""
    prices = [100.0, 102.0, 98.0, 100.0] * 10
    score = calc_trend_strength_ctsi(prices, window=20)
    assert 0.1 <= score <= 0.9


def test_ctsi_zero_channel_range_finite():
    """Completely constant price produces finite score (channel_pos neutral 0.5)."""
    prices = [50.0] * 30
    df = pd.DataFrame({"PX": prices})
    res = calculate_ctsi(df, window=20)
    score = float(res.iloc[-1]["PX"])
    assert np.isfinite(score)
    # MA div = 0, channel_pos = 0.5, alignment = 0 -> 0.4*0 + 0.4*0.5 + 0.2*0 = 0.20
    assert score == pytest.approx(0.20, abs=1e-4)


def test_ctsi_ma_alignment_positive_contribution():
    """Fast MA5 > MA20 condition gives positive score boost."""
    rising = [10.0 + i * 0.5 for i in range(30)]
    falling = [50.0 - i * 0.5 for i in range(30)]
    score_rising = calc_trend_strength_ctsi(rising, window=20)
    score_falling = calc_trend_strength_ctsi(falling, window=20)
    assert score_rising > score_falling


# ===========================================================================
# 4. Empirical Percentile Ranking Tests
# ===========================================================================

def test_percentile_ranking_bounds():
    """All percentile ranks strictly bounded in [0.0, 100.0]."""
    s = pd.Series([10.0, 50.0, -100.0, 20.0, 999.0, 0.0])
    ranks = compute_cross_asset_percentile_rank(s)
    assert ranks.min() == pytest.approx(0.0)
    assert ranks.max() == pytest.approx(100.0)


def test_percentile_ranking_monotonicity():
    """Percentile ranks are strictly monotonic with respect to input factor scores."""
    s = pd.Series([1.2, 2.5, 3.8, 9.9, 12.0])
    ranks = compute_cross_asset_percentile_rank(s)
    assert ranks.is_monotonic_increasing


def test_percentile_ranking_tie_handling():
    """Tied values receive identical percentile rank."""
    s = pd.Series([5.0, 15.0, 15.0, 25.0])
    ranks = compute_cross_asset_percentile_rank(s)
    assert ranks.iloc[1] == pytest.approx(ranks.iloc[2])
    # Average rank of 2 and 3 is 2.5; (2.5 - 1) / 3 * 100 = 50.0
    assert ranks.iloc[1] == pytest.approx(50.0)


def test_percentile_ranking_single_element():
    """Single element series produces 100.0 without divide-by-zero."""
    s = pd.Series([99.0])
    ranks = compute_cross_asset_percentile_rank(s)
    assert ranks.iloc[0] == 100.0


def test_percentile_ranking_nan_handling():
    """NaNs in series are safely preserved as NaN in percentile output."""
    s = pd.Series({"A": 10.0, "B": np.nan, "C": 20.0})
    ranks = compute_cross_asset_percentile_rank(s)
    assert pd.isna(ranks["B"])
    assert ranks["A"] == pytest.approx(0.0)
    assert ranks["C"] == pytest.approx(100.0)


# ===========================================================================
# 5. Top-K Selection and Weighting Tests
# ===========================================================================

def test_select_top_k_inverse_vol_weighting():
    """Top-K items under inverse_vol weighting have weights summing to 1.0."""
    df = pd.DataFrame([
        {"rank": 1, "symbol": "SA", "name": "纯碱", "asset_type": "FUTURES", "momentum_20d": 0.15, "inv_vol": 5.0, "trend_strength": 0.8, "composite_score": 85.0},
        {"rank": 2, "symbol": "FG", "name": "玻璃", "asset_type": "FUTURES", "momentum_20d": 0.10, "inv_vol": 10.0, "trend_strength": 0.7, "composite_score": 80.0},
        {"rank": 3, "symbol": "600519", "name": "茅台", "asset_type": "STOCK", "momentum_20d": 0.05, "inv_vol": 15.0, "trend_strength": 0.6, "composite_score": 75.0},
        {"rank": 4, "symbol": "000858", "name": "五粮液", "asset_type": "STOCK", "momentum_20d": -0.02, "inv_vol": 12.0, "trend_strength": 0.5, "composite_score": 50.0},
    ])
    items = select_top_k(df, k=3, weighting="inverse_vol")
    assert len(items) == 3
    total_w = sum(it.target_weight for it in items)
    assert total_w == pytest.approx(1.0, rel=1e-3)
    # Higher inv_vol (茅台 15.0) has higher weight than FG (10.0) and SA (5.0)
    w_map = {it.symbol: it.target_weight for it in items}
    assert w_map["600519"] > w_map["FG"] > w_map["SA"]


def test_select_top_k_equal_weighting():
    """Top-K items under equal weighting have 1/K weights summing to 1.0."""
    df = pd.DataFrame([
        {"rank": 1, "symbol": "SA", "name": "纯碱", "asset_type": "FUTURES", "momentum_20d": 0.1, "inv_vol": 5.0, "trend_strength": 0.8, "composite_score": 80.0},
        {"rank": 2, "symbol": "FG", "name": "玻璃", "asset_type": "FUTURES", "momentum_20d": 0.1, "inv_vol": 10.0, "trend_strength": 0.7, "composite_score": 70.0},
        {"rank": 3, "symbol": "AU", "name": "黄金", "asset_type": "FUTURES", "momentum_20d": 0.1, "inv_vol": 15.0, "trend_strength": 0.6, "composite_score": 60.0},
        {"rank": 4, "symbol": "600519", "name": "茅台", "asset_type": "STOCK", "momentum_20d": 0.0, "inv_vol": 12.0, "trend_strength": 0.5, "composite_score": 50.0},
    ])
    items = select_top_k(df, k=3, weighting="equal")
    assert len(items) == 3
    for it in items:
        assert it.target_weight == pytest.approx(1.0 / 3.0, abs=1e-5)


def test_select_top_k_empty_or_zero_k():
    """Empty input DataFrame or k <= 0 returns empty list."""
    assert select_top_k(pd.DataFrame(), k=5) == []
    df = pd.DataFrame([{"rank": 1, "symbol": "SA", "inv_vol": 10.0, "composite_score": 50.0}])
    assert select_top_k(df, k=0) == []


# ===========================================================================
# 6. CrossAssetRanker Engine Tests
# ===========================================================================

@pytest.fixture
def synthetic_mixed_dataset() -> AlignedDataset:
    """Creates a 40-day dataset with 5 stocks and 3 futures."""
    dates = pd.bdate_range("2024-01-02", periods=40)
    stocks = ["600519", "000858", "601318", "000333", "600036"]
    futures = ["SA", "FG", "AU"]
    all_syms = stocks + futures

    rng = np.random.default_rng(100)
    rets_dict = {}
    px_dict = {}
    types = {}

    for sym in all_syms:
        is_fut = sym in futures
        types[sym] = "FUTURES" if is_fut else "STOCK"
        base_px = 2000.0 if sym in ["SA", "FG"] else (500.0 if sym == "AU" else 100.0)
        daily_ret = rng.normal(0.001 if sym == "AU" else 0.0005, 0.015, len(dates))
        rets_dict[sym] = daily_ret
        px_dict[sym] = base_px * np.cumprod(1.0 + daily_ret)

    rets_df = pd.DataFrame(rets_dict, index=dates)
    prices_df = pd.DataFrame(px_dict, index=dates)

    return AlignedDataset(
        dates=dates,
        prices=prices_df,
        returns=rets_df,
        asset_types=types,
        settle_prices=prices_df.copy(),
    )


def test_ranker_mixed_universe_evaluation(synthetic_mixed_dataset):
    """Ranker processes mixed universe and outputs valid RankResult."""
    ranker = CrossAssetRanker(
        dataset=synthetic_mixed_dataset,
        momentum_weight=0.4,
        inv_vol_weight=0.3,
        trend_weight=0.3,
    )
    as_of = str(synthetic_mixed_dataset.dates[-1].date())
    res = ranker.rank_universe(as_of_date=as_of, top_k=5)

    assert isinstance(res, RankResult)
    assert res.as_of_date == as_of
    assert len(res.selected_top_k) == 5
    assert len(res.ranked_df) == 8  # 5 stocks + 3 futures

    # Top-K descending score validation
    scores = [it.composite_score for it in res.selected_top_k]
    assert scores == sorted(scores, reverse=True)

    # Asset types contain both
    types = {it.asset_type for it in res.selected_top_k}
    assert len(types) >= 1

    # Weights sum to 1.0
    total_w = sum(it.target_weight for it in res.selected_top_k)
    assert total_w == pytest.approx(1.0, rel=1e-3)


def test_ranker_history_shorter_than_window_returns_empty(synthetic_mixed_dataset):
    """Evaluating when history < window returns empty RankResult safely."""
    ranker = CrossAssetRanker(dataset=synthetic_mixed_dataset)
    # Day 5 (only 5 days of history, lookback needs 20)
    as_of = str(synthetic_mixed_dataset.dates[4].date())
    res = ranker.rank_universe(as_of_date=as_of, window=20, top_k=5)
    assert len(res.selected_top_k) == 0
    assert res.ranked_df.empty


def test_ranker_universe_smaller_than_top_k():
    """When universe size (2) is less than requested top_k (5), returns all available."""
    dates = pd.bdate_range("2024-01-02", periods=25)
    rets = pd.DataFrame({"SA": [0.01] * 25, "FG": [0.02] * 25}, index=dates)
    px = pd.DataFrame({"SA": [2000.0] * 25, "FG": [1500.0] * 25}, index=dates)
    ds = AlignedDataset(dates, px, rets, {"SA": "FUTURES", "FG": "FUTURES"}, px.copy())

    ranker = CrossAssetRanker(dataset=ds)
    res = ranker.rank_universe(as_of_date=str(dates[-1].date()), top_k=5)
    assert len(res.selected_top_k) == 2
    total_w = sum(it.target_weight for it in res.selected_top_k)
    assert total_w == pytest.approx(1.0, rel=1e-3)


def test_rank_cross_asset_universe_convenience_function(synthetic_mixed_dataset):
    """Validates top-level functional wrapper rank_cross_asset_universe."""
    as_of = str(synthetic_mixed_dataset.dates[-1].date())
    res = rank_cross_asset_universe(
        dataset=synthetic_mixed_dataset,
        as_of_date=as_of,
        window=20,
        top_k=4,
        weighting="equal",
    )
    assert len(res.selected_top_k) == 4
    for it in res.selected_top_k:
        assert it.target_weight == pytest.approx(0.25, abs=1e-5)
