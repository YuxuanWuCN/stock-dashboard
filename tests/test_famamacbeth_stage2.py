# -*- coding: utf-8 -*-
"""tests/test_famamacbeth_stage2.py —— Fama-MacBeth Stage 2 截面回归与 |t| < 3.0 修剪门禁测试 (Week 3)"""

import pandas as pd
import numpy as np
import pytest

from src.analysis.famamacbethv3 import FamaMacBethV3Engine, Stage2Result


def test_famamacbeth_stage2_cross_sectional_and_prune():
    """测试 Stage 2 截面回归、Newey-West HAC 检验与 Harvey et al. (2016) |t| < 3.0 因子修剪。"""
    engine = FamaMacBethV3Engine(t_stat_threshold=3.0)
    np.random.seed(42)
    T = 250
    N = 10
    tickers = [f"STOCK_{i:02d}" for i in range(N)]
    dates = pd.date_range("2024-01-01", periods=T, freq="B")

    # 1. 模拟资产在 4 因子上的真实暴露 Beta
    betas_dict = {
        "MKT": np.linspace(0.8, 1.5, N),
        "SMB": np.linspace(-0.5, 0.8, N),
        "HML": np.linspace(-0.2, 0.4, N),
        "NOISE_FACTOR": np.random.normal(0, 0.05, N)  # 无显著溢价的伪因子
    }
    stage1_betas_df = pd.DataFrame(betas_dict, index=tickers)

    # 2. 模拟真实风险溢价 (MKT: 0.001, SMB: 0.0006, HML: 0.00001, NOISE: 0.0)
    true_gammas = [0.0002, 0.001, 0.0006, 0.00001, 0.0000]
    B_mat = np.column_stack([np.ones(N), stage1_betas_df.values])

    returns_data = {}
    for t in range(T):
        # 截面收益率 = B * gamma + noise
        r_t = B_mat @ true_gammas + np.random.normal(0, 0.002, N)
        returns_data[dates[t]] = r_t

    returns_panel = pd.DataFrame(returns_data, index=tickers).T

    # 3. 运行 Stage 2 回归
    res = engine.run_stage2_cross_sectional(returns_panel, stage1_betas_df)

    assert isinstance(res, Stage2Result)
    assert len(res.risk_premiums) == 4
    # MKT 或 SMB 高显著，进入 active_factors
    assert "MKT" in res.active_factors or "SMB" in res.active_factors
    # NOISE_FACTOR 伪因子由于 |t| < 3.0 被自动 prune
    assert "NOISE_FACTOR" in res.pruned_factors
    assert len(res.idiosyncratic_alphas) == N
