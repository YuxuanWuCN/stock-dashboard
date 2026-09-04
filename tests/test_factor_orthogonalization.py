# -*- coding: utf-8 -*-
"""tests/test_factor_orthogonalization.py —— 因子正交化与 PCA 降维单元测试"""

import numpy as np
import pandas as pd
import pytest
import warnings

from src.pricing.factor_orthogonalization import (
    orthogonalize_factor,
    pca_factor_reduction,
    LowR2Warning,
)


@pytest.fixture
def sample_carhart_data():
    """构造包含 100 个交易日的 Carhart 四因子数据集。"""
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    df = pd.DataFrame(
        {
            "MKT": np.random.normal(0.001, 0.015, n),
            "SMB": np.random.normal(0.0005, 0.010, n),
            "HML": np.random.normal(-0.0002, 0.008, n),
            "MOM": np.random.normal(0.0008, 0.012, n),
        },
        index=dates
    )
    return df


def test_orthogonalize_removes_style_exposure(sample_carhart_data):
    """测试正交化后残差与 Carhart 各因子完全正交（相关系数接近 0）。"""
    np.random.seed(123)
    n = len(sample_carhart_data)
    # y 包含显著的风格因子暴露 + 纯特质噪声
    mkt = sample_carhart_data["MKT"]
    smb = sample_carhart_data["SMB"]
    noise = np.random.normal(0, 0.005, n)
    raw_factor = pd.Series(1.5 * mkt - 0.8 * smb + noise, index=sample_carhart_data.index, name="alpha_raw")

    residual = orthogonalize_factor(raw_factor, sample_carhart_data)

    assert isinstance(residual, pd.Series)
    assert len(residual) == n
    assert abs(residual.mean()) < 1e-10

    # 验证与所有 4 个因子的相关系数接近 0
    for col in sample_carhart_data.columns:
        corr = residual.corr(sample_carhart_data[col])
        assert abs(corr) < 1e-10, f"Correlation with {col} is {corr}, expected ~0"


def test_orthogonalize_returns_exposures(sample_carhart_data):
    """测试返回暴露字典及统计量。"""
    np.random.seed(456)
    n = len(sample_carhart_data)
    raw_factor = pd.Series(
        2.0 * sample_carhart_data["MKT"] + 1.0 * sample_carhart_data["MOM"] + np.random.normal(0, 0.002, n),
        index=sample_carhart_data.index
    )

    residual, exposures = orthogonalize_factor(raw_factor, sample_carhart_data, return_exposure=True)

    assert isinstance(exposures, dict)
    assert "R2" in exposures
    assert exposures["R2"] > 0.80  # 真实构造包含强关联，R2 应很高
    assert pytest.approx(exposures["MKT"], rel=0.1) == 2.0
    assert pytest.approx(exposures["MOM"], rel=0.1) == 1.0
    assert "t_MKT" in exposures
    assert abs(exposures["t_MKT"]) > 10.0


def test_orthogonalize_validation_errors(sample_carhart_data):
    """测试输入验证与边界异常抛出。"""
    dates = sample_carhart_data.index
    valid_series = pd.Series(np.random.randn(len(dates)), index=dates)

    # 1. 索引不对齐
    bad_dates = pd.date_range("2025-01-01", periods=len(dates), freq="B")
    unaligned_series = pd.Series(np.random.randn(len(dates)), index=bad_dates)
    with pytest.raises(ValueError, match="Date indices"):
        orthogonalize_factor(unaligned_series, sample_carhart_data)

    # 2. 存在 NaN / Inf
    nan_series = valid_series.copy()
    nan_series.iloc[5] = np.nan
    with pytest.raises(ValueError, match="NaN or Inf"):
        orthogonalize_factor(nan_series, sample_carhart_data)

    inf_carhart = sample_carhart_data.copy()
    inf_carhart.iloc[2, 0] = np.inf
    with pytest.raises(ValueError, match="NaN or Inf"):
        orthogonalize_factor(valid_series, inf_carhart)

    # 3. 观测样本过少 (< 30)
    short_carhart = sample_carhart_data.iloc[:25]
    short_series = valid_series.iloc[:25]
    with pytest.raises(ValueError, match="At least 30 observations required"):
        orthogonalize_factor(short_series, short_carhart)

    # 4. 类型错误
    with pytest.raises(TypeError):
        orthogonalize_factor(valid_series.values, sample_carhart_data)
    with pytest.raises(TypeError):
        orthogonalize_factor(valid_series, sample_carhart_data.values)


