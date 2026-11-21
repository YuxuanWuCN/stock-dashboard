
"""Read-only market data contract and return construction."""
from __future__ import annotations

from hashlib import sha256
from importlib import import_module
import json
from pathlib import Path
import sys
from typing import Protocol

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
LEGACY_TOOLS = ROOT / "research-outputs/rfof_stability_20261108/tools"
sys.path.insert(0, str(LEGACY_TOOLS))

from stability_universe import QUALIFIED_CODES

ETF_CODES = tuple(QUALIFIED_CODES)
CASH = "511880"
BENCHMARK = "510300"
EXTRA_ETF = "510880"
FUTURES = {"AU": 0.50, "M": 0.25, "CU": 0.25}
PANEL = Path("data/task_split/csmar_master/csmar_factor_panel_master.parquet")

# Contract rates for a small individual subscription and redemption after lock-up.
# These are percentages, not decimal returns. Actual distribution rebates may vary.
PRODUCTS = {
    "017247": ("华夏养老2040三年持有混合（FOF）Y", 0.45, 0.10, 1.50,
               "https://www.chinaamc.com/fund/017247/jijinfeilv.shtml"),
    "017258": ("建信普泽养老2040三年持有混合（FOF）Y", 0.50, 0.075, 1.00,
               "https://pdf.dfcfw.com/pdf/H2_AN202509251750166794_1.pdf"),
    "017377": ("南方养老目标日期2040三年持有混合发起（FOF）Y", 0.50, 0.10, 1.20,
               "https://www.nffund.com/new/personal-financing/detail.html?fundCode=017377"),
}


class MarketReader(Protocol):
    """The read methods consumed by the study. Frames use ISO dates and string codes."""

    def stock_panel(self) -> pd.DataFrame: ...
    def etf_closes(self) -> pd.DataFrame: ...
    def fund_navs(self) -> pd.DataFrame: ...
    def actions(self) -> pd.DataFrame: ...
    def futures_closes(self) -> pd.DataFrame: ...


class DuckDBMarketReader:
    """Local read-only implementation while Issue #14's shared interface is pending."""

    def __init__(self, root: Path, market_dir: Path):
        self.root = root
        self.market_dir = market_dir

    def _query(self, sql: str, path: Path) -> pd.DataFrame:
        import duckdb

        if not path.is_file():
            raise FileNotFoundError(path)
        with duckdb.connect(":memory:") as db:
            return db.execute(sql, [str(path)]).fetchdf()

    def _csv(self, name: str) -> pd.DataFrame:
        return self._query("SELECT * FROM read_csv(?, all_varchar=true)", self.market_dir / name)

    def stock_panel(self) -> pd.DataFrame:
        return self._query(
            "SELECT stock_code, trade_date, close, volume, turnover_rate, market_value, ret "
            "FROM read_parquet(?) ORDER BY trade_date, stock_code", self.root / PANEL,
        )

    def etf_closes(self) -> pd.DataFrame:
        return self._csv("etf_close.csv")

    def fund_navs(self) -> pd.DataFrame:
        return self._csv("fund_nav.csv")

    def actions(self) -> pd.DataFrame:
        return self._csv("actions.csv")

    def futures_closes(self) -> pd.DataFrame:
        return self._csv("futures_close.csv")


def open_reader(root: Path, market_dir: Path, factory: str | None) -> MarketReader:
    if factory is None:
        return DuckDBMarketReader(root, market_dir)
    module, sep, name = factory.partition(":")
    if not sep or not module or not name:
        raise ValueError("reader must be module:factory")
    return getattr(import_module(module), name)(root=root, market_dir=market_dir)


def snapshot_manifest(market_dir: Path) -> dict:
    manifest = json.loads((market_dir / "sources.json").read_text(encoding="utf-8"))
    expected = {"actions.csv", "etf_close.csv", "fund_nav.csv", "futures_close.csv"}
    if set(manifest["snapshot_sha256"]) != expected:
        raise ValueError("market manifest has unexpected snapshot file set")
    for name, digest in manifest["snapshot_sha256"].items():
        if sha256((market_dir / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"market snapshot hash mismatch: {name}")
    return manifest


def _dated(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    result = frame.loc[frame["code"].eq(code)].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], format="%Y-%m-%d", errors="raise")
    return result.set_index("trade_date").sort_index()


def total_returns(levels: pd.Series, events: pd.DataFrame) -> pd.Series:
    """Compute price/NAV total returns by reinvesting each cash distribution at ex-date close."""
    if levels.index.has_duplicates or not levels.index.is_monotonic_increasing or len(levels) < 2:
        raise ValueError("levels require at least two unique chronological observations")
    if not np.isfinite(levels).all() or (levels <= 0).any():
        raise ValueError("levels must be finite and positive")
    # Before the first observation no holder is simulated. No backfill across listing.
    actual = events.loc[(events.index > levels.index[0]) & (events.index <= levels.index[-1])]
    missing_dates = actual.index.difference(levels.index)
    if len(missing_dates):
        raise ValueError(f"unmapped corporate action dates for {levels.name}: {missing_dates.date}")
    cash = actual.groupby(level=0)["cash"].sum().reindex(levels.index, fill_value=0.0)
    ratio = actual.groupby(level=0)["ratio"].prod().reindex(levels.index, fill_value=1.0)
    if not np.isfinite(cash).all() or not np.isfinite(ratio).all() or (cash < 0).any() or (ratio <= 0).any():
        raise ValueError("invalid corporate action amount or ratio")
    return ((levels * ratio + cash) / levels.shift(1) - 1.0).iloc[1:]


