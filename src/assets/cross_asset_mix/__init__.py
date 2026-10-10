"""Cross-Asset Mixed Portfolio Package.

Provides contract definitions, data homogenization, ticker feeds, cross-asset momentum ranking,
dual-track margin accounting, and backtesting for equities and commodity futures.
"""

from .contracts import (
    AssetPosition,
    AssetType,
    CONTRACT_SPECS,
    ContractSpec,
    FuturesExchange,
    OrderSide,
    OrderType,
    SPEC_AU,
    SPEC_FG,
    SPEC_SA,
    TradeOrder,
    calculate_margin_requirement,
    calculate_notional_value,
    get_contract_spec,
    get_stock_contract_spec,
    round_to_lot_size,
)
from .data_loader import (
    AlignedDataset,
    DataLoader,
    load_aligned_market_data,
)
from .ranking import (
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
from .ledger import (
    DailyLedgerState,
    DualTrackLedger,
    Position,
    TradeRecord,
)
from .backtest_engine import (
    BacktestConfig,
    BacktestResult,
    CrossAssetBacktestEngine,
    calculate_diversification_ratio,
    calculate_mpt_metrics,
    export_backtest_json,
    generate_markdown_report,
    run_cross_asset_pipeline,
)


def run_cli() -> None:
    """Lazy wrapper for runner CLI main entrypoint."""
    from .runner import main
    main()


__all__ = [
    # Contracts & specs
    "AssetPosition",
    "AssetType",
    "CONTRACT_SPECS",
    "ContractSpec",
    "FuturesExchange",
    "OrderSide",
    "OrderType",
    "SPEC_AU",
    "SPEC_FG",
    "SPEC_SA",
    "TradeOrder",
    "calculate_margin_requirement",
    "calculate_notional_value",
    "get_contract_spec",
    "get_stock_contract_spec",
    "round_to_lot_size",
    # Data feeds & homogenization
    "AlignedDataset",
    "DataLoader",
    "load_aligned_market_data",
    # Ranking & Top-K selection
    "CrossAssetRanker",
    "RankItem",
    "RankResult",
    "calc_compounded_momentum",
    "calc_inverse_volatility",
    "calc_trend_strength_ctsi",
    "calculate_compounded_20d_momentum",
    "calculate_ctsi",
    "calculate_inverse_volatility",
    "compute_cross_asset_percentile_rank",
    "rank_cross_asset_universe",
    "select_top_k",
    # Dual-track ledger & accounting
    "DailyLedgerState",
    "DualTrackLedger",
    "Position",
    "TradeRecord",
    # Backtest engine & reporting
    "BacktestConfig",
    "BacktestResult",
    "CrossAssetBacktestEngine",
    "calculate_diversification_ratio",
    "calculate_mpt_metrics",
    "export_backtest_json",
    "generate_markdown_report",
    "run_cross_asset_pipeline",
    "run_cli",
]
