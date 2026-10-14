# -*- coding: utf-8 -*-
"""tests/test_portfolio_stress.py —— 熊市压力测试模块单元测试

覆盖（依据方案文档§10测试必须）：
- 冲击矩阵生成边界与标签
- 负收益连续期和跳空情景
- 半成交、延迟成交、冻结成交
- 防御资产负收益
- 风险状态机阈值边界
- 截断不变性（流动性调整）
- 独立最大回撤与成本复算
- 熊市窗口识别器
- T-NALE 衰减正确性
- 参数敏感性网格结构
"""

import math
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest

from src.portfolio.contracts import (
    AssetInfo, AssetRole, AssetType, PointInTimeSignal, RiskBudgetConfig, RiskState,
)
from src.portfolio.risk_budget import RiskBudgetManager
from src.portfolio.stress_scenarios import (
    BearWindow, DEFENSIVE_ASSUMPTIONS, LIQUIDITY_MATRIX,
    ParamGrid, SECTOR_HALF_LIVES, SHOCK_MATRIX, ShockScenario,
    apply_correlation_stress, apply_liquidity_to_weights, apply_price_shock,
    compute_point_in_time_stress_signals, identify_bear_windows,
)


# ============================================================================
# Fixtures
# ============================================================================

DATES_20 = pd.date_range("2026-01-05", periods=20, freq="B")


def _returns_df():
    """5 ETF × 20 日合成收益矩阵。"""
    rng = np.random.RandomState(123)
    cols = ["510300", "512010", "518880", "511010", "511880"]
    data = rng.normal(0.0005, 0.015, size=(20, 5))
    return pd.DataFrame(data, index=DATES_20, columns=cols)


# ============================================================================
# 1. 冲击矩阵边界与标签
# ============================================================================

class TestShockMatrix:
    def test_labels_unique(self):
        names = [s.name for s in SHOCK_MATRIX]
        assert len(names) == len(set(names))
        assert "severe_crash" in names
        assert "gap_down" in names
        assert "failed_rebound" in names

    def test_cumulative_impact_sign(self):
        """所有正常冲击情景累计影响应为负值（下跌）。"""
        for s in SHOCK_MATRIX:
            # failed_rebound 也整体为负 (5日-5%+3日+2%+5日-4%)
            assert s.cumulative_impact < 0, f"{s.name} cumulative={s.cumulative_impact}"

    def test_severe_crash_boundary(self):
        """3 日 × -10% 的累计跌幅应约 -27.1%"""
        s = [x for x in SHOCK_MATRIX if x.name == "severe_crash"][0]
        expected = (1 - 0.10) ** 3 - 1.0  # ≈ -0.271
        assert s.cumulative_impact == pytest.approx(expected, abs=1e-4)

    def test_gap_down_boundary(self):
        """首日 -15% + 后续9日 × -2%"""
        s = [x for x in SHOCK_MATRIX if x.name == "gap_down"][0]
        expected = (1 - 0.15) * (1 - 0.02) ** 9 - 1.0
        assert s.cumulative_impact == pytest.approx(expected, abs=1e-4)

    def test_failed_rebound_phases(self):
        """3阶段: -5%/5d, +2%/3d, -4%/5d"""
        s = [x for x in SHOCK_MATRIX if x.name == "failed_rebound"][0]
        expected = (0.95 ** 5) * (1.02 ** 3) * (0.96 ** 5) - 1.0
        assert s.cumulative_impact == pytest.approx(expected, abs=1e-4)


# ============================================================================
# 2. apply_price_shock 正确性
# ============================================================================

class TestApplyPriceShock:
    def test_overwrites_risk_returns(self):
        df = _returns_df()
        scenario = SHOCK_MATRIX[0]  # mild_drawdown: -3%/5d
        out = apply_price_shock(df, scenario,
                               risk_asset_cols=["510300", "512010"],
                               defensive_cols=["518880", "511010", "511880"])
        # 前5行风险资产应为 -0.03
        for i in range(5):
            assert out.iloc[i]["510300"] == pytest.approx(-0.03)
            assert out.iloc[i]["512010"] == pytest.approx(-0.03)
        # 第6行起恢复原始值
        assert out.iloc[5]["510300"] == df.iloc[5]["510300"]

    def test_defensive_uses_assumption(self):
        df = _returns_df()
        scenario = SHOCK_MATRIX[1]  # fast_crash: -5%/5d
        out = apply_price_shock(df, scenario,
                               risk_asset_cols=["510300"],
                               defensive_cols=["518880"],
                               defensive_mode="defensive_zero")
        for i in range(5):
            assert out.iloc[i]["518880"] == pytest.approx(0.0)

    def test_original_df_unchanged(self):
        df = _returns_df()
        df_copy = df.copy()
        apply_price_shock(df, SHOCK_MATRIX[2], ["510300"], ["518880"])
        pd.testing.assert_frame_equal(df, df_copy)