def market_series(reader: MarketReader) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return ETF/cash returns, raw ETF prices, the audited input table and Y-share history."""
    quotes, navs, actions = reader.etf_closes(), reader.fund_navs(), reader.actions()
    calendar = _dated(quotes, BENCHMARK).index
    returns, raw_prices, audit, products = {}, {}, [], []
    for code in (*ETF_CODES, CASH, EXTRA_ETF, *PRODUCTS):
        use_nav = code == CASH or code in PRODUCTS
        price = (_dated(navs, code)["nav"] if use_nav else _dated(quotes, code)["close"]).astype(float)
        price = price.rename(code)
        events = _dated(actions, code)[["cash", "ratio"]].astype(float)
        reinvested = total_returns(price, events)
        counted = events.loc[(events.index > price.index[0]) & (events.index <= price.index[-1])]
        if use_nav:
            # NAV series include occasional weekend/period-end disclosures. Compound
            # on the vendor NAV calendar, then sample the common trading calendar.
            wealth = (1 + reinvested).cumprod().reindex(price.index, fill_value=1.0)
            on_market = wealth.reindex(calendar)
            session_returns = on_market.pct_change(fill_method=None)
            missing_marks = int(on_market.loc[on_market.first_valid_index():on_market.last_valid_index()].isna().sum())
        else:
            session_returns = reinvested.reindex(calendar)
            inside_life = session_returns.loc[reinvested.index[0]:reinvested.index[-1]]
            missing_marks = int(inside_life.isna().sum())
            # A day with no market close is carried at last close. The cumulative move
            # through the suspension belongs to the next observed return.
            session_returns.loc[inside_life.index] = inside_life.fillna(0.0)
            limit = 0.21 if code in {"159915", "588000"} else 0.11
            if (reinvested.abs() > limit).any():
                raise ValueError(f"unexplained post-action ETF jump for {code}: "
                                 f"{reinvested[reinvested.abs() > limit].to_dict()}")
        if code not in PRODUCTS:
            returns[code] = session_returns
            close = _dated(quotes, code)["close"].astype(float).rename(code)
            raw_prices[code] = close.reindex(calendar)
            comparison_dates = close.index.intersection(price.index)
            raw_same_dates = close.reindex(comparison_dates)
            price_gain = raw_same_dates.iloc[-1] / raw_same_dates.iloc[0] - 1
            reinvested_gain = (1 + reinvested.loc[comparison_dates[0]:comparison_dates[-1]].iloc[
                int(comparison_dates[0] in reinvested.index):
            ]).prod() - 1
        else:
            products.append(pd.DataFrame({
                "trade_date": price.index, "fund_code": code, "unit_nav": price.to_numpy(),
                "cash_per_unit": events["cash"].groupby(level=0).sum().reindex(price.index, fill_value=0).to_numpy(),
                "total_return_nav": wealth.to_numpy(),
            }))
            comparison_dates = price.index
            price_gain = price.iloc[-1] / price.iloc[0] - 1
            reinvested_gain = wealth.iloc[-1] - 1
        audit.append({
            "code": code, "basis": "fund_unit_nav" if use_nav else "market_close",
            "first_level_date": price.index[0].date().isoformat(),
            "last_level_date": price.index[-1].date().isoformat(),
            "level_observations": len(price), "missing_market_marks": missing_marks,
            "dividends": int((counted["cash"] > 0).sum()), "splits": int((counted["ratio"] != 1).sum()),
            "raw_price_or_nav_gain_pct": 100 * price_gain,
            "comparison_first_date": comparison_dates[0].date().isoformat(),
            "comparison_last_date": comparison_dates[-1].date().isoformat(),
            "reinvested_total_gain_pct": 100 * reinvested_gain,
            "max_absolute_session_return_pct": 100 * session_returns.abs().max(),
        })
    return pd.DataFrame(returns), pd.DataFrame(raw_prices), pd.DataFrame(audit), pd.concat(products, ignore_index=True)


def stock_declarations(root: Path) -> pd.DataFrame:
    policy = json.loads((root / "config/data_caliber/csmar_master_close_basis.json").read_text(encoding="utf-8"))
    frames = []
    for key, properties in policy["cohorts"].items():
        sample = root / f"data/task_split/{key.lower()}/csmar/{key.lower()}_csmar_factor_panel_filtered.csv"
        codes = pd.read_csv(sample, usecols=["stock_code"], dtype={"stock_code": str})["stock_code"]
        frames.append(pd.DataFrame({"stock_code": codes.unique(), "cohort": key}).assign(**{
            label: properties[label] for label in (
                "close_basis", "source_table", "adjustment", "provenance", "total_return_available",
            )
        }))
    result = pd.concat(frames, ignore_index=True)
    if result["stock_code"].duplicated().any():
        raise ValueError("stock code has overlapping cohort declarations")
    return result


def futures_prices(reader: MarketReader) -> pd.DataFrame:
    quotes = reader.futures_closes()
    series = {code: _dated(quotes, code)["close"].astype(float) for code in FUTURES}
    for code, price in series.items():
        if price.empty or price.index.has_duplicates or not np.isfinite(price).all() or (price <= 0).any():
            raise ValueError(f"invalid continuous futures prices: {code}")
    return pd.DataFrame(series).sort_index()
