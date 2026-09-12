"""B0 calibration and ten-component NALE gates for the Week1 experiment.

Inputs here are an already audited, point-in-time training panel. No market
file in this repository is silently treated as a real historical panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.optimize import check_grad, minimize
from scipy.special import expit


@dataclass(frozen=True)
class TrainingPanel:
    signal_dates: Sequence[str]
    label_available_at: Sequence[str]
    s0: Sequence[float]
    difference: Sequence[float]
    z: np.ndarray
    excess_return: Sequence[float]
    age_trading_days: Sequence[int] | None = None


@dataclass(frozen=True)
class B0Calibration:
    intercept: float
    slope: float
    fit_cutoff: str
    n_signal_dates: int
    n_rows: int

    def predict(self, score: np.ndarray) -> np.ndarray:
        return self.intercept + self.slope * np.asarray(score, dtype=np.float64)


@dataclass(frozen=True)
class GateFit:
    version: str
    intercept: float
    weights: np.ndarray
    calibration: B0Calibration
    ridge_lambda: float
    half_life_days: float | None
    fit_cutoff: str
    n_signal_dates: int
    n_rows: int
    converged: bool
    objective: float
    gradient_norm: float
    gradient_check_error: float | None
    optimizer_message: str
    fallback_reason: str | None
    initial_parameters: tuple[float, ...] = (0.0,) * 11

    def alpha(self, z: np.ndarray) -> np.ndarray:
        scores = np.asarray(z, dtype=np.float64)
        if scores.ndim != 2 or scores.shape[1] != 10 or not np.isfinite(scores).all():
            raise ValueError("z must be a finite N x 10 matrix")
        if self.fallback_reason is not None:
            return np.full(scores.shape[0], 0.4)
        linear = self.intercept + scores @ self.weights
        if not np.isfinite(linear).all():
            raise ValueError("gate linear predictor overflowed")
        return 0.05 + 0.70 * expit(linear)

    def predict(self, s0: Sequence[float], difference: Sequence[float], z: np.ndarray) -> np.ndarray:
        scores = np.asarray(s0, dtype=np.float64)
        deltas = np.asarray(difference, dtype=np.float64)
        if scores.ndim != 1 or scores.shape != deltas.shape or not np.isfinite(scores).all() or not np.isfinite(deltas).all():
            raise ValueError("s0 and difference must be finite equal-length vectors")
        alpha = self.alpha(z)
        if alpha.shape != scores.shape:
            raise ValueError("z row count must match s0")
        prediction = self.calibration.predict(scores + alpha * deltas)
        if not np.isfinite(prediction).all():
            raise ValueError("calibrated prediction overflowed")
        return prediction


def _finite_vector(values: Sequence[float], size: int, name: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if result.shape != (size,) or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite vector of length {size}")
    return result


def _validated_panel(panel: TrainingPanel, fit_cutoff: str, min_train_dates: int):
    cutoff = pd.Timestamp(fit_cutoff)
    if pd.isna(cutoff) or cutoff.tzinfo is None:
        raise ValueError("fit_cutoff must include an explicit timezone")
    cutoff_utc = cutoff.tz_convert("UTC")
    cutoff_local_day = cutoff.tz_convert("Asia/Shanghai").date()
    size = len(panel.signal_dates)
    if size == 0 or len(panel.label_available_at) != size:
        raise ValueError("signal and label availability rows must align")
    try:
        signal_days = np.asarray([np.datetime64(date.fromisoformat(str(value))) for value in panel.signal_dates])
    except (TypeError, ValueError) as exc:
        raise ValueError("signal_dates must be ISO calendar dates") from exc
    if any(day >= np.datetime64(cutoff_local_day) for day in signal_days):
        raise ValueError("signal date is not before fit cutoff")
    for value in panel.label_available_at:
        available = pd.Timestamp(value)
        if pd.isna(available) or available.tzinfo is None or available.tz_convert("UTC") >= cutoff_utc:
            raise ValueError("all labels must be mature before the fit cutoff")
    unique_days = np.unique(signal_days)
    if min_train_dates < 1 or unique_days.size < min_train_dates:
        raise ValueError("insufficient mature signal dates")

    self_score = _finite_vector(panel.s0, size, "s0")
    difference = _finite_vector(panel.difference, size, "difference")
    y = _finite_vector(panel.excess_return, size, "excess_return")
    z = np.asarray(panel.z, dtype=np.float64)
    if z.shape != (size, 10) or not np.isfinite(z).all():
        raise ValueError("z must be a finite N x 10 matrix")
    return signal_days, self_score, difference, z, y, cutoff


def date_sample_weights(
    signal_days: Sequence[np.datetime64],
    *,
    age_trading_days: Sequence[int] | None = None,
    half_life_days: float | None = None,
) -> np.ndarray:
    """Weight dates, then divide each date's weight equally among its stocks."""
    days = np.asarray(signal_days, dtype="datetime64[D]")
    if days.ndim != 1 or days.size == 0 or np.isnat(days).any():
        raise ValueError("signal_days must be nonempty valid dates")
    unique_days, inverse, counts = np.unique(days, return_inverse=True, return_counts=True)
    if half_life_days is None:
        if age_trading_days is not None:
            raise ValueError("age_trading_days requires half_life_days")
        date_weight = np.ones(unique_days.size, dtype=np.float64)
    else:
        if not np.isfinite(half_life_days) or half_life_days <= 0 or age_trading_days is None:
            raise ValueError("V3 requires a positive half-life and actual trading-day ages")
        ages = _finite_vector(age_trading_days, days.size, "age_trading_days")
        if (ages < 0).any() or (ages != np.floor(ages)).any():
            raise ValueError("trading-day ages must be nonnegative integers")
        per_date_age = np.empty(unique_days.size, dtype=np.float64)
        for index in range(unique_days.size):
            same_day = ages[inverse == index]
            if not np.all(same_day == same_day[0]):
                raise ValueError("all stocks on a date must share the same trading-day age")
            per_date_age[index] = same_day[0]
        if unique_days.size < 2 or not np.all(np.diff(per_date_age) < 0):
            raise ValueError("trading-day ages must decrease across training dates")
        date_weight = np.exp2(-per_date_age / float(half_life_days))
        if not np.isfinite(date_weight).all() or date_weight.sum() <= 0:
            raise ValueError("time weights are not identifiable")
    return date_weight[inverse] / counts[inverse] / date_weight.sum()


