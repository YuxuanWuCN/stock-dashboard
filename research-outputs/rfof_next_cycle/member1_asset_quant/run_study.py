
"""Offline replay of Issue #12 from checksummed market snapshots and the CSMAR master."""
from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from market import BENCHMARK, CASH, PANEL, PRODUCTS, ROOT
from market import futures_prices, market_series, open_reader, snapshot_manifest, stock_declarations
from backtest import ANN, METHODS, defense_ledger, defense_windows, futures_ledger
from backtest import lifecycle_ledger, metrics, stock_ledger
from fetch_market import MARKET_DIR
from retirement import SEED, block_indices, eet_table, opening_trend, simulate_retirement
from stability_verdict import judge_method_results

SLEEVE_BPS = 30
LEGACY = ROOT / "research-outputs/rfof_stability_20261108/reports/tables"


def bootstrap_deltas(daily: pd.DataFrame, cash: pd.Series, baseline: str, scope: str) -> pd.DataFrame:
    """Paired moving-block bootstrap, with shared blocks for portfolio and cash."""
    daily = daily.copy()
    daily["cash"] = cash.reindex(daily.index)
    if daily.isna().any().any():
        raise ValueError("bootstrap requires complete matched returns")
    sample = daily.to_numpy()
    reference = list(daily.columns).index(baseline)

    def measures(values):
        nav = np.cumprod(1 + values, axis=1)
        drawdown = nav / np.maximum(np.maximum.accumulate(nav, axis=1), 1) - 1
        residual = values[:, :, :-1] - values[:, :, -1:]
        sharpe = np.sqrt(ANN) * residual.mean(axis=1) / residual.std(axis=1, ddof=1)
        return [100 * (nav[:, -1, :-1] ** (ANN / values.shape[1]) - 1),
                100 * drawdown[:, :, :-1].min(axis=1), sharpe]

    actual = measures(sample[None, :, :])
    rows = []
    for block in (21, 63):
        indices = block_indices(len(sample), len(sample), block, 800, SEED)
        estimates = measures(sample[indices])
        for metric, estimate, point in zip(("cagr_pp", "max_dd_pp", "sharpe"), estimates, actual):
            for j, name in enumerate(daily.columns[:-1]):
                if name == baseline:
                    continue
                delta = estimate[:, j] - estimate[:, reference]
                low, high = np.quantile(delta, [.025, .975])
                rows.append({
                    "sample": scope, "candidate": name, "baseline": baseline, "metric": metric,
                    "point_delta": point[0, j] - point[0, reference], "ci95_low": low, "ci95_high": high,
                    "block_days": block, "repetitions": len(indices), "seed": SEED, "n_days": len(sample),
                })
    return pd.DataFrame(rows)


def fund_products(source: dict) -> pd.DataFrame:
    rows = []
    meta = {row["code"]: row for row in source["funds"]}
    for code, (name, management, custody, entry, fee_source) in PRODUCTS.items():
        status = meta[code]
        if code not in source["registry_rows"] or "开放申购" not in status["subscription_status"]:
            raise ValueError(f"{code} missing from official register or not open for subscriptions at cutoff")
        rows.append({
            "fund_code": code, "name": name, "target_year": 2040, "minimum_holding_years": 3,
            "management_fee_pct_pa": management, "custody_fee_pct_pa": custody, "sales_service_pct_pa": 0,
            "reference_small_purchase_fee_pct": entry, "post_lock_redemption_fee_pct": 0,
            "subscription_status": status["subscription_status"], "status_date": status["status_date"],
            "fee_source": fee_source, "status_source": status["status_source"],
            "nav_source": status["nav_source"], "registry_source": source["registry_page"],
        })
    return pd.DataFrame(rows)


