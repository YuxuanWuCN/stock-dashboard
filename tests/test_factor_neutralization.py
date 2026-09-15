# -*- coding: utf-8 -*-
"""tests/test_factor_neutralization.py —— A 股因子去极值、中性化与标准化单元测试"""

import numpy as np
import pandas as pd
import pytest

from src.pricing.factor_neutralization import (
    FACTOR_NAME_MAPPING,
    ASharePCAFactorPipeline,
    neutralize_cross_section,
    process_ashare_factor,
    standardize_zscore,
    winsorize_mad,
)


def test_winsorize_mad_handles_outliers():
    """验证 MAD 去极值对极端异常值的截断有效性。"""
    np.random.seed(42)
    # 正常标准正态分布数据 + 两个极端异常值
    data = np.random.normal(0, 1, 100)
    data[0] = 100.0   # 极端大
    data[1] = -100.0  # 极端小
    s = pd.Series(data, index=[f"{i:06d}" for i in range(100)])

    res = winsorize_mad(s, n=3.0)

    # 极端值被截断，不再等于 100
    assert res.iloc[0] < 10.0
    assert res.iloc[1] > -10.0
    # 中间正常值基本保持不变
    assert np.isclose(res.iloc[2], s.iloc[2])


def test_winsorize_mad_constant_and_empty():
    """边界测试：全常数、全缺失与空 Series。"""
    s_const = pd.Series([5.0] * 20, index=[f"{i:06d}" for i in range(20)])
    res_const = winsorize_mad(s_const)
    assert np.allclose(res_const.to_numpy(), 5.0)

    s_empty = pd.Series([], dtype=float)
    assert winsorize_mad(s_empty).empty

    s_nan = pd.Series([np.nan, np.nan], index=["000001", "000002"])
    assert winsorize_mad(s_nan).isna().all()


def test_standardize_zscore():
    """验证 Z-score 均值归零与方差归一。"""
    np.random.seed(42)
    s = pd.Series(np.random.uniform(10, 50, 50), index=[f"{i:06d}" for i in range(50)])
    z = standardize_zscore(s)

    assert pytest.approx(z.mean(), abs=1e-12) == 0.0
    assert pytest.approx(z.std(ddof=1), abs=1e-12) == 1.0

    # 零方差处理
    s_const = pd.Series([3.0] * 10)
    z_const = standardize_zscore(s_const)
    assert (z_const == 0.0).all()


def test_neutralize_cross_section_orthogonality():
    """核心数学检验：中性化后残差与对数市值及行业哑变量完全正交（协方差/相关系数为0）。"""
    np.random.seed(42)
    n = 120
    codes = [f"{i:06d}" for i in range(n)]
    industries = pd.Series(np.random.choice(["Tech", "Energy", "Finance", "Consumer"], size=n), index=codes)
    market_caps = pd.Series(np.random.uniform(1e9, 1e11, size=n), index=codes)

    # 构造一个人为带有严重市值风格和行业偏倚的因子
    log_cap = np.log(market_caps)
    ind_bias = industries.map({"Tech": 2.0, "Energy": -1.5, "Finance": 0.5, "Consumer": 0.0})
    raw_factor = 0.8 * log_cap + ind_bias + np.random.normal(0, 0.5, size=n)

    # 执行中性化
    residual = neutralize_cross_section(raw_factor, industries, market_caps)

    # 检验 1：残差与 log(market_cap) 的皮尔逊相关系数严格接近 0
    corr_size = np.corrcoef(residual.to_numpy(), log_cap.to_numpy())[0, 1]
    assert abs(corr_size) < 1e-10, f"残差与市值未正交，相关系数: {corr_size}"

    # 检验 2：残差在每个行业内的均值与总均值无系统性偏差
    ind_dummies = pd.get_dummies(industries, drop_first=False, dtype=float)
    for col in ind_dummies.columns:
        corr_ind = np.corrcoef(residual.to_numpy(), ind_dummies[col].to_numpy())[0, 1]
        assert abs(corr_ind) < 1e-10, f"残差与行业 {col} 未正交，相关系数: {corr_ind}"


def test_neutralize_cross_section_missing_values_and_small_sample():
    """边界输入测试：包含缺失值、非法市值和样本极小情况。"""
    codes = ["000001", "000002", "000003", "000004", "000005"]
    factor = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0], index=codes)
    industries = pd.Series(["A", "A", "B", "B", "B"], index=codes)
    market_caps = pd.Series([100.0, -10.0, 200.0, 300.0, 400.0], index=codes)  # 000002 市值非法

    res = neutralize_cross_section(factor, industries, market_caps)
    # 000002 和 000003 应该为 NaN，其余有效
    assert pd.isna(res.loc["000002"])
    assert pd.isna(res.loc["000003"])
    assert pd.notna(res.loc["000001"])
    assert pd.notna(res.loc["000004"])
    assert pd.notna(res.loc["000005"])


def test_process_ashare_factor_end_to_end():
    """单因子流水线端到端测试：去极值 -> 中性化 -> 标准化。"""
    np.random.seed(42)
    n = 60
    codes = [f"{i:06d}" for i in range(n)]
    f = pd.Series(np.random.normal(0, 1, n), index=codes)
    ind = pd.Series(np.random.choice(["IndA", "IndB", "IndC"], n), index=codes)
    cap = pd.Series(np.random.uniform(1e8, 1e10, n), index=codes)

    clean_f = process_ashare_factor(f, ind, cap)
    assert len(clean_f) == n
    assert pytest.approx(clean_f.mean(), abs=1e-10) == 0.0
    assert pytest.approx(clean_f.std(ddof=1), abs=1e-10) == 1.0


def test_ashare_pca_factor_pipeline():
    """多因子 Pipeline 测试：从 PC1~PC5 生成 5 大标准化因子及合成 Alpha。"""
    np.random.seed(42)
    n = 80
    codes = [f"{i:06d}" for i in range(n)]
    pca_df = pd.DataFrame({
        "PC1": np.random.normal(0, 1, n),
        "PC2": np.random.normal(0, 1, n),
        "PC3": np.random.normal(0, 1, n),
        "PC4": np.random.normal(0, 1, n),
        "PC5": np.random.normal(0, 1, n),
    }, index=codes)
    industries = pd.Series(np.random.choice(["Tech", "Energy", "Finance"], n), index=codes)
    caps = pd.Series(np.random.uniform(5e9, 5e11, n), index=codes)

    pipeline = ASharePCAFactorPipeline()
    bundle = pipeline.transform_cross_section(pca_df, industries, caps)

    # 验证 5 大子因子完整映射
    assert set(bundle.sub_factors.columns) == set(FACTOR_NAME_MAPPING.values())
    for col in bundle.sub_factors.columns:
        assert pytest.approx(bundle.sub_factors[col].mean(), abs=1e-10) == 0.0
        assert pytest.approx(bundle.sub_factors[col].std(ddof=1), abs=1e-10) == 1.0

    # 验证综合 Alpha
    assert bundle.composite_alpha.name == "alpha_composite_nale"
    assert len(bundle.composite_alpha) == n
    assert pytest.approx(bundle.composite_alpha.mean(), abs=1e-10) == 0.0
    assert pytest.approx(bundle.composite_alpha.std(ddof=1), abs=1e-10) == 1.0
