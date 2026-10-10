# src/core/math/fama_macbeth.py
"""
Rainbow-FinGPT v4.0 核心数学底层 —— Fama-MacBeth 资产定价与 Newey-West HAC 稳健标准误引擎
Unified Fama-MacBeth 2-Stage Cross-Sectional Regression with Newey-West HAC Standard Errors.
"""

from typing import Dict, Optional, Tuple, Union
import numpy as np
import pandas as pd
import statsmodels.api as sm


def calc_newey_west_lags(n_obs: int) -> int:
    """
    计算 Newey-West (1987) 自适应滞后带宽阶数:
    q = max(1, floor(4 * (T / 100)^(2/9)))
    
    参数:
        n_obs (int): 时间序列有效样本量 T
    返回:
        int: 稳健滞后阶数 q >= 1
    """
    if n_obs <= 0:
        return 1
    q = int(np.floor(4.0 * (float(n_obs) / 100.0) ** (2.0 / 9.0)))
    return max(1, q)


def run_ols_newey_west(
    y: np.ndarray,
    X: np.ndarray,
    lags: Optional[int] = None,
    add_constant: bool = True
) -> Dict[str, Union[float, np.ndarray]]:
    """
    单资产/单时序 OLS 回归配合 Newey-West HAC 异方差自相关稳健协方差修正。
    
    参数:
        y: (T,) 因变量 (如超额收益率)
        X: (T, K) 自变量矩阵 (如因子收益率)
        lags: 自定义滞后阶数，默认使用自适应 calc_newey_west_lags
        add_constant: 是否自动追加截距项 alpha
    
    返回:
        字典包含:
            - alpha: 截距项估计值 (若 add_constant=True)
            - betas: 斜率系数估计值 (K,)
            - t_stats: Newey-West 修正后的 t 统计量
            - p_values: 双侧显著性水平
            - residuals: 残差项 (T,)
            - r_squared: 回归判定系数
            - sigma_eps: 残差样本标准差 (带 1e-9 除零保护)
            - information_ratio: 信息比率 alpha / sigma_eps
    """
    T = len(y)
    if T < 5:
        raise ValueError(f"样本量不足以进行 HAC 稳健检验: T={T} < 5")
    
    if lags is None:
        lags = calc_newey_west_lags(T)
        
    X_reg = sm.add_constant(X) if add_constant else X
    model = sm.OLS(y, X_reg)
    res = model.fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    
    params = res.params
    tvalues = res.tvalues
    pvalues = res.pvalues
    resid = res.resid
    rsquared = float(res.rsquared)
    
    sigma_eps = float(np.std(resid, ddof=1))
    
    if add_constant:
        alpha = float(params[0])
        alpha_t = float(tvalues[0])
        alpha_p = float(pvalues[0])
        betas = np.array(params[1:], dtype=float)
        beta_t = np.array(tvalues[1:], dtype=float)
        beta_p = np.array(pvalues[1:], dtype=float)
        ir = alpha / max(sigma_eps, 1e-9) if sigma_eps > 1e-9 else 0.0
    else:
        alpha = 0.0
        alpha_t = 0.0
        alpha_p = 1.0
        betas = np.array(params, dtype=float)
        beta_t = np.array(tvalues, dtype=float)
        beta_p = np.array(pvalues, dtype=float)
        ir = 0.0
        
    return {
        "alpha": alpha,
        "alpha_t": alpha_t,
        "alpha_p": alpha_p,
        "betas": betas,
        "beta_t": beta_t,
        "beta_p": beta_p,
        "t_stats": tvalues,
        "p_values": pvalues,
        "residuals": resid,
        "r_squared": rsquared,
        "sigma_eps": sigma_eps,
        "information_ratio": float(ir),
        "hac_lags": lags,
        "n_obs": T
    }


class UnifiedFamaMacBeth:
    """全域统一 Fama-MacBeth 两阶段回归模型"""
    
    def __init__(self, lag_nw: Optional[int] = None):
        self.lag_nw = lag_nw

    def stage_one_time_series(
        self,
        excess_returns: pd.DataFrame,
        factors: pd.DataFrame
    ) -> Dict[str, Dict[str, float]]:
        """
        阶段一：对全池资产分别做时序回归，提取因子暴露 Beta 与特质 Alpha。
        
        excess_returns: (T, N) 各资产超额收益
        factors: (T, K) 因子超额收益
        """
        results = {}
        common_idx = excess_returns.index.intersection(factors.index)
        Y_all = excess_returns.loc[common_idx]
        X_all = factors.loc[common_idx].values
        
        for col in Y_all.columns:
            y = Y_all[col].dropna()
            valid_idx = y.index
            if len(y) < 15:
                continue
            X = factors.loc[valid_idx].values
            res = run_ols_newey_west(y.values, X, lags=self.lag_nw, add_constant=True)
            results[str(col)] = {
                "alpha": res["alpha"],
                "alpha_t": res["alpha_t"],
                "alpha_p": res["alpha_p"],
                "ir": res["information_ratio"],
                "r2": res["r_squared"],
                "sigma_eps": res["sigma_eps"],
                "betas": res["betas"]
            }
        return results
