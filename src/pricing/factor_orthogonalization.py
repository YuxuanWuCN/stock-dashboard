# -*- coding: utf-8 -*-
"""src/pricing/factor_orthogonalization.py —— 因子正交化与降维模块

基于 API 契约 specs/contest-2026/contracts/factor_orthogonalization.md：
1. orthogonalize_factor: 对候选因子进行 Carhart 四因子正交化，剥离风格暴露，提取纯净特质 Alpha 残差。
2. pca_factor_reduction: 对高共线性语义/技术因子矩阵进行 PCA 降维。
"""

from __future__ import annotations

import warnings
from typing import Dict, Optional, Tuple, Union

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


class LowR2Warning(UserWarning):
    """四因子解释力弱警告。"""
    pass


class HighVIFWarning(UserWarning):
    """因子间多重共线性过高警告。"""
    pass


def orthogonalize_factor(
    candidate_factor: pd.Series,
    carhart_factors: pd.DataFrame,
    return_exposure: bool = False,
    add_constant: bool = True
) -> Union[pd.Series, Tuple[pd.Series, Dict[str, float]]]:
    """对候选因子正交化，剥离市场/规模/价值/动量风格暴露。

    Parameters
    ----------
    candidate_factor : pd.Series
        原始因子值，index 为日期，values 为因子得分
    carhart_factors : pd.DataFrame
        Carhart 四因子或多因子时间序列，如 columns = ['MKT', 'SMB', 'HML', 'MOM']
    return_exposure : bool, default False
        是否返回对四因子的暴露系数及统计量
    add_constant : bool, default True
        回归中是否包含常数项

    Returns
    -------
    orthogonal_residual : pd.Series
        正交化后的特质成分（回归残差）
    exposures : Dict[str, float], optional
        对因子的回归系数及 R2、t 统计量

    Raises
    ------
    ValueError
        如果日期不对齐、存在 NaN/Inf 或观测点不足 30
    """
    if not isinstance(candidate_factor, pd.Series):
        raise TypeError("candidate_factor must be a pd.Series")
    if not isinstance(carhart_factors, pd.DataFrame):
        raise TypeError("carhart_factors must be a pd.DataFrame")

    # 1. 校验日期索引对齐
    if not candidate_factor.index.equals(carhart_factors.index):
        raise ValueError("Date indices of candidate_factor and carhart_factors must align exactly")

    # 2. 校验缺失值与无穷值
    if candidate_factor.isna().any() or np.isinf(candidate_factor).any():
        raise ValueError("candidate_factor contains NaN or Inf values")
    if carhart_factors.isna().any().any() or np.isinf(carhart_factors).any().any():
        raise ValueError("carhart_factors contains NaN or Inf values")

    # 3. 校验样本量
    n_obs = len(candidate_factor)
    if n_obs < 30:
        raise ValueError(f"At least 30 observations required, got {n_obs}")

    y = candidate_factor.values.astype(float)
    X_df = carhart_factors.copy()
    if add_constant:
        X = sm.add_constant(X_df, prepend=True)
    else:
        X = X_df

    # 4. 执行 OLS 回归
    model = sm.OLS(y, X).fit()
    residuals = pd.Series(
        model.resid,
        index=candidate_factor.index,
        name=candidate_factor.name or "orthogonal_factor"
    )

    # 5. 警告评估 (Low R2 & Multicollinearity)
    if model.rsquared < 0.3:
        warnings.warn(
            f"Low R2 ({model.rsquared:.4f} < 0.3): style factors have weak explanatory power.",
            LowR2Warning
        )

    if not return_exposure:
        return residuals

    # 6. 整理暴露字典
    exposures: Dict[str, float] = {
        "R2": float(model.rsquared),
        "f_pvalue": float(model.f_pvalue) if model.f_pvalue is not None else 1.0,
    }
    for col in carhart_factors.columns:
        if col in model.params:
            exposures[col] = float(model.params[col])
            exposures[f"t_{col}"] = float(model.tvalues[col])
            exposures[f"p_{col}"] = float(model.pvalues[col])

    if add_constant and "const" in model.params:
        exposures["const"] = float(model.params["const"])
        exposures["t_const"] = float(model.tvalues["const"])

    return residuals, exposures


def pca_factor_reduction(
    semantic_factors: pd.DataFrame,
    n_components: Union[int, float] = 0.8,
    standardize: bool = True,
    return_loadings: bool = False
) -> Union[pd.DataFrame, Tuple[pd.DataFrame, pd.DataFrame]]:
    """对语义或多因子矩阵进行 PCA 降维，消除共线性。

    Parameters
    ----------
    semantic_factors : pd.DataFrame
        因子矩阵，行=日期，列=因子名称
    n_components : int or float, default 0.8
        保留主成分数 (int >= 1) 或累计方差贡献率阈值 (float 0 < x < 1)
    standardize : bool, default True
        是否进行标准差标准化 (Z-score)，确保各因子量纲一致
    return_loadings : bool, default False
        是否返回因子载荷矩阵

    Returns
    -------
    principal_components : pd.DataFrame
        正交主成分矩阵，列名为 ['PC1', 'PC2', ...]
    loadings : pd.DataFrame, optional
        载荷矩阵，行=原始因子，列=主成分
    """
    if not isinstance(semantic_factors, pd.DataFrame):
        raise TypeError("semantic_factors must be a pd.DataFrame")
    if semantic_factors.isna().any().any() or np.isinf(semantic_factors).any().any():
        raise ValueError("semantic_factors contains NaN or Inf values")
    if semantic_factors.shape[1] < 2:
        raise ValueError("At least 2 factors required for PCA reduction")

    X = semantic_factors.values.astype(float)
    if standardize:
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
    else:
        # 中心化
        X_scaled = X - np.mean(X, axis=0)

    pca = PCA(n_components=n_components, svd_solver="full" if isinstance(n_components, float) else "auto")
    X_pca = pca.fit_transform(X_scaled)

    num_pcs = X_pca.shape[1]
    pc_cols = [f"PC{i+1}" for i in range(num_pcs)]

    pcs_df = pd.DataFrame(
        X_pca,
        index=semantic_factors.index,
        columns=pc_cols
    )

    if not return_loadings:
        return pcs_df

    loadings_df = pd.DataFrame(
        pca.components_.T,
        index=semantic_factors.columns,
        columns=pc_cols
    )
    return pcs_df, loadings_df
