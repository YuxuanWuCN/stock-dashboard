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


def normalize_network(adjacency: np.ndarray, size: int | None = None) -> np.ndarray:
    """权威的行归一化实现（唯一入口，供网络工厂与传播层共用）。

    * 邻接矩阵必须为方阵、有限、非负；行和 > 0 的行按行和缩放；
    * 行和 = 0 的孤立行置为**自环**（``W[i, i] = 1``），即"无邻居 ⇒ N = S0"；
    * 本函数只做归一化，不做阈值/稀疏化，也不接受负权重。

    Parameters
    ----------
    adjacency : np.ndarray
        原始邻接矩阵（N×N）。
    size : int | None
        可选的期望阶数；给定时会与矩阵阶数校验。

    Returns
    -------
    np.ndarray
        行归一化（孤立行为自环）的矩阵，浮点新数组，不修改入参。
    """
    matrix = np.asarray(adjacency, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("adjacency must be an N x N matrix")
    if size is not None and matrix.shape[0] != int(size):
        raise ValueError("adjacency size does not match the declared universe")
    return _normalize_network(matrix, matrix.shape[0])


def propagate_nale_vectorized(
    S0: np.ndarray,
    W_norm: np.ndarray,
    alpha: np.ndarray | float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """唯一权威的向量化 NALE 传播核（M1 收敛结果，规则 §8-V4）。

    语义与原 `src/pricing/dynamic_nale_alpha.propagate_nale` 完全一致：
    ``S = S0 + alpha * ((S0 @ W.T) - S0)``，输入校验规则如下：

    * ``S0`` 一维或二维、有限；``W_norm`` 为 ``(n, n)`` 有限非负方阵，且
      每行行和要么≈1（已归一化），要么=0（孤立行，会被置为自环）；
    * ``alpha`` 标量或按资产广播的向量，取值须在 ``[0, 1]``。

    Parameters
    ----------
    S0 : np.ndarray
        自有得分向量（或批处理矩阵）。
    W_norm : np.ndarray
        行归一化（或全零孤立行）的邻接矩阵；本函数**不再二次归一化**。
    alpha : np.ndarray | float
        传播系数（标量或按资产广播）。

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray]
        ``(S, N, D)``：传播后得分、邻居聚合 ``N = S0 @ W.T``、差分 ``D = N - S0``。
    """
    s = np.asarray(S0, dtype=float)
    w = np.asarray(W_norm, dtype=float)
    a = np.asarray(alpha, dtype=float)
    if not (np.isfinite(s).all() and np.isfinite(w).all() and np.isfinite(a).all()):
        raise ValueError("S0, W and alpha must all be finite")
    if s.ndim not in (1, 2) or w.shape != (s.shape[-1], s.shape[-1]):
        raise ValueError("S0 and W shapes do not align")
    if np.any(w < 0) or np.any((a < 0) | (a > 1)):
        raise ValueError("W must be nonnegative and alpha must be in [0,1]")
    sums = w.sum(1)
    if not np.all(np.isclose(sums, 1) | (sums == 0)):
        raise ValueError("W must be row-normalized")
    w = w.copy()
    isolated = np.flatnonzero(sums == 0)
    w[isolated, isolated] = 1
    n = s @ w.T
    d = n - s
    output = s + a * d
    if output.shape != s.shape:
        raise ValueError("alpha broadcasting changed the score shape")
    return output, n, d


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
    # 与权威核的一致性自证（等式恒成立；不是运行时校验，仅防未来改写时静默漂移）
    core_score, core_n, core_d = propagate_nale_vectorized(self_score, network, alpha)
    assert np.array_equal(score, core_score) and np.array_equal(neighbor_score, core_n) and np.array_equal(difference, core_d)
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
