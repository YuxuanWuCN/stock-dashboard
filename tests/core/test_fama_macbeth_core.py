# tests/core/test_fama_macbeth.py
"""
Rainbow-FinGPT v4.0 核心数学底层单元测试
Unit Tests for Unified Fama-MacBeth, Gram-Schmidt Orthogonalization, and Alpha Gate.
"""

import numpy as np
import pytest
from src.core.math.fama_macbeth import calc_newey_west_lags, run_ols_newey_west
from src.core.math.orthogonalization import gram_schmidt_orthogonalize, pca_dimension_reduction
from src.core.math.alpha_gate import AlphaStatisticalGate


def test_calc_newey_west_lags():
    """测试 Newey-West 自适应滞后阶数计算"""
    assert calc_newey_west_lags(0) == 1
    assert calc_newey_west_lags(100) == 4  # floor(4 * 1.0) = 4
    assert calc_newey_west_lags(252) >= 4


def test_ols_newey_west_reproducibility():
    """测试 OLS + Newey-West HAC 基础回归数值稳定性"""
    np.random.seed(42)
    T = 150
    X = np.random.randn(T, 2)
    true_beta = np.array([1.5, -0.8])
    true_alpha = 0.05
    noise = np.random.randn(T) * 0.1
    y = true_alpha + X @ true_beta + noise
    
    res = run_ols_newey_west(y, X, add_constant=True)
    
    assert abs(res["alpha"] - true_alpha) < 0.05
    assert np.allclose(res["betas"], true_beta, atol=0.05)
    assert res["r_squared"] > 0.90
    assert res["information_ratio"] > 0.0
    assert res["hac_lags"] == calc_newey_west_lags(T)


def test_gram_schmidt_orthogonalization():
    """测试 Gram-Schmidt 正交化矩阵性质: Q.T @ Q == I_k 且 X == Q @ R"""
    np.random.seed(101)
    T, K = 100, 3
    X = np.random.randn(T, K)
    
    Q, R = gram_schmidt_orthogonalize(X)
    
    # 校验 Q 的各列标准正交
    I_k = np.eye(K)
    assert np.allclose(Q.T @ Q, I_k, atol=1e-10)
    
    # 校验重构恢复 X == Q @ R
    assert np.allclose(Q @ R, X, atol=1e-10)


def test_alpha_statistical_gate():
    """测试双重一票否决代码门禁与除零安全保护"""
    gate = AlphaStatisticalGate(p_threshold=0.05, ir_threshold=0.30)
    
    # 案例 1: 达标 (p < 0.05 且 IR >= 0.30)
    res1 = gate.evaluate("600519", alpha=0.04, sigma_eps=0.10, p_value=0.02)
    assert res1.veto_passed is True
    assert res1.information_ratio == pytest.approx(0.40)
    
    # 案例 2: p 值不显著一票否决
    res2 = gate.evaluate("000001", alpha=0.04, sigma_eps=0.10, p_value=0.08)
    assert res2.veto_passed is False
    assert "p-value" in str(res2.rejection_reason)
    
    # 案例 3: IR 不达标一票否决
    res3 = gate.evaluate("000002", alpha=0.01, sigma_eps=0.10, p_value=0.01)
    assert res3.veto_passed is False
    assert "IR" in str(res3.rejection_reason)
    
    # 案例 4: 零残差/除零安全保护
    res4 = gate.evaluate("688981", alpha=0.05, sigma_eps=0.0, p_value=0.01)
    assert res4.veto_passed is False
    assert res4.information_ratio == 0.0
