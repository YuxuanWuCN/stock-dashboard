
"""China personal-pension tax and paired decumulation scenarios for ages 60–85."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategies.trend_gate import detect_trend

AGING = np.arange(60, 86)
CONTRIBUTION = 12_000
WITHDRAWAL_TAX = 0.03
BASE_WITHDRAWAL = 0.048
INFLATION = 0.02
SEED = 20261112


def income_tax(taxable: float) -> float:
    """Annual comprehensive income tax on the already taxable income in CNY."""
    ends = (36_000, 144_000, 300_000, 420_000, 660_000, 960_000, float("inf"))
    rates = (.03, .10, .20, .25, .30, .35, .45)
    return sum(rate * max(0., min(taxable, hi) - lo)
               for lo, hi, rate in zip((0, *ends[:-1]), ends, rates))


def annuity_future_value(contribution: float, annual_return: float, years: int) -> float:
    if years < 1 or not np.isfinite(annual_return) or annual_return <= -1 or contribution < 0:
        raise ValueError("invalid accumulation scenario")
    return contribution * sum((1 + annual_return) ** year for year in range(years))


def eet_table(annual_return: float, years: int = 30) -> pd.DataFrame:
    """Compare accounts funded with equal working-age out-of-pocket cost."""
    rows = []
    for rate, taxable in ((3, 30_000), (10, 100_000), (20, 200_000)):
        tax = income_tax(taxable)
        saving = tax - income_tax(taxable - CONTRIBUTION)
        gross_wage = taxable + 60_000
        net_wage = gross_wage - tax
        eet_balance = annuity_future_value(CONTRIBUTION, annual_return, years)
        annual_sacrifice = CONTRIBUTION - saving
        outside_balance = annuity_future_value(annual_sacrifice, annual_return, years)
        eet_gross = eet_balance * BASE_WITHDRAWAL
        outside_gross = outside_balance * BASE_WITHDRAWAL
        eet_net = eet_gross * (1 - WITHDRAWAL_TAX)
        rows.append({
            "marginal_tax_pct": rate, "years": years, "net_nominal_return_assumption_pct": annual_return * 100,
            "annual_gross_wage_cny": gross_wage, "annual_taxable_income_before_eet_cny": taxable,
            "annual_net_wage_before_eet_cny": net_wage, "annual_eet_contribution_cny": CONTRIBUTION,
            "annual_tax_saving_cny": saving, "annual_equal_sacrifice_cny": annual_sacrifice,
            "eet_end_balance_cny": eet_balance, "outside_end_balance_cny": outside_balance,
            "eet_gross_first_withdrawal_cny": eet_gross, "eet_first_withdrawal_tax_cny": eet_gross * WITHDRAWAL_TAX,
            "eet_net_first_withdrawal_cny": eet_net, "outside_net_first_withdrawal_cny": outside_gross,
            "outside_gross_replacement_pct": 100 * outside_gross / gross_wage,
            "eet_gross_replacement_pct": 100 * eet_gross / gross_wage,
            "outside_net_replacement_pct": 100 * outside_gross / net_wage,
            "eet_net_replacement_pct": 100 * eet_net / net_wage,
            "net_replacement_gain_pp": 100 * (eet_net - outside_gross) / net_wage,
        })
    return pd.DataFrame(rows)


def block_indices(length: int, horizon: int, block: int, paths: int, seed: int) -> np.ndarray:
    """Sample blocks with replacement and keep order within every block."""
    if not 1 <= block <= length or horizon < 1 or paths < 1:
        raise ValueError("invalid path count, horizon or block length")
    rng = np.random.default_rng(seed)
    count = (horizon + block - 1) // block
    starts = rng.integers(0, length - block + 1, size=(paths, count), dtype=np.int32)
    return (starts[..., None] + np.arange(block, dtype=np.int32)).reshape(paths, -1)[:, :horizon]


def annual_withdrawals(
    returns: np.ndarray,
    cash_returns: np.ndarray,
    gate_closed: np.ndarray,
    initial: float,
    *,
    dynamic: bool,
    inflation: float = INFLATION,
    medical_rate: float = 0.012,
) -> dict[str, np.ndarray]:
    """Withdraw at start of year. Medical liability is identical for both policies."""
    if (
        returns.ndim != 2 or returns.shape[1] != len(AGING)
        or returns.shape != cash_returns.shape or returns.shape != gate_closed.shape
        or not np.isfinite(returns).all() or not np.isfinite(cash_returns).all()
        or (returns <= -1).any() or (cash_returns <= -1).any()
        or not np.isfinite([initial, inflation, medical_rate]).all()
        or initial <= 0 or inflation <= -1 or medical_rate < 0
    ):
        raise ValueError("invalid retirement scenario")
    accounts = np.full(returns.shape[0], initial, dtype=float)
    reserve = np.zeros_like(accounts)
    records = {key: np.zeros(returns.shape) for key in (
        "end_balance", "reserve", "full_living", "requested_living", "requested_medical",
        "paid_living", "paid_medical",
    )}
    for year, age in enumerate(AGING):
        price_level = (1 + inflation) ** year
        living = BASE_WITHDRAWAL * initial * price_level
        medical = medical_rate * initial * price_level if age >= 78 else 0.0
        if dynamic and age == 78:
            transfer = 0.20 * accounts
            reserve += transfer
            accounts -= transfer
        spending = living * (np.where(gate_closed[:, year], 0.8, 1.0) if dynamic else 1.0)
        drawn_reserve = np.minimum(reserve, medical)
        reserve -= drawn_reserve
        drawn_account = np.minimum(accounts, medical - drawn_reserve)
        accounts -= drawn_account
        paid_living = np.minimum(accounts, spending)
        accounts -= paid_living
        accounts *= 1 + returns[:, year]
        reserve *= 1 + cash_returns[:, year]
        records["end_balance"][:, year] = accounts + reserve
        records["reserve"][:, year] = reserve
        records["full_living"][:, year] = living
        records["requested_living"][:, year] = spending
        records["requested_medical"][:, year] = medical
        records["paid_living"][:, year] = paid_living
        records["paid_medical"][:, year] = drawn_reserve + drawn_account
    records["ruined"] = records["end_balance"][:, -1] <= 1e-8
    return records


def opening_trend(benchmark: pd.Series) -> pd.Series:
    wealth = (1 + benchmark.dropna()).cumprod().to_numpy()
    closed = [detect_trend(wealth[max(0, i - 60):i].tolist())[0] == "downtrend"
              for i in range(len(wealth))]
    return pd.Series(closed, index=benchmark.dropna().index, name="trend_gate_closed")


def simulate_retirement(
    daily: pd.DataFrame, initial: float, *, paths: int = 2000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bootstrap aligned real-history blocks as hypothetical future years."""
    trading_days = 252
    horizon = len(AGING) * trading_days
    records, age_records = [], []
    if not daily.index.is_monotonic_increasing or daily.index.has_duplicates or daily.isna().any().any():
        raise ValueError("retirement inputs require unique chronological dates and complete paired rows")
    for scenario, block, stress, medical_rate in (
        ("63d_blocks", 63, False, 0.012),
        ("126d_blocks", 126, False, 0.012),
        ("lower_drift_3pct", 63, False, 0.012),
        ("worst_observed_first_block", 63, True, 0.012),
        ("double_medical_liability", 63, False, 0.024),
    ):
        indices = block_indices(len(daily), horizon, block, paths, SEED)
        stress_start = ""
        if stress:
            log = np.log1p(daily["portfolio_return"]).to_numpy()
            worst = int(np.convolve(log, np.ones(block), mode="valid").argmin())
            indices[:, :block] = np.arange(worst, worst + block)
            stress_start = daily.index[worst].date().isoformat()
        annual = {}
        for name in ("portfolio_return", "cash_return"):
            logs = np.log1p(daily[name].to_numpy())
            if scenario == "lower_drift_3pct" and name == "portfolio_return":
                logs = logs - logs.mean() + np.log1p(.03) / trading_days
            annual[name] = np.expm1(logs[indices].reshape(paths, len(AGING), trading_days).sum(axis=2))
        gate = daily["trend_gate_closed"].to_numpy(dtype=bool)[indices[:, ::trading_days]]
        fixed_ruin = None
        for policy in ("fixed_4_8", "dynamic_guardrail"):
            result = annual_withdrawals(
                annual["portfolio_return"], annual["cash_return"], gate, initial,
                dynamic=policy == "dynamic_guardrail", medical_rate=medical_rate,
            )
            ruined = result["ruined"]
            if fixed_ruin is None:
                fixed_ruin = ruined
            delta = ruined.astype(float) - fixed_ruin.astype(float)
            real = (1 + INFLATION) ** np.arange(len(AGING))
            end_real = result["end_balance"] / real
            net_living = (result["paid_living"] / real).sum(axis=1) * (1 - WITHDRAWAL_TAX)
            net_medical = (result["paid_medical"] / real).sum(axis=1) * (1 - WITHDRAWAL_TAX)
            gap = (result["full_living"] - result["paid_living"]) / real
            records.append({
                "scenario": scenario, "policy": policy, "block_days": block, "paths": paths, "seed": SEED,
                "hist_daily_obs": len(daily), "stress_first_block_date": stress_start,
                "starting_balance_cny": initial, "medical_budget_pct_of_initial": 100 * medical_rate,
                "ruined_paths": int(ruined.sum()), "ruin_by_85_pct": 100 * ruined.mean(),
                "paired_ruin_delta_pp": 100 * delta.mean(),
                "paired_delta_mc_se_pp": 100 * delta.std(ddof=1) / np.sqrt(paths) if paths > 1 else np.nan,
                "some_planned_living_unpaid_pct": 100 * (result["paid_living"] + 1e-8 < result["requested_living"]).any(axis=1).mean(),
                "some_medical_unpaid_pct": 100 * (result["paid_medical"] + 1e-8 < result["requested_medical"]).any(axis=1).mean(),
                "median_real_net_living_cny": np.median(net_living),
                "p10_real_net_living_cny": np.quantile(net_living, .10),
                "median_real_net_medical_cny": np.median(net_medical),
                "median_real_full_living_gap_cny": np.median(gap.sum(axis=1)),
                "median_end_real_balance_cny": np.median(end_real[:, -1]),
            })
            for k, age in enumerate(AGING):
                age_records.append({
                    "scenario": scenario, "policy": policy, "age": age,
                    "balance_p10_real_cny": np.quantile(end_real[:, k], .1),
                    "balance_median_real_cny": np.median(end_real[:, k]),
                    "balance_p90_real_cny": np.quantile(end_real[:, k], .9),
                    "ruin_by_age_pct": 100 * (result["end_balance"][:, k] <= 1e-8).mean(),
                    "median_real_medical_reserve_cny": np.median(result["reserve"][:, k] / real[k]),
                    "mean_net_real_living_cny": (result["paid_living"][:, k] / real[k]).mean() * (1 - WITHDRAWAL_TAX),
                })
    return pd.DataFrame(records), pd.DataFrame(age_records)