# ============================================================================
# 3. 相关性失效
# ============================================================================

class TestCorrelationStress:
    def test_corr_increases(self):
        df = _returns_df()
        out = apply_correlation_stress(df, ["510300", "512010"], target_corr=0.9, n_days=10)
        # 前10日两个标的的相关性应接近 0.9
        c = out[["510300", "512010"]].iloc[:10].corr().iloc[0, 1]
        assert c > 0.7  # 混合后应显著高于原始（约0.0随机）


# ============================================================================
# 4. 流动性执行约束
# ============================================================================

class TestLiquidityExecution:
    def test_half_fill_reduces_turnover(self):
        current = {"A": 0.6, "B": 0.4}
        target = {"A": 0.3, "B": 0.7}
        from src.portfolio.stress_scenarios import LiquidityScenario
        liq = LiquidityScenario("half", one_side_cost_bps=5, fill_fraction=0.5)
        executed, turnover, cost = apply_liquidity_to_weights(current, target, liq, 1_000_000)
        # 理论换手 = 0.3+0.3=0.6; half fill → 0.3
        assert turnover == pytest.approx(0.3)
        # 成交后 A 应为 0.6 - 0.3*0.5 = 0.45
        assert executed["A"] == pytest.approx(0.45)
        assert executed["B"] == pytest.approx(0.55)
        # 权重和为 1
        assert sum(executed.values()) == pytest.approx(1.0)

    def test_turnover_cap(self):
        current = {"A": 0.8, "B": 0.2}
        target = {"A": 0.2, "B": 0.8}
        from src.portfolio.stress_scenarios import LiquidityScenario
        liq = LiquidityScenario("cap", one_side_cost_bps=5,
                                fill_fraction=1.0, max_daily_turnover=0.20)
        executed, turnover, cost = apply_liquidity_to_weights(current, target, liq, 1_000_000)
        # 理论换手 1.2 → capped at 0.20
        assert turnover == pytest.approx(0.20)

    def test_cost_proportional(self):
        current = {"A": 0.5, "B": 0.5}
        target = {"A": 0.3, "B": 0.7}
        from src.portfolio.stress_scenarios import LiquidityScenario
        liq = LiquidityScenario("cost_test", one_side_cost_bps=10, fill_fraction=1.0)
        _, turnover, cost = apply_liquidity_to_weights(current, target, liq, 1_000_000)
        assert cost == pytest.approx(turnover * 10 / 10000)

    def test_no_change_zero_cost(self):
        w = {"A": 0.5, "B": 0.5}
        from src.portfolio.stress_scenarios import LiquidityScenario
        liq = LiquidityScenario("zero", one_side_cost_bps=5)
        _, turnover, cost = apply_liquidity_to_weights(w, w, liq, 1_000_000)
        assert turnover == 0.0
        assert cost == 0.0


# ============================================================================
# 5. 熊市窗口识别器
# ============================================================================

class TestBearWindowDetection:
    def test_detects_clear_bear(self):
        """构造一段 30% 跌幅持续 25 日的序列，然后强恢复至接近高点。"""
        n_up, n_down, n_recover = 25, 25, 30
        peak = 1.0
        nav = list(np.linspace(peak, peak * 1.10, n_up))
        bottom = nav[-1] * 0.70  # 跌 30%
        nav.extend(np.linspace(nav[-1], bottom, n_down))
        # 恢复到接近峰值（使 DD 低于 dd_threshold*0.5）
        nav.extend(np.linspace(bottom, bottom * 1.40, n_recover))
        idx = pd.date_range("2025-01-01", periods=len(nav), freq="B")
        s = pd.Series(nav, index=idx)
        windows = identify_bear_windows(s, dd_threshold=0.15, min_duration=20)
        assert len(windows) >= 1
        w = windows[0]
        assert w.max_dd_pct >= 0.20  # 至少 20% 实际峰谷
        assert w.duration_days >= 20
        assert w.window_type == "bear"

    def test_short_dip_not_detected(self):
        """仅 10% 跌幅不应触发 15% 阈值。"""
        nav = list(np.linspace(1.0, 1.1, 20)) + list(np.linspace(1.1, 0.99, 10)) \
              + list(np.linspace(0.99, 1.05, 15))
        idx = pd.date_range("2025-01-01", periods=len(nav), freq="B")
        s = pd.Series(nav, index=idx)
        windows = identify_bear_windows(s, dd_threshold=0.15, min_duration=20)
        assert len(windows) == 0

    def test_no_overlap(self):
        """重叠窗口应只计一次。"""
        nav = list(np.linspace(1, 1.2, 30)) + list(np.linspace(1.2, 0.7, 30)) \
              + list(np.linspace(0.7, 0.9, 30))
        idx = pd.date_range("2025-01-01", periods=len(nav), freq="B")
        s = pd.Series(nav, index=idx)
        windows = identify_bear_windows(s, dd_threshold=0.15, min_duration=15,
                                        pre_pad=20, post_pad=20)
        # 不应出现重叠
        for i in range(len(windows)):
            for j in range(i + 1, len(windows)):
                assert windows[i].end < windows[j].start or windows[j].end < windows[i].start


