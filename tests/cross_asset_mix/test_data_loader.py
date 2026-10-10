"""Unit tests for Cross-Asset Data Homogenization & Ticker Feeds Engine."""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path

from src.assets.cross_asset_mix.contracts import AssetType, ContractSpec
from src.assets.cross_asset_mix.data_loader import (
    AlignedDataset,
    DataLoader,
    load_aligned_market_data,
)


@pytest.fixture
def data_loader() -> DataLoader:
    """Fixture providing a configured DataLoader."""
    return DataLoader()


class TestDataLoading:
    """Test raw data ingestion from CSV sources."""

    def test_load_stock_data_success(self, data_loader: DataLoader):
        stocks_df, benchmark = data_loader.load_stock_data()
        assert not stocks_df.empty
        assert len(stocks_df.columns) == 202
        assert len(stocks_df) == 99
        assert isinstance(stocks_df.index, pd.DatetimeIndex)
        assert stocks_df.isna().sum().sum() == 0

        assert not benchmark.empty
        assert len(benchmark) == 99
        assert benchmark.name == "000300.SH"
        assert benchmark.isna().sum() == 0

    def test_load_stock_metadata(self, data_loader: DataLoader):
        meta = data_loader.load_stock_metadata()
        assert not meta.empty
        assert "code" in meta.columns
        assert "name" in meta.columns
        assert "sector" in meta.columns
        assert len(meta) >= 202

    def test_load_czce_futures(self, data_loader: DataLoader):
        sa_df = data_loader.load_czce_futures("SA")
        assert not sa_df.empty
        assert len(sa_df) > 1000
        for col in ["open", "high", "low", "close", "volume", "open_interest", "settle"]:
            assert col in sa_df.columns
        assert isinstance(sa_df.index, pd.DatetimeIndex)

        fg_df = data_loader.load_czce_futures("FG")
        assert not fg_df.empty
        assert len(fg_df) > 2000

        with pytest.raises(ValueError, match="Unsupported CZCE symbol"):
            data_loader.load_czce_futures("INVALID_SYM")

    def test_load_shfe_au(self, data_loader: DataLoader):
        au_df = data_loader.load_shfe_au()
        assert not au_df.empty
        assert len(au_df) > 3000
        assert "close" in au_df.columns
        assert "settle" in au_df.columns
        assert (au_df["close"] > 0).all()


class TestRolloverGapAdjustment:
    """Test mathematical precision and logic of rollover gap elimination."""

    def test_synthetic_rollover_gap_elimination(self):
        """Construct synthetic continuous contract with a 10% rollover basis jump."""
        dates = pd.date_range("2026-01-01", periods=10, freq="B")
        # Days 0-4: contract C1 trading around 1000
        # Day 5: Rollover to contract C2! Open jumps to 1100 (+10%), Close is 1105
        # Days 6-9: contract C2 trading around 1105
        opens = [1000, 1002, 1005, 1008, 1010, 1100, 1105, 1108, 1110, 1112]
        closes = [1002, 1005, 1008, 1010, 1012, 1105, 1108, 1110, 1112, 1115]
        settles = closes.copy()
        oi = [10000, 9500, 9000, 8500, 8000, 15000, 16000, 16500, 17000, 17500]

        df = pd.DataFrame(
            {
                "open": opens,
                "high": [max(o, c) + 2 for o, c in zip(opens, closes)],
                "low": [min(o, c) - 2 for o, c in zip(opens, closes)],
                "close": closes,
                "volume": 5000,
                "open_interest": oi,
                "settle": settles,
            },
            index=dates,
        )

        adj_ret, adj_close, adj_settle, is_roll = DataLoader.adjust_rollover_gap(
            df, gap_threshold=0.05
        )

        # Day 5 must be detected as roll day
        assert is_roll.iloc[5] == True
        assert is_roll.sum() == 1

        # Naive raw return on Day 5 would be (1105 - 1012) / 1012 = +9.189%
        naive_ret = (df["close"].iloc[5] - df["close"].iloc[4]) / df["close"].iloc[4]
        assert naive_ret > 0.09

        # Adjusted return on Day 5 must be the intraday return: (1105 - 1100) / 1100 = +0.4545%
        expected_adj_ret = (1105.0 - 1100.0) / 1100.0
        assert pytest.approx(adj_ret.iloc[5], rel=1e-5) == expected_adj_ret

        # Verify mathematical identity of backward-adjusted prices
        # (adj_close[t] - adj_close[t-1]) / adj_close[t-1] == adj_ret[t]
        recomputed_ret = adj_close.pct_change().fillna(0.0)
        np.testing.assert_allclose(recomputed_ret.values[1:], adj_ret.values[1:], rtol=1e-10)

    def test_real_futures_rollover_adjustment(self, data_loader: DataLoader):
        sa_df = data_loader.load_czce_futures("SA")
        adj_ret, adj_close, adj_settle, is_roll = DataLoader.adjust_rollover_gap(sa_df)

        # Verify rolls were detected across CZCE SA history (01, 05, 09 cycle)
        assert is_roll.sum() >= 10
        # Verify no NaN or negative prices
        assert (adj_close > 0).all()
        assert not adj_close.isna().any()
        assert not adj_ret.isna().any()

        # Verify mathematical identity across 1,600+ days
        recomputed = adj_close.pct_change().fillna(0.0)
        diff = (recomputed - adj_ret).abs().max()
        assert diff < 1e-12


