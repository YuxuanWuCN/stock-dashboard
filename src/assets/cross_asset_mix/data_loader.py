"""Cross-Asset Market Data Homogenization & Ticker Feeds Engine.

This module unifies A-share equities (202 stock universe + CSI 300 benchmark)
and Chinese commodity futures (CZCE Pure Soda SA, CZCE Glass FG, SHFE Gold AU)
into a synchronized daily market dataset.

Key features:
1. Continuous futures contract stitching & rollover gap elimination.
2. Calendar alignment across equity and commodity trading days.
3. No lookahead bias with strict forward-fill and return=0 for suspensions/holidays.
4. Offline caching support with automatic fallback to akshare data feeds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .contracts import (
    AssetType,
    ContractSpec,
    get_contract_spec,
    get_stock_contract_spec,
    SPEC_SA,
    SPEC_FG,
    SPEC_AU,
)

logger = logging.getLogger(__name__)


@dataclass
class AlignedDataset:
    """Synchronized cross-asset market dataset container.

    Attributes:
        dates: Unified DatetimeIndex of trading days.
        prices: Daily adjusted close prices DataFrame (columns: 202 stocks + SA, FG, AU, index: dates).
        returns: Daily percentage returns DataFrame (rollover-adjusted, suspended/ffilled days return=0).
        settle_prices: Daily settlement prices DataFrame (exchange settle prices for futures; close for stocks).
        asset_types: Dictionary mapping asset ticker to 'STOCK' or 'FUTURES'.
        metadata: Supplementary metadata (benchmark series, contract specs, roll dates, etc.).
    """
    dates: pd.DatetimeIndex
    prices: pd.DataFrame
    returns: pd.DataFrame
    settle_prices: pd.DataFrame
    asset_types: Dict[str, str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def symbols(self) -> List[str]:
        """List of all asset symbols in the universe."""
        return list(self.prices.columns)

    @property
    def stock_symbols(self) -> List[str]:
        """List of equity stock symbols."""
        return [sym for sym, t in self.asset_types.items() if t == AssetType.STOCK.value or t == "STOCK"]

    @property
    def futures_symbols(self) -> List[str]:
        """List of commodity futures symbols."""
        return [sym for sym, t in self.asset_types.items() if t == AssetType.FUTURES.value or t == "FUTURES"]

    @property
    def benchmark_prices(self) -> Optional[pd.Series]:
        """CSI 300 (000300.SH) benchmark close prices series."""
        return self.metadata.get("benchmark_prices")

    @property
    def benchmark_returns(self) -> Optional[pd.Series]:
        """CSI 300 benchmark daily percentage returns series."""
        return self.metadata.get("benchmark_returns")

    def get_asset_type(self, symbol: str) -> str:
        """Get asset class string ('STOCK' or 'FUTURES') for symbol."""
        return self.asset_types.get(symbol, "STOCK")

    def get_contract_spec(self, symbol: str) -> ContractSpec:
        """Get ContractSpec for an asset symbol."""
        specs = self.metadata.get("contract_specs", {})
        if symbol in specs:
            return specs[symbol]
        return get_contract_spec(symbol)


class DataLoader:
    """Cross-asset market data loader and homogenization engine."""

    def __init__(
        self,
        rainbow_root: Optional[Union[str, Path]] = None,
        stock_prices_path: Optional[Union[str, Path]] = None,
        stock_meta_path: Optional[Union[str, Path]] = None,
        sa_futures_path: Optional[Union[str, Path]] = None,
        fg_futures_path: Optional[Union[str, Path]] = None,
        au_futures_path: Optional[Union[str, Path]] = None,
    ) -> None:
        """Initialize DataLoader with project paths.

        If paths are not explicitly provided, attempts to auto-resolve from the
        repository layout.
        """
        # Resolve Rainbow_FinGPTv2 root
        if rainbow_root is not None:
            self.rainbow_root = Path(rainbow_root).resolve()
        else:
            # Current file is in Rainbow_FinGPTv2/src/assets/cross_asset_mix/
            self.rainbow_root = Path(__file__).resolve().parents[3]

        # Stock 202 dataset paths
        default_stock_prices = (
            self.rainbow_root / "data" / "raw" / "backtest_paper_100d_202stocks" / "market_prices.csv"
        )
        default_stock_meta = (
            self.rainbow_root / "data" / "raw" / "backtest_paper_100d_202stocks" / "universe_metadata.csv"
        )
        self.stock_prices_path = Path(stock_prices_path).resolve() if stock_prices_path else default_stock_prices
        self.stock_meta_path = Path(stock_meta_path).resolve() if stock_meta_path else default_stock_meta

        # Commodity futures raw paths
        default_sa_path = (
            self.rainbow_root / "competitions" / "czce_futures" / "data" / "raw" / "czce_sa_futures_daily_raw.csv"
        )
        default_fg_path = (
            self.rainbow_root / "competitions" / "czce_futures" / "data" / "raw" / "czce_fg_futures_daily_raw.csv"
        )
        default_au_path = (
            self.rainbow_root / "data" / "raw" / "shfe_au_futures_daily_raw.csv"
        )
        self.sa_futures_path = Path(sa_futures_path).resolve() if sa_futures_path else default_sa_path
        self.fg_futures_path = Path(fg_futures_path).resolve() if fg_futures_path else default_fg_path
        self.au_futures_path = Path(au_futures_path).resolve() if au_futures_path else default_au_path

    def load_stock_data(
        self, filepath: Optional[Union[str, Path]] = None
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """Load A-share 202 stock prices and CSI 300 benchmark series.

        Returns:
            Tuple of (stocks_dataframe, benchmark_series).
        """
        target_path = Path(filepath).resolve() if filepath else self.stock_prices_path
        if not target_path.exists():
            raise FileNotFoundError(f"Stock price dataset not found at: {target_path}")

        df = pd.read_csv(target_path, index_col=0)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        benchmark_col = "000300.SH"
        if benchmark_col in df.columns:
            benchmark_series = df[benchmark_col].astype(float)
            stocks_df = df.drop(columns=[benchmark_col]).astype(float)
        else:
            benchmark_series = pd.Series(dtype=float)
            stocks_df = df.astype(float)

        return stocks_df, benchmark_series

    def load_stock_metadata(
        self, filepath: Optional[Union[str, Path]] = None
    ) -> pd.DataFrame:
        """Load A-share stock universe metadata (code, name, sector, beta)."""
        target_path = Path(filepath).resolve() if filepath else self.stock_meta_path
        if not target_path.exists():
            logger.warning("Stock metadata file not found at %s", target_path)
            return pd.DataFrame()
        meta = pd.read_csv(target_path)
        return meta

    def _read_futures_csv(self, filepath: Path) -> pd.DataFrame:
        """Read and normalize Chinese commodity futures CSV file."""
        if not filepath.exists():
            raise FileNotFoundError(f"Futures file not found: {filepath}")

        # Attempt utf-8-sig first, fallback to gbk/gb18030
        df = None
        for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                df = pd.read_csv(filepath, encoding=enc)
                break
            except Exception:
                continue

        if df is None:
            raise ValueError(f"Failed to read futures CSV with standard encodings: {filepath}")

        # Map standard Chinese or English headers
        col_map = {
            "日期": "date",
            "开盘价": "open",
            "最高价": "high",
            "最低价": "low",
            "收盘价": "close",
            "成交量": "volume",
            "持仓量": "open_interest",
            "动态结算价": "settle",
            "结算价": "settle",
        }
        df = df.rename(columns=lambda c: col_map.get(str(c).strip(), str(c).strip()))

        # Verify required columns
        required = ["date", "open", "high", "low", "close"]
        for req in required:
            if req not in df.columns:
                raise ValueError(f"Missing required column '{req}' in {filepath}. Found: {df.columns.tolist()}")

        if "settle" not in df.columns:
            df["settle"] = df["close"]
        if "open_interest" not in df.columns:
            df["open_interest"] = 0.0
        if "volume" not in df.columns:
            df["volume"] = 0.0

        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        numeric_cols = ["open", "high", "low", "close", "volume", "open_interest", "settle"]
        for nc in numeric_cols:
            df[nc] = pd.to_numeric(df[nc], errors="coerce")

        return df

    def load_czce_futures(
        self, symbol: str, filepath: Optional[Union[str, Path]] = None
    ) -> pd.DataFrame:
        """Load CZCE commodity futures raw daily data (SA or FG)."""
        sym_clean = symbol.upper().replace("0", "")
        if filepath is not None:
            target = Path(filepath).resolve()
        elif sym_clean == "SA":
            target = self.sa_futures_path
        elif sym_clean == "FG":
            target = self.fg_futures_path
        else:
            raise ValueError(f"Unsupported CZCE symbol: {symbol}. Expected 'SA' or 'FG'.")

        return self._read_futures_csv(target)

    def load_shfe_au(
        self,
        filepath: Optional[Union[str, Path]] = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Load SHFE Gold (AU) futures raw daily data.

        If local cache is missing or force_refresh is True, fetches via akshare.futures_main_sina('AU0')
        and persists locally.
        """
        target_path = Path(filepath).resolve() if filepath else self.au_futures_path

        # If cache exists and not refreshing, read from cache
        if target_path.exists() and not force_refresh:
            return self._read_futures_csv(target_path)

        # Otherwise attempt online fetch via akshare
        logger.info("Fetching SHFE Gold AU0 data via akshare...")
        try:
            import akshare as ak
            df_au = ak.futures_main_sina(symbol="AU0")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            df_au.to_csv(target_path, index=False, encoding="utf-8-sig")
            logger.info("Successfully cached AU0 data to %s (rows: %d)", target_path, len(df_au))
            return self._read_futures_csv(target_path)
        except Exception as e:
            if target_path.exists():
                logger.warning("Online fetch failed (%s), falling back to existing cache %s", e, target_path)
                return self._read_futures_csv(target_path)
            raise RuntimeError(
                f"Failed to fetch and cache SHFE AU0 data: {e}. "
                f"Please ensure network access or provide valid CSV at {target_path}."
            ) from e

    @staticmethod
    def adjust_rollover_gap(
        futures_df: pd.DataFrame,
        gap_threshold: float = 0.035,
        anchor_mode: str = "latest",
    ) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        """Eliminate rollover price jumps (移仓换月跳空偏差) for continuous futures.

        When the dominant contract switches (e.g. from 05 to 09), the raw continuous
        series experiences an artificial basis step change that does not reflect actual
        holding returns.

        Mathematical Formulation:
        1. On non-roll days:
           r_t = (Close_t - Close_{t-1}) / Close_{t-1}
        2. On roll days:
           r_t = (Close_t - Open_t) / Open_t (intraday holding return on new contract)
        3. Backward-adjusted synthetic continuous price (后复权平滑价格):
           Anchored at T (P_T^{adj} = Close_T),
           P_{t-1}^{adj} = P_t^{adj} / (1 + r_t)
           This ensures (P_t^{adj} - P_{t-1}^{adj}) / P_{t-1}^{adj} == r_t exactly.
        4. Settle price adjusted proportionally:
           Settle_t^{adj} = Settle_t * (P_t^{adj} / Close_t)

        Args:
            futures_df: DataFrame with OHLCV and settle columns, sorted by DatetimeIndex.
            gap_threshold: Threshold for overnight gap |Open_t - Close_{t-1}| / Close_{t-1}.
            anchor_mode: 'latest' (anchor to latest close price) or 'initial' (anchor to start).

        Returns:
            Tuple of:
                - adj_return: Unbiased holding percentage return series.
                - adj_close: Backward-adjusted continuous close price series.
                - adj_settle: Backward-adjusted continuous settle price series.
                - is_roll: Boolean Series indicating detected roll dates.
        """
        df = futures_df.copy()
        raw_close = df["close"].astype(float)
        raw_open = df["open"].astype(float)
        raw_settle = df["settle"].astype(float)
        oi = df["open_interest"].astype(float)

        raw_ret = raw_close.pct_change().fillna(0.0)
        overnight_gap = (raw_open - raw_close.shift(1)) / raw_close.shift(1)

        # Detect contract switch: overnight jump accompanied by stable/increasing open interest
        oi_shift = oi > (oi.shift(1) * 0.85)
        is_roll = (overnight_gap.abs() > gap_threshold) & oi_shift
        is_roll.iloc[0] = False  # First day cannot be a roll

        # Holding return calculation
        intraday_ret = (raw_close - raw_open) / raw_open
        adj_ret = raw_ret.copy()
        adj_ret[is_roll] = intraday_ret[is_roll]
        adj_ret = adj_ret.fillna(0.0)

        # Backward adjusted continuous price series
        n_obs = len(df)
        adj_close_vals = np.zeros(n_obs, dtype=float)

        if anchor_mode == "latest":
            adj_close_vals[-1] = raw_close.iloc[-1]
            for i in range(n_obs - 2, -1, -1):
                adj_close_vals[i] = adj_close_vals[i + 1] / (1.0 + adj_ret.iloc[i + 1])
        else:
            # Anchor at initial price
            cum_ret = (1.0 + adj_ret).cumprod()
            adj_close_vals = raw_close.iloc[0] * cum_ret.values

        adj_close = pd.Series(adj_close_vals, index=df.index, name="adj_close")
        factor = adj_close / raw_close
        adj_settle = pd.Series(raw_settle * factor, index=df.index, name="adj_settle")

        return adj_ret, adj_close, adj_settle, is_roll

    def align_market_data(
        self,
        stocks_df: pd.DataFrame,
        futures_dict: Dict[str, pd.DataFrame],
        benchmark_series: pd.Series,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust_rollover: bool = True,
        stock_meta: Optional[pd.DataFrame] = None,
    ) -> AlignedDataset:
        """Align stocks and futures to a unified daily trading calendar without lookahead bias.

        Rules:
        - Trading calendar is derived from stock trading days within [start_date, end_date].
        - Suspensions and non-trading days for futures are forward-filled (ffill).
        - For suspended / forward-filled days, daily percentage return is strictly 0.0.
        - First day return is strictly 0.0.
        - Stocks settle at close price (spot cash settlement).
        """
        # Establish base trading calendar from stocks
        calendar = stocks_df.index
        if start_date is not None:
            calendar = calendar[calendar >= pd.to_datetime(start_date)]
        if end_date is not None:
            calendar = calendar[calendar <= pd.to_datetime(end_date)]
        calendar = calendar.sort_values()

        if len(calendar) == 0:
            raise ValueError(f"No trading days found in range [{start_date}, {end_date}]")

        # 1. Align Stocks
        aligned_stocks = stocks_df.reindex(calendar).ffill().bfill().astype(float)
        stock_returns = aligned_stocks.pct_change().fillna(0.0)
        # Any day where price did not change (suspended) has zero return
        stock_settle = aligned_stocks.copy()

        # 2. Align Benchmark
        if not benchmark_series.empty:
            aligned_benchmark = benchmark_series.reindex(calendar).ffill().bfill().astype(float)
            benchmark_ret = aligned_benchmark.pct_change().fillna(0.0)
        else:
            aligned_benchmark = pd.Series(index=calendar, dtype=float)
            benchmark_ret = pd.Series(0.0, index=calendar)

        # 3. Process and Align Futures
        futures_prices_dict: Dict[str, pd.Series] = {}
        futures_returns_dict: Dict[str, pd.Series] = {}
        futures_settle_dict: Dict[str, pd.Series] = {}
        roll_dates_dict: Dict[str, List[pd.Timestamp]] = {}

        for sym, f_df in futures_dict.items():
            if adjust_rollover:
                adj_ret, adj_close, adj_settle, is_roll = self.adjust_rollover_gap(f_df)
                roll_dates_dict[sym] = f_df.index[is_roll].tolist()
            else:
                adj_close = f_df["close"].astype(float)
                adj_settle = f_df["settle"].astype(float)
                adj_ret = adj_close.pct_change().fillna(0.0)
                roll_dates_dict[sym] = []

            # Reindex to common trading calendar
            aligned_close = adj_close.reindex(calendar).ffill().bfill()
            aligned_settle = adj_settle.reindex(calendar).ffill().bfill()

            # True holding return over the calendar:
            # If a day was missing (forward-filled), price difference is 0, return is 0.0.
            # On normal and roll days, percentage change of backward-adjusted price matches adj_ret.
            aligned_ret = aligned_close.pct_change().fillna(0.0)
            aligned_ret.iloc[0] = 0.0

            futures_prices_dict[sym] = aligned_close
            futures_returns_dict[sym] = aligned_ret
            futures_settle_dict[sym] = aligned_settle

        # 4. Assemble Universe Matrices
        all_prices = aligned_stocks.copy()
        all_returns = stock_returns.copy()
        all_settle = stock_settle.copy()

        for sym in futures_dict.keys():
            all_prices[sym] = futures_prices_dict[sym]
            all_returns[sym] = futures_returns_dict[sym]
            all_settle[sym] = futures_settle_dict[sym]

        # 5. Asset Type Registry
        asset_types: Dict[str, str] = {}
        contract_specs: Dict[str, ContractSpec] = {}

        # Stocks
        meta_dict = {}
        if stock_meta is not None and not stock_meta.empty and "code" in stock_meta.columns:
            meta_dict = stock_meta.set_index("code").to_dict(orient="index")

        for col in aligned_stocks.columns:
            asset_types[col] = AssetType.STOCK.value
            info = meta_dict.get(col, {})
            name = info.get("name", f"A股_{col}")
            contract_specs[col] = get_stock_contract_spec(symbol=col, name=name)

        # Futures
        for sym in futures_dict.keys():
            asset_types[sym] = AssetType.FUTURES.value
            contract_specs[sym] = get_contract_spec(sym)

        # 6. Metadata Container
        metadata: Dict[str, Any] = {
            "benchmark_symbol": "000300.SH",
            "benchmark_prices": aligned_benchmark,
            "benchmark_returns": benchmark_ret,
            "contract_specs": contract_specs,
            "rollover_days": roll_dates_dict,
            "stock_count": len(aligned_stocks.columns),
            "futures_count": len(futures_dict),
            "total_assets_count": len(all_prices.columns),
            "date_range": (calendar[0].strftime("%Y-%m-%d"), calendar[-1].strftime("%Y-%m-%d")),
            "adjust_rollover": adjust_rollover,
        }
        if stock_meta is not None and not stock_meta.empty:
            metadata["stock_metadata"] = stock_meta

        return AlignedDataset(
            dates=calendar,
            prices=all_prices,
            returns=all_returns,
            settle_prices=all_settle,
            asset_types=asset_types,
            metadata=metadata,
        )

    def load_aligned_market_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust_rollover: bool = True,
        include_extended_futures: bool = False,
    ) -> AlignedDataset:
        """Load all stocks, commodity futures (SA, FG, AU, plus extended 9 commodities if enabled), and benchmark.

        Args:
            start_date: Optional start date string (e.g., '2026-04-07').
            end_date: Optional end date string (e.g., '2026-08-21').
            adjust_rollover: If True, applies holding return stitching & backward adjustment.
            include_extended_futures: If True, loads 9 additional commodity futures (AG, CU, AL, RB, I, SC, TA, M, P).

        Returns:
            AlignedDataset with dates, prices, returns, settle_prices, asset_types, and metadata.
        """
        # 1. Load stocks and benchmark
        stocks_df, benchmark = self.load_stock_data()
        stock_meta = self.load_stock_metadata()

        # 2. Load futures
        sa_df = self.load_czce_futures("SA")
        fg_df = self.load_czce_futures("FG")
        au_df = self.load_shfe_au()

        futures_dict = {
            "SA": sa_df,
            "FG": fg_df,
            "AU": au_df,
        }

        # Auto-discover additional commodity futures from data/raw/commodity_futures/ if requested
        if include_extended_futures:
            comm_dir = self.rainbow_root / "data" / "raw" / "commodity_futures"
            if comm_dir.exists():
                for p in sorted(comm_dir.glob("*_futures_daily_raw.csv")):
                    sym = p.name.split("_")[0].upper()
                    if sym not in futures_dict:
                        try:
                            futures_dict[sym] = self._read_futures_csv(p)
                        except Exception as e:
                            logger.warning("Failed to load commodity future %s from %s: %s", sym, p, e)

        # 3. Align datasets
        return self.align_market_data(
            stocks_df=stocks_df,
            futures_dict=futures_dict,
            benchmark_series=benchmark,
            start_date=start_date,
            end_date=end_date,
            adjust_rollover=adjust_rollover,
            stock_meta=stock_meta,
        )


def load_aligned_market_data(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    adjust_rollover: bool = True,
    rainbow_root: Optional[Union[str, Path]] = None,
    include_extended_futures: bool = False,
) -> AlignedDataset:
    """Convenience top-level function to load aligned cross-asset market data."""
    loader = DataLoader(rainbow_root=rainbow_root)
    return loader.load_aligned_market_data(
        start_date=start_date,
        end_date=end_date,
        adjust_rollover=adjust_rollover,
        include_extended_futures=include_extended_futures,
    )
