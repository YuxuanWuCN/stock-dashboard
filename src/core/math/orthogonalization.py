# src/core/math/orthogonalization.py
"""
Rainbow-FinGPT v4.0 核心数学底层 —— Gram-Schmidt 因子正交化与 PCA 降维算子
Gram-Schmidt Factor Orthogonalization and Principal Component Analysis (PCA).
"""

from typing import Tuple, Union
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA


def gram_schmidt_orthogonalize(X: Union[np.ndarray, pd.DataFrame]) -> Tuple[np.ndarray, np.ndarray]:
    """
    经典 Gram-Schmidt 向量与因子矩阵正交化。
    
    参数:
        X: (T, K) 原始因子矩阵
        
    返回:
        (Q, R):
            Q: (T, K) 正交化后的基向量矩阵 (各列两两正交，||q_k|| = 1)
            R: (K, K) 上三角投影变换矩阵，满足 X = Q @ R
    """
    if isinstance(X, pd.DataFrame):
        X_mat = X.values.astype(float)
    else:
        X_mat = np.array(X, dtype=float)
        
    T, K = X_mat.shape
    Q = np.zeros((T, K))
    R = np.zeros((K, K))
    
    for j in range(K):
        v = X_mat[:, j].copy()
        for i in range(j):
            R[i, j] = np.dot(Q[:, i], X_mat[:, j])
            v = v - R[i, j] * Q[:, i]
        
        norm_v = np.linalg.norm(v)
        if norm_v < 1e-12:
            R[j, j] = 0.0
            Q[:, j] = 0.0
        else:
            R[j, j] = norm_v
            Q[:, j] = v / norm_v
            
    return Q, R


def sequential_residual_orthogonalize(
    factors_df: pd.DataFrame,
    lead_col: str
) -> pd.DataFrame:
    """
    序贯残差正交化：以 lead_col 为主导基准，其余因子依次对先验因子集作 OLS 回归取残差。
    保证正交化后的因子彻底剔除与主导因子（如市场大盘 MKT 或基准风格）的线性重叠。
    """
    cols = [lead_col] + [c for c in factors_df.columns if c != lead_col]
    ortho_df = pd.DataFrame(index=factors_df.index)
    ortho_df[lead_col] = factors_df[lead_col]
    
    for i in range(1, len(cols)):
        curr_col = cols[i]
        y = factors_df[curr_col].values
        X_basis = ortho_df[cols[:i]].values
        X_design = np.column_stack([np.ones(len(y)), X_basis])
        
        # OLS 投影求残差
        beta, _, _, _ = np.linalg.lstsq(X_design, y, rcond=None)
        residuals = y - X_design @ beta
        ortho_df[curr_col] = residuals
        
    return ortho_df


def pca_dimension_reduction(
    X: Union[np.ndarray, pd.DataFrame],
    n_components: Union[int, float] = 0.85
) -> Tuple[np.ndarray, PCA]:
    """
    基于主成分分析 (PCA) 的动态因子降维算子。
    
    参数:
        X: (T, K) 原始高维特征/因子矩阵
        n_components: 目标主成分维度 (int) 或累计方差解释比率门槛 (float, 如 0.85)
        
    返回:
        (X_pca, pca_model): 降维后低维矩阵及拟合的 PCA 模型对象
    """
    if isinstance(X, pd.DataFrame):
        X_mat = X.fillna(0.0).values
    else:
        X_mat = np.nan_to_num(X)
        
    pca = PCA(n_components=n_components, svd_solver="auto")
    X_pca = pca.fit_transform(X_mat)
    return X_pca, pca
