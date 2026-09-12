"""Paired out-of-sample diagnostics for NALE alpha experiment predictions.

These metrics describe prediction quality, not an executable portfolio. Net
Sharpe, drawdown, turnover, and fees require a separate trading-rule backtest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import rankdata


VERSIONS = ("B0", "B1", "V1", "V2", "V3", "V4", "V5")
MAIN_PAIRS = (("V1", "B0"), ("V2", "V1"), ("V3", "V2"), ("V4", "V3"), ("V5", "V4"))
B1_PAIRS = (("B1", "B0"), *((version, "B1") for version in VERSIONS[2:]))


@dataclass(frozen=True)
class EvaluationResult:
    daily_ics: pd.DataFrame
    version_comparison: pd.DataFrame
    paired_differences: pd.DataFrame
    phase: str
    evidence_class: str


def _validate_predictions(predictions: pd.DataFrame) -> tuple[pd.DataFrame, str, str]:
    if not isinstance(predictions, pd.DataFrame) or predictions.empty:
        raise ValueError("predictions must be a nonempty DataFrame")
    required = {"date", "code", "version", "phase", "evidence_class", "predicted_excess", "y_excess"}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"missing prediction columns: {sorted(missing)}")
    frame = predictions.copy()
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}", value) for value in frame["code"]):
        raise ValueError("code must be a six-digit string")
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) for value in frame["date"]):
        raise ValueError("date must be an ISO calendar date")
    try:
        for value in frame["date"]:
            date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date is not a valid calendar date") from exc
    if not set(frame["version"]).issubset(VERSIONS):
        raise ValueError("unknown NALE model version")
    if frame.duplicated(["date", "code", "version"]).any():
        raise ValueError("duplicate date/code/version prediction")
    if frame["phase"].nunique() != 1 or frame["evidence_class"].nunique() != 1:
        raise ValueError("one evaluation must contain one phase and evidence class")
    for field in ("predicted_excess", "y_excess"):
        try:
            frame[field] = pd.to_numeric(frame[field], errors="raise").astype(np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be numeric") from exc
        if not np.isfinite(frame[field].to_numpy()).all():
            raise ValueError(f"{field} contains NaN or Inf")
    if (frame.groupby(["date", "code"])["y_excess"].nunique() > 1).any():
        raise ValueError("versions disagree on the same realized excess-return label")
    return frame, str(frame["phase"].iloc[0]), str(frame["evidence_class"].iloc[0])


def _correlations(predicted: np.ndarray, realized: np.ndarray, min_stocks: int) -> tuple[float, float]:
    if predicted.size < min_stocks:
        return np.nan, np.nan
    if np.std(predicted) <= 1e-15 or np.std(realized) <= 1e-15:
        return np.nan, np.nan
    pearson = float(np.corrcoef(predicted, realized)[0, 1])
    ranked_prediction = rankdata(predicted, method="average")
    ranked_realization = rankdata(realized, method="average")
    if np.std(ranked_prediction) <= 1e-15 or np.std(ranked_realization) <= 1e-15:
        return pearson, np.nan
    rank_ic = float(np.corrcoef(ranked_prediction, ranked_realization)[0, 1])
    return pearson, rank_ic


def _bootstrap(values: np.ndarray, *, block_days: int, iterations: int, seed: int) -> tuple[float, float, float]:
    size = values.size
    if size < block_days:
        return np.nan, np.nan, np.nan
    generator = np.random.default_rng(seed)
    blocks_per_draw = (size + block_days - 1) // block_days
    starts = generator.integers(0, size - block_days + 1, size=(iterations, blocks_per_draw))
    draws = (starts[:, :, None] + np.arange(block_days)).reshape(iterations, -1)[:, :size]
    means = values[draws].mean(axis=1)
    lower, upper = np.quantile(means, [0.025, 0.975])
    lower_tail = (1 + np.count_nonzero(means <= 0)) / (iterations + 1)
    upper_tail = (1 + np.count_nonzero(means >= 0)) / (iterations + 1)
    p_value = min(1.0, 2.0 * min(lower_tail, upper_tail))
    return float(lower), float(upper), float(p_value)


def _pair_metrics(
    frame: pd.DataFrame,
    newer: str,
    baseline: str,
    *,
    min_stocks: int,
    block_days: int,
    iterations: int,
    seed: int,
    family: str,
) -> dict:
    name = newer + "-" + baseline
    record = {
        "comparison": name,
        "new_version": newer,
        "base_version": baseline,
        "family": family,
        "status": "missing_version",
        "n_paired_dates": 0,
        "n_common_stock_date": 0,
        "rank_ic_delta_mean": np.nan,
        "pearson_ic_delta_mean": np.nan,
        "rank_ic_ci_lower": np.nan,
        "rank_ic_ci_upper": np.nan,
        "rank_ic_p": np.nan,
        "holm_p": np.nan,
        "holm_family_size": 0,
        "block_days": block_days,
        "block_half_ci_lower": np.nan,
        "block_half_ci_upper": np.nan,
        "block_double_ci_lower": np.nan,
        "block_double_ci_upper": np.nan,
        "sample_warning": None,
    }
    if newer not in set(frame["version"]) or baseline not in set(frame["version"]):
        return record
    left = frame.loc[frame["version"] == newer, ["date", "code", "predicted_excess", "y_excess"]]
    right = frame.loc[frame["version"] == baseline, ["date", "code", "predicted_excess", "y_excess"]]
    aligned = left.merge(right, on=["date", "code"], suffixes=("_new", "_base"), how="inner")
    if not np.array_equal(aligned["y_excess_new"].to_numpy(), aligned["y_excess_base"].to_numpy()):
        raise ValueError("paired versions have inconsistent labels")
    daily_rank_deltas = []
    daily_pearson_deltas = []
    common_count = 0
    for _, group in aligned.groupby("date", sort=True):
        y = group["y_excess_new"].to_numpy()
        new_p, new_r = _correlations(group["predicted_excess_new"].to_numpy(), y, min_stocks)
        old_p, old_r = _correlations(group["predicted_excess_base"].to_numpy(), y, min_stocks)
        if np.isfinite(new_r) and np.isfinite(old_r):
            daily_rank_deltas.append(new_r - old_r)
            if np.isfinite(new_p) and np.isfinite(old_p):
                daily_pearson_deltas.append(new_p - old_p)
            common_count += len(group)
    values = np.asarray(daily_rank_deltas, dtype=np.float64)
    record["n_paired_dates"] = values.size
    record["n_common_stock_date"] = common_count
    if values.size == 0:
        record["status"] = "insufficient_daily_stocks_or_variance"
        return record
    record["rank_ic_delta_mean"] = float(values.mean())
    record["pearson_ic_delta_mean"] = float(np.mean(daily_pearson_deltas)) if daily_pearson_deltas else np.nan
    if values.size < block_days:
        record["status"] = "insufficient_paired_dates_for_bootstrap"
        return record
    lower, upper, p_value = _bootstrap(values, block_days=block_days, iterations=iterations, seed=seed)
    record.update({
        "status": "evaluated",
        "rank_ic_ci_lower": lower,
        "rank_ic_ci_upper": upper,
        "rank_ic_p": p_value,
        "sample_warning": "short_relative_to_block" if values.size < 2 * block_days else None,
    })
    half = max(1, block_days // 2)
    double = 2 * block_days
    half_lower, half_upper, _ = _bootstrap(values, block_days=half, iterations=iterations, seed=seed + 101)
    double_lower, double_upper, _ = _bootstrap(values, block_days=double, iterations=iterations, seed=seed + 202)
    record.update({
        "block_half_ci_lower": half_lower,
        "block_half_ci_upper": half_upper,
        "block_double_ci_lower": double_lower,
        "block_double_ci_upper": double_upper,
    })
    return record


def _holm_adjust(rows: list[dict], family: str) -> None:
    candidates = [index for index, row in enumerate(rows) if row["family"] == family and np.isfinite(row["rank_ic_p"])]
    candidates.sort(key=lambda index: rows[index]["rank_ic_p"])
    count = len(candidates)
    running = 0.0
    for rank, index in enumerate(candidates):
        running = max(running, min(1.0, (count - rank) * rows[index]["rank_ic_p"]))
        rows[index]["holm_p"] = running
        rows[index]["holm_family_size"] = count


def evaluate_versions(
    predictions: pd.DataFrame,
    *,
    horizon_days: int = 5,
    min_stocks: int = 20,
    bootstrap_iterations: int = 2000,
    block_days: int | None = None,
    seed: int = 42,
) -> EvaluationResult:
    """Evaluate every version and paired deltas on common stock/date rows."""
    if horizon_days not in {5, 20}:
        raise ValueError("supported evaluation horizons are 5 and 20 trading days")
    if not isinstance(min_stocks, int) or min_stocks < 2:
        raise ValueError("min_stocks must be at least two")
    if not isinstance(bootstrap_iterations, int) or bootstrap_iterations < 1:
        raise ValueError("bootstrap_iterations must be positive")
    if block_days is None:
        block_days = 10 if horizon_days == 5 else 40
    if not isinstance(block_days, int) or block_days < 1:
        raise ValueError("block_days must be positive")
    frame, phase, evidence_class = _validate_predictions(predictions)
    daily_records = []
    for (version, day), group in frame.groupby(["version", "date"], sort=True):
        pearson, rank_ic = _correlations(
            group["predicted_excess"].to_numpy(), group["y_excess"].to_numpy(), min_stocks,
        )
        daily_records.append({
            "version": version, "date": day, "n_stocks": len(group),
            "pearson_ic": pearson, "rank_ic": rank_ic,
        })
    daily = pd.DataFrame(daily_records)
    comparisons = []
    for version in VERSIONS:
        subset = frame.loc[frame["version"] == version]
        base = {
            "version": version, "phase": phase, "evidence_class": evidence_class,
            "status": "missing_version", "n_predictions": len(subset),
            "n_signal_dates": subset["date"].nunique(), "n_valid_ic_dates": 0,
            "pearson_ic_mean": np.nan, "rank_ic_mean": np.nan, "rank_icir": np.nan,
            "direction_accuracy_excess": np.nan, "direction_coverage": np.nan,
            "n_direction_scored": 0, "n_prediction_abstentions": 0,
            "n_true_zero": 0, "majority_class_rate": np.nan,
            "ordinary_direction_accuracy": np.nan,
            "ordinary_direction_status": "not_evaluable_without_raw_return_predictions",
            "net_sharpe": np.nan, "max_drawdown_loss": np.nan,
            "turnover": np.nan, "fees": np.nan,
            "strategy_status": "not_evaluable_without_executable_portfolio",
            "return_unit": "decimal", "icir_annualized": False,
        }
        if subset.empty:
            comparisons.append(base)
            continue
        version_daily = daily.loc[daily["version"] == version]
        valid_rank = version_daily["rank_ic"].dropna()
        valid_pearson = version_daily["pearson_ic"].dropna()
        predicted = subset["predicted_excess"].to_numpy()
        realized = subset["y_excess"].to_numpy()
        nonzero_prediction = predicted != 0
        nonzero_realization = realized != 0
        direction_sample = nonzero_prediction & nonzero_realization
        scored = int(direction_sample.sum())
        if scored:
            correct = np.sign(predicted[direction_sample]) == np.sign(realized[direction_sample])
            accuracy = float(correct.mean())
            realized_sign = realized[direction_sample]
            majority = float(max(np.count_nonzero(realized_sign > 0), np.count_nonzero(realized_sign < 0)) / scored)
        else:
            accuracy = np.nan
            majority = np.nan
        std_rank = float(valid_rank.std(ddof=1)) if len(valid_rank) >= 2 else np.nan
        base.update({
            "status": "evaluated" if len(valid_rank) else "insufficient_daily_stocks_or_variance",
            "n_valid_ic_dates": len(valid_rank),
            "pearson_ic_mean": float(valid_pearson.mean()) if len(valid_pearson) else np.nan,
            "rank_ic_mean": float(valid_rank.mean()) if len(valid_rank) else np.nan,
            "rank_icir": float(valid_rank.mean() / std_rank) if np.isfinite(std_rank) and std_rank > 0 else np.nan,
            "direction_accuracy_excess": accuracy,
            "direction_coverage": float(nonzero_prediction.mean()),
            "n_direction_scored": scored,
            "n_prediction_abstentions": int((~nonzero_prediction).sum()),
            "n_true_zero": int((~nonzero_realization).sum()),
            "majority_class_rate": majority,
        })
        comparisons.append(base)

    paired = []
    for index, (newer, baseline) in enumerate(MAIN_PAIRS):
        paired.append(_pair_metrics(
            frame, newer, baseline, min_stocks=min_stocks, block_days=block_days,
            iterations=bootstrap_iterations, seed=seed + index, family="main_adjacent_5",
        ))
    for index, (newer, baseline) in enumerate(B1_PAIRS):
        paired.append(_pair_metrics(
            frame, newer, baseline, min_stocks=min_stocks, block_days=block_days,
            iterations=bootstrap_iterations, seed=seed + 100 + index, family="b1_reference",
        ))
    _holm_adjust(paired, "main_adjacent_5")
    _holm_adjust(paired, "b1_reference")
    return EvaluationResult(
        daily_ics=daily,
        version_comparison=pd.DataFrame(comparisons),
        paired_differences=pd.DataFrame(paired),
        phase=phase, evidence_class=evidence_class,
    )
