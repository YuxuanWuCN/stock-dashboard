# -*- coding: utf-8 -*-
"""src/analysis/famamacbethv3.py —— Two-Stage Fama-MacBeth OLS Kernel with Harvey (2016) Factor Prune Gate (Weeks 2-3)

依据规范：
1. 《StockDashboard v3.0 & Serenity Chokepoint 12-Week Roadmap》Phase I: Weeks 2–3
2. Stage 1: Rolling-window Time-Series OLS -> 资产因子暴露 beta_{i,k} 与 VIF 共线性诊断
3. Stage 2: Cross-Sectional OLS -> 风险溢价 gamma_t 与特异性 Alpha 剥离
4. Newey-West HAC 协方差自适应修正：q = max(1, floor(4 * (T/100)^(2/9)))
5. Harvey et al. (2016) Factor Prune Gate: |t| < 3.0 伪因子自动修剪与抑制
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import scipy.stats as stats

logger = logging.getLogger("famamacbethv3")


@dataclass
class Stage1Result:
    """Stage 1 时序回归估计结果。"""
    ticker: str
    alpha: float
    betas: Dict[str, float]
    beta_tstats: Dict[str, float]
    residual_std: float
    r_squared: float
    vif: Dict[str, float]
    dynamic_covariance: np.ndarray
    n_obs: int


@dataclass
class Stage2Result:
    """Stage 2 截面回归与因子检验结果。"""
    gamma_0: float  # 截距 (平均未解释超额收益)
    risk_premiums: Dict[str, float]  # 各因子平均风险溢价 gamma_k
    premium_tstats: Dict[str, float]  # Newey-West HAC t 统计量
    premium_pvalues: Dict[str, float]
    pruned_factors: List[str]  # 被 |t| < 3.0 规则剔除的因子列表
    active_factors: List[str]  # 最终保留的高显著性因子列表
    hac_lags: int
    idiosyncratic_alphas: Dict[str, float]  # 各个标的的纯特异性 Alpha


class FamaMacBethV3Engine:
    """学术与工业级两阶段 Fama-MacBeth 计量回归引擎。"""

    def __init__(
        self,
        t_stat_threshold: float = 3.0,  # Harvey et al. (2016) 因子修剪阈值
        use_adaptive_hac: bool = True
    ):
        self.t_stat_threshold = t_stat_threshold
        self.use_adaptive_hac = use_adaptive_hac

    @staticmethod
    def calc_adaptive_hac_lags(n_obs: int) -> int:
        """根据 Andrews (1991) 与 Newey-West 最优准则计算自适应滞后阶数。
        公式: q = max(1, floor(4 * (T / 100)^(2/9)))
        """
        if n_obs <= 0:
            return 1
        return max(1, int(math.floor(4.0 * ((n_obs / 100.0) ** (2.0 / 9.0)))))

    @staticmethod
    def calculate_vif(X: pd.DataFrame) -> Dict[str, float]:
        """计算自变量多重共线性方差膨胀因子 (VIF)。"""
        vif_dict = {}
        cols = list(X.columns)
        if len(cols) <= 1:
            return {c: 1.0 for c in cols}

        for i, col in enumerate(cols):
            y_i = X[col]
            X_other = X.drop(columns=[col])
            X_mat = np.column_stack([np.ones(len(X_other)), X_other.values])
            try:
                beta, residuals, _, _ = np.linalg.lstsq(X_mat, y_i.values, rcond=None)
                y_pred = X_mat @ beta
                ss_tot = np.sum((y_i.values - np.mean(y_i.values)) ** 2)
                ss_res = np.sum((y_i.values - y_pred) ** 2)
                r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0
                vif = 1.0 / (1.0 - r2) if (1.0 - r2) > 1e-8 else 999.0
            except Exception:
                vif = 1.0
            vif_dict[col] = float(vif)
        return vif_dict

    def run_stage1_time_series(
        self,
        returns: pd.Series,
        factors_df: pd.DataFrame,
        ticker: str = "ASSET",
        window_size: Optional[int] = None
    ) -> Stage1Result:
        r"""Stage 1: 时序滚动多元 OLS 回归。
        
        回归方程: R_{i,t} - R_{f,t} = \alpha_i + \sum_{k} \beta_{i,k} F_{k,t} + \epsilon_{i,t}
        """
        common_idx = returns.index.intersection(factors_df.index)
        y = returns.loc[common_idx].copy()
        X_df = factors_df.loc[common_idx].copy()

        if window_size and len(y) > window_size:
            y = y.iloc[-window_size:]
            X_df = X_df.iloc[-window_size:]

        # 处理无风险利率超额收益
        rf = X_df["rf"] if "rf" in X_df.columns else 0.0
        factor_cols = [c for c in X_df.columns if c.lower() != "rf"]
        X_data = X_df[factor_cols]
        y_excess = y - rf

        T = len(y_excess)
        K = len(factor_cols)
        X_mat = np.column_stack([np.ones(T), X_data.values])

        # OLS 求解
        params, _, _, _ = np.linalg.lstsq(X_mat, y_excess.values, rcond=None)
        alpha = float(params[0])
        betas = {factor_cols[k]: float(params[k + 1]) for k in range(K)}

        # 残差与统计量
        y_pred = X_mat @ params
        residuals = y_excess.values - y_pred
        sse = np.sum(residuals ** 2)
        sst = np.sum((y_excess.values - np.mean(y_excess.values)) ** 2)
        r2 = 1.0 - (sse / sst) if sst > 1e-12 else 0.0
        res_std = float(np.std(residuals, ddof=K + 1))

        # HAC 标准误
        q = self.calc_adaptive_hac_lags(T) if self.use_adaptive_hac else 4
        cov_matrix = self._compute_newey_west_cov(X_mat, residuals, q)
        std_errs = np.sqrt(np.maximum(np.diag(cov_matrix), 1e-12))

        beta_tstats = {
            factor_cols[k]: float(params[k + 1] / std_errs[k + 1])
            for k in range(K)
        }
        vif_dict = self.calculate_vif(X_data)

        return Stage1Result(
            ticker=ticker,
            alpha=alpha,
            betas=betas,
            beta_tstats=beta_tstats,
            residual_std=res_std,
            r_squared=float(r2),
            vif=vif_dict,
            dynamic_covariance=cov_matrix,
            n_obs=T
        )

    def run_stage2_cross_sectional(
        self,
        returns_panel: pd.DataFrame,  # 行: 日期, 列: 各标的收益率
        stage1_betas_df: pd.DataFrame  # 行: 各标的, 列: 各因子 beta
    ) -> Stage2Result:
        r"""Stage 2: 截面 Fama-MacBeth 回归与 Harvey (2016) 因子修剪。
        
        每个截面时点 t: R_{i,t} = \gamma_{0,t} + \sum_{k} \gamma_{k,t} \hat{\beta}_{i,k} + \eta_{i,t}
        随后对时间序列 \gamma_{k,t} 实施 Newey-West HAC 检验并以 |t| < 3.0 修剪伪因子。
        """
        tickers = [t for t in returns_panel.columns if t in stage1_betas_df.index]
        if len(tickers) < 2:
            raise ValueError("Stage 2 截面回归至少需要 2 只股票资产。")

        factors = list(stage1_betas_df.columns)
        N = len(tickers)
        K = len(factors)
        T = len(returns_panel)

        # 截面自变量矩阵 B: (N x (K + 1))
        B_mat = np.column_stack([np.ones(N), stage1_betas_df.loc[tickers].values])

        gamma_series = np.zeros((T, K + 1))
        for t in range(T):
            r_t = returns_panel.iloc[t][tickers].values
            gammas, _, _, _ = np.linalg.lstsq(B_mat, r_t, rcond=None)
            gamma_series[t, :] = gammas

        # 计算时间序列均值与 Newey-West HAC t 统计量
        gamma_means = np.mean(gamma_series, axis=0)
        q = self.calc_adaptive_hac_lags(T) if self.use_adaptive_hac else 4

        t_stats = []
        p_values = []
        for k in range(K + 1):
            ts = gamma_series[:, k]
            mean_val = gamma_means[k]
            # 单变量 Newey-West 方差
            var_hac = self._compute_1d_newey_west(ts, q)
            se = math.sqrt(max(var_hac / T, 1e-12))
            t_val = mean_val / se
            p_val = 2.0 * (1.0 - stats.norm.cdf(abs(t_val)))
            t_stats.append(float(t_val))
            p_values.append(float(p_val))

        gamma_0 = float(gamma_means[0])
        risk_premiums = {factors[k]: float(gamma_means[k + 1]) for k in range(K)}
        premium_tstats = {factors[k]: float(t_stats[k + 1]) for k in range(K)}
        premium_pvals = {factors[k]: float(p_values[k + 1]) for k in range(K)}

        # Harvey (2016) Factor Prune Gate: |t| < 3.0 抑制
        pruned = [f for f, t in premium_tstats.items() if abs(t) < self.t_stat_threshold]
        active = [f for f, t in premium_tstats.items() if abs(t) >= self.t_stat_threshold]

        # 剥离各标的的特异性 Alpha
        idiosyncratic_alphas = {}
        for ticker in tickers:
            avg_ret = float(returns_panel[ticker].mean())
            factor_exp = np.array([stage1_betas_df.loc[ticker, f] for f in factors])
            expected_ret = gamma_0 + np.sum(factor_exp * gamma_means[1:])
            idiosyncratic_alphas[ticker] = avg_ret - expected_ret

        return Stage2Result(
            gamma_0=gamma_0,
            risk_premiums=risk_premiums,
            premium_tstats=premium_tstats,
            premium_pvalues=premium_pvals,
            pruned_factors=pruned,
            active_factors=active,
            hac_lags=q,
            idiosyncratic_alphas=idiosyncratic_alphas
        )

    def _compute_newey_west_cov(self, X: np.ndarray, residuals: np.ndarray, lags: int) -> np.ndarray:
        """矩阵维度 Newey-West HAC 异方差自相关稳健协方差。"""
        T, K = X.shape
        meat = np.zeros((K, K))
        for t in range(T):
            xt = X[t, :].reshape(-1, 1)
            meat += (residuals[t] ** 2) * (xt @ xt.T)

        for l in range(1, lags + 1):
            weight = 1.0 - (l / (lags + 1.0))
            for t in range(l, T):
                xt = X[t, :].reshape(-1, 1)
                xt_lag = X[t - l, :].reshape(-1, 1)
                term = residuals[t] * residuals[t - l] * (xt @ xt_lag.T + xt_lag @ xt.T)
                meat += weight * term

        xtx_inv = np.linalg.pinv(X.T @ X)
        cov = xtx_inv @ meat @ xtx_inv
        return cov

    def _compute_1d_newey_west(self, series: np.ndarray, lags: int) -> float:
        """一维时间序列 Newey-West HAC 长期方差。"""
        T = len(series)
        demeaned = series - np.mean(series)
        gamma_0 = np.sum(demeaned ** 2) / T
        hac_var = gamma_0

        for l in range(1, lags + 1):
            weight = 1.0 - (l / (lags + 1.0))
            cov_l = np.sum(demeaned[l:] * demeaned[:-l]) / T
            hac_var += 2.0 * weight * cov_l
        return float(max(hac_var, 1e-12))
