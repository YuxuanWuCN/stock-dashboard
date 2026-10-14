# -*- coding: utf-8 -*-
r"""tests/test_portfolio_fof.py —— FOF 组合配置系统全链路与独立复核测试

覆盖：
1. NALE 传播公式手算小样本精确验证 (S_{NALE} = (1 - \alpha)S_0 + \alpha W S_0)
2. 信号适配器 Fail-Closed 边界与缺失值测试
3. 资产配置器全额归一 (\sum w = 1.0)、单标的上限与行业上限约束
4. 风险预算分层回撤状态机与恢复确认机制
5. 调仓死区与摩擦成本计算
6. 截断不变性测试 (严格无未来函数)
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from src.portfolio.contracts import (
    AggregationMethod,
    AssetInfo,
    AssetRole,
    AssetType,
    PointInTimeSignal,
    PortfolioWeights,
    RiskBudgetConfig,
    RiskState,
)
from src.portfolio.signal_adapter import NALESignalAdapter
from src.portfolio.allocator import AllocationConfig, FOFAllocator
from src.portfolio.risk_budget import RiskBudgetManager
from src.portfolio.rebalancer import RebalanceConfig, RebalanceManager
from src.portfolio.backtest import BacktestConfig, FOFBacktestEngine


# ============================================================================
# 1. 手算小样本测试 (Hand-computed small sample verification)
# ============================================================================

def test_nale_hand_computation_small_sample():
    r"""手算验证 NALE 核心传导方程:
    S_{NALE} = (1 - \alpha) S_0 + \alpha \cdot (W_{norm} S_0)

    设定 3 个节点 A, B, C:
    S_0 = [0.8, -0.4, 0.2]^T
    W = [[0, 1, 1],
         [1, 0, 0],
         [0, 1, 0]]
    alpha = 0.4 (1 - alpha = 0.6)

    行和归一化 W_{norm}:
    Row 0: [0, 0.5, 0.5] -> 0.5*(-0.4) + 0.5*(0.2) = -0.2 + 0.1 = -0.10
    Row 1: [1, 0, 0]     -> 1.0*(0.8) = 0.80
    Row 2: [0, 1, 0]     -> 1.0*(-0.4) = -0.40

    理论计算:
    S_{NALE, A} = 0.6 * 0.8 + 0.4 * (-0.10) = 0.48 - 0.04 = 0.44
    S_{NALE, B} = 0.6 * (-0.4) + 0.4 * 0.80 = -0.24 + 0.32 = 0.08
    S_{NALE, C} = 0.6 * 0.2 + 0.4 * (-0.40) = 0.12 - 0.16 = -0.04
    """
    adapter = NALESignalAdapter(default_alpha=0.4)
    ticker_list = ["A", "B", "C"]
    node_scores = {"A": 0.8, "B": -0.4, "C": 0.2}
    adj = np.array([
        [0.0, 1.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ])

    scores = adapter.compute_static_nale(
        node_scores=node_scores,
        adjacency_matrix=adj,
        ticker_list=ticker_list,
        alpha=0.4,
    )

    assert pytest.approx(scores["A"], rel=1e-5) == 0.44
    assert pytest.approx(scores["B"], rel=1e-5) == 0.08
    assert pytest.approx(scores["C"], rel=1e-5) == -0.04


def test_fund_aggregation_hand_computation():
    r"""手算验证行业/基金三种解耦聚合公式:
    成分股:
    Stock 1: score=0.6, q=0.8, weight=100
    Stock 2: score=-0.2, q=1.0, weight=200
    Stock 3: score=0.4, q=0.5, weight=100

    1. EQUAL_WEIGHT (等权聚合):
       S_{fund} = (0.6 + (-0.2) + 0.4) / 3 = 0.8 / 3 ≈ 0.266667

    2. MCAP_WEIGHT (市值加权):
       Denominator = 100 + 200 + 100 = 400
       Numerator = 100*0.6 + 200*(-0.2) + 100*0.4 = 60
       S_{fund} = 60 / 400 = 0.15

    3. CONFIDENCE_WEIGHT (置信度加权):
       Denominator = 0.8 + 1.0 + 0.5 = 2.3
       Numerator = 0.8*0.6 + 1.0*(-0.2) + 0.5*0.4 = 0.48
       S_{fund} = 0.48 / 2.3 ≈ 0.2086957
    """
    adapter = NALESignalAdapter()
    constituents = ["S1", "S2", "S3"]
    scores = {"S1": 0.6, "S2": -0.2, "S3": 0.4}
    confs = {"S1": 0.8, "S2": 1.0, "S3": 0.5}
    weights = {"S1": 100.0, "S2": 200.0, "S3": 100.0}

    # 1. 等权测试
    sig_eq = adapter.aggregate_to_fund_signal(
        as_of_date="2026-10-13",
        fund_ticker="ETF_TEST",
        constituents=constituents,
        stock_scores=scores,
        stock_confidences=confs,
        constituent_weights=weights,
        method=AggregationMethod.EQUAL_WEIGHT,
    )
    assert sig_eq.is_valid is True
    assert pytest.approx(sig_eq.score, rel=1e-5) == (0.8 / 3.0)

    # 2. 市值加权测试
    sig_mcap = adapter.aggregate_to_fund_signal(
        as_of_date="2026-10-13",
        fund_ticker="ETF_TEST",
        constituents=constituents,
        stock_scores=scores,
        stock_confidences=confs,
        constituent_weights=weights,
        method=AggregationMethod.MCAP_WEIGHT,
    )
    assert sig_mcap.is_valid is True
    assert pytest.approx(sig_mcap.score, rel=1e-5) == 0.15

    # 3. 置信度加权测试
    sig_conf = adapter.aggregate_to_fund_signal(
        as_of_date="2026-10-13",
        fund_ticker="ETF_TEST",
        constituents=constituents,
        stock_scores=scores,
        stock_confidences=confs,
        constituent_weights=weights,
        method=AggregationMethod.CONFIDENCE_WEIGHT,
    )
    assert sig_conf.is_valid is True
    assert pytest.approx(sig_conf.score, rel=1e-5) == (0.48 / 2.3)
    assert sig_eq.score != sig_mcap.score != sig_conf.score


# ============================================================================
# 2. 信号适配器 Fail-Closed 边界测试
# ============================================================================

def test_signal_adapter_fail_closed_cases():
    adapter = NALESignalAdapter()

    # 1. 成分股为空
    sig_empty = adapter.aggregate_to_fund_signal(
        as_of_date="2026-10-13",
        fund_ticker="ETF_EMPTY",
        constituents=[],
        stock_scores={"S1": 0.5},
    )
    assert sig_empty.is_valid is False
    assert "empty" in sig_empty.refusal_reason.lower()
    assert sig_empty.score == 0.0

    # 2. 成分股全部缺失打分
    sig_missing = adapter.aggregate_to_fund_signal(
        as_of_date="2026-10-13",
        fund_ticker="ETF_MISSING",
        constituents=["S1", "S2"],
        stock_scores={"S9": 0.5},
    )
    assert sig_missing.is_valid is False
    assert sig_missing.score == 0.0

    # 3. 包含 NaN / Inf
    sig_nan = adapter.aggregate_to_fund_signal(
        as_of_date="2026-10-13",
        fund_ticker="ETF_NAN",
        constituents=["S1"],
        stock_scores={"S1": float("nan")},
    )
    assert sig_nan.is_valid is False
    assert sig_nan.score == 0.0


# ============================================================================
# 3. 资产配置器约束与权重归一测试
# ============================================================================

@pytest.fixture
def sample_assets():
    return {
        "BOND": AssetInfo(
            ticker="BOND",
            name="国债ETF",
            asset_type=AssetType.BOND,
            role=AssetRole.CORE_DEFENSIVE,
            benchmark_weight=0.70,
            max_weight=1.00,
        ),
        "INDEX300": AssetInfo(
            ticker="INDEX300",
            name="沪深300ETF",
            asset_type=AssetType.BROAD_EQUITY,
            role=AssetRole.CORE_BETA,
            benchmark_weight=0.30,
            max_weight=0.50,
        ),
        "SAT_CHIP": AssetInfo(
            ticker="SAT_CHIP",
            name="芯片ETF",
            asset_type=AssetType.SECTOR_ETF,
            role=AssetRole.SATELLITE_ALPHA,
            sector="semiconductor",
            max_weight=0.10,
        ),
        "SAT_GREEN": AssetInfo(
            ticker="SAT_GREEN",
            name="光伏ETF",
            asset_type=AssetType.SECTOR_ETF,
            role=AssetRole.SATELLITE_ALPHA,
            sector="new_energy",
            max_weight=0.10,
        ),
        "SAT_GOLD": AssetInfo(
            ticker="SAT_GOLD",
            name="黄金ETF",
            asset_type=AssetType.SECTOR_ETF,
            role=AssetRole.SATELLITE_ALPHA,
            sector="gold",
            max_weight=0.10,
        ),
    }


def test_allocator_strict_unity_and_caps(sample_assets):
    risk_config = RiskBudgetConfig(
        max_satellite_budget=0.25,
        max_single_satellite=0.08,
        max_sector_exposure=0.12,
        min_defensive_weight=0.45,
    )
    allocator = FOFAllocator(
        assets=sample_assets,
        alloc_config=AllocationConfig(base_satellite_budget=0.20),
        risk_config=risk_config,
    )

    signals = {
        "SAT_CHIP": PointInTimeSignal("2026-10-13", "SAT_CHIP", score=0.9, confidence=1.0, source_method="test"),
        "SAT_GREEN": PointInTimeSignal("2026-10-13", "SAT_GREEN", score=0.8, confidence=1.0, source_method="test"),
        "SAT_GOLD": PointInTimeSignal("2026-10-13", "SAT_GOLD", score=-0.3, confidence=1.0, source_method="test"),
    }

    pw = allocator.allocate(
        trade_date="2026-10-13",
        signals=signals,
        current_risk_state=RiskState.NORMAL,
    )

    # 1. 权重精确归一
    assert pytest.approx(sum(pw.weights.values()), rel=1e-5) == 1.0

    # 2. 单标的上限严格生效 (<= 0.08)
    assert pw.weights["SAT_CHIP"] <= 0.08 + 1e-6
    assert pw.weights["SAT_GREEN"] <= 0.08 + 1e-6

    # 3. 负信号不予分配
    assert pw.weights["SAT_GOLD"] == 0.0

    # 4. 最低防御底仓硬约束 (>= 0.45)
    assert pw.weights["BOND"] >= 0.45 - 1e-6


def test_allocator_graceful_fallback_on_negative_or_invalid_signals(sample_assets):
    allocator = FOFAllocator(assets=sample_assets)

    # 全部无效或为负信号
    signals = {
        "SAT_CHIP": PointInTimeSignal("2026-10-13", "SAT_CHIP", score=-0.5, confidence=1.0, source_method="test"),
        "SAT_GREEN": PointInTimeSignal("2026-10-13", "SAT_GREEN", score=0.0, confidence=1.0, source_method="test", is_valid=False),
    }

    pw = allocator.allocate(
        trade_date="2026-10-13",
        signals=signals,
        current_risk_state=RiskState.NORMAL,
    )

    # 卫星仓位全为 0
    assert pw.weights["SAT_CHIP"] == 0.0
    assert pw.weights["SAT_GREEN"] == 0.0
    assert pw.weights["SAT_GOLD"] == 0.0
    # 权重严格归一
    assert pytest.approx(sum(pw.weights.values()), rel=1e-5) == 1.0
    # 防御仓吸收了未分配预算
    assert pw.weights["BOND"] >= 0.50


# ============================================================================
# 4. 风险预算状态机测试
# ============================================================================

def test_risk_budget_state_machine_transitions():
    config = RiskBudgetConfig(
        dd_threshold_watch=0.05,
        dd_threshold_defensive=0.08,
        dd_threshold_protective=0.10,
        recovery_confirmation_days=3,
    )
    rm = RiskBudgetManager(config=config)

    # 初始 NORMAL
    state, dd, peak = rm.update_risk_state(1.0)
    assert state == RiskState.NORMAL
    assert dd == 0.0

    # 净值下跌 6% -> 触发 WATCH (回撤 6% >= 5%)
    state, dd, peak = rm.update_risk_state(0.94)
    assert state == RiskState.WATCH
    assert pytest.approx(dd, rel=1e-4) == 0.06

    # 净值下跌 9% -> 触发 DEFENSIVE (回撤 9% >= 8%)
    state, dd, peak = rm.update_risk_state(0.91)
    assert state == RiskState.DEFENSIVE

    # 净值下跌 11% -> 触发 PROTECTIVE (回撤 11% >= 10%)
    state, dd, peak = rm.update_risk_state(0.89)
    assert state == RiskState.PROTECTIVE

    # 企稳回升到 0.93 (回撤 7% 应对应 WATCH)，需 3 天确认
    state1, _, _ = rm.update_risk_state(0.93)
    assert state1 == RiskState.PROTECTIVE  # 第 1 天未确认，保持原保护状态
    state2, _, _ = rm.update_risk_state(0.93)
    assert state2 == RiskState.PROTECTIVE  # 第 2 天未确认
    state3, _, _ = rm.update_risk_state(0.93)
    assert state3 == RiskState.WATCH        # 第 3 天确认升级恢复


# ============================================================================
# 5. 截断不变性测试 (严格无未来函数)
# ============================================================================

def test_truncation_invariance_no_lookahead(sample_assets):
    """截断不变性测试：在序列后追加未来数据，不应改变历史时点的任何权重与信号。"""
    dates = pd.date_range("2026-01-01", periods=10, freq="B").strftime("%Y-%m-%d").tolist()
    returns_full = pd.DataFrame(
        np.random.RandomState(42).normal(0.0005, 0.01, size=(10, len(sample_assets))),
        index=dates,
        columns=list(sample_assets.keys()),
    )

    signals_by_date = {
        d: {
            "SAT_CHIP": PointInTimeSignal(d, "SAT_CHIP", score=0.6, confidence=1.0, source_method="mock"),
            "SAT_GREEN": PointInTimeSignal(d, "SAT_GREEN", score=0.3, confidence=0.8, source_method="mock"),
        }
        for d in dates
    }

    engine_short = FOFBacktestEngine(
        assets=sample_assets,
        returns_df=returns_full.iloc[:5],
    )
    logs_short, _ = engine_short.run_backtest(
        mode="risk_constrained_nale",
        signals_by_date=signals_by_date,
        config=BacktestConfig(start_date=dates[0], end_date=dates[4]),
    )

    engine_full = FOFBacktestEngine(
        assets=sample_assets,
        returns_df=returns_full,
    )
    logs_full, _ = engine_full.run_backtest(
        mode="risk_constrained_nale",
        signals_by_date=signals_by_date,
        config=BacktestConfig(start_date=dates[0], end_date=dates[9]),
    )

    # 检查前 5 天的逐日净值与持仓权重完全一致
    for i in range(5):
        assert logs_short[i].trade_date == logs_full[i].trade_date
        assert pytest.approx(logs_short[i].nav, rel=1e-6) == logs_full[i].nav
        for ticker in sample_assets:
            assert pytest.approx(
                logs_short[i].weights[ticker], rel=1e-6
            ) == logs_full[i].weights[ticker]


# ============================================================================
# 6. 四组回测模式完整性与死区交易测试
# ============================================================================

def test_backtest_all_four_modes(sample_assets):
    dates = pd.date_range("2026-01-01", periods=10, freq="B").strftime("%Y-%m-%d").tolist()
    returns_df = pd.DataFrame(
        np.random.RandomState(42).normal(0.0005, 0.01, size=(10, len(sample_assets))),
        index=dates,
        columns=list(sample_assets.keys()),
    )
    signals_by_date = {
        d: {
            "SAT_CHIP": PointInTimeSignal(d, "SAT_CHIP", score=0.6, confidence=1.0, source_method="mock"),
            "SAT_GREEN": PointInTimeSignal(d, "SAT_GREEN", score=0.3, confidence=0.8, source_method="mock"),
        }
        for d in dates
    }
    cfg = BacktestConfig(start_date=dates[0], end_date=dates[-1], benchmark_ticker="INDEX300")
    engine = FOFBacktestEngine(assets=sample_assets, returns_df=returns_df)

    for mode in ["baseline", "nale", "risk_constrained_nale", "sentiment_only"]:
        logs, metrics = engine.run_backtest(mode, signals_by_date, cfg)
        assert len(logs) == 10
        assert metrics.trading_days == 10
        assert math.isfinite(metrics.annualized_return)
        assert math.isfinite(metrics.max_drawdown)
        # 逐日权重归一性校验
        for log in logs:
            assert pytest.approx(sum(log.weights.values()), rel=1e-5) == 1.0


def test_rebalance_deadband_execution(sample_assets):
    rm = RebalanceManager(sample_assets, RebalanceConfig(deadband_threshold=0.02, min_trade_weight=0.005))
    curr_w = {"BOND": 0.70, "INDEX300": 0.30, "SAT_CHIP": 0.0, "SAT_GREEN": 0.0, "SAT_GOLD": 0.0}
    # 目标持仓变动在死区内 (0.01 < 0.02)
    target_w = PortfolioWeights(
        trade_date="2026-10-13",
        weights={"BOND": 0.69, "INDEX300": 0.31, "SAT_CHIP": 0.0, "SAT_GREEN": 0.0, "SAT_GOLD": 0.0},
        risk_state=RiskState.NORMAL,
        satellite_budget_used=0.0,
        volatility_scale=1.0,
    )
    exec_w, turnover, cost, trades = rm.apply_deadband_and_execute("2026-10-13", curr_w, target_w)
    # 应被死区过滤，不发生交易
    assert turnover == 0.0
    assert cost == 0.0
    assert len(trades) == 0
    assert exec_w["BOND"] == 0.70
    assert exec_w["INDEX300"] == 0.30