class TestCalendarAlignment:
    """Test cross-market trading day synchronization and zero lookahead bias."""

    def test_align_market_data_basic(self, data_loader: DataLoader):
        dataset = data_loader.load_aligned_market_data()

        # Dimension checks: 99 trading days, 202 stocks + 3 futures = 205 assets
        assert len(dataset.dates) == 99
        assert dataset.prices.shape == (99, 205)
        assert dataset.returns.shape == (99, 205)
        assert dataset.settle_prices.shape == (99, 205)

        # Check asset types
        assert len(dataset.stock_symbols) == 202
        assert dataset.futures_symbols == ["SA", "FG", "AU"]
        for sym in ["SA", "FG", "AU"]:
            assert dataset.get_asset_type(sym) == AssetType.FUTURES.value
        assert dataset.get_asset_type("300750") == AssetType.STOCK.value

        # Zero NaNs anywhere
        assert dataset.prices.isna().sum().sum() == 0
        assert dataset.returns.isna().sum().sum() == 0
        assert dataset.settle_prices.isna().sum().sum() == 0

    def test_suspension_and_holiday_return_is_zero(self, data_loader: DataLoader):
        """Verify non-trading days for futures have return=0 and forward-filled prices."""
        dataset = data_loader.load_aligned_market_data()

        # Dates where futures exchange was closed (May Day holiday: 2026-05-01, 05-04, 05-05)
        holiday_dates = [pd.to_datetime("2026-05-01"), pd.to_datetime("2026-05-04"), pd.to_datetime("2026-05-05")]
        for h_date in holiday_dates:
            if h_date in dataset.dates:
                for fut in ["SA", "FG", "AU"]:
                    # Return on missing/holiday days must be strictly 0.0
                    assert dataset.returns.loc[h_date, fut] == 0.0

        # Day 0 return must be 0.0 for all assets
        assert (dataset.returns.iloc[0] == 0.0).all()

    def test_no_lookahead_bias(self, data_loader: DataLoader):
        """Ensure prices and returns on day t depend only on information up to day t."""
        dataset_full = data_loader.load_aligned_market_data()

        # Sub-period up to index 50
        cut_date = dataset_full.dates[50].strftime("%Y-%m-%d")
        dataset_sub = data_loader.load_aligned_market_data(end_date=cut_date)

        # The historical price and return series on the sub-period must be identical or monotonic
        assert len(dataset_sub.dates) == 51
        # Check stock price identity
        stock_sample = dataset_full.stock_symbols[0]
        np.testing.assert_allclose(
            dataset_full.prices.loc[dataset_sub.dates, stock_sample].values,
            dataset_sub.prices[stock_sample].values,
            rtol=1e-10,
        )

    def test_date_range_slicing(self, data_loader: DataLoader):
        start = "2026-05-06"
        end = "2026-07-15"
        dataset = data_loader.load_aligned_market_data(start_date=start, end_date=end)
        assert dataset.dates[0] >= pd.to_datetime(start)
        assert dataset.dates[-1] <= pd.to_datetime(end)
        assert len(dataset.prices) == len(dataset.dates)


class TestAlignedDatasetInterface:
    """Test AlignedDataset public methods, properties, and metadata."""

    def test_dataset_properties(self, data_loader: DataLoader):
        dataset = data_loader.load_aligned_market_data()

        assert len(dataset.symbols) == 205
        assert len(dataset.stock_symbols) == 202
        assert dataset.futures_symbols == ["SA", "FG", "AU"]

        assert dataset.benchmark_prices is not None
        assert len(dataset.benchmark_prices) == 99
        assert dataset.benchmark_returns is not None
        assert len(dataset.benchmark_returns) == 99

        # Contract specs
        spec_sa = dataset.get_contract_spec("SA")
        assert spec_sa.symbol == "SA"
        assert spec_sa.multiplier == 20.0
        assert spec_sa.margin_ratio == 0.12

        spec_stock = dataset.get_contract_spec(dataset.stock_symbols[0])
        assert spec_stock.multiplier == 100.0
        assert spec_stock.margin_ratio == 1.0

        # Metadata
        assert dataset.metadata["stock_count"] == 202
        assert dataset.metadata["futures_count"] == 3
        assert dataset.metadata["total_assets_count"] == 205
        assert dataset.metadata["benchmark_symbol"] == "000300.SH"

    def test_convenience_function(self):
        dataset = load_aligned_market_data(start_date="2026-06-01", end_date="2026-07-01")
        assert not dataset.prices.empty
        assert dataset.dates[0] >= pd.to_datetime("2026-06-01")


class TestEdgeCasesAndErrors:
    """Test error handling and defensive protections."""

    def test_missing_stock_file_raises(self):
        loader = DataLoader(stock_prices_path="non_existent_file.csv")
        with pytest.raises(FileNotFoundError):
            loader.load_stock_data()

    def test_missing_futures_file_raises(self):
        loader = DataLoader(sa_futures_path="non_existent_sa.csv")
        with pytest.raises(FileNotFoundError):
            loader.load_czce_futures("SA")

    def test_invalid_date_range_raises(self, data_loader: DataLoader):
        with pytest.raises(ValueError, match="No trading days found"):
            data_loader.load_aligned_market_data(start_date="2027-01-01", end_date="2027-01-05")

    def test_unadjusted_rollover_mode(self, data_loader: DataLoader):
        dataset_unadj = data_loader.load_aligned_market_data(adjust_rollover=False)
        assert dataset_unadj.metadata["adjust_rollover"] is False
        assert dataset_unadj.prices.shape == (99, 205)
