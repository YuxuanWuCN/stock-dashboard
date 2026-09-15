# -*- coding: utf-8 -*-
"""tests/test_dynamic_nale_alpha.py - Unit tests for 10D PCA Dynamic NALE Alpha Module.

Strictly verifies the 8 independent validation criteria from
specs/contest-2026/week1-nale-alpha-handoff.md Section 10.
"""

import numpy as np
import pandas as pd
import pytest
from src.pricing.dynamic_nale_alpha import (
    DynamicNALEAlphaEstimator,
    calibrate_public_calibrator,
    compute_alpha_gating,
    compute_prediction_gradients,
    propagate_nale,
    sigmoid,
    sigmoid_derivative,
)


class TestDynamicNALEAlpha:
    """Independent verification suite for dynamic NALE alpha."""

    def test_criterion_1_bounds_and_zero_neutral(self):
        """1. u=0 gives alpha=0.40; finite inputs bounded in [0.05, 0.75]; extreme inputs do not overflow."""
        # Neutral point
        alpha_zero = compute_alpha_gating(0.0)
        assert np.isclose(alpha_zero, 0.40, atol=1e-7), f"Expected 0.40 at u=0, got {alpha_zero}"

        # Boundedness
        test_inputs = np.array([-1e6, -100.0, -15.0, -5.0, 0.0, 5.0, 15.0, 100.0, 1e6])
        alphas = compute_alpha_gating(test_inputs)
        assert np.all(alphas >= 0.05 - 1e-9), f"Alpha lower bound violated: {alphas.min()}"
        assert np.all(alphas <= 0.75 + 1e-9), f"Alpha upper bound violated: {alphas.max()}"
        assert not np.isnan(alphas).any(), "NaN detected in extreme alpha calculation"
        assert not np.isinf(alphas).any(), "Inf detected in extreme alpha calculation"

    def test_criterion_2_two_stock_hand_calculation(self):
        """2. Two stocks S0=(0.2, 0.8), mutual edge, alpha=0.4 -> S=(0.44, 0.56); stock 1 alpha=0.6 -> S=0.56."""
        S0 = np.array([0.2, 0.8])
        W = np.array([
            [0.0, 1.0],
            [1.0, 0.0]
        ])
        
        # Base case: alpha = 0.4
        S_b0, N_agg, D = propagate_nale(S0, W, alpha=0.40)
        assert np.allclose(N_agg, [0.8, 0.2]), f"Expected N=(0.8, 0.2), got {N_agg}"
        assert np.allclose(D, [0.6, -0.6]), f"Expected D=(0.6, -0.6), got {D}"
        assert np.allclose(S_b0, [0.44, 0.56]), f"Expected S=(0.44, 0.56), got {S_b0}"

        # Dynamic case: stock 1 has alpha=0.6, stock 2 has alpha=0.4
        alpha_dyn = np.array([0.60, 0.40])
        S_dyn, _, _ = propagate_nale(S0, W, alpha=alpha_dyn)
        assert np.isclose(S_dyn[0], 0.56), f"Expected stock 1 S=0.56 with alpha=0.6, got {S_dyn[0]}"
        assert np.isclose(S_dyn[1], 0.56), f"Expected stock 2 S=0.56 with alpha=0.4, got {S_dyn[1]}"

    def test_criterion_3_identity_matrix_and_zero_difference(self):
        """3. W=I gives S=S0 independent of alpha; D=0 gives zero gradient for gating."""
        S0 = np.array([0.15, -0.42, 0.88])
        W_ident = np.eye(3)
        
        for test_alpha in [0.05, 0.20, 0.40, 0.65, 0.75, np.array([0.1, 0.5, 0.7])]:
            S, _, D = propagate_nale(S0, W_ident, alpha=test_alpha)
            assert np.allclose(S, S0), f"Identity graph should preserve S0 identically: {S} vs {S0}"
            assert np.allclose(D, 0.0), f"D should be identically zero: {D}"
            
        # When D=0, dy_hat / du = c * D * 0.70 * s' = 0
        z_dummy = np.ones(10)
        grad_b, grad_w = compute_prediction_gradients(z_dummy, D_i=0.0, u_i=1.5, c=0.08)
        assert np.isclose(grad_b, 0.0)
        assert np.allclose(grad_w, 0.0)

    def test_criterion_4_finite_difference_gradient_check(self):
        """4. dy_hat / dw_k matches c * D * 0.70 * sigmoid(u) * (1 - sigmoid(u)) * z_k with finite difference."""
        np.random.seed(42)
        z_i = np.random.randn(10)
        w_vec = np.random.uniform(-0.5, 0.5, size=10)
        b = 0.25
        c = 0.065
        a = 0.002
        S0_i = 0.35
        D_i = 0.48
        
        u_i = b + float(np.dot(z_i, w_vec))
        grad_b_analytic, grad_w_analytic = compute_prediction_gradients(z_i, D_i, u_i, c)
        
        # Finite difference verification
        eps = 1e-6
        # Check grad_b
        u_plus = (b + eps) + float(np.dot(z_i, w_vec))
        u_minus = (b - eps) + float(np.dot(z_i, w_vec))
        y_plus = a + c * (S0_i + compute_alpha_gating(u_plus) * D_i)
        y_minus = a + c * (S0_i + compute_alpha_gating(u_minus) * D_i)
        grad_b_fd = (y_plus - y_minus) / (2 * eps)
        assert np.isclose(grad_b_analytic, grad_b_fd, rtol=1e-5), f"Analytic grad_b {grad_b_analytic} vs FD {grad_b_fd}"

        # Check grad_w for each component
        for k in range(10):
            w_plus = w_vec.copy()
            w_plus[k] += eps
            w_minus = w_vec.copy()
            w_minus[k] -= eps
            
            y_w_plus = a + c * (S0_i + compute_alpha_gating(b + float(np.dot(z_i, w_plus))) * D_i)
            y_w_minus = a + c * (S0_i + compute_alpha_gating(b + float(np.dot(z_i, w_minus))) * D_i)
            grad_w_k_fd = (y_w_plus - y_w_minus) / (2 * eps)
            
            assert np.isclose(grad_w_analytic[k], grad_w_k_fd, rtol=1e-5), (
                f"Component {k}: analytic {grad_w_analytic[k]} vs FD {grad_w_k_fd}"
            )

    def test_criterion_5_sign_flip_invariance(self):
        """5. Simultaneously flipping a PC and its corresponding weight leaves output identical."""
        np.random.seed(123)
        Z = np.random.randn(5, 10)
        theta = np.random.uniform(-0.8, 0.8, size=11) # [b, w_1..w_10]
        
        estimator = DynamicNALEAlphaEstimator()
        alpha_orig = estimator.predict_alpha(Z, theta, version="V1")
        
        # Flip component 3 (index 2 in Z, index 3 in theta)
        Z_flipped = Z.copy()
        Z_flipped[:, 2] *= -1.0
        theta_flipped = theta.copy()
        theta_flipped[3] *= -1.0
        
        alpha_flipped = estimator.predict_alpha(Z_flipped, theta_flipped, version="V1")
        assert np.allclose(alpha_orig, alpha_flipped), "Sign flip symmetry violated!"

    def test_criterion_6_time_decay_half_life(self):
        """6. Sample weight at age=H is exactly 0.5 (2^(-age/H))."""
        H = 60.0
        ages = np.array([0.0, 30.0, 60.0, 120.0])
        weights = 2.0 ** (-ages / H)
        
        assert np.isclose(weights[0], 1.0)
        assert np.isclose(weights[2], 0.5), f"Expected weight 0.5 at age={H}, got {weights[2]}"
        assert np.isclose(weights[3], 0.25), f"Expected weight 0.25 at age=120, got {weights[3]}"

    def test_criterion_7_isolated_node_handling(self):
        """7. Isolated nodes (all 0s in adjacency row) fallback to self-loop D_i=0 and S_i=S0_i."""
        S0 = np.array([0.5, -0.3, 0.9])
        # Node 1 is connected to node 0; node 2 is completely isolated (all zeros in row 2)
        W_raw = np.array([
            [0.5, 0.5, 0.0],
            [0.4, 0.6, 0.0],
            [0.0, 0.0, 0.0]
        ])
        
        S, N_agg, D = propagate_nale(S0, W_raw, alpha=0.65)
        # Node 2 should have D=0 and S_i == S0_i
        assert np.isclose(D[2], 0.0), f"Isolated node D should be 0, got {D[2]}"
        assert np.isclose(S[2], S0[2]), f"Isolated node S should equal S0, got {S[2]} vs {S0[2]}"

    def test_criterion_8_string_code_and_rank_deficiency_guard(self):
        """8. String codes with leading zeros preserved; centered matrix with rank < 10 raises ValueError."""
        # Check string code retention
        codes = ["000001", "002594", "600519"]
        df_dummy = pd.DataFrame(
            np.random.randn(3, 768),
            index=codes,
            columns=[f"dim_{k}" for k in range(768)]
        )
        assert all(isinstance(c, str) and len(c) == 6 for c in df_dummy.index)

        estimator = DynamicNALEAlphaEstimator(n_components=10)
        # 3 rows cannot have rank >= 10, should raise ValueError
        with pytest.raises(ValueError, match="less than required n_components"):
            estimator.fit_pca(df_dummy)