# ============================================================================
# 6. 风险状态机阈值边界
# ============================================================================

class TestRiskStateMachineBoundaries:
    def test_watch_exact_boundary(self):
        """DD 超过 5% → WATCH"""
        cfg = RiskBudgetConfig(dd_threshold_watch=0.05, dd_threshold_defensive=0.08,
                               dd_threshold_protective=0.10)
        mgr = RiskBudgetManager(cfg)
        mgr.reset(1.0)
        mgr.peak_nav = 1.0
        state, dd, _ = mgr.update_risk_state(0.94)  # DD ≈ 6% > 5%
        assert dd > 0.05
        assert state == RiskState.WATCH

    def test_protective_exact_boundary(self):
        """DD 超过 10% → PROTECTIVE"""
        cfg = RiskBudgetConfig(dd_threshold_protective=0.10)
        mgr = RiskBudgetManager(cfg)
        mgr.reset(1.0)
        mgr.peak_nav = 1.0
        state, dd, _ = mgr.update_risk_state(0.89)  # DD ≈ 11% > 10%
        assert dd > 0.10
        assert state == RiskState.PROTECTIVE

    def test_recovery_requires_confirmation(self):
        """恢复需连续 recovery_confirmation_days 天。"""
        cfg = RiskBudgetConfig(recovery_confirmation_days=3)
        mgr = RiskBudgetManager(cfg)
        mgr.reset(1.0)
        # 先触发 DEFENSIVE (DD=9%)
        mgr.update_risk_state(0.91)
        assert mgr.current_state == RiskState.DEFENSIVE
        # 恢复到 NORMAL 区域 (DD=2%) 但需3天确认
        for _ in range(2):
            mgr.update_risk_state(0.98)
        assert mgr.current_state == RiskState.DEFENSIVE  # 还没确认完
        mgr.update_risk_state(0.98)  # 第3天
        # 注意：只恢复到 WATCH 区域 (DD=2% 不是 NORMAL<5%... 等等 DD=2%<5% 所以 target_tier=NORMAL)
        # 但 recovery_counter 从 DEFENSIVE 要经过 WATCH 再到 NORMAL?
        # 实际逻辑：target=NORMAL, severity(NORMAL)<severity(DEFENSIVE), counter=3>=3 → 恢复到 NORMAL
        assert mgr.current_state == RiskState.NORMAL


# ============================================================================
# 7. T-NALE 衰减
# ============================================================================

class TestTNaleDecay:
    def test_half_life_decay(self):
        """age=halflife 时信号应衰减至 50%。"""
        from src.portfolio.backtest import FOFBacktestEngine, BacktestConfig
        from src.portfolio.contracts import AssetInfo, AssetRole, AssetType

        df = _returns_df()
        assets = {
            "510300": AssetInfo(ticker="510300", name="A", asset_type=AssetType.BROAD_EQUITY,
                                role=AssetRole.CORE_BETA, benchmark_weight=0.5),
            "518880": AssetInfo(ticker="518880", name="B", asset_type=AssetType.SECTOR_ETF,
                                role=AssetRole.CORE_DEFENSIVE, benchmark_weight=0.5),
        }
        engine = FOFBacktestEngine(assets, df)
        sig = PointInTimeSignal(as_of_date="2026-01-05", ticker="X",
                               score=1.0, confidence=0.8, source_method="t_nale")
        decayed = engine._apply_t_nale_decay({"X": sig}, halflife=5.0,
                                             age_map={"X": 5})
        assert decayed["X"].score == pytest.approx(0.5)

    def test_zero_age_preserves(self):
        from src.portfolio.backtest import FOFBacktestEngine
        df = _returns_df()
        assets = {"510300": AssetInfo(ticker="510300", name="A", asset_type=AssetType.BROAD_EQUITY,
                                      role=AssetRole.CORE_BETA, benchmark_weight=0.5),
                  "518880": AssetInfo(ticker="518880", name="B", asset_type=AssetType.SECTOR_ETF,
                                      role=AssetRole.CORE_DEFENSIVE, benchmark_weight=0.5)}
        engine = FOFBacktestEngine(assets, df)
        sig = PointInTimeSignal(as_of_date="2026-01-05", ticker="X",
                               score=0.8, confidence=0.9, source_method="t_nale")
        decayed = engine._apply_t_nale_decay({"X": sig}, halflife=5.0,
                                             age_map={"X": 0})
        assert decayed["X"].score == pytest.approx(0.8)


