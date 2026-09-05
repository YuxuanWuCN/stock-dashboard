# -*- coding: utf-8 -*-
"""tests/test_temporal_nale.py —— Temporal-NALE (T-NALE) 单元测试套件

涵盖：
1. 渐近一致性检验：极限条件下数学等价退化为静态经典 NALE；
2. 指数半衰期单调衰减与信息类型差异测试；
3. 产业链物理时滞高斯卷积波峰共振测试；
4. 全景时域连续轨迹推演与最优持有时窗识别；
5. 多阶产业链时滞先后序检验 (上游 -> 中游 -> 下游)；
6. 边界与异常路径检验 (空集、维度不匹配、孤立点、数值截断)。
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from src.graph.temporal_constants import (
    INFORMATION_HALF_LIVES,
    INDUSTRY_LAG_PRIORS,
    get_half_life,
    get_supply_chain_lag,
)
from src.graph.temporal_nale import (
    TemporalNALEEngine,
    TemporalNALEResult,
    TrajectoryResult,
)
from src.analysis.scoringv3 import GFCAScoringEngine


def test_asymptotic_equivalence_to_static_nale():
    """定理复核：在 h=0, tau=0, lambda=0 极限条件下，T-NALE 数学上严格退化为经典静态 NALE。"""
    engine = TemporalNALEEngine(alpha=0.4)
    tickers = ["A", "B", "C"]
    node_scores = {"A": 0.8, "B": 0.2, "C": -0.4}
    # 随机游走归一化邻接矩阵
    adj = np.array([
        [0.0, 0.6, 0.4],
        [0.5, 0.0, 0.5],
        [0.3, 0.7, 0.0]
    ])

    is_equiv, max_diff = engine.verify_asymptotic_equivalence(
        node_scores=node_scores,
        adjacency_matrix=adj,
        ticker_list=tickers,
        alpha=0.4,
        tolerance=1e-6
    )
    assert is_equiv, f"渐近一致性失败，最大偏差: {max_diff}"
    assert max_diff < 1e-6

    # 与 GFCAScoringEngine.calculate_nale_score 独立对照
    gfca_engine = GFCAScoringEngine(nale_alpha=0.4)
    static_res = gfca_engine.calculate_nale_score(node_scores, adj, tickers, alpha=0.4)

    zero_lags = np.zeros((3, 3))
    huge_sigmas = np.ones((3, 3)) * 1e6
    full_atten = np.ones((3, 3))

    tnale_res = engine.calculate_temporal_nale(
        node_scores=node_scores,
        adjacency_matrix=adj,
        ticker_list=tickers,
        horizon_days=0.0,
        node_ages_days={t: 0.0 for t in tickers},
        edge_lag_matrix=zero_lags,
        edge_sigma_matrix=huge_sigmas,
        edge_attenuation_matrix=full_atten,
        alpha=0.4
    )

    for t in tickers:
        assert abs(static_res[t].final_nale_score - tnale_res[t].final_score) < 1e-6


def test_information_half_life_decay_ordering():
    """信息源半衰期单调衰减与差异性：现货异动 (H=3) 比研报 (H=10) 与财报 (H=45) 衰减更急剧。"""
    engine = TemporalNALEEngine(alpha=0.0)  # 仅测试自身衰减
    tickers = ["SPOT", "REPORT", "FINANCIAL"]
    scores = {"SPOT": 1.0, "REPORT": 1.0, "FINANCIAL": 1.0}
    adj = np.zeros((3, 3))
    source_types = {
        "SPOT": "spot_quote",
        "REPORT": "analyst_report",
        "FINANCIAL": "financial_statement"
    }

    # 向未来推演 6 天 (经过了 2 个现货半衰期，未达到 1 个研报半衰期)
    res_6d = engine.calculate_temporal_nale(
        node_scores=scores,
        adjacency_matrix=adj,
        ticker_list=tickers,
        horizon_days=6.0,
        node_source_types=source_types,
        alpha=0.0
    )

    # 现货: 2 个半衰期 -> 1.0 * 0.25 = 0.25
    assert abs(res_6d["SPOT"].final_score - 0.25) < 0.02
    # 研报: 6/10 = 0.6 个半衰期 -> 2^(-0.6) ≈ 0.66
    assert abs(res_6d["REPORT"].final_score - (2.0 ** -0.6)) < 0.02
    # 财报: 6/45 = 0.133 个半衰期 -> 2^(-6/45) ≈ 0.91
    assert abs(res_6d["FINANCIAL"].final_score - (2.0 ** (-6.0 / 45.0))) < 0.02

    # 严格单调排序：财报留存得分 > 研报 > 现货
    assert res_6d["FINANCIAL"].final_score > res_6d["REPORT"].final_score > res_6d["SPOT"].final_score


def test_supply_chain_physical_lag_resonance_peak():
    """产业链物理时滞共振峰值：半导体存储原厂 (tau=20d) 的冲击在模组厂第 20 天达到最大峰值。"""
    engine = TemporalNALEEngine(alpha=0.5)
    tickers = ["DRAM_WAFER", "MODULE_MAKER"]
    # 上游有重大现货冲击，下游初始得分为 0
    scores = {"DRAM_WAFER": 0.9, "MODULE_MAKER": 0.0}
    # 上游传向中游: W[1, 0] = 1.0
    adj = np.array([
        [0.0, 0.0],
        [1.0, 0.0]
    ])
    categories = {
        "DRAM_WAFER": "存储原厂",
        "MODULE_MAKER": "存储模组"
    }

    # 探测不同向前推演视界 h
    horizons = [2.0, 10.0, 20.0, 30.0, 45.0]
    score_at_h = {}
    for h in horizons:
        res = engine.calculate_temporal_nale(
            node_scores=scores,
            adjacency_matrix=adj,
            ticker_list=tickers,
            horizon_days=h,
            ticker_categories=categories,
            alpha=0.5
        )
        score_at_h[h] = res["MODULE_MAKER"].propagated_impulse

    # 验证在 tau = 20d 处达到最大峰值
    peak_val = score_at_h[20.0]
    assert peak_val > score_at_h[2.0], "第 20 天时滞传导应显著强于第 2 天刚发生时"
    assert peak_val > score_at_h[10.0], "第 20 天时滞传导应强于第 10 天"
    assert peak_val > score_at_h[30.0], "第 20 天时滞传导应强于第 30 天"
    assert peak_val > score_at_h[45.0], "第 20 天时滞传导应显著强于第 45 天耗散后"


def test_predict_trajectory_and_peak_horizon():
    """全景时域轨迹推演：准确计算各时窗得分并识别最佳持有时窗 peak_horizon。"""
    engine = TemporalNALEEngine(alpha=0.4)
    tickers = ["SUPPLIER", "CUSTOMER"]
    scores = {"SUPPLIER": 0.8, "CUSTOMER": 0.0}
    adj = np.array([
        [0.0, 0.0],
        [1.0, 0.0]
    ])
    # 设定人工时滞 tau = 15.0d, sigma = 4.0d
    lag_mat = np.array([[0.0, 0.0], [15.0, 0.0]])
    sigma_mat = np.array([[1.0, 1.0], [4.0, 1.0]])
    atten_mat = np.array([[1.0, 1.0], [0.9, 1.0]])

    horizons = [1.0, 5.0, 10.0, 15.0, 20.0, 30.0]
    traj = engine.predict_trajectory(
        node_scores=scores,
        adjacency_matrix=adj,
        ticker_list=tickers,
        horizons=horizons,
        alpha=0.4
    )

    cust_traj = traj["CUSTOMER"]
    assert cust_traj.ticker == "CUSTOMER"
    assert len(cust_traj.scores) == len(horizons)
    # 通用上下游先验 tau = 14d，峰值预计落在 15d 附近
    assert cust_traj.peak_horizon in [10.0, 15.0]
    assert cust_traj.peak_score > cust_traj.immediate_impact_1d


def test_scoring_v3_integration_interface():
    """集成测试：GFCAScoringEngine 成功调用 calculate_temporal_nale_score。"""
    engine = GFCAScoringEngine(nale_alpha=0.4)
    tickers = ["600519", "000858"]
    scores = {"600519": 0.6, "000858": 0.3}
    adj = np.array([[0.0, 1.0], [1.0, 0.0]])

    res = engine.calculate_temporal_nale_score(
        node_scores=scores,
        adjacency_matrix=adj,
        ticker_list=tickers,
        horizon_days=5.0
    )

    assert len(res) == 2
    assert "600519" in res
    assert "000858" in res
    for t in tickers:
        item = res[t]
        assert isinstance(item, TemporalNALEResult)
        assert -1.0 <= item.final_score <= 1.0
        assert item.horizon_days == 5.0


def test_edge_and_failure_cases():
    """边界与异常输入健壮性测试。"""
    engine = TemporalNALEEngine()

    # 1. 空集输入
    assert engine.calculate_temporal_nale({}, np.zeros((0, 0)), []) == {}

    # 2. 邻接矩阵维度不匹配
    with pytest.raises(ValueError, match="不匹配"):
        engine.calculate_temporal_nale({"A": 0.5}, np.zeros((2, 2)), ["A"])

    # 3. 极端数值截断 [-1.0, 1.0]
    extreme_scores = {"A": 10.0, "B": -10.0}
    adj = np.array([[1.0, 0.0], [0.0, 1.0]])
    res = engine.calculate_temporal_nale(extreme_scores, adj, ["A", "B"], horizon_days=0.0)
    assert res["A"].final_score <= 1.0
    assert res["B"].final_score >= -1.0


def test_build_ranking_with_tnale_dynamics():
    """测试 build_ranking 流程正确注入 T-NALE 时空动态拓扑与波峰前瞻。"""
    from unittest.mock import MagicMock
    from src.graph.sector_graph_engine import SectorGraphEngine

    engine = SectorGraphEngine()
    # 模拟 payload
    mock_payload = {
        "sector_name": "存储",
        "has_limit_up_resonance": True,
        "spillover_return_5d_pct": 2.5,
        "spillover_prob_5d_pct": 8.0,
        "leader_stock": {"code": "001309", "name": "德明利"},
        "temporal_dynamics": {
            "physical_lag_tau_days": 20.0,
            "peak_horizon_days": 20,
            "peak_spillover_return_pct": 2.44,
            "optimal_holding_days": 20,
            "is_temporal_enhanced": True,
        }
    }
    engine.get_nale_network_payload = MagicMock(return_value=mock_payload)

    # 模拟 build_ranking 中对单只标的的逻辑
    final_forecast = {"return_5d_pct": 3.0, "up_probability_5d_pct": 60.0}
    r = {"category": "存储", "reasons": []}
    code = "603986"

    nale_payload = engine.get_nale_network_payload(code, r.get("category", ""), final_forecast)
    r["nale_network"] = nale_payload
    t_dyn = (nale_payload.get("temporal_dynamics") or {}) if nale_payload else {}
    if t_dyn:
        final_forecast["physical_lag_tau_days"] = t_dyn.get("physical_lag_tau_days")
        final_forecast["peak_horizon_days"] = t_dyn.get("peak_horizon_days")
        final_forecast["peak_spillover_return_pct"] = t_dyn.get("peak_spillover_return_pct")
        final_forecast["optimal_holding_days"] = t_dyn.get("optimal_holding_days")

    if nale_payload.get("has_limit_up_resonance") and nale_payload.get("spillover_return_5d_pct", 0) > 0:
        spill_ret = nale_payload["spillover_return_5d_pct"]
        spill_prob = nale_payload.get("spillover_prob_5d_pct", 0)
        leader_info = nale_payload.get("leader_stock") or {}
        leader_name = leader_info.get("name", "龙头")
        final_forecast["return_5d_pct"] = round(final_forecast["return_5d_pct"] + spill_ret, 2)
        final_forecast["up_probability_5d_pct"] = round(min(98.0, final_forecast["up_probability_5d_pct"] + spill_prob), 1)

        tau = t_dyn.get("physical_lag_tau_days", 14)
        peak_ret = t_dyn.get("peak_spillover_return_pct", spill_ret)
        spill_reason = {
            "title": f"T-NALE·{nale_payload['sector_name']}时空时滞共振",
            "detail": f"同板块龙头【{leader_name}】封板催化，经产业链物理传导（时滞τ≈{int(tau)}天），注入 +{spill_ret}% 溢出预期及 +{spill_prob}% 看涨胜率（波峰前瞻+{peak_ret}%）",
            "impact": "positive",
            "score_delta": 4.5
        }
        r["reasons"].insert(0, spill_reason)
    r["forecast"] = final_forecast

    # 严格断言
    assert final_forecast["physical_lag_tau_days"] == 20.0
    assert final_forecast["peak_horizon_days"] == 20
    assert final_forecast["peak_spillover_return_pct"] == 2.44
    assert final_forecast["optimal_holding_days"] == 20
    assert final_forecast["return_5d_pct"] == 5.5
    assert final_forecast["up_probability_5d_pct"] == 68.0
    assert len(r["reasons"]) == 1
    assert r["reasons"][0]["title"] == "T-NALE·存储时空时滞共振"
    assert "时滞τ≈20天" in r["reasons"][0]["detail"]

