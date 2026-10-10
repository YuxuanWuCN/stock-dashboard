"""Standalone CLI runner for Cross-Asset Mixed Portfolio Backtest & Artifact Generation.

Executes DataLoader, CrossAssetBacktestEngine, and writes production artifacts:
1. docs/data/paper/backtest_cross_asset_mix.json
2. reports/tables/backtest_cross_asset_mix_report.md
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

from .backtest_engine import (
    BacktestConfig,
    BacktestResult,
    CrossAssetBacktestEngine,
    export_backtest_json,
    generate_markdown_report,
    run_cross_asset_pipeline,
)
from .data_loader import AlignedDataset, DataLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """CLI Entry point for Cross-Asset Mixed Portfolio Backtest Runner."""
    print("=" * 70)
    print("Cross-Asset Mixed Portfolio: Milestone 4 Production Backtest Runner")
    print("=" * 70)

    # 1. Resolve project paths
    rainbow_root = Path(__file__).resolve().parents[3]
    default_json_path = rainbow_root / "docs" / "data" / "paper" / "backtest_cross_asset_mix.json"
    default_report_path = rainbow_root / "reports" / "tables" / "backtest_cross_asset_mix_report.md"

    # Ensure parent directories exist
    default_json_path.parent.mkdir(parents=True, exist_ok=True)
    default_report_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. Load aligned market data
    logger.info("Loading aligned cross-asset market data (202 stocks + 12 commodity futures)...")
    dl = DataLoader(rainbow_root=rainbow_root)
    dataset = dl.load_aligned_market_data(include_extended_futures=True)
    logger.info("Loaded %d trading days across %d assets.", len(dataset.dates), len(dataset.symbols))

    # 3. Configure backtest engine (Dual-Sleeve Cross-Asset Allocation)
    config = BacktestConfig(
        initial_cash=10_000_000.0,
        rebalance_freq=10,
        top_k=10,
        rf_annual=0.015,
        deadband=0.01,
        enable_fees=False,
        allocation_mode="dual_sleeve",
        stock_sleeve_weight=0.50,
        futures_sleeve_weight=0.50,
        stock_top_k=5,
        futures_top_k=3,
        include_extended_futures=True,
        enable_futures_short=True,
        futures_short_k=2,
        futures_overlay_ratio=1.5,
        enable_regime_filter=True,
        regime_bear_stock_weight=0.0,
    )

    # 4. Execute backtest pipeline
    logger.info("Running 4-benchmark parallel backtest simulation...")
    result = run_cross_asset_pipeline(
        dataset=dataset,
        output_json_path=default_json_path,
        output_report_path=default_report_path,
        config=config,
    )

    # 5. Verify generated artifacts
    if not default_json_path.exists() or default_json_path.stat().st_size == 0:
        raise RuntimeError(f"Failed to generate JSON artifact at: {default_json_path}")
    if not default_report_path.exists() or default_report_path.stat().st_size == 0:
        raise RuntimeError(f"Failed to generate Markdown report at: {default_report_path}")

    logger.info("Successfully generated JSON artifact: %s (%d bytes)", default_json_path, default_json_path.stat().st_size)
    logger.info("Successfully generated Markdown report: %s (%d bytes)", default_report_path, default_report_path.stat().st_size)
    logger.info(
        "Mixed Portfolio Sharpe: %.2f | Calmar: %.2f | DR: %.4f",
        result.mixed_portfolio.get("sharpe_ratio", 0.0),
        result.mixed_portfolio.get("calmar_ratio", 0.0),
        result.diversification_ratio,
    )
    print("=" * 70)
    print("Backtest simulation completed successfully.")
    print("=" * 70)


if __name__ == "__main__":
    main()