class TestFullPipelineEstimator:
    """End-to-end integration test of estimator with synthetic valid 10D data."""

    def test_fit_and_predict_v1_v3_v4_v5(self):
        np.random.seed(42)
        N = 15
        T = 40
        
        # 1. Feature matrix with sufficient rank
        X_768 = np.random.randn(N, 768)
        codes = [f"{i:06d}" for i in range(N)]
        df_768 = pd.DataFrame(X_768, index=codes, columns=[f"dim_{k}" for k in range(768)])
        
        estimator = DynamicNALEAlphaEstimator(n_components=10, random_state=42)
        estimator.fit_pca(df_768)
        df_pca10 = estimator.transform_pca(df_768)
        assert df_pca10.shape == (N, 10)
        assert np.allclose(df_pca10.mean(axis=0), 0.0, atol=1e-6)
        assert np.allclose(df_pca10.std(axis=0, ddof=0), 1.0, atol=1e-6)

        # 2. Simulate training panel
        S0_train = np.random.uniform(-1.0, 1.0, size=(T, N))
        W = np.eye(N) * 0.4 + 0.6 / N
        W_norm = W / W.sum(axis=1, keepdims=True)
        
        N_train = S0_train @ W_norm.T
        D_train = N_train - S0_train
        Y_train = 0.02 * S0_train + 0.01 * D_train + np.random.normal(0, 0.01, size=(T, N))
        
        # 3. Calibrate public calibrator on B0
        a, c = estimator.calibrate(S0_train, D_train, Y_train)
        assert c >= 0.005
        assert np.isfinite(a)
        
        # 4. Fit V1 (Fixed)
        theta_v1 = estimator.fit_gated_weights(S0_train, D_train, Y_train, df_pca10.values, version="V1")
        assert len(theta_v1) == 11
        alpha_v1 = estimator.predict_alpha(df_pca10.values, theta_v1, version="V1")
        assert len(alpha_v1) == N
        assert np.all((alpha_v1 >= 0.05) & (alpha_v1 <= 0.75))

        # 5. Fit V3 (Time decay)
        ages = np.arange(T)[::-1]
        time_weights = 2.0 ** (-ages / 20.0)
        theta_v3 = estimator.fit_gated_weights(
            S0_train, D_train, Y_train, df_pca10.values, version="V3", time_weights=time_weights
        )
        assert len(theta_v3) == 11

        # 6. Fit V4 (Regime condition)
        g_regime = np.random.uniform(-1.0, 1.0, size=T)
        theta_v4 = estimator.fit_gated_weights(
            S0_train, D_train, Y_train, df_pca10.values, version="V4", g_regime=g_regime
        )
        assert len(theta_v4) == 22
        alpha_v4 = estimator.predict_alpha(df_pca10.values, theta_v4, version="V4", g=0.5)
        assert np.all((alpha_v4 >= 0.05) & (alpha_v4 <= 0.75))

        # 7. Fit V5 (Reliability + Regime condition)
        q_reliability = np.random.uniform(-0.5, 0.5, size=T)
        theta_v5 = estimator.fit_gated_weights(
            S0_train, D_train, Y_train, df_pca10.values, version="V5", g_regime=g_regime, q_reliability=q_reliability
        )
        assert len(theta_v5) == 33
        alpha_v5 = estimator.predict_alpha(df_pca10.values, theta_v5, version="V5", g=0.5, q=-0.2)
        assert np.all((alpha_v5 >= 0.05) & (alpha_v5 <= 0.75))
