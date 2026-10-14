# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_performance_metrics.py —— 回测绩效指标纯函数独立复核

全部断言用小样本手算值核对（AGENTS.md 第3条），不依赖被测函数自身推导结果。
"""

import math

import pytest

from src.sector_rotation.backtest.performance_metrics import (
    PerformanceMetrics,
    annualized_return,
    average_holding_days,
    compute_metrics,
    cost_ratio,
    daily_returns,
    max_drawdown,
    rotation_count,
    sharpe_ratio,
    total_return,
    win_rate,
)


class TestTotalReturn:
    def test_hand_computed(self):
        # 100 -> 110 -> 99: 总收益 = 99/100 - 1 = -0.01
        assert total_return([100.0, 110.0, 99.0]) == pytest.approx(-0.01)

    def test_short_series_defensive(self):
        assert total_return([]) == 0.0
        assert total_return([100.0]) == 0.0

    def test_zero_start_defensive(self):
        assert total_return([0.0, 100.0]) == 0.0


class TestDailyReturns:
    def test_hand_computed(self):
        # 100->110: +0.1; 110->99: -0.1
        assert daily_returns([100.0, 110.0, 99.0]) == pytest.approx([0.1, -0.1])

    def test_zero_prev_gives_zero(self):
        assert daily_returns([0.0, 5.0]) == pytest.approx([0.0])

    def test_length_relation(self):
        nav = [1.0, 2.0, 3.0, 4.0]
        assert len(daily_returns(nav)) == len(nav) - 1


class TestAnnualizedReturn:
    def test_full_year_equals_total(self):
        # 252 交易日翻 1.1 倍 -> 年化即 0.1
        nav = [100.0, 110.0]
        assert annualized_return(nav, trading_days=252) == pytest.approx(0.1)

    def test_half_year_compounds(self):
        # 126 日 +10% -> 年化 (1.1)^2 - 1 = 0.21
        nav = [100.0, 110.0]
        assert annualized_return(nav, trading_days=126) == pytest.approx(0.21, rel=1e-9)

    def test_total_loss_floor(self):
        assert annualized_return([100.0, 0.0]) == -1.0


class TestSharpeRatio:
    def test_hand_computed_two_points(self):
        # rets [0.1, -0.1]: mean=0 -> sharpe=0（var>0 可计算）
        assert sharpe_ratio([0.1, -0.1]) == pytest.approx(0.0)

    def test_hand_computed_three_points(self):
        # rets [0.01, 0.02, 0.03]: mean=0.02, std(ddof=1)=0.01
        # sharpe = 0.02/0.01*sqrt(252) = 2*sqrt(252)
        expected = 2.0 * math.sqrt(252.0)
        assert sharpe_ratio([0.01, 0.02, 0.03]) == pytest.approx(expected)

    def test_none_when_insufficient(self):
        assert sharpe_ratio([]) is None
        assert sharpe_ratio([0.05]) is None

    def test_none_when_zero_variance(self):
        # 全零波动不可计算返回 None（而非伪装为 0）
        assert sharpe_ratio([0.0, 0.0, 0.0]) is None


class TestMaxDrawdown:
    def test_hand_computed(self):
        # peak 110 -> trough 99: 1 - 99/110 = 0.1
        assert max_drawdown([100.0, 110.0, 99.0, 105.0]) == pytest.approx(0.1)

    def test_monotonic_up_zero(self):
        assert max_drawdown([1.0, 2.0, 3.0]) == 0.0

    def test_monotonic_down(self):
        # 峰值为首点 100，低点 50 -> 0.5
        assert max_drawdown([100.0, 80.0, 50.0]) == pytest.approx(0.5)

    def test_short_series(self):
        assert max_drawdown([100.0]) == 0.0


class TestWinRateAndCounts:
    def test_hand_computed(self):
        assert win_rate([0.1, -0.2, 0.05, 0.0]) == pytest.approx(0.5)

    def test_none_when_empty(self):
        assert win_rate([]) is None

    def test_rotation_count(self):
        decisions = [{"should_rotate": True}, {"should_rotate": False}, {"should_rotate": True}]
        assert rotation_count(decisions) == 2

    def test_rotation_count_accepted_basis(self):
        # 带 rotation_accepted 标记时以被实际接受的轮动为准（重复触发不计入）
        decisions = [
            {"should_rotate": True, "rotation_accepted": True},
            {"should_rotate": True},   # 计划执行中重复触发，未被接受
            {"should_rotate": False},
        ]
        assert rotation_count(decisions) == 1

    def test_average_holding_days(self):
        assert average_holding_days([5, 10, 15]) == pytest.approx(10.0)
        assert average_holding_days([]) is None
        assert average_holding_days([0, 0]) is None

    def test_cost_ratio(self):
        assert cost_ratio(1000.0, 100_000.0) == pytest.approx(0.01)
        assert cost_ratio(1000.0, 0.0) == 0.0


class TestComputeMetrics:
    def test_aggregation_consistency(self):
        nav = [100.0, 110.0, 99.0, 108.9]
        decisions = [{"should_rotate": True}]
        m = compute_metrics(
            nav=nav, decisions=decisions,
            trade_returns=[0.089], holding_segments=[4],
            total_cost=100.0, initial_capital=100.0,
        )
        assert isinstance(m, PerformanceMetrics)
        # 手算：total = 108.9/100 - 1 = 0.089
        assert m.total_return == pytest.approx(0.089)
        assert m.rotations == 1
        assert m.win_rate == pytest.approx(1.0)
        assert m.avg_holding_days == pytest.approx(4.0)
        assert m.cost_ratio == pytest.approx(1.0)
        assert m.n_observations == 4

    def test_serializable(self):
        m = PerformanceMetrics(
            total_return=0.1, annualized_return=0.2, sharpe=None, max_drawdown=0.05,
            win_rate=None, rotations=0, avg_holding_days=None, cost_ratio=0.0,
            n_observations=10,
        )
        d = m.to_dict()
        assert d["sharpe"] is None
        assert d["sharpe_annualization"].startswith("mean/std(ddof=1)*sqrt(252)")
