"""Common NALE propagation path for fixed and learned mixing weights.

This adapter does not infer point-in-time network evidence. Callers must supply
the network and scores that were available at the signal cutoff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class NALEAlphaResult:
    codes: tuple[str, ...]
    s0: np.ndarray
    neighbor_score: np.ndarray
    difference: np.ndarray
    normalized_network: np.ndarray
    z: np.ndarray | None
    contributions: np.ndarray | None
    u: np.ndarray | None
    alpha_nale: np.ndarray
    score: np.ndarray


def _finite_vector(values: Sequence[float], size: int, name: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if result.shape != (size,) or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite vector of length {size}")
    return result


def _normalize_network(adjacency: np.ndarray, size: int) -> np.ndarray:
    network = np.asarray(adjacency, dtype=np.float64)
    if network.shape != (size, size):
        raise ValueError("adjacency must be an N x N matrix")
    if not np.isfinite(network).all() or (network < 0).any():
        raise ValueError("adjacency must contain finite nonnegative weights")

    row_sum = network.sum(axis=1)
    if not np.isfinite(row_sum).all():
        raise ValueError("adjacency row sums must be finite")
    normalized = np.divide(
        network,
        row_sum[:, None],
        out=np.zeros_like(network),
        where=row_sum[:, None] > 0,
    )
    isolated = np.flatnonzero(row_sum == 0)
    normalized[isolated, isolated] = 1.0
    return normalized


def _bounded_sigmoid(u: np.ndarray) -> np.ndarray:
    result = np.empty_like(u)
    positive = u >= 0
    result[positive] = 1.0 / (1.0 + np.exp(-u[positive]))
    negative_exp = np.exp(u[~positive])
    result[~positive] = negative_exp / (1.0 + negative_exp)
    return result


def propagate_nale(
    codes: Sequence[str],
    s0: Sequence[float],
    adjacency: np.ndarray,
    *,
    z: np.ndarray | None = None,
    weights: Sequence[float] | None = None,
    intercept: float = 0.0,
    alpha_override: float | Sequence[float] | None = None,
) -> NALEAlphaResult:
    """Apply B0, an external per-node alpha, or the ten-PC learned gate.

    ``alpha_override`` lets the existing event-based B1 provide its own alpha.
    Learned weights and an override are mutually exclusive so a caller cannot
    silently bypass the ten-PC model.
    """
    ordered_codes = tuple(codes)
    size = len(ordered_codes)
    if not size or any(not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code) for code in ordered_codes):
        raise ValueError("codes must be nonempty six-digit strings")
    if len(set(ordered_codes)) != size:
        raise ValueError("duplicate stock code")

    self_score = _finite_vector(s0, size, "s0")
    network = _normalize_network(adjacency, size)
    pc_scores = None
    if z is not None:
        pc_scores = np.asarray(z, dtype=np.float64)
        if pc_scores.shape != (size, 10) or not np.isfinite(pc_scores).all():
            raise ValueError("z must be a finite N x 10 matrix")

    if weights is not None:
        if pc_scores is None or alpha_override is not None:
            raise ValueError("learned weights require z and exclude alpha_override")
        gate_weights = _finite_vector(weights, 10, "weights")
        if not np.isfinite(intercept):
            raise ValueError("intercept must be finite")
        contributions = pc_scores * gate_weights[None, :]
        u = float(intercept) + contributions.sum(axis=1)
        if not np.isfinite(contributions).all() or not np.isfinite(u).all():
            raise ValueError("gate linear predictor overflowed")
        alpha = 0.05 + 0.70 * _bounded_sigmoid(u)
    else:
        if intercept != 0.0:
            raise ValueError("intercept requires learned weights")
        contributions = None
        u = None
        if alpha_override is None:
            alpha = np.full(size, 0.4, dtype=np.float64)
        else:
            raw_alpha = np.asarray(alpha_override, dtype=np.float64)
            alpha = np.full(size, float(raw_alpha), dtype=np.float64) if raw_alpha.shape == () else raw_alpha
            if alpha.shape != (size,) or not np.isfinite(alpha).all() or (alpha < 0.05).any() or (alpha > 0.75).any():
                raise ValueError("alpha_override must be finite and within [0.05, 0.75]")

    neighbor_score = network @ self_score
    difference = neighbor_score - self_score
    score = self_score + alpha * difference
    if not np.isfinite(score).all():
        raise ValueError("propagated score overflowed")
    return NALEAlphaResult(
        codes=ordered_codes,
        s0=self_score,
        neighbor_score=neighbor_score,
        difference=difference,
        normalized_network=network,
        z=pc_scores,
        contributions=contributions,
        u=u,
        alpha_nale=alpha,
        score=score,
    )
