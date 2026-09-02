# -*- coding: utf-8 -*-
"""tests/test_storage_gold_joint_runner.py —— 存储+黄金跨周期双资产杠铃融合回测单元测试"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.storage_gold_joint_runner import (
    StorageGoldJointEngine,
    STORAGE_STOCKS,
    GOLD_STOCKS,
)


def test_storage_gold_joint_engine_initialization():
    engine = StorageGoldJointEngine()
    assert len(engine.storage_codes) == 7
    assert len(engine.gold_codes) == 7
    assert len(engine.all_codes) == 14
    assert not engine.prices_df.empty


def test_storage_gold_joint_backtest_execution():
    engine = StorageGoldJointEngine()
    res = engine.run_backtest()

    assert "strategies" in res
    assert "pure_storage" in res["strategies"]
    assert "pure_gold" in res["strategies"]
    assert "static_barbell_50_50" in res["strategies"]
    assert "dynamic_regime_barbell" in res["strategies"]

    # 验证动态杠铃策略夏普比率与收益
    dyn_stat = res["strategies"]["dynamic_regime_barbell"]
    assert dyn_stat["total_return"] > 0
    assert dyn_stat["max_drawdown"] < 0.30

    # 验证相关系数与分散化比率
    assert -1.0 <= res["correlation_storage_gold"] <= 1.0
    assert res["diversification_ratio"] > 1.0
    assert res["harvey_alpha_t_stat"] >= 3.0


def test_storage_gold_joint_nav_series_continuity():
    engine = StorageGoldJointEngine()
    res = engine.run_backtest()
    navs = res["nav_series"]

    dates_len = len(navs["dates"])
    assert len(navs["csi300"]) == dates_len
    assert len(navs["dynamic_regime_barbell"]) == dates_len
    assert navs["dynamic_regime_barbell"][0] == 1.0
    assert not any(np.isnan(x) for x in navs["dynamic_regime_barbell"])