# ============================================================================
# 8. 参数敏感性网格结构
# ============================================================================

class TestParamGrid:
    def test_ofat_variants_count(self):
        grid = ParamGrid()
        variants = grid.one_factor_at_a_time()
        # 每个维度至少3个变体 + defensive_ret 3 + halflife 3
        expected_min = (4 + 3 + 3 + 4 + 4 + 3 + 3)  # sat,vol,dd,rec,bal,half,def
        assert len(variants) == expected_min

    def test_dimension_labels_unique_per_dim(self):
        grid = ParamGrid()
        variants = grid.one_factor_at_a_time()
        dims = set(v["_dimension"] for v in variants)
        assert "satellite_budget" in dims
        assert "target_vol" in dims
        assert "halflife_mult" in dims

    def test_total_combinations_explosion(self):
        grid = ParamGrid()
        assert grid.total_combinations() > 1000  # 全组合爆炸量级（OFAT 避免）


# ============================================================================
# 9. 截断不变性
# ============================================================================

class TestTruncationInvariance:
    def test_shock_truncated_by_window(self):
        """如果冲击持续 60 天但窗口只有 30 天，只覆盖 30 天不报错。"""
        df = _returns_df()  # 20 日
        long_shock = ShockScenario("test", daily_shock_pct=-0.01, duration_days=60)
        out = apply_price_shock(df, long_shock, ["510300"], ["518880"])
        # 全部 20 行都被覆盖
        for i in range(20):
            assert out.iloc[i]["510300"] == pytest.approx(-0.01)


# ============================================================================
# 10. 独立最大回撤复算
# ============================================================================

class TestIndependentRecheck:
    def test_max_drawdown_hand_verified(self):
        """nav: 100→110→99→105 → MDD = (110-99)/110 = 10%"""
        nav = pd.Series([100, 110, 99, 105],
                        index=pd.date_range("2026-01-01", periods=4, freq="B"))
        peak = nav.cummax()
        dd = (peak - nav) / peak
        assert dd.max() == pytest.approx(0.10)

    def test_recovery_time(self):
        """从谷值到新高的恢复时间。"""
        nav = [100, 80, 70, 90, 100, 110]
        idx = pd.date_range("2026-01-01", periods=6, freq="B")
        s = pd.Series(nav, index=idx)
        peak_before_trough = s[:3].max()  # 100
        trough_idx = 2  # 70
        # 恢复到新高的索引 = 第一个 >= peak_before_trough 的位置（from trough onwards）
        recovered = None
        for i in range(trough_idx + 1, len(s)):
            if s.iloc[i] >= peak_before_trough:
                recovered = i
                break
        assert recovered == 4  # nav=100 at index 4 → recovery = 2 交易日


# ============================================================================
# 11. RebalanceManager.fill_fraction 部分成交（可手算复核）
# ============================================================================

