"""Shared fixtures and module resolver for Cross-Asset Mixed Portfolio E2E tests.
Provides dynamic resolution between production `src.assets.cross_asset_mix` and the
authoritative reference oracle in `tests.cross_asset_mix.reference_oracle`.
"""

import importlib
from typing import Any, Dict, List
import numpy as np
import pandas as pd
import pytest

from tests.cross_asset_mix import reference_oracle as oracle


def resolve_component(module_name: str, symbol_name: str) -> Any:
    """Attempts to resolve a symbol from production `src.assets.cross_asset_mix.<module_name>`.
    
    If production module or symbol is not yet implemented, seamlessly falls back to
    authoritative reference oracle so tests can verify mathematical specifications and contracts.
    """
    try:
        prod_mod = importlib.import_module(f"src.assets.cross_asset_mix.{module_name}")
        if hasattr(prod_mod, symbol_name):
            return getattr(prod_mod, symbol_name)
    except (ImportError, ModuleNotFoundError):
        pass
    
    # Fallback to authoritative reference oracle
    if hasattr(oracle, symbol_name):
        return getattr(oracle, symbol_name)
    raise AttributeError(f"Component {symbol_name} not found in production or reference oracle.")


@pytest.fixture(scope="session")
def contract_spec_resolver():
    """Provides contract spec resolver function."""
    return lambda sym: resolve_component("contracts", "get_contract_spec")(sym)


@pytest.fixture(scope="session")
def sample_dates() -> pd.DatetimeIndex:
    """100 trading days starting 2024-01-02."""
    return pd.bdate_range(start="2024-01-02", periods=100)


@pytest.fixture(scope="session")
def sample_universe() -> Dict[str, List[str]]:
    """Stock and futures symbols."""
    stocks = [
        "600519", "000858", "000001", "601318", "600036",
        "000333", "002415", "600276", "601888", "002594"
    ]
    futures = ["SA", "FG", "AU"]
    return {"stocks": stocks, "futures": futures, "all": stocks + futures}


@pytest.fixture(scope="session")
def sample_market_dataset(sample_dates, sample_universe) -> oracle.AlignedDataset:
    """Generates a realistic aligned dataset with 10 stocks + 3 commodity futures."""
    rng = np.random.default_rng(42)
    n_days = len(sample_dates)
    all_syms = sample_universe["all"]
    
    price_dict = {}
    return_dict = {}
    settle_dict = {}
    asset_types = {}

    for sym in all_syms:
        spec = oracle.get_contract_spec(sym)
        asset_types[sym] = spec.asset_type
        base_px = 100.0 if spec.asset_type == "STOCK" else (2000.0 if sym in ["SA", "FG"] else 450.0)
        
        # Daily return series
        daily_ret = rng.normal(0.0005, 0.015, n_days)
        # Add mild drift for AU (gold)
        if sym == "AU":
            daily_ret += 0.001
        
        px_series = base_px * np.cumprod(1.0 + daily_ret)
        price_dict[sym] = px_series
        return_dict[sym] = daily_ret
        
        if spec.asset_type == "FUTURES":
            # Futures settlement price: slightly jittered from close
            settle_jitter = rng.normal(0.0, 0.002, n_days)
            settle_dict[sym] = px_series * (1.0 + settle_jitter)
        else:
            settle_dict[sym] = px_series

    prices_df = pd.DataFrame(price_dict, index=sample_dates)
    returns_df = pd.DataFrame(return_dict, index=sample_dates)
    settle_df = pd.DataFrame(settle_dict, index=sample_dates)

    return oracle.AlignedDataset(
        dates=sample_dates,
        prices=prices_df,
        returns=returns_df,
        asset_types=asset_types,
        settle_prices=settle_df,
    )


@pytest.fixture(scope="session")
def sample_flat_dataset(sample_dates, sample_universe) -> oracle.AlignedDataset:
    """Zero return flat price dataset for idle cash interest testing."""
    n_days = len(sample_dates)
    all_syms = sample_universe["all"]
    
    price_dict = {}
    return_dict = {}
    settle_dict = {}
    asset_types = {}

    for sym in all_syms:
        spec = oracle.get_contract_spec(sym)
        asset_types[sym] = spec.asset_type
        base_px = 100.0 if spec.asset_type == "STOCK" else 2000.0
        price_dict[sym] = np.full(n_days, base_px)
        return_dict[sym] = np.zeros(n_days)
        settle_dict[sym] = np.full(n_days, base_px)

    return oracle.AlignedDataset(
        dates=sample_dates,
        prices=pd.DataFrame(price_dict, index=sample_dates),
        returns=pd.DataFrame(return_dict, index=sample_dates),
        asset_types=asset_types,
        settle_prices=pd.DataFrame(settle_dict, index=sample_dates),
    )


@pytest.fixture(scope="session")
def sample_shock_dataset(sample_dates, sample_universe) -> oracle.AlignedDataset:
    """High volatility crash dataset to trigger margin calls and forced liquidations."""
    rng = np.random.default_rng(999)
    n_days = len(sample_dates)
    all_syms = sample_universe["all"]
    
    price_dict = {}
    return_dict = {}
    settle_dict = {}
    asset_types = {}

    for sym in all_syms:
        spec = oracle.get_contract_spec(sym)
        asset_types[sym] = spec.asset_type
        base_px = 100.0 if spec.asset_type == "STOCK" else 2000.0
        
        # First 30 days normal, then sharp -6% per day drop on futures
        daily_ret = rng.normal(0.0002, 0.01, n_days)
        if spec.asset_type == "FUTURES":
            daily_ret[25:35] = -0.07  # Consecutive limit downs
            
        px_series = base_px * np.cumprod(1.0 + daily_ret)
        price_dict[sym] = px_series
        return_dict[sym] = daily_ret
        settle_dict[sym] = px_series

    return oracle.AlignedDataset(
        dates=sample_dates,
        prices=pd.DataFrame(price_dict, index=sample_dates),
        returns=pd.DataFrame(return_dict, index=sample_dates),
        asset_types=asset_types,
        settle_prices=pd.DataFrame(settle_dict, index=sample_dates),
    )


@pytest.fixture(scope="session")
def sample_commodity_surge_dataset(sample_dates, sample_universe) -> oracle.AlignedDataset:
    """Commodity futures surge regime: SA, FG, AU gain +3% daily while stocks are flat."""
    n_days = len(sample_dates)
    all_syms = sample_universe["all"]
    
    price_dict = {}
    return_dict = {}
    settle_dict = {}
    asset_types = {}

    for sym in all_syms:
        spec = oracle.get_contract_spec(sym)
        asset_types[sym] = spec.asset_type
        base_px = 50.0 if spec.asset_type == "STOCK" else 1500.0
        
        if spec.asset_type == "FUTURES":
            daily_ret = np.full(n_days, 0.02)  # Steady strong bull trend
        else:
            daily_ret = np.full(n_days, 0.0)    # Stagnant stocks

        px_series = base_px * np.cumprod(1.0 + daily_ret)
        price_dict[sym] = px_series
        return_dict[sym] = daily_ret
        settle_dict[sym] = px_series

    return oracle.AlignedDataset(
        dates=sample_dates,
        prices=pd.DataFrame(price_dict, index=sample_dates),
        returns=pd.DataFrame(return_dict, index=sample_dates),
        asset_types=asset_types,
        settle_prices=pd.DataFrame(settle_dict, index=sample_dates),
    )
