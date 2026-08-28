# -*- coding: utf-8 -*-
"""tests/test_famamacbeth_stage1.py —— Fama-MacBeth Stage 1 时序回归测试 (Week 2)"""

import pandas as pd
import numpy as np
import pytest

from src.analysis.famamacbethv3 import FamaMacBethV3Engine, Stage1Result


def test_famamacbeth_stage1_ols():
    """测试 Stage 1 时序多元 OLS、自适应 HAC 滞后阶数与 VIF 计算。"""
    engine = FamaMacBethV3Engine()
    np.random.seed(42)
    T = 250
    dates = pd.date_range("2024-01-01", periods=T, freq="B")

    # 生成 4 因子
    factors_df = pd.DataFrame({
        "MKT": np.random.normal(0.0005, 0.01, T),
        "SMB": np.random.normal(0.0001, 0.005, T),
        "HML": np.random.normal(0.00005, 0.006, T),
        "MOM": np.random.normal(0.0002, 0.007, T),
        "rf": np.full(T, 0.0001)
    }, index=dates)

    # 生成真实 beta: (1.2, 0.5, -0.3, 0.4), alpha=0.0008
    true_alpha = 0.0008
    stock_returns = (
        factors_df["rf"]
        + true_alpha
        + 1.2 * factors_df["MKT"]
        + 0.5 * factors_df["SMB"]
        - 0.3 * factors_df["HML"]
        + 0.4 * factors_df["MOM"]
        + np.random.normal(0, 0.001, T)
    )

    res = engine.run_stage1_time_series(stock_returns, factors_df, ticker="001309")

    assert isinstance(res, Stage1Result)
    assert res.ticker == "001309"
    assert res.n_obs == T
    assert abs(res.betas["MKT"] - 1.2) < 0.1
    assert abs(res.betas["SMB"] - 0.5) < 0.1
    assert abs(res.betas["HML"] - (-0.3)) < 0.1
    assert abs(res.betas["MOM"] - 0.4) < 0.1
    assert res.r_squared > 0.8
    assert all(v < 5.0 for v in res.vif.values())  # 正交因子 VIF ~ 1.0
