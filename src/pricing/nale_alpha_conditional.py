"""V4/V5 conditional NALE gates. Engineering code, not an empirical result.

The caller owns point-in-time construction of PCA scores, S0, graph, labels,
market bars, and frozen out-of-sample prediction snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


@dataclass(frozen=True)
class ReliabilityObservation:
    code: str
    signal_date: date
    prediction_asof: datetime
    label_available_at: datetime
    actual_excess_return: float
    solo_prediction: float
    network_prediction: float


@dataclass(frozen=True)
class ReliabilityValue:
    q: float
    available: bool
    mature_days: int


def reliability_from_frozen_history(
    observations: Sequence[ReliabilityObservation],
    *,
    code: str,
    decision_cutoff: datetime,
    window_days: int = 60,
    min_days: int = 20,
) -> ReliabilityValue:
    """Compare frozen solo/network squared errors on mature signal days.

    Predictions made after their signal date are rejected, never backfilled.
    Missing history gives q=0 with an explicit unavailable marker.
    """
    if window_days < min_days or min_days < 1:
        raise ValueError("invalid reliability window")
    selected = []
    for row in observations:
        if row.code != code or row.signal_date >= decision_cutoff.date():
            continue
        if row.prediction_asof.date() > row.signal_date:
            raise ValueError("historical prediction was created after its signal date")
        if row.label_available_at > decision_cutoff:
            continue
        values = (row.actual_excess_return, row.solo_prediction, row.network_prediction)
        if not all(np.isfinite(value) for value in values):
            raise ValueError("nonfinite frozen reliability observation")
        selected.append(row)
    selected.sort(key=lambda row: row.signal_date)
    dates = [row.signal_date for row in selected]
    if len(dates) != len(set(dates)):
        raise ValueError("duplicate reliability signal date")
    selected = selected[-window_days:]
    if len(selected) < min_days:
        return ReliabilityValue(0.0, False, len(selected))
    solo = np.array([(r.actual_excess_return - r.solo_prediction) ** 2 for r in selected])
    network = np.array([(r.actual_excess_return - r.network_prediction) ** 2 for r in selected])
    return ReliabilityValue(float(np.mean(solo - network)), True, len(selected))


def market_state_from_history(benchmark_closes: Sequence[float]) -> float:
    """MA20/MA60 - 1 from the last 60 decision-visible benchmark closes."""
    closes = np.asarray(benchmark_closes, dtype=np.float64)
    if closes.ndim != 1 or len(closes) < 60 or not np.all(np.isfinite(closes[-60:])):
        raise ValueError("market state requires 60 observed benchmark closes")
    if np.any(closes[-60:] <= 0):
        raise ValueError("benchmark closes must be positive")
    return float(np.mean(closes[-20:]) / np.mean(closes[-60:]) - 1.0)


@dataclass(frozen=True)
class ConditionalPanel:
    dates: np.ndarray
    age_days: np.ndarray
    z: np.ndarray
    g: np.ndarray
    q: np.ndarray | None
    q_available: np.ndarray | None
    s0: np.ndarray
    d: np.ndarray
    y: np.ndarray


@dataclass(frozen=True)
class ContextScale:
    g_mean: float
    g_std: float
    q_mean: float | None
    q_std: float | None


@dataclass(frozen=True)
class ConditionalFit:
    version: str
    theta: np.ndarray
    scale: ContextScale | None
    status: str
    reason: str | None
    n_observations: int
    n_dates: int
    initial_objective: float | None
    final_objective: float | None
    gradient_max_abs_error: float | None
    optimizer_success: bool


def _validated_panel(panel: ConditionalPanel, version: str) -> tuple[int, np.ndarray]:
    if version not in {"V4", "V5"}:
        raise ValueError("conditional version must be V4 or V5")
    z = np.asarray(panel.z, dtype=np.float64)
    if z.ndim != 2 or z.shape[1] != 10:
        raise ValueError("z must have exactly ten PC columns")
    n = len(z)
    for name in ("dates", "age_days", "g", "s0", "d", "y"):
        value = np.asarray(getattr(panel, name))
        if value.ndim != 1 or len(value) != n:
            raise ValueError(f"{name} must have one value per observation")
    for name in ("age_days", "g", "s0", "d", "y"):
        if not np.all(np.isfinite(np.asarray(getattr(panel, name), dtype=np.float64))):
            raise ValueError(f"nonfinite {name}")
    if not np.all(np.isfinite(z)) or np.any(np.asarray(panel.age_days) < 0):
        raise ValueError("nonfinite PCs or negative training age")
    if version == "V5":
        if panel.q is None or panel.q_available is None:
            raise ValueError("V5 needs q values and availability markers")
        q = np.asarray(panel.q, dtype=np.float64)
        available = np.asarray(panel.q_available)
        if q.shape != (n,) or available.shape != (n,) or not np.all(np.isfinite(q)):
            raise ValueError("invalid q observations")
    return n, z


def _scale_context(panel: ConditionalPanel, version: str) -> ContextScale:
    g = np.asarray(panel.g, dtype=np.float64)
    g_std = float(np.std(g))
    if g_std <= 1e-12:
        raise ValueError("market state is unidentifiable")
    if version == "V4":
        return ContextScale(float(np.mean(g)), g_std, None, None)
    q = np.asarray(panel.q, dtype=np.float64)
    available = np.asarray(panel.q_available, dtype=bool)
    if not np.any(available):
        raise ValueError("no mature network reliability observations")
    q_std = float(np.std(q[available]))
    if q_std <= 1e-12:
        raise ValueError("network reliability is unidentifiable")
    return ContextScale(float(np.mean(g)), g_std, float(np.mean(q[available])), q_std)


def _design(
    z: np.ndarray, g: np.ndarray, q: np.ndarray | None,
    q_available: np.ndarray | None, scale: ContextScale, version: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    g_scaled = np.clip((g - scale.g_mean) / scale.g_std, -3.0, 3.0)
    columns = [np.ones(len(z)), z.T, g_scaled, (z * g_scaled[:, None]).T]
    x = np.column_stack([np.ones(len(z)), z, g_scaled, z * g_scaled[:, None]])
    if version == "V5":
        available = np.asarray(q_available, dtype=bool)
        q_scaled = np.zeros(len(z), dtype=np.float64)
        q_scaled[available] = np.clip(
            (q[available] - scale.q_mean) / scale.q_std, -3.0, 3.0
        )
        x = np.column_stack([x, q_scaled, z * q_scaled[:, None]])
    else:
        q_scaled = None
    return x, g_scaled, q_scaled


def _date_weights(dates: np.ndarray, ages: np.ndarray, half_life: int) -> tuple[np.ndarray, int]:
    if half_life <= 0:
        raise ValueError("half_life must be positive")
    unique, inverse, counts = np.unique(dates, return_inverse=True, return_counts=True)
    if len(unique) == 0:
        raise ValueError("empty training panel")
    age_by_date = np.zeros(len(unique))
    for j in range(len(unique)):
        date_ages = ages[inverse == j]
        if not np.all(date_ages == date_ages[0]):
            raise ValueError("training age must be constant within a date")
        age_by_date[j] = date_ages[0]
    date_weight = np.exp2(-age_by_date / half_life)
    if not np.any(date_weight > 0):
        raise ValueError("all time weights underflowed")
    row_weight = date_weight[inverse] / counts[inverse] / np.sum(date_weight)
    return row_weight, len(unique)


def _fallback(version: str, reason: str, n: int, n_dates: int) -> ConditionalFit:
    return ConditionalFit(version, np.zeros(22 if version == "V4" else 33), None,
                          "fallback_b0", reason, n, n_dates, None, None, None, False)


def fit_conditional_gate(
    panel: ConditionalPanel, *, version: str, a: float, c: float,
    ridge: float, half_life: int, maxiter: int = 500,
) -> ConditionalFit:
    """Fit date-balanced, time-weighted bounded nonlinear gate with L2 ridge."""
    n, z = _validated_panel(panel, version)
    if not all(np.isfinite(v) for v in (a, c, ridge)) or c < 0 or ridge < 0:
        raise ValueError("invalid frozen calibration or ridge")
    weights, n_dates = _date_weights(np.asarray(panel.dates), np.asarray(panel.age_days, dtype=float), half_life)
    n_params = 22 if version == "V4" else 33
    if n <= n_params or c <= 1e-12 or np.mean(np.abs(panel.d) <= 1e-12) > 0.5:
        return _fallback(version, "gate_unidentifiable", n, n_dates)
    try:
        scale = _scale_context(panel, version)
    except ValueError as exc:
        return _fallback(version, str(exc), n, n_dates)
    x, _, _ = _design(z, np.asarray(panel.g, dtype=float),
                      None if panel.q is None else np.asarray(panel.q, dtype=float),
                      panel.q_available, scale, version)
    y = np.asarray(panel.y, dtype=float)
    s0 = np.asarray(panel.s0, dtype=float)
    d = np.asarray(panel.d, dtype=float)

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        sigmoid = expit(x @ theta)
        alpha = 0.05 + 0.70 * sigmoid
        residual = a + c * (s0 + alpha * d) - y
        value = float(np.sum(weights * residual**2) + ridge * (theta @ theta))
        local = c * d * 0.70 * sigmoid * (1.0 - sigmoid)
        gradient = 2.0 * (x.T @ (weights * residual * local) + ridge * theta)
        return value, gradient

    zero = np.zeros(n_params, dtype=np.float64)
    initial, analytic = objective(zero)
    eps = 1e-6
    numeric = np.empty(n_params)
    for j in range(n_params):
        delta = np.zeros(n_params)
        delta[j] = eps
        numeric[j] = (objective(delta)[0] - objective(-delta)[0]) / (2 * eps)
    gradient_error = float(np.max(np.abs(numeric - analytic)))
    if gradient_error > 1e-4:
        return _fallback(version, "gradient_check_failed", n, n_dates)
    result = minimize(objective, zero, jac=True, method="L-BFGS-B", options={"maxiter": maxiter})
    if not result.success or not np.all(np.isfinite(result.x)) or not np.isfinite(result.fun):
        return _fallback(version, "optimizer_failed", n, n_dates)
    return ConditionalFit(version, np.asarray(result.x, dtype=float), scale, "fitted", None,
                          n, n_dates, initial, float(result.fun), gradient_error, True)


def predict_conditional_gate(
    fit: ConditionalFit, *, z: np.ndarray, g: np.ndarray,
    q: np.ndarray | None, q_available: np.ndarray | None,
    s0: np.ndarray, d: np.ndarray, a: float, c: float,
) -> dict[str, np.ndarray]:
    """Apply frozen scaling/coefficients; fallback uses the common B0 alpha=0.4."""
    z = np.asarray(z, dtype=float)
    g = np.asarray(g, dtype=float)
    s0 = np.asarray(s0, dtype=float)
    d = np.asarray(d, dtype=float)
    if z.ndim != 2 or z.shape[1] != 10 or any(v.shape != (len(z),) for v in (g, s0, d)):
        raise ValueError("invalid prediction shapes")
    if not all(np.all(np.isfinite(v)) for v in (z, g, s0, d)):
        raise ValueError("nonfinite prediction input")
    if fit.version == "V5":
        if q is None or q_available is None or np.asarray(q).shape != (len(z),):
            raise ValueError("V5 prediction requires q and availability")
        if not np.all(np.isfinite(np.asarray(q, dtype=float))):
            raise ValueError("nonfinite q")
    if fit.status == "fallback_b0":
        alpha = np.full(len(z), 0.4)
        u = np.full(len(z), np.nan)
        g_scaled = np.full(len(z), np.nan)
        q_scaled = None if fit.version == "V4" else np.zeros(len(z))
    else:
        x, g_scaled, q_scaled = _design(z, g, None if q is None else np.asarray(q, dtype=float),
                                         q_available, fit.scale, fit.version)
        u = x @ fit.theta
        alpha = 0.05 + 0.70 * expit(u)
    score = s0 + alpha * d
    return {"u": u, "alpha_nale": alpha, "score": score,
            "predicted_excess_return": a + c * score,
            "g_scaled": g_scaled,
            "q_scaled": q_scaled if q_scaled is not None else np.full(len(z), np.nan),
            "q_missing": np.zeros(len(z), dtype=bool) if fit.version == "V4" else ~np.asarray(q_available, dtype=bool)}