def _fit_b0(
    s0: np.ndarray, difference: np.ndarray, y: np.ndarray,
    uniform_weights: np.ndarray, cutoff: pd.Timestamp, n_dates: int,
) -> B0Calibration:
    baseline_score = s0 + 0.4 * difference
    mean_x = float(np.dot(uniform_weights, baseline_score))
    mean_y = float(np.dot(uniform_weights, y))
    centered_x = baseline_score - mean_x
    variance = float(np.dot(uniform_weights, centered_x * centered_x))
    covariance = float(np.dot(uniform_weights, centered_x * (y - mean_y)))
    slope = max(0.0, covariance / variance) if variance > 1e-15 else 0.0
    intercept = mean_y - slope * mean_x
    return B0Calibration(intercept, slope, cutoff.isoformat(), n_dates, y.size)


def fit_b0_calibration(
    panel: TrainingPanel, *, fit_cutoff: str, min_train_dates: int = 126,
) -> B0Calibration:
    days, s0, difference, _, y, cutoff = _validated_panel(panel, fit_cutoff, min_train_dates)
    return _fit_b0(s0, difference, y, date_sample_weights(days), cutoff, np.unique(days).size)


def gate_loss_and_gradient(
    theta: np.ndarray,
    *,
    z: np.ndarray,
    s0: np.ndarray,
    difference: np.ndarray,
    y: np.ndarray,
    calibration: B0Calibration,
    sample_weights: np.ndarray,
    ridge_lambda: float,
) -> tuple[float, np.ndarray]:
    """Exact date-weighted nonlinear objective and analytic gradient."""
    parameters = np.asarray(theta, dtype=np.float64)
    features = np.asarray(z, dtype=np.float64)
    size = features.shape[0] if features.ndim == 2 else 0
    if parameters.shape != (11,) or not np.isfinite(parameters).all() or features.shape != (size, 10) or not np.isfinite(features).all():
        raise ValueError("theta and z must be finite with 11 and 10 dimensions")
    score = _finite_vector(s0, size, "s0")
    delta = _finite_vector(difference, size, "difference")
    target = _finite_vector(y, size, "y")
    row_weight = _finite_vector(sample_weights, size, "sample_weights")
    if (row_weight < 0).any() or not np.isclose(row_weight.sum(), 1.0):
        raise ValueError("sample_weights must be nonnegative and sum to one")
    if not np.isfinite(ridge_lambda) or ridge_lambda < 0 or calibration.slope < 0:
        raise ValueError("invalid ridge penalty or calibration slope")
    linear = parameters[0] + features @ parameters[1:]
    if not np.isfinite(linear).all():
        raise ValueError("gate linear predictor overflowed")
    sigmoid = expit(linear)
    alpha = 0.05 + 0.70 * sigmoid
    residual = calibration.intercept + calibration.slope * (score + alpha * delta) - target
    objective = float(np.dot(row_weight, residual * residual) + ridge_lambda * np.dot(parameters, parameters))
    shared = 2.0 * row_weight * residual * calibration.slope * delta * 0.70 * sigmoid * (1.0 - sigmoid)
    gradient = np.empty(11, dtype=np.float64)
    gradient[0] = shared.sum()
    gradient[1:] = features.T @ shared
    gradient += 2.0 * ridge_lambda * parameters
    if not np.isfinite(objective) or not np.isfinite(gradient).all():
        raise ValueError("non-finite gate objective or gradient")
    return objective, gradient