def test_low_r2_warning(sample_carhart_data):
    """测试当 R2 < 0.3 时正确发出 LowR2Warning 警告。"""
    np.random.seed(999)
    # 纯随机白噪声序列，与四因子几乎没有线性关系
    noise_factor = pd.Series(np.random.randn(len(sample_carhart_data)), index=sample_carhart_data.index)

    with pytest.warns(LowR2Warning, match="Low R2"):
        orthogonalize_factor(noise_factor, sample_carhart_data)


def test_pca_factor_reduction_orthogonality():
    """测试 PCA 降维后各主成分间完全两两正交。"""
    np.random.seed(789)
    n = 120
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    # 构造存在多重共线性的 5 个因子
    f1 = np.random.randn(n)
    f2 = 0.85 * f1 + np.random.normal(0, 0.2, n)
    f3 = -0.70 * f1 + 0.4 * f2 + np.random.normal(0, 0.2, n)
    f4 = np.random.randn(n)
    f5 = 0.60 * f4 + np.random.normal(0, 0.3, n)

    factors_df = pd.DataFrame(
        {"order_growth": f1, "capacity_expand": f2, "margin_up": f3, "rd_exp": f4, "patent_count": f5},
        index=dates
    )

    pcs_df = pca_factor_reduction(factors_df, n_components=0.85)

    assert isinstance(pcs_df, pd.DataFrame)
    assert len(pcs_df) == n
    assert pcs_df.shape[1] < 5  # 降维后维度应减少

    # 验证主成分两两相关系数 < 1e-10
    corr_matrix = pcs_df.corr().values
    triu_indices = np.triu_indices_from(corr_matrix, k=1)
    off_diagonal = corr_matrix[triu_indices]
    assert np.all(np.abs(off_diagonal) < 1e-10)


def test_pca_loadings_and_exceptions():
    """测试 PCA 返回载荷矩阵及异常输入。"""
    np.random.seed(111)
    n = 60
    df = pd.DataFrame(
        {"f1": np.random.randn(n), "f2": np.random.randn(n), "f3": np.random.randn(n)},
        index=pd.date_range("2026-01-01", periods=n)
    )

    pcs, loadings = pca_factor_reduction(df, n_components=2, return_loadings=True)
    assert pcs.shape == (n, 2)
    assert loadings.shape == (3, 2)
    assert list(loadings.columns) == ["PC1", "PC2"]
    assert list(loadings.index) == ["f1", "f2", "f3"]

    # 单列抛出异常
    with pytest.raises(ValueError, match="At least 2 factors required"):
        pca_factor_reduction(df[["f1"]])

    # NaN 抛出异常
    df_nan = df.copy()
    df_nan.iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN or Inf"):
        pca_factor_reduction(df_nan)


def test_li_xin_neng_yuan_simulation_case(sample_carhart_data):
    """复现立新能源案例：+80% 收益其实由大盘风格贡献，正交化后纯 Alpha 不显著。"""
    np.random.seed(888)
    n = len(sample_carhart_data)
    # 模拟真实市场：80% 由 MKT 和 SMB 驱动，特质项仅有微弱无偏随机波动
    stock_returns = 1.6 * sample_carhart_data["MKT"] + 0.9 * sample_carhart_data["SMB"] + np.random.normal(0, 0.001, n)
    stock_series = pd.Series(stock_returns, index=sample_carhart_data.index)

    residual, exposures = orthogonalize_factor(stock_series, sample_carhart_data, return_exposure=True)

    # 拟合度 R2 极高，表明所谓"高收益"几乎全部被风格因子解释
    assert exposures["R2"] > 0.90
    assert exposures["t_MKT"] > 15.0
    # 正交后残差均方差极小，特质 Alpha 常数项不显著
    assert abs(exposures.get("const", 0.0)) < 0.005
