# -*- coding: utf-8 -*-
"""src/pricing/factor_neutralization.py —— A 股截面因子去极值、行业市值中性化与标准化流水线

功能契约：
1. winsorize_mad: 截面 3 倍中位数绝对偏差（MAD）去极值，平抑厚尾异常值扰动。
2. standardize_zscore: 截面均值归零、方差归一标准化。
3. neutralize_cross_section: 针对行业分类（哑变量）与对数流通市值（ln(Market_Cap)）执行多元 OLS 回归，
   提取特质残差，彻底剥离传统宏观板块轮动与大小盘风格暴露，并保证残差与解释变量正交。
4. ASharePCAFactorPipeline: 封装 768 维降维主成分（PC1~PC5）至 A 股标准化因子的端到端工程转换，
   提供标准金融经济学命名与综合 Alpha 合成。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FACTOR_NAME_MAPPING: dict[str, str] = {
    "PC1": "alpha_speculative_momentum",
    "PC2": "alpha_retail_divergence",
    "PC3": "alpha_institutional_value",
    "PC4": "alpha_northbound_flow",
    "PC5": "alpha_institutional_gaming",
}

FACTOR_CHINESE_DESCRIPTIONS: dict[str, str] = {
    "alpha_speculative_momentum": "小盘题材游资动量因子 (PC1)",
    "alpha_retail_divergence": "散户跟风大单背离因子 (PC2)",
    "alpha_institutional_value": "机构深度价值红利因子 (PC3)",
    "alpha_northbound_flow": "外资北向流动性因子 (PC4)",
    "alpha_institutional_gaming": "机构博弈兑现回踩因子 (PC5)",
}


def winsorize_mad(series: pd.Series, n: float = 3.0, scale: float = 1.4826) -> pd.Series:
    """截面中位数绝对偏差（MAD）去极值。

    Parameters
    ----------
    series : pd.Series
        待去极值的原始因子序列，index 为股票代码
    n : float, default 3.0
        MAD 倍数容忍度，标准正态分布下 3*1.4826*MAD 对应 99.7% 置信区间
    scale : float, default 1.4826
        正态分布一致性缩放常数（1 / Phi^(-1)(0.75) ≈ 1.4826）

    Returns
    -------
    pd.Series
        去极值后的因子序列
    """
    if series.empty:
        return series.copy()

    s = series.astype(float)
    valid_mask = s.notna() & np.isfinite(s)
    if not valid_mask.any():
        return series.copy()

    valid_vals = s[valid_mask]
    median = float(valid_vals.median())
    mad = float((valid_vals - median).abs().median())

    if mad <= 1e-12:
        # 方差极小或几乎全相等时，不作强制截断
        return series.copy()

    threshold = n * scale * mad
    lower_bound = median - threshold
    upper_bound = median + threshold

    clipped = s.clip(lower=lower_bound, upper=upper_bound)
    return clipped


def standardize_zscore(series: pd.Series) -> pd.Series:
    """截面 Z-score 均值归零、方差归一标准化。

    Parameters
    ----------
    series : pd.Series
        待标准化的因子序列

    Returns
    -------
    pd.Series
        均值为 0，标准差为 1 的标准化序列（保留原有缺失位置为 NaN）
    """
    if series.empty:
        return series.copy()

    s = series.astype(float)
    valid_mask = s.notna() & np.isfinite(s)
    if not valid_mask.any():
        return series.copy()

    valid_vals = s[valid_mask]
    mean = float(valid_vals.mean())
    std = float(valid_vals.std(ddof=1)) if len(valid_vals) > 1 else 0.0

    if std <= 1e-12:
        # 零方差时填充 0.0
        result = pd.Series(index=series.index, dtype=float)
        result[valid_mask] = 0.0
        return result

    result = pd.Series(index=series.index, dtype=float)
    result[valid_mask] = (valid_vals - mean) / std
    return result


def neutralize_cross_section(
    factor: pd.Series,
    industries: pd.Series,
    market_caps: pd.Series,
    add_constant: bool = True,
) -> pd.Series:
    """截面行业哑变量与对数流通市值 OLS 回归剥离（中性化）。

    回归设定：
        Factor_i = beta_0 + sum(beta_{ind, j} * Ind_{i, j}) + beta_{size} * ln(Cap_i) + eps_i

    Parameters
    ----------
    factor : pd.Series
        原始因子打分（建议已完成去极值），index 为股票代码
    industries : pd.Series
        股票所属行业（申万一级行业或板块分类），index 为股票代码
    market_caps : pd.Series
        股票流通市值，index 为股票代码
    add_constant : bool, default True
        是否加入截距项（加入截距项时行业哑变量 drop_first=True 以避免多重共线性）

    Returns
    -------
    pd.Series
        中性化后的纯净特质残差 eps_i（保留缺失位置为 NaN）
    """
    # 对齐 index
    df = pd.DataFrame({
        "factor": factor,
        "industry": industries,
        "market_cap": market_caps,
    }, index=factor.index).dropna()

    df = df[np.isfinite(df["factor"]) & (df["market_cap"] > 0)]
    if len(df) < 5:
        # 样本过少无法进行稳健多元回归，返回有效样本的标准化值，无效样本保留为 NaN
        fallback = pd.Series(index=factor.index, dtype=float)
        if len(df) > 0:
            fallback.loc[df.index] = standardize_zscore(df["factor"])
        return fallback

    # 1. 解释变量构建
    # 对数市值
    log_cap = np.log(df["market_cap"].astype(float))
    
    # 行业哑变量
    ind_dummies = pd.get_dummies(df["industry"].astype(str), prefix="ind", drop_first=add_constant, dtype=float)

    # 组合设计矩阵 X
    X_parts = [ind_dummies, log_cap.rename("log_cap")]
    if add_constant:
        const_col = pd.Series(1.0, index=df.index, name="const")
        X_parts.insert(0, const_col)

    X = pd.concat(X_parts, axis=1)
    y = df["factor"].astype(float)

    # 2. 最小二乘求解 (使用 SVD / lstsq 具备数值稳定性与秩亏容错)
    X_mat = X.to_numpy(dtype=float)
    y_mat = y.to_numpy(dtype=float)

    try:
        beta, residuals, rank, s = np.linalg.lstsq(X_mat, y_mat, rcond=None)
        pred = X_mat @ beta
        res = y_mat - pred
    except Exception as e:
        logger.warning(f"多元回归求解异常 ({e})，降级使用均值残差")
        res = y_mat - np.mean(y_mat)

    # 3. 构造输出 Series 并保持输入原始索引对齐
    residual_series = pd.Series(index=factor.index, dtype=float)
    residual_series.loc[df.index] = res
    return residual_series


def process_ashare_factor(
    factor: pd.Series,
    industries: pd.Series,
    market_caps: pd.Series,
    winsorize: bool = True,
    standardize: bool = True,
) -> pd.Series:
    """单因子标准 A 股化清洗流程：3倍MAD去极值 -> 行业市值中性化 -> Z-score 标准化。"""
    s = factor.copy()
    if winsorize:
        s = winsorize_mad(s)
    s = neutralize_cross_section(s, industries, market_caps)
    if standardize:
        s = standardize_zscore(s)
    return s


@dataclass(frozen=True)
class NeutralizedFactorBundle:
    """5 大子因子与复合 Alpha 因子的结构化产物容器。"""
    sub_factors: pd.DataFrame
    composite_alpha: pd.Series
    metadata: Mapping[str, object]


class ASharePCAFactorPipeline:
    """768 维降维主成分 A 股化流水线。"""

    def __init__(
        self,
        weights: Mapping[str, float] | None = None,
        winsorize: bool = True,
        standardize: bool = True,
    ):
        """
        Parameters
        ----------
        weights : Mapping[str, float], optional
            子因子合成综合 Alpha 的权重。默认结合资产定价实证结果：
            - alpha_speculative_momentum: 0.15
            - alpha_retail_divergence: -0.15 (反转/背离)
            - alpha_institutional_value: 0.35 (核心价值)
            - alpha_northbound_flow: 0.20 (外资动能)
            - alpha_institutional_gaming: -0.35 (显著负溢价，做空博弈/做多利好兑现安全垫)
        """
        self.winsorize = winsorize
        self.standardize = standardize
        self.weights = weights or {
            "alpha_speculative_momentum": 0.15,
            "alpha_retail_divergence": -0.15,
            "alpha_institutional_value": 0.35,
            "alpha_northbound_flow": 0.20,
            "alpha_institutional_gaming": -0.35,
        }

    def transform_cross_section(
        self,
        pca_factors: pd.DataFrame,
        industries: pd.Series,
        market_caps: pd.Series,
    ) -> NeutralizedFactorBundle:
        """对截面上的 PC1~PC5 进行中性化清洗并合成综合 Alpha。

        Parameters
        ----------
        pca_factors : pd.DataFrame
            包含 PC1~PC5（或 PC01~PC05）的 DataFrame，index 为股票代码
        industries : pd.Series
            股票行业分类，index 为股票代码
        market_caps : pd.Series
            股票流通市值，index 为股票代码
        """
        clean_factors = {}
        for pc_key, std_name in FACTOR_NAME_MAPPING.items():
            # 兼容 PC1 或 PC01
            col = pc_key if pc_key in pca_factors.columns else f"PC{int(pc_key[2:]):02d}"
            if col in pca_factors.columns:
                raw_series = pca_factors[col]
            else:
                raw_series = pd.Series(0.0, index=pca_factors.index)

            clean_series = process_ashare_factor(
                raw_series,
                industries=industries,
                market_caps=market_caps,
                winsorize=self.winsorize,
                standardize=self.standardize,
            )
            clean_factors[std_name] = clean_series

        sub_df = pd.DataFrame(clean_factors, index=pca_factors.index)

        # 合成加权综合 Alpha
        composite = pd.Series(0.0, index=pca_factors.index, dtype=float)
        for name, w in self.weights.items():
            if name in sub_df.columns:
                composite += w * sub_df[name]

        if self.standardize:
            composite = standardize_zscore(composite)

        meta = {
            "sub_factors": list(FACTOR_NAME_MAPPING.values()),
            "weights": dict(self.weights),
            "n_stocks": len(pca_factors),
        }
        return NeutralizedFactorBundle(
            sub_factors=sub_df,
            composite_alpha=composite.rename("alpha_composite_nale"),
            metadata=meta,
        )
