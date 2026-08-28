# -*- coding: utf-8 -*-
"""tests/test_sector_graph_engine.py —— Spec 015 NALE 板块图谱与涨停龙头溢出引擎单元测试"""

import numpy as np
import pandas as pd
import pytest

from src.graph.sector_graph_engine import (
    SectorGraphEngine,
    SectorGraphState,
    is_limit_up,
)


def test_is_limit_up_rules():
    # 主板 10%
    assert is_limit_up("600519", 9.98) is True
    assert is_limit_up("000001", 9.60) is True
    assert is_limit_up("600519", 8.50) is False
    assert is_limit_up("600519", -2.0) is False

    # 科创板 20%
    assert is_limit_up("688525", 19.95) is True
    assert is_limit_up("688525", 15.0) is False

    # 创业板 20% (如德明利 001309 是主板，但江波龙 301308 是创业板)
    assert is_limit_up("301308", 19.80) is True
    assert is_limit_up("301308", 10.00) is False

    # None 或异常值
    assert is_limit_up("600519", None) is False
    assert is_limit_up("600519", float("nan")) is False


def test_sector_graph_engine_limit_up_spillover():
    engine = SectorGraphEngine(corr_threshold=0.40)

    # 模拟存储板块股票池
    stocks = [
        {"code": "001309", "name": "德明利", "category": "存储"},
        {"code": "603986", "name": "兆易创新", "category": "存储"},
        {"code": "688525", "name": "佰维存储", "category": "存储"},
        {"code": "600519", "name": "贵州茅台", "category": "白酒"},
    ]

    # 构造 K 线数据：德明利与兆易创新强正相关 (ρ ≈ 0.85)，德明利涨停 (+9.98%)
    np.random.seed(42)
    t_len = 60
    base_returns = np.random.normal(0.001, 0.02, t_len)
    
    dml_ret = base_returns + np.random.normal(0, 0.005, t_len)
    zy_ret = base_returns * 0.9 + np.random.normal(0, 0.005, t_len)
    bw_ret = base_returns * 0.8 + np.random.normal(0, 0.008, t_len)
    mt_ret = np.random.normal(0, 0.015, t_len)

    def to_closes(rets, final_chg):
        closes = [10.0]
        for r in rets[:-1]:
            closes.append(closes[-1] * (1.0 + r))
        # 最后一根模拟指定涨幅
        closes.append(closes[-1] * (1.0 + final_chg / 100.0))
        return closes

    kline_map = {
        "001309": {"kline": [[f"2026-08-{i}", c] for i, c in enumerate(to_closes(dml_ret, 9.98))]},
        "603986": {"kline": [[f"2026-08-{i}", c] for i, c in enumerate(to_closes(zy_ret, 3.20))]},
        "688525": {"kline": [[f"2026-08-{i}", c] for i, c in enumerate(to_closes(bw_ret, 1.50))]},
        "600519": {"kline": [[f"2026-08-{i}", c] for i, c in enumerate(to_closes(mt_ret, -0.50))]},
    }

    engine.build_graph(stocks, kline_map, lookback_days=60)

    # 1. 检验存储板块状态
    storage_state = engine.sector_states.get("存储")
    assert storage_state is not None
    assert storage_state.total_count == 3
    assert storage_state.up_count == 3
    assert storage_state.breadth_pct == 100.0
    assert storage_state.has_limit_up is True
    assert storage_state.leader is not None
    assert storage_state.leader["code"] == "001309"
    assert storage_state.leader["is_limit_up"] is True

    # 2. 检验德明利 (龙头自身) 的 NALE 输出
    dml_nale = engine.get_nale_network_payload("001309", "存储")
    assert dml_nale["tier_role"] == "leader"
    assert dml_nale["has_limit_up_resonance"] is True
    assert dml_nale["spillover_return_5d_pct"] == 0.0

    # 3. 检验兆易创新 (高协同中军/补涨标的) 的 NALE 溢出加成
    zy_nale = engine.get_nale_network_payload("603986", "存储")
    assert zy_nale["tier_role"] == "follower_catchup"
    assert zy_nale["has_limit_up_resonance"] is True
    assert zy_nale["spillover_return_5d_pct"] >= 0.5
    assert zy_nale["spillover_prob_5d_pct"] >= 5.0
    assert zy_nale["leader_stock"]["code"] == "001309"
    assert len(zy_nale["co_movement_peers"]) > 0

    # 4. 检验白酒板块 (无涨停板的常态)
    bj_nale = engine.get_nale_network_payload("600519", "白酒")
    assert bj_nale["has_limit_up_resonance"] is False
    assert bj_nale["tier_role"] in ("neutral", "core_mid")