def compare_products(returns: pd.DataFrame, cash: pd.Series, products: pd.DataFrame, window: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    common = returns.dropna()
    if len(common) < 2:
        raise ValueError(f"no usable common Y-share history for {window}")
    # Dropping leading/trailing pre-inception or unpublished dates is allowed.
    # An internal hole would compare multi-session and single-session returns.
    if returns.loc[common.index[0]:common.index[-1]].isna().any().any():
        raise ValueError(f"Y-share comparison contains gaps inside {window}")
    fees = products.set_index("fund_code")["reference_small_purchase_fee_pct"].to_dict()
    rows = []
    for code, series in common.items():
        entry = fees.get(code, 0) / 100
        observed = metrics(series, cash)
        after = series.copy()
        after.iloc[0] = (1 + after.iloc[0]) / (1 + entry) - 1
        entry_adjusted = metrics(after, cash)
        rows.append({
            "comparison_window": window, "strategy_id": code,
            **observed, "entry_fee_pct": entry * 100,
            "total_ret_after_entry_pct": entry_adjusted["total_ret_pct"],
            "ann_ret_after_entry_pct": entry_adjusted["ann_ret_pct"],
        })
    return pd.DataFrame(rows), common


def write_table(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, float_format="%.10g", date_format="%Y-%m-%d", lineterminator="\n")


def run(market_dir: Path, output: Path, reader_factory: str | None, paths: int, plots: bool) -> None:
    if output.exists():
        raise FileExistsError(f"choose a new run directory: {output}")
    source = snapshot_manifest(market_dir)
    reader = open_reader(ROOT, market_dir, reader_factory)
    etf_returns, prices, etf_audit, tdf_history = market_series(reader)
    cash = etf_returns[CASH]
    benchmark = etf_returns[BENCHMARK]
    panel = reader.stock_panel()
    equity, stock_audit = stock_ledger(panel, stock_declarations(ROOT))
    if (stock_audit["stocks"], stock_audit["sessions"], stock_audit["rows"]) != (299, 644, 192199):
        raise ValueError(f"unexpected CSMAR master coverage: {stock_audit}")
    print(f"CSMAR {stock_audit['stocks']} stocks × {stock_audit['sessions']} sessions", flush=True)

    ledgers = {(method, "primary", bps): defense_ledger(etf_returns, method, cost_bps=bps)
               for method in METHODS for bps in (15, SLEEVE_BPS)}
    for method in METHODS[1:]:
        ledgers[(method, "lookback504", SLEEVE_BPS)] = defense_ledger(etf_returns, method, lookback=504)
    for method in ("A3", "A4"):
        for target in (.06, .10):
            ledgers[(method, f"target{target * 100:.0f}", SLEEVE_BPS)] = defense_ledger(
                etf_returns, method, target_vol=target,
            )
    defense_stats = defense_windows(ledgers, cash)
    verdict = judge_method_results(
        defense_stats.loc[defense_stats["cost_bps_round_trip"].eq(SLEEVE_BPS)],
        primary_params={method: "primary" for method in METHODS},
    )
    defense = {method: ledgers[(method, "primary", SLEEVE_BPS)] for method in METHODS}
    defense_returns = pd.DataFrame({method: frame["net_return"] for method, frame in defense.items()})
    print(f"ETF defense: {defense_returns.index[0].date()} to {defense_returns.index[-1].date()}", flush=True)

    # Old price-only convention on the exact new calendar and strategy code. The
    # published historical outputs are a separate comparison with different inputs.
    raw = prices.ffill().pct_change(fill_method=None)
    raw[CASH] = pd.Series(.024 / ANN, index=cash.index).where(cash.notna())
    price_only = defense_windows(
        {(method, "price_only", SLEEVE_BPS): defense_ledger(raw, method) for method in METHODS},
        cash,
    )

    aligned_cash = cash.reindex(equity.index)
    futures = futures_ledger(futures_prices(reader), aligned_cash)
    full = {
        f"RFOF_{method}_{variant}": lifecycle_ledger(defense[method], equity, futures, variant)
        for method, variant in (("A0", "B2"), ("A3", "B0"), ("A3", "B1"), ("A3", "B2"), ("A4", "B2"))
    }
    age60 = lifecycle_ledger(defense["A3"], equity, futures, "B2", start_age=60)
    benchmarks = {code: pd.DataFrame({
        "net_return": series.dropna(), "nav": (1 + series.dropna()).cumprod(),
    }) for code, series in ((BENCHMARK, benchmark), (CASH, cash))}
    ledger_map = {**defense, **full, "RFOF_A3_B2_age60": age60, "CSMAR_299": equity, **benchmarks}
    trend = opening_trend(benchmark)
    rows = []
    for name, frame in ledger_map.items():
        rows.append(frame.assign(strategy_id=name, trend_gate_closed=trend.reindex(frame.index))
                    .rename_axis("trade_date").reset_index())

    products = fund_products(source)
    fund_returns = (
        tdf_history.pivot(index="trade_date", columns="fund_code", values="total_return_nav")
        .reindex(etf_returns.index).pct_change(fill_method=None)
    )
    for code in PRODUCTS:
        ret = fund_returns[code].dropna()
        nav = tdf_history.loc[tdf_history["fund_code"].eq(code)].set_index("trade_date")["total_return_nav"]
        rows.append(pd.DataFrame({
            "trade_date": ret.index, "strategy_id": code, "net_return": ret.to_numpy(),
            "nav": nav.reindex(ret.index).to_numpy(), "trend_gate_closed": trend.reindex(ret.index).to_numpy(),
        }))
    returns = pd.DataFrame({name: ledger["net_return"] for name, ledger in full.items()})
    returns[BENCHMARK] = benchmark.reindex(returns.index)
    returns["CSMAR_299"] = equity["net_return"]

    tdf_long, tdf_long_returns = compare_products(
        pd.concat([defense_returns, benchmark.rename(BENCHMARK), fund_returns], axis=1),
        cash, products, "defense_and_y_common",
    )
    tdf_recent, tdf_recent_returns = compare_products(
        pd.concat([returns, fund_returns.reindex(returns.index)], axis=1), cash, products,
        "csmar_and_y_common",
    )
    stats = pd.concat([
        bootstrap_deltas(defense_returns, cash, "A0", "full_etf"),
        bootstrap_deltas(defense_returns[["A3", "A4"]], cash, "A3", "full_etf"),
        bootstrap_deltas(returns[list(full)], cash, "RFOF_A0_B2", "full_csmar"),
        bootstrap_deltas(returns[["RFOF_A3_B2", "RFOF_A4_B2"]], cash, "RFOF_A3_B2", "full_csmar"),
    ], ignore_index=True)

    tax = pd.concat([eet_table(rate) for rate in (0, .03, .05)], ignore_index=True)
    initial = tax.loc[tax["net_nominal_return_assumption_pct"].eq(3), "eet_end_balance_cny"].iat[0]
    # Exclude the entry day from retirement history: the portfolio is already funded.
    simulation_data = pd.DataFrame({
        "portfolio_return": age60["net_return"].iloc[1:],
        "cash_return": aligned_cash, "trend_gate_closed": trend,
    }).reindex(age60.index[1:])
    ruin, by_age = simulate_retirement(simulation_data, initial, paths=paths)

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix=".study-") as temporary:
        stage = Path(temporary) / "result"
        tables = stage / "tables"
        tables.mkdir(parents=True)
        deliveries = {
            "etf_data_audit": etf_audit, "fund_products": products, "tdf_daily_nav": tdf_history,
            "defense_method_results": defense_stats, "stability_verdict": verdict,
            "price_only_replay": price_only, "paired_block_comparison": stats,
            "tdf_comparison": pd.concat([tdf_long, tdf_recent], ignore_index=True),
            "futures_variants": futures.rename_axis("trade_date").reset_index(),
            "futures_comparison": pd.DataFrame([{"variant": key, **metrics(futures[key], cash)}
                                                for key in ("B0", "B1", "B2")]),
            "daily_ledger": pd.concat(rows, ignore_index=True, sort=False).sort_values(["strategy_id", "trade_date"]),
            "eet_net_replacement": tax, "retirement_ruin": ruin, "retirement_age_profile": by_age,
        }
        for name, frame in deliveries.items():
            write_table(tables / f"{name}.csv", frame)
        meta = {
            "stock_panel": stock_audit,
            "stock_panel_sha256": sha256((ROOT / PANEL).read_bytes()).hexdigest(),
            "stock_basis_policy_sha256": sha256(
                (ROOT / "config/data_caliber/csmar_master_close_basis.json").read_bytes()
            ).hexdigest(),
            "reader": reader_factory or "local DuckDB implementation",
            "legacy_tables_sha256": {name: sha256((LEGACY / name).read_bytes()).hexdigest()
                                     for name in ("defense_method_results.csv", "futures_sensitivity.csv", "verdict.csv")},
            "market": source,
            "software": {name: version(name) for name in (
                "duckdb", "numpy", "pandas", "scipy", "scikit-learn", "matplotlib", "pyarrow",
                "akshare", "requests", "lxml",
            )},
            "output_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(tables.glob("*.csv"))},
        }
        (stage / "run_manifest.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        if plots:
            from plot_study import create_figures

            create_figures(stage / "figures", defense_returns, tdf_long_returns, tdf_recent_returns, tax, by_age)
        stage.rename(output)
    print(f"Saved {len(deliveries)} tables to {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-dir", type=Path, default=MARKET_DIR)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reader", help="Optional #14 adapter as module:factory")
    parser.add_argument("--paths", type=int, default=2000)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    run(args.market_dir.resolve(), args.output.resolve(), args.reader, args.paths, not args.no_plots)