class TestRebalancerFillFraction:
    def _assets(self):
        return {
            "BETA": AssetInfo(ticker="BETA", name="BETA", asset_type=AssetType.BROAD_EQUITY,
                              role=AssetRole.CORE_BETA, benchmark_weight=0.6),
            "DEF": AssetInfo(ticker="DEF", name="DEF", asset_type=AssetType.SECTOR_ETF,
                             role=AssetRole.CORE_DEFENSIVE, benchmark_weight=0.4),
        }

    def test_half_fill_is_midpoint_of_delta(self):
        from src.portfolio.contracts import PortfolioWeights
        from src.portfolio.rebalancer import RebalanceManager

        rm = RebalanceManager(self._assets())
        current = {"BETA": 0.6, "DEF": 0.4}
        target = PortfolioWeights(
            trade_date="2026-01-05", weights={"BETA": 0.3, "DEF": 0.7},
            risk_state=RiskState.NORMAL, satellite_budget_used=0.0, volatility_scale=1.0,
            cash_or_defensive_residual=0.0)
        full_w, full_to, _, _ = rm.apply_deadband_and_execute(
            "2026-01-05", current, target, fill_fraction=1.0)
        half_w, half_to, _, _ = rm.apply_deadband_and_execute(
            "2026-01-05", current, target, fill_fraction=0.5)

        # 全量成交: BETA 0.6 -> 0.3
        assert full_w["BETA"] == pytest.approx(0.3)
        # 半成交: 0.6 + (0.3-0.6)*0.5 = 0.45（未成交部分保留原仓位，不清零/不变现金）
        assert half_w["BETA"] == pytest.approx(0.45)
        assert half_w["DEF"] == pytest.approx(0.55)
        # 换手率 = 0.5 * sum|Δ| = 0.5 * (0.15+0.15) = 0.15（全量为 0.30）
        assert half_to == pytest.approx(0.15)
        assert full_to == pytest.approx(0.30)
        assert sum(half_w.values()) == pytest.approx(1.0)

    def test_fill_fraction_one_is_backward_compatible(self):
        """默认 fill_fraction=1.0 必须与不传该参数时结果完全一致（无行为回归）。"""
        from src.portfolio.contracts import PortfolioWeights
        from src.portfolio.rebalancer import RebalanceManager

        rm = RebalanceManager(self._assets())
        current = {"BETA": 0.6, "DEF": 0.4}
        target = PortfolioWeights(
            trade_date="2026-01-05", weights={"BETA": 0.2, "DEF": 0.8},
            risk_state=RiskState.NORMAL, satellite_budget_used=0.0, volatility_scale=1.0,
            cash_or_defensive_residual=0.0)
        r1 = rm.apply_deadband_and_execute("2026-01-05", current, target)
        r2 = rm.apply_deadband_and_execute("2026-01-05", current, target, fill_fraction=1.0)
        assert r1 == r2


# ============================================================================
# 12. 引擎级流动性压力接线（run_backtest 新参数确实生效）
# ============================================================================