def fit_gate(
    panel: TrainingPanel,
    *,
    version: str,
    fit_cutoff: str,
    ridge_lambda: float,
    half_life_days: float | None = None,
    min_train_dates: int = 126,
) -> GateFit:
    """Fit V1/V2/V3 parameters; the caller controls once/monthly scheduling."""
    if version not in {"V1", "V2", "V3"}:
        raise ValueError("version must be V1, V2, or V3")
    if not np.isfinite(ridge_lambda) or ridge_lambda < 0:
        raise ValueError("ridge_lambda must be finite and nonnegative")
    days, s0, difference, z, y, cutoff = _validated_panel(panel, fit_cutoff, min_train_dates)
    n_dates = np.unique(days).size
    uniform_weights = date_sample_weights(days)
    calibration = _fit_b0(s0, difference, y, uniform_weights, cutoff, n_dates)
    if version == "V3":
        row_weights = date_sample_weights(
            days, age_trading_days=panel.age_trading_days, half_life_days=half_life_days,
        )
    else:
        if half_life_days is not None:
            raise ValueError("half_life_days applies only to V3")
        row_weights = uniform_weights

    initial = np.zeros(11, dtype=np.float64)

    def objective_and_grad(theta: np.ndarray) -> tuple[float, np.ndarray]:
        return gate_loss_and_gradient(
            theta, z=z, s0=s0, difference=difference, y=y,
            calibration=calibration, sample_weights=row_weights,
            ridge_lambda=ridge_lambda,
        )

    initial_objective, initial_gradient = objective_and_grad(initial)

    def fallback(reason: str, message: str, gradient_error: float | None = None) -> GateFit:
        return GateFit(
            version=version, intercept=0.0, weights=np.zeros(10),
            calibration=calibration, ridge_lambda=float(ridge_lambda),
            half_life_days=half_life_days, fit_cutoff=cutoff.isoformat(),
            n_signal_dates=n_dates, n_rows=y.size, converged=False,
            objective=initial_objective,
            gradient_norm=float(np.linalg.norm(initial_gradient)),
            gradient_check_error=gradient_error, optimizer_message=message,
            fallback_reason=reason,
        )

    if calibration.slope <= 1e-12:
        return fallback("calibration_slope_zero", "B0 calibration has no positive slope")
    if np.mean(np.abs(difference) <= 1e-12) > 0.5:
        return fallback("network_difference_unidentifiable", "most rows have D=0")

    try:
        error = float(check_grad(
            lambda theta: objective_and_grad(theta)[0],
            lambda theta: objective_and_grad(theta)[1], initial,
        ))
        if not np.isfinite(error) or error > 1e-4 * (1.0 + np.linalg.norm(initial_gradient)):
            return fallback("gradient_check_failed", "analytic gradient differs from finite difference", error)
        result = minimize(objective_and_grad, initial, method="L-BFGS-B", jac=True, options={"maxiter": 500})
        if not result.success or not np.isfinite(result.x).all() or not np.isfinite(result.fun):
            return fallback("optimizer_failed", str(result.message), error)
        final_objective, final_gradient = objective_and_grad(result.x)
    except (ArithmeticError, ValueError, RuntimeError) as exc:
        return fallback("optimizer_failed", str(exc))

    return GateFit(
        version=version, intercept=float(result.x[0]), weights=np.asarray(result.x[1:], dtype=np.float64),
        calibration=calibration, ridge_lambda=float(ridge_lambda),
        half_life_days=half_life_days, fit_cutoff=cutoff.isoformat(),
        n_signal_dates=n_dates, n_rows=y.size, converged=True,
        objective=final_objective, gradient_norm=float(np.linalg.norm(final_gradient)),
        gradient_check_error=error, optimizer_message=str(result.message), fallback_reason=None,
    )
