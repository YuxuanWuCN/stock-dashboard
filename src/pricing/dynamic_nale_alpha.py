"""Bounded NALE gates with shared calibration and exact handoff loss."""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.decomposition import PCA

from src.graph.nale_alpha_adapter import propagate_nale_vectorized


def _finite(value: Any, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if not np.isfinite(arr).all():
        raise ValueError(f"{name} must contain only finite values")
    return arr


def sigmoid(u: Any) -> np.ndarray:
    """Stable sigmoid without clipping discontinuities."""
    return expit(_finite(u, "u"))


def sigmoid_derivative(u: Any) -> np.ndarray:
    """Derivative of the same function used for prediction."""
    s = sigmoid(u)
    return s * (1 - s)


def compute_alpha_gating(u: Any) -> np.ndarray:
    """Bound alpha to [0.05,0.75]; zero maps to 0.4."""
    return .05 + .70 * sigmoid(u)


# M1 收敛（规则 §8-V4）：传播核唯一权威实现位于
# ``src.graph.nale_alpha_adapter.propagate_nale_vectorized``。这里以**模块级别名**
# 方式再导出（而不是再写一层 def 包装），因此 ``is`` 同一性成立，任何一方被改动
# 都会被 ``tests/test_nale_propagation_authority.py`` 立刻发现。
# 语义完全不变：``S = S0 + alpha * ((S0 @ W.T) - S0)``。
propagate_nale = propagate_nale_vectorized


def calibrate_public_calibrator(S_B0: np.ndarray, Y_returns: np.ndarray,
                                min_c: float = 0.) -> tuple[float, float, float]:
    """Fit a+cS, c>=0, with equal dates and equal valid stocks per date.

    A vector is one cross section. NaN pairs are missing; infinity is invalid.
    Target variance is diagnostic only, never used to normalize the gate loss.
    """
    s, y = np.asarray(S_B0, float), np.asarray(Y_returns, float)
    if min_c != 0:
        raise ValueError("The handoff requires min_c=0")
    if s.shape != y.shape or s.ndim not in (1, 2):
        raise ValueError("Calibrator score and target shapes must match")
    if np.isinf(s).any() or np.isinf(y).any():
        raise ValueError("Calibrator inputs cannot contain infinity")
    s, y = np.atleast_2d(s), np.atleast_2d(y)
    valid = np.isfinite(s) & np.isfinite(y)
    if valid.sum() < 2:
        raise ValueError("Insufficient valid samples to calibrate public calibrator")
    weights = valid / np.maximum(valid.sum(1)[:, None], 1)
    weights /= weights.sum()
    ss, yy = np.where(valid, s, 0), np.where(valid, y, 0)
    ms, my = np.sum(weights * ss), np.sum(weights * yy)
    vs = float(np.sum(weights * (ss - ms) ** 2))
    vy = float(np.sum(weights * (yy - my) ** 2))
    cov = float(np.sum(weights * (ss - ms) * (yy - my)))
    c = max(0., cov / vs) if vs > 1e-14 else 0.
    return float(my - c * ms), float(c), vy


def compute_prediction_gradients(z_i: np.ndarray, D_i: float, u_i: float, c: float) -> tuple:
    """Return dy/db and dy/dw for independent numerical checks."""
    common = c * D_i * .70 * sigmoid_derivative(u_i)
    return common, common * _finite(z_i, "z")


def gate_design(z: np.ndarray, version: str, g: Any = 0., q: Any = 0.) -> np.ndarray:
    """Construct 11/22/33 regressors for Z[N,10] or Z[T,N,10]."""
    z = _finite(z, "Z")
    if z.ndim not in (2, 3) or z.shape[-1] != 10:
        raise ValueError("Z must have shape (N,10) or (T,N,10)")
    if version not in ("V1", "V2", "V3", "V4", "V5"):
        raise ValueError(f"Unknown version: {version}")
    ones = np.ones(z.shape[:-1] + (1,))
    def condition(value: Any) -> np.ndarray:
        arr = _finite(value, "condition")
        if z.ndim == 3 and arr.shape == (z.shape[0],):
            arr = arr[:, None]
        return np.broadcast_to(arr, z.shape[:-1])[..., None]
    if version in ("V1", "V2", "V3"):
        return np.concatenate([ones, z], axis=-1)
    gg = condition(g)
    if version == "V4":
        return np.concatenate([ones, gg, z, gg * z], axis=-1)
    qq = condition(q)
    return np.concatenate([ones, gg, qq, z, gg * z, qq * z], axis=-1)


def gate_loss_gradient(theta: np.ndarray, design: np.ndarray, s0: np.ndarray,
                       d: np.ndarray, y: np.ndarray, a: float, c: float,
                       weights: np.ndarray, l2_reg: float) -> tuple[float, np.ndarray]:
    """Exact date-weighted MSE plus regularization of ALL coefficients."""
    sig = expit(design @ theta)
    residual = a + c * (s0 + (.05 + .70 * sig) * d) - y
    loss = float(np.sum(weights * residual ** 2) + l2_reg * (theta @ theta))
    delta = 2 * weights * residual * c * d * .70 * sig * (1 - sig)
    grad = np.einsum("tn,tnk->k", delta, design) + 2 * l2_reg * theta
    return loss, grad


class DynamicNALEAlphaEstimator:
    """Frozen PCA and calibrated five-version nonlinear gate estimator."""

    def __init__(self, n_components: int = 10, l2_reg: float = .001,
                 half_life: float = 60., random_state: int = 42):
        if n_components != 10 or not np.isfinite(l2_reg) or l2_reg < 0:
            raise ValueError("Requires ten PCs and finite nonnegative regularization")
        if not np.isfinite(half_life) or half_life <= 0:
            raise ValueError("half_life must be positive")
        self.n_components, self.l2_reg = n_components, l2_reg
        self.half_life, self.random_state = half_life, random_state
        self.pca_model = None
        self.calibrator_a = self.calibrator_c = self.train_var_y = None
        self.last_fit_diagnostics: dict[str, Any] = {}

    def fit_pca(self, factors_768_df: pd.DataFrame) -> DynamicNALEAlphaEstimator:
        """Fit full SVD to historical training rows provided by the caller."""
        cols = [c for c in factors_768_df if c.startswith("dim_")]
        if not cols or factors_768_df.columns.duplicated().any():
            raise ValueError("Missing or duplicate dim_ feature columns")
        x = _finite(factors_768_df[cols].to_numpy(), "PCA input")
        self.feature_columns_ = cols
        self.pca_mean_, self.pca_std_ = x.mean(0), x.std(0)
        self.pca_std_[self.pca_std_ < 1e-12] = 1
        x = (x - self.pca_mean_) / self.pca_std_
        self.pca_model = PCA(n_components=10, svd_solver="full", random_state=self.random_state)
        if min(x.shape) <= 10:
            raise ValueError("Effective rank is less than required n_components")
        scores = self.pca_model.fit_transform(x)
        tol = np.finfo(float).eps * max(x.shape) * self.pca_model.singular_values_[0]
        if self.pca_model.singular_values_[-1] <= tol:
            self.pca_model = None
            raise ValueError("Effective rank is less than required n_components")
        self.pc_score_mean_, self.pc_score_std_ = scores.mean(0), scores.std(0)
        return self

    def transform_pca(self, factors_768_df: pd.DataFrame) -> pd.DataFrame:
        """Apply saved column semantics, basis, and scales."""
        if self.pca_model is None:
            raise RuntimeError("PCA model has not been fitted yet")
        cols = [c for c in factors_768_df if c.startswith("dim_")]
        if len(cols) != len(set(cols)) or set(cols) != set(self.feature_columns_):
            raise ValueError("PCA feature column schema changed")
        x = _finite(factors_768_df[self.feature_columns_].to_numpy(), "PCA input")
        scores = self.pca_model.transform((x - self.pca_mean_) / self.pca_std_)
        return pd.DataFrame((scores - self.pc_score_mean_) / self.pc_score_std_,
                            index=factors_768_df.index, columns=[f"PC{k+1:02d}" for k in range(10)])

    def calibrate(self, S0_train: np.ndarray, D_train: np.ndarray, Y_train: np.ndarray) -> tuple:
        """Store common B0 calibration; a zero slope is a valid fallback."""
        a, c, var = calibrate_public_calibrator(S0_train + .4 * D_train, Y_train)
        self.calibrator_a, self.calibrator_c, self.train_var_y = a, c, var
        return a, c

    def fit_gated_weights(self, S0_train: np.ndarray, D_train: np.ndarray,
                          Y_train: np.ndarray, Z_train: np.ndarray, version: str = "V1",
                          time_weights: np.ndarray | None = None,
                          g_regime: np.ndarray | None = None,
                          q_reliability: np.ndarray | None = None) -> np.ndarray:
        """Fit exact MSE and save diagnostics; failures return neutral gates."""
        if self.calibrator_a is None or self.calibrator_c is None:
            raise RuntimeError("Public calibrator not set")
        s0, d = _finite(S0_train, "S0"), _finite(D_train, "D")
        y = np.asarray(Y_train, float)
        if y.shape != s0.shape or d.shape != s0.shape or s0.ndim != 2:
            raise ValueError("Training arrays must have matching (T,N) shapes")
        if np.isinf(y).any():
            raise ValueError("Infinite target")
        z = _finite(Z_train, "Z")
        if z.ndim == 2:
            z = np.broadcast_to(z, s0.shape + (10,))
        if z.shape != s0.shape + (10,):
            raise ValueError("Z and training scores must align")
        design = gate_design(z, version, 0 if g_regime is None else g_regime,
                             0 if q_reliability is None else q_reliability)
        valid = np.isfinite(y)
        counts = valid.sum(1)
        wt = np.ones(len(s0)) if time_weights is None else _finite(time_weights, "weights")
        if wt.shape != (len(s0),) or np.any(wt < 0):
            raise ValueError("Invalid date weights")
        wt = wt * (counts > 0)
        if wt.sum() <= 0:
            raise ValueError("No positively weighted valid dates")
        weights = (wt / wt.sum())[:, None] * valid / np.maximum(counts[:, None], 1)
        y = np.where(valid, y, 0)
        theta0 = np.zeros(design.shape[-1])
        diag: dict[str, Any] = {"version": version, "initial_theta": theta0.tolist(),
                               "valid_samples": int(valid.sum()), "valid_dates": int((counts > 0).sum()),
                               "l2_reg": self.l2_reg, "fallback_reason": "", "success": False}
        self.last_fit_diagnostics = diag
        if self.calibrator_c == 0 or np.mean(np.abs(d[valid]) < 1e-12) > .5:
            diag.update(fallback_reason="unidentifiable_c_or_D", success=True)
            return theta0
        args = (design, s0, d, y, self.calibrator_a, self.calibrator_c, weights, self.l2_reg)
        res = minimize(gate_loss_gradient, theta0, args=args, jac=True, method="L-BFGS-B",
                       options={"ftol": 1e-14, "gtol": 1e-10, "maxiter": 500})
        diag.update(success=bool(res.success), message=str(res.message), objective=float(res.fun),
                    gradient_norm=float(np.linalg.norm(res.jac)), iterations=int(res.nit))
        if not res.success or not np.isfinite(res.x).all():
            diag["fallback_reason"] = "optimization_failed"
            return theta0
        return res.x

    def predict_alpha(self, Z: np.ndarray, theta: np.ndarray, version: str = "V1",
                      g: Any = 0., q: Any = 0.) -> np.ndarray:
        """Predict gates from an immutable historical coefficient snapshot."""
        z = _finite(Z, "Z")
        if version == "B0":
            return np.full(z.shape[:-1], .4)
        design = gate_design(z, version, g, q)
        theta = _finite(theta, "theta")
        if theta.shape != (design.shape[-1],):
            raise ValueError("Wrong coefficient count")
        return compute_alpha_gating(design @ theta)
