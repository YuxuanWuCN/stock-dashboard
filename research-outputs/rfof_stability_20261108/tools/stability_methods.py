"""Portfolio weighting algorithms for R-FOF defense sleeve stability comparison.

Implements FR-003:
- A0: Static baseline (36% Cash/Bond + 40% Large-Cap Value/Dividend + 24% Broad CSI300)
- A1: Ledoit-Wolf covariance shrinkage with constrained minimum variance
- A2: López de Prado (2016) Hierarchical Risk Parity (HRP)
- A3: Volatility Target dynamic cash overlay (strict no-leverage, target 8% p.a.)

All weighting functions are strictly point-in-time: they accept an estimation return
matrix up to date t-1 and produce target weights for day t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.optimize import minimize
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf

ANN_FACTOR = 252.0


def weights_a0(returns: pd.DataFrame) -> pd.Series:
    """A0 baseline: static allocation replicating SilverWealthAllocator defense sleeve.

    Sleeve structure:
    - 36% Cash / Pure-Bond (511010 or synthetic CASH)
    - 40% Large-Cap Value / Dividend (510050)
    - 24% Broad Market Equity (510300)

    If the universe lacks these specific assets, distribute proportionally among available.
    """
    assets = list(returns.columns)
    weights = pd.Series(0.0, index=assets, dtype=float)

    preferred_cash = "511010"
    preferred_val = "510050"
    preferred_broad = "510300"

    allocated = 0.0
    if preferred_cash in assets:
        weights[preferred_cash] = 0.36
        allocated += 0.36
    if preferred_val in assets:
        weights[preferred_val] = 0.40
        allocated += 0.40
    if preferred_broad in assets:
        weights[preferred_broad] = 0.24
        allocated += 0.24

    if allocated == 0.0:
        # Fallback to 1/N if none of the canonical three are present
        weights[:] = 1.0 / len(assets)
    elif not np.isclose(allocated, 1.0):
        # Renormalize among present assets
        weights = weights / weights.sum()

    return weights


def weights_lw_minvar(returns: pd.DataFrame, cap: float = 0.40) -> pd.Series:
    """A1: Minimum-variance portfolio under Ledoit-Wolf covariance shrinkage.

    Solves:
        min w.T @ Sigma_LW @ w
        s.t. sum(w) = 1, 0 <= w_i <= cap
    """
    clean_ret = returns.dropna(how="any")
    assets = list(returns.columns)
    n = len(assets)

    if clean_ret.shape[0] < 5:
        # Insufficient history for covariance estimation: fallback to equal weight
        return pd.Series(1.0 / n, index=assets, dtype=float)

    # Estimate shrunk covariance
    lw = LedoitWolf()
    lw.fit(clean_ret.values)
    cov = lw.covariance_

    # Objective: portfolio variance
    def port_var(w: np.ndarray) -> float:
        return float(w.T @ cov @ w)

    # Initial guess: equal weight clipped to cap
    w0 = np.full(n, 1.0 / n)
    bounds = [(0.0, float(cap)) for _ in range(n)]
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

    res = minimize(
        port_var,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 200, "ftol": 1e-8},
    )

    if res.success:
        raw_w = np.clip(res.x, 0.0, cap)
        norm_w = raw_w / np.sum(raw_w)
        return pd.Series(norm_w, index=assets, dtype=float)

    # Fallback to inverse variance if optimizer fails
    variances = np.diag(cov)
    inv_var = 1.0 / np.maximum(variances, 1e-8)
    inv_w = np.clip(inv_var / np.sum(inv_var), 0.0, cap)
    return pd.Series(inv_w / np.sum(inv_w), index=assets, dtype=float)


def _get_quasi_diag(link: np.ndarray) -> list[int]:
    """Sort clustered items to achieve quasi-diagonalization (López de Prado 2016)."""
    link = link.astype(int)
    sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
    num_items = link[-1, 3]
    while sort_ix.max() >= num_items:
        sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)
        df0 = sort_ix[sort_ix >= num_items]
        i = df0.index
        j = df0.values - num_items
        sort_ix[i] = link[j, 0]
        df0 = pd.Series(link[j, 1], index=i + 1)
        sort_ix = pd.concat([sort_ix, df0]).sort_index()
        sort_ix.index = range(sort_ix.shape[0])
    return sort_ix.tolist()


def _get_cluster_var(cov: np.ndarray, c_items: list[int]) -> float:
    """Compute variance of a cluster using inverse-variance asset weighting."""
    cov_slice = cov[np.ix_(c_items, c_items)]
    w_ = 1.0 / np.diag(cov_slice)
    w_ = w_ / np.sum(w_)
    return float(w_.T @ cov_slice @ w_)


def _get_rec_bipart(cov: np.ndarray, sort_ix: list[int]) -> pd.Series:
    """Compute HRP weights via recursive bisection."""
    w = pd.Series(1.0, index=sort_ix)
    c_items = [sort_ix]
    while len(c_items) > 0:
        c_items = [
            i[j:k]
            for i in c_items
            for j, k in ((0, len(i) // 2), (len(i) // 2, len(i)))
            if len(i) > 1
        ]
        for i in range(0, len(c_items), 2):
            c_items0 = c_items[i]
            c_items1 = c_items[i + 1]
            var0 = _get_cluster_var(cov, c_items0)
            var1 = _get_cluster_var(cov, c_items1)
            alpha = 1.0 - var0 / (var0 + var1)
            w[c_items0] *= alpha
            w[c_items1] *= 1.0 - alpha
    return w


def weights_hrp(returns: pd.DataFrame) -> pd.Series:
    """A2: Hierarchical Risk Parity (HRP) algorithm (López de Prado 2016)."""
    clean_ret = returns.dropna(how="any")
    assets = list(returns.columns)
    n = len(assets)

    if n <= 1:
        return pd.Series(1.0, index=assets, dtype=float)
    if clean_ret.shape[0] < 5:
        return pd.Series(1.0 / n, index=assets, dtype=float)

    corr = clean_ret.corr().fillna(0.0).values
    cov = clean_ret.cov().values

    # Step 1: Distance matrix D = sqrt(0.5 * (1 - corr))
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    # Step 2: Hierarchical tree clustering
    # Zero out diagonal to avoid negative zeros
    np.fill_diagonal(dist, 0.0)
    condensed_dist = squareform(dist, checks=False)
    link = linkage(condensed_dist, method="single")

    # Step 3: Quasi-diagonalization
    sort_ix = _get_quasi_diag(link)

    # Step 4: Recursive bisection
    raw_weights = _get_rec_bipart(cov, sort_ix)
    # Map back to asset names in original order
    ordered_assets = [assets[i] for i in raw_weights.index]
    result = pd.Series(raw_weights.values, index=ordered_assets).reindex(assets)
    return result / result.sum()


def vol_target_scale(
    port_ret: pd.Series,
    target_vol: float = 0.08,
    window: int = 60,
    max_leverage: float = 1.0,
) -> float:
    """A3: Volatility Target dynamic scaling factor (strict no-leverage).

    Computes:
        scale = min(max_leverage, target_vol / realized_vol)

    Unallocated proportion (1.0 - scale) is allocated to risk-free CASH.
    """
    clean = port_ret.dropna().tail(window)
    if len(clean) < 10:
        return 1.0

    realized_vol = float(clean.std() * np.sqrt(ANN_FACTOR))
    if realized_vol <= 1e-6:
        return float(max_leverage)

    raw_scale = target_vol / realized_vol
    return float(np.clip(raw_scale, 0.0, max_leverage))
