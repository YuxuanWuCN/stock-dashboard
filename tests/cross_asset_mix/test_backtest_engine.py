"""Unit tests for Cross-Asset Mixed Portfolio Backtest Engine and Analytics.

Tests:
1. BacktestConfig dataclass and parameter customization.
2. Modern Portfolio Theory (MPT) metric calculations and boundary guards.
3. Choueifaty & Coignard (2008) Diversification Ratio (DR).
4. Multi-benchmark parallel simulation across 4 tracks.
5. Markdown report generation and JSON artifact export.
6. End-to-end pipeline execution.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.assets.cross_asset_mix.backtest_engine import (
    BacktestConfig,
    BacktestResult,
    CrossAssetBacktestEngine,
    calculate_diversification_ratio,
    calculate_mpt_metrics,
    export_backtest_json,
    generate_markdown_report,
    run_cross_asset_pipeline,
)
from src.assets.cross_asset_mix.data_loader import AlignedDataset


# ===========================================================================
# 1. BacktestConfig Tests
# ===========================================================================

def test_backtest_config_defaults():
    """Verify default parameters for BacktestConfig."""
    cfg = BacktestConfig()
    assert cfg.initial_cash == 10_000_000.0
    assert cfg.rebalance_freq == 10
    assert cfg.top_k == 10
    assert cfg.rf_annual == 0.015
    assert cfg.deadband == 0.01
    assert cfg.enable_fees is False
    assert cfg.start_date == ""
    assert cfg.end_date == ""


def test_backtest_config_custom():
    """Verify custom parameters for BacktestConfig."""
    cfg = BacktestConfig(
        start_date="2024-01-02",
        end_date="2024-06-30",
        initial_cash=5_000_000.0,
        rebalance_freq=5,
        top_k=5,
        rf_annual=0.02,
        deadband=0.02,
        enable_fees=True,
    )
    assert cfg.start_date == "2024-01-02"
    assert cfg.end_date == "2024-06-30"
    assert cfg.initial_cash == 5_000_000.0
    assert cfg.rebalance_freq == 5
    assert cfg.top_k == 5
    assert cfg.rf_annual == 0.02
    assert cfg.deadband == 0.02
    assert cfg.enable_fees is True


# ===========================================================================
# 2. MPT Metrics Tests
# ===========================================================================

def test_mpt_metrics_empty():
    """Empty or None input yields all zero metrics."""
    res_empty = calculate_mpt_metrics(pd.Series([], dtype=float))
    assert res_empty["total_return"] == 0.0
    assert res_empty["sharpe_ratio"] == 0.0
    assert res_empty["max_drawdown"] == 0.0
    assert res_empty["calmar_ratio"] == 0.0

    res_none = calculate_mpt_metrics(None)
    assert res_none["total_return"] == 0.0


def test_mpt_metrics_single_element():
    """Single element series produces 0 return and 0 Sharpe without crashing."""
    res = calculate_mpt_metrics(pd.Series([100.0]))
    assert res["total_return"] == 0.0
    assert res["sharpe_ratio"] == 0.0
    assert res["max_drawdown"] == 0.0


def test_mpt_metrics_standard_equity_curve():
    """Verify standard metrics from known equity values."""
    # Equity curve: 100 -> 120 -> 96 -> 120
    # Peak is 120, trough is 96 -> max drawdown is exactly (120-96)/120 = 0.20
    eq = pd.Series([100.0, 120.0, 96.0, 120.0])
    res = calculate_mpt_metrics(eq, rf_annual=0.015)
    assert res["total_return"] == pytest.approx(0.20, abs=1e-4)
    assert res["max_drawdown"] == pytest.approx(0.20, abs=1e-4)
    assert res["calmar_ratio"] == pytest.approx(res["annual_return"] / 0.20, rel=1e-2)
    assert "annualized_return" in res
    assert "annualized_volatility" in res


def test_mpt_metrics_from_daily_returns():
    """Verify metric computation when passing daily returns explicitly."""
    daily_rets = pd.Series([0.01, -0.005, 0.02, -0.01, 0.015])
    res = calculate_mpt_metrics(daily_rets, is_returns=True)
    assert res["total_return"] > 0.0
    assert res["annual_volatility"] > 0.0
    assert res["win_rate"] == pytest.approx(3.0 / 5.0)


def test_mpt_metrics_flat_equity():
    """Flat equity curve has 0 volatility and 0 Sharpe."""
    eq = pd.Series([100.0] * 50)
    res = calculate_mpt_metrics(eq)
    assert res["total_return"] == 0.0
    assert res["annual_volatility"] == 0.0
    assert res["sharpe_ratio"] == 0.0
    assert res["max_drawdown"] == 0.0


def test_mpt_metrics_strictly_increasing():
    """Strictly increasing curve has 0 drawdown and finite Calmar."""
    eq = pd.Series([100.0 * (1.001 ** i) for i in range(100)])
    res = calculate_mpt_metrics(eq, rf_annual=0.015)
    assert res["total_return"] > 0.0
    assert res["max_drawdown"] == 0.0
    assert np.isfinite(res["calmar_ratio"])
    assert res["sharpe_ratio"] > 0.0


def test_mpt_metrics_losing_portfolio():
    """Consistently losing portfolio produces negative Sharpe and total return."""
    eq = pd.Series([100.0 * (0.995 ** i) for i in range(50)])
    res = calculate_mpt_metrics(eq, rf_annual=0.015)
    assert res["total_return"] < 0.0
    assert res["sharpe_ratio"] < 0.0
    assert res["max_drawdown"] > 0.0


# ===========================================================================
# 3. Diversification Ratio Tests
# ===========================================================================

def test_diversification_ratio_single_asset():
    """Single asset has DR = 1.0."""
    dr = calculate_diversification_ratio([1.0], [0.20], [[0.04]])
    assert dr == pytest.approx(1.0)


def test_diversification_ratio_two_orthogonal_assets():
    """Two uncorrelated equal-weight, equal-vol assets yield DR = sqrt(2)."""
    weights = np.array([0.5, 0.5])
    vols = np.array([0.20, 0.20])
    cov = np.array([[0.04, 0.0], [0.0, 0.04]])
    dr = calculate_diversification_ratio(weights, vols, cov)
    assert dr == pytest.approx(math.sqrt(2.0), rel=1e-3)


def test_diversification_ratio_scalar_portfolio_vol():
    """Passing portfolio volatility directly as scalar."""
    weights = np.array([0.5, 0.5])
    vols = np.array([0.20, 0.20])
    # Weighted vol = 0.20. Given port_vol = 0.10, DR = 2.0
    dr = calculate_diversification_ratio(weights, vols, cov_or_portfolio_vol=0.10)
    assert dr == pytest.approx(2.0)


def test_diversification_ratio_perfect_correlation():
    """Assets with correlation 1.0 yield DR = 1.0."""
    weights = np.array([0.5, 0.5])
    vols = np.array([0.20, 0.20])
    cov = np.array([[0.04, 0.04], [0.04, 0.04]])
    dr = calculate_diversification_ratio(weights, vols, cov)
    assert dr == pytest.approx(1.0, abs=1e-4)


def test_diversification_ratio_empty_guards():
    """Empty inputs yield 1.0."""
    assert calculate_diversification_ratio([], []) == 1.0


# ===========================================================================
# 4. CrossAssetBacktestEngine Simulation Tests
# ===========================================================================

def test_backtest_engine_initialization(sample_market_dataset):
    """Engine initializes correctly with BacktestConfig."""
    cfg = BacktestConfig(initial_cash=5_000_000.0, rebalance_freq=5, top_k=5)
    engine = CrossAssetBacktestEngine(dataset=sample_market_dataset, config=cfg)
    assert engine.config.initial_cash == 5_000_000.0
    assert engine.config.rebalance_freq == 5
    assert engine.config.top_k == 5


def test_backtest_engine_runs_four_tracks(sample_market_dataset):
    """Engine produces valid equity series for all 4 tracks."""
    engine = CrossAssetBacktestEngine(
        dataset=sample_market_dataset,
        initial_cash=1_000_000.0,
        rebalance_freq=10,
        top_k=5,
    )
    res = engine.run()
    assert isinstance(res, BacktestResult)

    # Check 4 tracks in equity curve
    for col in ["Mixed", "PureStock", "PureFutures", "CSI300"]:
        assert col in res.equity_curve.columns
        assert len(res.equity_curve[col]) == len(sample_market_dataset.dates)
        assert not res.equity_curve[col].isna().any()
        assert (res.equity_curve[col] > 0).all()

    # Initial equity matches config (within 1 day interest accrual)
    assert float(res.equity_curve["Mixed"].iloc[0]) == pytest.approx(1_000_000.0, rel=1e-4)
    assert float(res.equity_curve["CSI300"].iloc[0]) == pytest.approx(1_000_000.0, rel=1e-4)

    # Rebalance dates recorded
    assert len(res.rebalance_dates) > 0

    # DR >= 1.0
    assert res.diversification_ratio >= 1.0

    # Accounting trajectories recorded
    assert res.accounting_trajectories is not None
    assert "cash" in res.accounting_trajectories
    assert "free_cash" in res.accounting_trajectories
    assert "margin_locked" in res.accounting_trajectories
    assert "stock_value" in res.accounting_trajectories


def test_backtest_engine_date_filtering(sample_market_dataset):
    """Start date and end date filtering works properly."""
    dates = sample_market_dataset.dates
    sub_start = str(dates[10].date())
    sub_end = str(dates[40].date())

    cfg = BacktestConfig(start_date=sub_start, end_date=sub_end, initial_cash=1_000_000.0)
    engine = CrossAssetBacktestEngine(dataset=sample_market_dataset, config=cfg)
    res = engine.run_backtest()

    assert len(res.equity_curve) == 31
    assert str(res.equity_curve.index[0].date()) == sub_start
    assert str(res.equity_curve.index[-1].date()) == sub_end


# ===========================================================================
# 5. Reporting and Artifact Export Tests
# ===========================================================================

def test_generate_markdown_report(sample_market_dataset):
    """Markdown report contains required benchmark rows and sections."""
    engine = CrossAssetBacktestEngine(dataset=sample_market_dataset, initial_cash=1_000_000.0)
    res = engine.run()
    md = generate_markdown_report(res)

    assert "# 跨资产混合投资组合 (Cross-Asset Mixed Portfolio) 回测报告" in md
    assert "混合池优选产品 (Mixed)" in md
    assert "纯股票 202 组合 (Pure Stock)" in md
    assert "纯商品期货组合 (Pure Futures)" in md
    assert "沪深 300 基准 (CSI 300)" in md
    assert "分散化增益 (Diversification Gain)" in md
    assert "DR" in md or "分散化比率" in md


def test_export_backtest_json(sample_market_dataset, tmp_path):
    """JSON artifact export has valid structure and schema."""
    engine = CrossAssetBacktestEngine(dataset=sample_market_dataset, initial_cash=1_000_000.0)
    res = engine.run()
    json_path = tmp_path / "test_artifact.json"

    export_backtest_json(res, json_path, dataset=sample_market_dataset)
    assert json_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "metadata" in data
    assert "metrics" in data
    assert "nav_summary" in data
    assert "accounting_trajectories" in data

    metrics = data["metrics"]
    for bench in ["mixed_portfolio", "pure_stock", "pure_futures", "csi_300"]:
        assert bench in metrics
        assert "sharpe_ratio" in metrics[bench]
        assert "total_return" in metrics[bench]
        assert "max_drawdown" in metrics[bench]

    assert metrics["diversification_ratio"] >= 1.0


def test_run_cross_asset_pipeline(sample_market_dataset, tmp_path):
    """Complete pipeline writes both JSON and Markdown files."""
    json_out = tmp_path / "paper" / "test_backtest.json"
    md_out = tmp_path / "tables" / "test_report.md"

    cfg = BacktestConfig(initial_cash=2_000_000.0, rebalance_freq=10, top_k=5)
    res = run_cross_asset_pipeline(
        dataset=sample_market_dataset,
        output_json_path=json_out,
        output_report_path=md_out,
        config=cfg,
    )

    assert json_out.exists()
    assert md_out.exists()
    assert json_out.stat().st_size > 0
    assert md_out.stat().st_size > 0
    assert res.diversification_ratio >= 1.0