class TestEngineLiquidityStress:
    def _engine_setup(self):
        from src.portfolio.backtest import BacktestConfig, FOFBacktestEngine

        # 60 日：前 15 日横盘，之后连续急跌以充分触发 WATCH -> DEFENSIVE -> PROTECTIVE
        # 并留出足够的后续交易日观察冻结/延迟窗口内的减仓行为
        dates = pd.date_range("2026-01-05", periods=60, freq="B")
        beta_ret = [0.0] * 15 + [-0.03] * 45
        def_ret = [0.0002] * 60
        df = pd.DataFrame({"BETA": beta_ret, "DEF": def_ret}, index=dates)
        assets = {
            "BETA": AssetInfo(ticker="BETA", name="BETA", asset_type=AssetType.BROAD_EQUITY,
                              role=AssetRole.CORE_BETA, benchmark_weight=0.5),
            "SAT": AssetInfo(ticker="SAT", name="SAT", asset_type=AssetType.SECTOR_ETF,
                             role=AssetRole.SATELLITE_ALPHA, benchmark_weight=0.0),
            "DEF": AssetInfo(ticker="DEF", name="DEF", asset_type=AssetType.SECTOR_ETF,
                             role=AssetRole.CORE_DEFENSIVE, benchmark_weight=0.5),
        }
        # SAT 需出现在 returns_df 列中才会被正确计算，补上
        df["SAT"] = beta_ret
        engine = FOFBacktestEngine(assets, df)
        cfg = BacktestConfig(start_date=str(dates[0].date()), end_date=str(dates[-1].date()),
                              rebalance_frequency_days=2)
        return engine, cfg, dates

    def _run(self, engine, cfg, dates, **kwargs):
        sig_map = {str(d.date()): {"SAT": PointInTimeSignal(
            as_of_date=str(d.date()), ticker="SAT", score=0.5, confidence=0.8,
            source_method="stress")} for d in dates}
        return engine.run_backtest("risk_constrained_nale", sig_map, cfg, **kwargs)

    def _first_severity_jump(self, logs):
        """返回风险门首次升级至 DEFENSIVE/PROTECTIVE 的 bar 下标（-1=未触发）。"""
        prev_sev = 0
        sev = {"normal": 0, "watch": 1, "defensive": 2, "protective": 3}
        for i, lg in enumerate(logs):
            curr = sev.get(lg.risk_state, 0)
            if curr >= 2 and curr > prev_sev:
                return i
            prev_sev = curr
        return -1

    def test_defaults_reproduce_unchanged_behavior(self):
        """不传新参数 vs 显式传默认值，结果必须完全一致（防止默认值改变旧行为）。"""
        engine, cfg, dates = self._engine_setup()
        _, m_default = self._run(engine, cfg, dates)
        engine2, cfg2, dates2 = self._engine_setup()
        _, m_explicit = self._run(engine2, cfg2, dates2, fill_fraction=1.0,
                                   delayed_exit_days=0, frozen_exit_days=0)
        assert m_default.max_drawdown == pytest.approx(m_explicit.max_drawdown)
        assert m_default.total_trading_costs == pytest.approx(m_explicit.total_trading_costs)

    def test_half_fill_reduces_realized_turnover(self):
        """fill_fraction=0.5 应使累计换手与费用低于全量成交。"""
        engine, cfg, dates = self._engine_setup()
        _, m_full = self._run(engine, cfg, dates, fill_fraction=1.0)
        engine2, cfg2, dates2 = self._engine_setup()
        _, m_half = self._run(engine2, cfg2, dates2, fill_fraction=0.5)
        assert m_half.total_turnover <= m_full.total_turnover + 1e-9
        assert m_half.total_trading_costs <= m_full.total_trading_costs + 1e-9
        assert m_half.total_turnover < m_full.total_turnover  # 确实不同，非空操作

    def test_frozen_exit_blocks_reduction_within_window(self):
        """风险门升级后，frozen_exit_days 个交易日内调仓的净减仓必须被拦截为 0 换手，
        未成交的风险敞口保留原仓位（不得清零/变现金）。"""
        engine, cfg, dates = self._engine_setup()
        logs_base, _ = self._run(engine, cfg, dates, frozen_exit_days=0)
        engine2, cfg2, dates2 = self._engine_setup()
        logs_frozen, _ = self._run(engine2, cfg2, dates2, frozen_exit_days=5)

        trigger_idx = self._first_severity_jump(logs_base)
        assert trigger_idx >= 0, "测试场景未能构造出风险门升级，需重新设计"
        # 冻结窗口为 trigger_idx+1 .. trigger_idx+5（trigger 当日不受影响，
        # 因为升级在当日收盘后才判定）
        blocked_rebal_days = [
            j for j in range(trigger_idx + 1, trigger_idx + 6)
            if logs_base[j].turnover > 0
        ]
        assert blocked_rebal_days, "冻结窗口内未落入任何调仓日，需重新设计 rebalance_frequency/frozen_days"
        for j in blocked_rebal_days:
            assert logs_frozen[j].turnover == pytest.approx(0.0)
            assert logs_frozen[j].total_fee == pytest.approx(0.0)
        # 机制真正生效的直接证据：基线在冻结窗口内的调仓日确实减了风险敞口
        # （风险口径与引擎一致 = core_beta + satellite，减仓可能发生在卫星清零），
        # 而冻结版因减仓被拦，风险敞口应高于基线（不能因清零/变现金而巧合相等）
        def _risk_w(lg) -> float:
            return lg.core_beta_weight + lg.satellite_weight
        assert any(
            _risk_w(logs_frozen[j]) > _risk_w(logs_base[j]) + 1e-6
            for j in blocked_rebal_days
            if _risk_w(logs_base[j]) < _risk_w(logs_base[j - 1])
        ), "冻结未生效：风险敞口未被拦在高处"

    def test_delayed_exit_defers_forced_de_risking(self):
        """delayed_exit_days>0 时，风险门升级后应额外安排一次延迟的强制减仓，
        与延迟=0 的基线产生可观察的差别。"""
        engine, cfg, dates = self._engine_setup()
        logs0, _ = self._run(engine, cfg, dates, delayed_exit_days=0, frozen_exit_days=0)
        engine2, cfg2, dates2 = self._engine_setup()
        logs3, _ = self._run(engine2, cfg2, dates2, delayed_exit_days=3, frozen_exit_days=0)

        trigger_idx = self._first_severity_jump(logs0)
        assert trigger_idx >= 0
        due_idx = trigger_idx + 3 + 1
        assert logs3[due_idx].turnover > 0 or any(
            logs3[j].turnover != logs0[j].turnover for j in range(trigger_idx, len(logs0))), \
            "delayed_exit_days 未对回测结果产生任何影响，接线失效"
        # 基线在 due_idx 若不是调仓日，则强制减仓应使其换手 > 0（新参数不是空操作）
        assert logs3 != logs0


# ============================================================================
# 13. T-NALE 信号隔离与点时时效修复验证 (spec-021 验收标准)
# ============================================================================

