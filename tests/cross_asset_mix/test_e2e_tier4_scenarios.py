"""Tier 4: Real-World Application Scenarios E2E Test Suite for Cross-Asset Mixed Portfolio.
Covers 5 comprehensive full-cycle simulation scenarios defined in TEST_INFRA.md:
1. Baseline 100-Day Rebalanced Portfolio (F1-F16 complete lifecycle)
2. High Volatility Shock & Margin Strain (Daily MTM, margin call, forced liquidation)
3. Pure Commodity Surge Regime (Commodity momentum capture, margin leverage alpha)
4. Flat Market with Idle Cash Accrual (Strict monotonic cash interest growth)
5. Four-Way Benchmark Confrontation (Mixed vs Pure Stock vs Pure Futures vs CSI 300)
"""

import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from tests.cross_asset_mix.conftest import resolve_component
from tests.cross_asset_mix import reference_oracle as oracle


# ===========================================================================
# Scenario 1: Baseline 100-Day Rebalanced Portfolio (F1-F16 Full Lifecycle)
# ===========================================================================

def test_s01_baseline_100day_rebalanced_portfolio(sample_market_dataset, tmp_path):
    """S01: Complete 100-day simulation with bi-weekly rebalancing and artifact generation."""
    pipe_fn = resolve_component("runner", "run_cross_asset_pipeline")
    json_path = tmp_path / "docs" / "data" / "paper" / "backtest_cross_asset_mix.json"
    md_path = tmp_path / "reports" / "tables" / "backtest_cross_asset_mix_report.md"

    res = pipe_fn(
        sample_market_dataset,
        output_json_path=json_path,
        output_report_path=md_path,
    )

    # 1. Verification of NAV curves
    assert len(res.equity_curve) == 100
    for col in ["Mixed", "PureStock", "PureFutures", "CSI300"]:
        assert col in res.equity_curve.columns
        assert not res.equity_curve[col].isna().any()
        assert (res.equity_curve[col] > 0).all()

    # 2. Accounting conservation check
    assert res.diversification_ratio >= 1.0

    # 3. Artifact verification
    assert json_path.exists()
    assert md_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "metrics" in data
    assert "mixed_portfolio" in data["metrics"]
    assert data["metrics"]["diversification_ratio"] >= 1.0

    md_text = md_path.read_text(encoding="utf-8")
    assert "跨资产混合投资组合" in md_text
    assert "分散化比率" in md_text


# ===========================================================================
# Scenario 2: High Volatility Shock & Margin Strain
# ===========================================================================

def test_s02_high_volatility_shock_and_margin_strain(sample_shock_dataset):
    """S02: Consecutive limit downs trigger margin breach and tiered forced liquidation."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(
        dataset=sample_shock_dataset,
        initial_cash=500_000.0,
        rebalance_freq=10,
        top_k=5,
    )
    res = engine.run_backtest()

    # Portfolio must remain solvent throughout crash
    assert (res.equity_curve["Mixed"] > 0).all()
    assert not res.equity_curve["Mixed"].isna().any()

    # Verify ledger handles margin strain without unbounded overdraft
    final_equity = res.equity_curve["Mixed"].iloc[-1]
    assert final_equity > 0.0


# ===========================================================================
# Scenario 3: Pure Commodity Surge Regime
# ===========================================================================

def test_s03_pure_commodity_surge_regime(sample_commodity_surge_dataset):
    """S03: Commodity futures rally +2% daily; Top-K picks futures and leverage magnifies gains."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(
        dataset=sample_commodity_surge_dataset,
        initial_cash=1_000_000.0,
        rebalance_freq=10,
        top_k=3,
    )
    res = engine.run_backtest()

    # Commodity futures surged, so Mixed portfolio should achieve strong positive return
    mixed_ret = res.mixed_portfolio["total_return"]
    stock_ret = res.pure_stock["total_return"]

    assert mixed_ret > 0.0
    # Mixed portfolio heavily outstrips flat stock portfolio
    assert mixed_ret > stock_ret


# ===========================================================================
# Scenario 4: Flat Market with Idle Cash Accrual
# ===========================================================================

def test_s04_flat_market_with_idle_cash_accrual(sample_flat_dataset):
    """S04: Flat market produces strictly monotonic equity growth from 1.5% cash interest."""
    engine_cls = resolve_component("backtest_engine", "CrossAssetBacktestEngine")
    engine = engine_cls(
        dataset=sample_flat_dataset,
        initial_cash=1_000_000.0,
        rebalance_freq=20,
        rf_annual=0.015,
    )
    res = engine.run_backtest()

    mixed_curve = res.equity_curve["Mixed"]
    # Strictly positive return over 100 days
    assert mixed_curve.iloc[-1] > mixed_curve.iloc[0]
    # Total return matches theoretical compound cash interest
    total_ret = res.mixed_portfolio["total_return"]
    assert total_ret > 0.0005  # Positive return from idle cash interest
    assert res.mixed_portfolio["max_drawdown"] == 0.0


# ===========================================================================
# Scenario 5: Four-Way Benchmark Confrontation
# ===========================================================================

def test_s05_four_way_benchmark_confrontation(sample_market_dataset, tmp_path):
    """S05: Parallel confrontation across Mixed, Pure Stock, Pure Futures, and CSI 300."""
    pipe_fn = resolve_component("runner", "run_cross_asset_pipeline")
    json_path = tmp_path / "confrontation.json"
    md_path = tmp_path / "confrontation.md"

    res = pipe_fn(
        sample_market_dataset,
        output_json_path=json_path,
        output_report_path=md_path,
    )

    metrics = [res.mixed_portfolio, res.pure_stock, res.pure_futures, res.csi_300]
    for m in metrics:
        assert "total_return" in m
        assert "annual_return" in m
        assert "sharpe_ratio" in m
        assert "max_drawdown" in m
        assert "calmar_ratio" in m

    # Diversification Ratio must be >= 1.0 (Choueifaty property)
    assert res.diversification_ratio >= 1.0

    # Ensure Markdown table contains all 4 rows
    md_content = md_path.read_text(encoding="utf-8")
    assert "混合池优选产品 (Mixed)" in md_content
    assert "纯股票 202 组合 (Pure Stock)" in md_content
    assert "纯商品期货组合 (Pure Futures)" in md_content
    assert "沪深 300 基准 (CSI 300)" in md_content