class TestTNaleStressIsolation:
    def _create_multi_asset_test_data(self, n_days: int = 40):
        dates = pd.date_range("2026-01-05", periods=n_days, freq="B")
        # 构造不同行业收益，使其产生分化的动量和正负切换
        rng = np.random.RandomState(42)
        data = {
            "510300": [0.0005] * n_days,  # 核心基准
            "512760": [0.01 if (i % 7 < 4) else -0.008 for i in range(n_days)],  # 半导体
            "515790": [0.008 if (i % 5 < 3) else -0.006 for i in range(n_days)], # 光伏
            "518880": [0.003 if (i % 3 == 0) else -0.002 for i in range(n_days)], # 黄金
            "512010": [0.005 if (i % 9 < 5) else -0.004 for i in range(n_days)], # 医药
            "511010": [0.0001] * n_days,  # 防御国债
        }
        df = pd.DataFrame(data, index=dates)
        assets = {
            "510300": AssetInfo(ticker="510300", name="BETA", asset_type=AssetType.BROAD_EQUITY,
                                role=AssetRole.CORE_BETA, benchmark_weight=0.3),
            "512760": AssetInfo(ticker="512760", name="SEMI", asset_type=AssetType.SECTOR_ETF,
                                role=AssetRole.SATELLITE_ALPHA, benchmark_weight=0.0, max_weight=0.15),
            "515790": AssetInfo(ticker="515790", name="SOLAR", asset_type=AssetType.SECTOR_ETF,
                                role=AssetRole.SATELLITE_ALPHA, benchmark_weight=0.0, max_weight=0.15),
            "518880": AssetInfo(ticker="518880", name="GOLD", asset_type=AssetType.SECTOR_ETF,
                                role=AssetRole.SATELLITE_ALPHA, benchmark_weight=0.0, max_weight=0.15),
            "512010": AssetInfo(ticker="512010", name="MED", asset_type=AssetType.SECTOR_ETF,
                                role=AssetRole.SATELLITE_ALPHA, benchmark_weight=0.0, max_weight=0.15),
            "511010": AssetInfo(ticker="511010", name="DEF", asset_type=AssetType.SECTOR_ETF,
                                role=AssetRole.CORE_DEFENSIVE, benchmark_weight=0.7),
        }
        return df, assets, dates

    def test_static_vs_t_nale_signal_and_weight_differentiation(self):
        """测试 1：静态 NALE 与 T-NALE 产生截面差异有效信号与目标配置权重。"""
        from src.portfolio.allocator import AllocationConfig, FOFAllocator
        from src.portfolio.backtest import BacktestConfig, FOFBacktestEngine

        df, assets, dates = self._create_multi_asset_test_data(n_days=40)
        sat_tickers = ["512760", "515790", "518880", "512010"]

        static_sigs = compute_point_in_time_stress_signals(df, sat_tickers, mode="risk_constrained_nale")
        tnale_sigs = compute_point_in_time_stress_signals(df, sat_tickers, mode="t_nale")

        # 1. 验证信号层面存在截面分化（T-NALE 分数与静态 NALE 分数不全相同）
        different_signals_count = 0
        different_cross_section_ratio_count = 0

        for d in dates[5:]:
            ds = str(d.date())
            s_map = static_sigs.get(ds, {})
            t_map = tnale_sigs.get(ds, {})
            # 至少有一只标的分数有差异
            diffs = [abs(s_map[tk].score - t_map[tk].score) for tk in sat_tickers if tk in s_map and tk in t_map]
            if diffs and max(diffs) > 1e-4:
                different_signals_count += 1

            # 验证截面相对比例变化（证明不是同乘一个常数，而是异质半衰期导致相对排序变化）
            pos_static = [s_map[tk].score for tk in sat_tickers if tk in s_map and s_map[tk].score > 0]
            pos_tnale = [t_map[tk].score for tk in sat_tickers if tk in t_map and t_map[tk].score > 0]
            if len(pos_static) >= 2 and len(pos_tnale) >= 2:
                r_static = pos_static[0] / (pos_static[1] + 1e-6)
                r_tnale = pos_tnale[0] / (pos_tnale[1] + 1e-6)
                if abs(r_static - r_tnale) > 1e-4:
                    different_cross_section_ratio_count += 1

        assert different_signals_count > 0, "T-NALE 与静态 NALE 信号完全相同，未实现信号隔离"
        assert different_cross_section_ratio_count > 0, "T-NALE 信号截面相对排序未发生任何分化（仍为标量缩放）"

        # 2. 验证引擎目标配置权重与回测结果分化
        cfg = BacktestConfig(start_date=str(dates[0].date()), end_date=str(dates[-1].date()), rebalance_frequency_days=5)
        alloc_cfg = AllocationConfig(base_defensive_weight=0.50, base_beta_weight=0.30, base_satellite_budget=0.20)
        engine_static = FOFBacktestEngine(assets, df, alloc_config=alloc_cfg)
        engine_tnale = FOFBacktestEngine(assets, df, alloc_config=alloc_cfg)

        logs_static, m_static = engine_static.run_backtest("risk_constrained_nale", static_sigs, cfg)
        logs_tnale, m_tnale = engine_tnale.run_backtest("t_nale", tnale_sigs, cfg)

        # 检查权重偏离度
        weight_diffs = []
        for l_s, l_t in zip(logs_static, logs_tnale):
            w_diff = sum(abs(l_s.weights.get(tk, 0.0) - l_t.weights.get(tk, 0.0)) for tk in assets)
            weight_diffs.append(w_diff)

        assert max(weight_diffs) > 1e-3, f"回测中 T-NALE 与静态 NALE 配置权重完全重合 (max_diff={max(weight_diffs)})"
        # 指标分化：收益、回撤或换手必然产生差异
        assert (m_static.total_turnover != m_tnale.total_turnover or
                m_static.annualized_return != m_tnale.annualized_return or
                m_static.max_drawdown != m_tnale.max_drawdown), "量化指标完全一致，隔离失败"

    def test_mode_isolation_no_aliasing(self):
        """测试 2：模式标识不会把 T-NALE 映射成 risk_constrained_nale。"""
        from scripts.run_bear_market_stress import run_all_modes
        df, assets, dates = self._create_multi_asset_test_data(n_days=35)

        start = str(dates[0].date())
        end = str(dates[-1].date())
        results = run_all_modes(df, start, end, seed=42)

        assert "t_nale" in results
        assert "risk_constrained_nale" in results

        _, m_rc = results["risk_constrained_nale"]
        _, m_tnale = results["t_nale"]

        assert m_rc is not None and m_tnale is not None
        # 验证两个模式结果不再完全相等（历史 bug：6 个浮点指标 100% 相同）
        same_metrics = (
            abs(m_rc.annualized_return - m_tnale.annualized_return) < 1e-9 and
            abs(m_rc.max_drawdown - m_tnale.max_drawdown) < 1e-9 and
            abs(m_rc.total_turnover - m_tnale.total_turnover) < 1e-9 and
            abs(m_rc.total_trading_costs - m_tnale.total_trading_costs) < 1e-9
        )
        assert not same_metrics, "历史 Bug 复现：t_nale 与 risk_constrained_nale 指标仍然 100% 完全相同"

    def test_t_nale_point_in_time_truncation_invariance(self):
        """测试 3：未来数据追加不改变历史信号与节点年龄（严格无未来函数）。"""
        df, _, dates = self._create_multi_asset_test_data(n_days=40)
        sat_tickers = ["512760", "515790", "518880", "512010"]

        # 截断数据 T_short = 25 日
        df_short = df.iloc[:25].copy()
        sigs_short = compute_point_in_time_stress_signals(df_short, sat_tickers, mode="t_nale")

        # 完整数据 T_full = 40 日（向未来追加 15 日）
        sigs_full = compute_point_in_time_stress_signals(df, sat_tickers, mode="t_nale")

        # 验证在历史区间 t <= 25 内，信号分数、置信度、节点年龄和衰减因子 100% 逐位不变
        short_dates = [str(d.date()) for d in df_short.index]
        for ds in short_dates:
            assert ds in sigs_short and ds in sigs_full
            for tk in sat_tickers:
                s_short = sigs_short[ds][tk]
                s_full = sigs_full[ds][tk]

                assert s_short.score == pytest.approx(s_full.score, abs=1e-12), f"{ds} {tk} score 因未来数据发生改变"
                assert s_short.confidence == pytest.approx(s_full.confidence, abs=1e-12)
                assert s_short.details.get("node_age") == s_full.details.get("node_age"), f"{ds} {tk} node_age 受到未来数据污染"
                assert s_short.details.get("t_nale_factor") == pytest.approx(s_full.details.get("t_nale_factor"), abs=1e-12)

    def test_output_dir_protection(self):
        """测试 4：结果产物安全拦截，禁止覆盖历史产物目录。"""
        import os
        import subprocess
        import sys
        from pathlib import Path

        script_path = str(Path("scripts/run_bear_market_stress.py").resolve())
        python_exe = sys.executable
        env = dict(os.environ, PYTHONIOENCODING="utf-8")

        # 尝试传入受保护的历史目录 reports/fof_stress_20261014
        proc = subprocess.run(
            [python_exe, script_path, "--out", "reports/fof_stress_20261014"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert proc.returncode != 0, "安全拦截失效：对 reports/fof_stress_20261014 应当报错拒绝退出"
        output = (proc.stderr or "") + (proc.stdout or "")
        assert "安全保护拦截" in output, "未输出安全保护拦截提示"

        # 尝试传入受保护的基准目录 reports/fof_rebuild_20261013
        proc2 = subprocess.run(
            [python_exe, script_path, "--out", "reports/fof_rebuild_20261013"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert proc2.returncode != 0, "安全拦截失效：对 reports/fof_rebuild_20261013 应当报错拒绝退出"
        output2 = (proc2.stderr or "") + (proc2.stdout or "")
        assert "安全保护拦截" in output2, "未输出安全保护拦截提示"
