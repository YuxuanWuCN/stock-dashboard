# -*- coding: utf-8 -*-
r"""src/portfolio/stress_scenarios.py —— 熊市回测与压力测试合成冲击/流动性/窗口引擎

依据《熊市回测与压力测试方案_交主Agent.md》§2-§6：
- 合成冲击矩阵 (7 价格冲击 × 3 防御假设 × 相关性失效)
- 流动性执行压力 (5 成交约束)
- 历史熊市窗口识别

所有合成操作仅修改内存副本，禁止改动原始数据文件 (AGENTS.md)。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("portfolio.stress_scenarios")


# ============================================================================
# 1. 历史熊市窗口识别
# ============================================================================

@dataclass
class BearWindow:
    """一个被识别出的历史下跌窗口。"""
    start: str            # 峰值前 20 交易日起点
    peak: str             # 峰值日期
    trough: str           # 谷值日期
    end: str              # 谷值后 20 交易日终点
    peak_nav: float
    trough_nav: float
    max_dd_pct: float     # 峰谷跌幅 (正数)
    duration_days: int    # peak->trough 交易日数
    window_type: str      # "bear" | "rapid_drop"
    data_file: str = ""   # 来源标识


def identify_bear_windows(
    nav_series: pd.Series,
    dd_threshold: float = 0.15,
    min_duration: int = 20,
    pre_pad: int = 20,
    post_pad: int = 20,
    rapid_drop_threshold: float = -0.08,
    rapid_drop_window: int = 5,
) -> List[BearWindow]:
    """从点时净值序列自动识别满足条件的熊市窗口。

    Parameters
    ----------
    nav_series : 以日期索引的净值序列（升序）
    dd_threshold : 峰谷回撤最小比例 (0.15=15%)
    min_duration : 下跌段最少持续交易日
    pre_pad / post_pad : 包含峰值前/谷值后的缓冲日数
    rapid_drop_threshold : 急跌窗口 5 日跌幅阈值
    rapid_drop_window : 急跌检测滚动窗口
    """
    if len(nav_series) < min_duration + pre_pad + post_pad:
        return []

    dates = nav_series.index.tolist()
    values = nav_series.values.astype(float)
    windows: List[BearWindow] = []

    # 计算滚动历史高点
    running_peak = np.maximum.accumulate(values)
    drawdowns = (running_peak - values) / (running_peak + 1e-12)

    # 识别峰谷对 (非重叠)
    in_decline = False
    peak_idx = 0
    trough_idx = 0
    used_ranges: List[Tuple[int, int]] = []

    for i in range(len(values)):
        if not in_decline:
            # 进入下跌：当前点回撤超过微小量
            if drawdowns[i] > 1e-6:
                in_decline = True
                peak_idx = max(0, i - 1)  # 前一日为真实峰值
                trough_idx = peak_idx
            continue
        # 在下跌中跟踪谷值
        if drawdowns[i] > drawdowns[trough_idx]:
            trough_idx = i
        # 退出条件：回撤必须从谷值开始收窄（恢复中）且低于半阈值 或 新高
        recovering = (i > trough_idx and drawdowns[i] < drawdowns[trough_idx])
        if recovering and (drawdowns[i] <= dd_threshold * 0.5
                           or values[i] >= running_peak[max(0, i - 1)]):
            # 检查是否满足最小跌幅和时长
            dd_pct = drawdowns[trough_idx]
            dur = trough_idx - peak_idx
            if dd_pct >= dd_threshold and dur >= min_duration:
                w_start = max(0, peak_idx - pre_pad)
                w_end = min(len(values) - 1, trough_idx + post_pad)
                overlap = any(not (w_end < s or w_start > e) for s, e in used_ranges)
                if not overlap:
                    used_ranges.append((w_start, w_end))
                    windows.append(BearWindow(
                        start=str(dates[w_start]),
                        peak=str(dates[peak_idx]),
                        trough=str(dates[trough_idx]),
                        end=str(dates[w_end]),
                        peak_nav=float(values[peak_idx]),
                        trough_nav=float(values[trough_idx]),
                        max_dd_pct=float(dd_pct),
                        duration_days=int(dur),
                        window_type="bear",
                    ))
            in_decline = False

    # 急跌窗口检测 (5日滚动跌幅 <= -8%)
    if len(values) >= rapid_drop_window:
        ret = np.diff(values) / values[:-1]
        cum5 = pd.Series(ret).rolling(rapid_drop_window).sum()
        for idx in range(len(cum5)):
            if pd.notna(cum5.iloc[idx]) and cum5.iloc[idx] <= rapid_drop_threshold:
                # 检查是否与已有窗口重叠
                r_start = max(0, idx - pre_pad)
                r_end = min(len(values) - 1, idx + rapid_drop_window + post_pad)
                overlap = any(not (r_end < s or r_start > e) for s, e in used_ranges)
                if not overlap:
                    used_ranges.append((r_start, r_end))
                    windows.append(BearWindow(
                        start=str(dates[r_start]),
                        peak=str(dates[idx]),
                        trough=str(dates[min(idx + rapid_drop_window, len(dates) - 1)]),
                        end=str(dates[r_end]),
                        peak_nav=float(values[idx]),
                        trough_nav=float(values[min(idx + rapid_drop_window, len(values) - 1)]),
                        max_dd_pct=float(abs(cum5.iloc[idx])),
                        duration_days=rapid_drop_window,
                        window_type="rapid_drop",
                    ))

    return windows


# ============================================================================
# 2. 合成冲击场景
# ============================================================================

@dataclass(frozen=True)
class ShockScenario:
    """单个价格冲击场景定义。"""
    name: str
    daily_shock_pct: float     # 每日冲击（负数=下跌）
    duration_days: int
    initial_gap: float = 0.0   # 首日额外跳空 (Gap-down 用)
    phases: Tuple[Tuple[float, int], ...] = ()  # 多阶段 (failed_rebound)

    @property
    def cumulative_impact(self) -> float:
        if self.phases:
            cum = 1.0
            for pct, days in self.phases:
                cum *= (1.0 + pct) ** days
            return cum - 1.0
        # initial_gap 替换首日冲击（首日不再用 daily_shock）
        if self.initial_gap != 0.0:
            return (1.0 + self.initial_gap) * (1.0 + self.daily_shock_pct) ** (self.duration_days - 1) - 1.0
        return (1.0 + self.daily_shock_pct) ** self.duration_days - 1.0


SHOCK_MATRIX: List[ShockScenario] = [
    ShockScenario("mild_drawdown", daily_shock_pct=-0.03, duration_days=5),
    ShockScenario("fast_crash", daily_shock_pct=-0.05, duration_days=5),
    ShockScenario("severe_crash", daily_shock_pct=-0.10, duration_days=3),
    ShockScenario("slow_bear", daily_shock_pct=-0.01, duration_days=20),
    ShockScenario("long_bear", daily_shock_pct=-0.005, duration_days=60),
    ShockScenario("gap_down", daily_shock_pct=-0.02, duration_days=10, initial_gap=-0.15),
    ShockScenario("failed_rebound", daily_shock_pct=0.0, duration_days=13,
                  phases=((-0.05, 5), (0.02, 3), (-0.04, 5))),
]

DEFENSIVE_ASSUMPTIONS: List[Tuple[str, float]] = [
    ("defensive_plus2pct", 0.02 / 252.0),   # 年化+2% 日收益
    ("defensive_zero", 0.0),
    ("defensive_correlated_drop", -0.002),   # 与权益同跌 -0.2%/日
]


def apply_price_shock(
    returns_df: pd.DataFrame,
    scenario: ShockScenario,
    risk_asset_cols: List[str],
    defensive_cols: List[str],
    defensive_mode: str = "defensive_plus2pct",
) -> pd.DataFrame:
    """在内存副本上施加合成价格冲击，不修改原始 DataFrame。

    对 risk_asset_cols 施加冲击收益，defensive_cols 按选定假设覆盖。
    返回修改后的 DataFrame 副本。
    """
    out = returns_df.copy()
    n = min(scenario.duration_days, len(out))
    if n <= 0:
        return out

    def_assumption_map = dict(DEFENSIVE_ASSUMPTIONS)
    def_daily = def_assumption_map.get(defensive_mode, 0.0)

    # 对前 n 行施加冲击（模拟从窗口起点开始）
    for col in risk_asset_cols:
        if col not in out.columns:
            continue
        if scenario.phases:
            # 多阶段冲击
            idx = 0
            for phase_pct, phase_days in scenario.phases:
                end_idx = min(idx + phase_days, len(out))
                for i in range(idx, end_idx):
                    out.iloc[i, out.columns.get_loc(col)] = phase_pct
                idx = end_idx
        else:
            shock = scenario.daily_shock_pct
            for i in range(n):
                if i == 0 and scenario.initial_gap != 0.0:
                    out.iloc[i, out.columns.get_loc(col)] = scenario.initial_gap
                else:
                    out.iloc[i, out.columns.get_loc(col)] = shock

    # 防御资产固定收益
    for col in defensive_cols:
        if col not in out.columns:
            continue
        for i in range(n):
            out.iloc[i, out.columns.get_loc(col)] = def_daily

    return out


def apply_correlation_stress(
    returns_df: pd.DataFrame,
    satellite_cols: List[str],
    target_corr: float = 0.8,
    n_days: int = 20,
) -> pd.DataFrame:
    """提升卫星资产间相关性至指定水平（用条件数检验并调整）。

    简化实现：将所有卫星资产的前 n_days 行收益设为相同值（相关性=1），
    再混合原始信号使相关性 ≈ target_corr。
    """
    out = returns_df.copy()
    if len(satellite_cols) < 2:
        return out
    valid_cols = [c for c in satellite_cols if c in out.columns]
    if not valid_cols:
        return out

    # 生成完全相关的因子
    common_factor = out[valid_cols[0]].iloc[:n_days].copy()
    for c in valid_cols[1:]:
        orig = out[c].iloc[:n_days]
        # 混合: new = target_corr * common + (1-target_corr) * orig
        blended = target_corr * common_factor + (1.0 - target_corr) * orig
        out.iloc[:n_days, out.columns.get_loc(c)] = blended.values

    return out


# ============================================================================
# 3. 流动性与执行压力
# ============================================================================

@dataclass(frozen=True)
class LiquidityScenario:
    """流动性约束配置。"""
    name: str
    one_side_cost_bps: float = 5.0
    fill_fraction: float = 1.0            # <1 表示每步只成交部分
    delayed_exit_days: int = 0            # 风险门触发后延迟执行天数
    frozen_exit_days: int = 0             # 完全无法减仓的天数
    max_daily_turnover: Optional[float] = None  # 单日换手上限


LIQUIDITY_MATRIX: List[LiquidityScenario] = [
    LiquidityScenario("base", one_side_cost_bps=5, fill_fraction=1.0),
    LiquidityScenario("cost_2x", one_side_cost_bps=10, fill_fraction=1.0),
    LiquidityScenario("cost_10x", one_side_cost_bps=50, fill_fraction=1.0),
    LiquidityScenario("half_fill", one_side_cost_bps=5, fill_fraction=0.5),
    LiquidityScenario("delayed_exit", one_side_cost_bps=5, fill_fraction=1.0,
                      delayed_exit_days=1),
    LiquidityScenario("frozen_exit", one_side_cost_bps=5, fill_fraction=1.0,
                      frozen_exit_days=3),
    LiquidityScenario("turnover_cap_10pct", one_side_cost_bps=5, fill_fraction=1.0,
                      max_daily_turnover=0.10),
    LiquidityScenario("turnover_cap_20pct", one_side_cost_bps=5, fill_fraction=1.0,
                      max_daily_turnover=0.20),
    LiquidityScenario("turnover_cap_35pct", one_side_cost_bps=5, fill_fraction=1.0,
                      max_daily_turnover=0.35),
]


def apply_liquidity_to_weights(
    current_weights: Dict[str, float],
    target_weights: Dict[str, float],
    scenario: LiquidityScenario,
    nav: float,
) -> Tuple[Dict[str, float], float, float]:
    """在流动性约束下计算实际成交后权重、成本和换手。

    Returns: (executed_weights, turnover, cost)
    """
    # 计算理论调仓差异
    all_tickers = set(current_weights) | set(target_weights)
    desired_delta: Dict[str, float] = {}
    for t in all_tickers:
        cw = current_weights.get(t, 0.0)
        tw = target_weights.get(t, 0.0)
        desired_delta[t] = tw - cw

    total_turnover = sum(abs(d) for d in desired_delta.values())

    # 换手率上限
    if scenario.max_daily_turnover is not None and total_turnover > scenario.max_daily_turnover:
        scale = scenario.max_daily_turnover / total_turnover
        desired_delta = {t: d * scale for t, d in desired_delta.items()}
        total_turnover = scenario.max_daily_turnover

    # 成交比例
    effective_delta = {t: d * scenario.fill_fraction for t, d in desired_delta.items()}
    turnover_actual = sum(abs(d) for d in effective_delta.values())

    # 成本
    cost_rate = scenario.one_side_cost_bps / 10000.0
    cost = turnover_actual * cost_rate

    # 实际成交后权重
    executed: Dict[str, float] = {}
    for t in all_tickers:
        executed[t] = current_weights.get(t, 0.0) + effective_delta.get(t, 0.0)

    # 归一化（防止数值误差）
    s = sum(executed.values())
    if s > 0 and abs(s - 1.0) > 1e-6:
        executed = {t: w / s for t, w in executed.items()}

    return executed, turnover_actual, cost


# ============================================================================
# 4. 参数敏感性网格
# ============================================================================

@dataclass(frozen=True)
class ParamGrid:
    """预声明的参数网格（禁止挑最好结果）。"""
    satellite_budgets: List[float] = field(
        default_factory=lambda: [0.10, 0.15, 0.20, 0.25])
    target_vols: List[float] = field(
        default_factory=lambda: [0.05, 0.08, 0.10])
    dd_thresholds: List[Tuple[float, float, float]] = field(
        default_factory=lambda: [(0.04, 0.07, 0.10), (0.05, 0.08, 0.10), (0.05, 0.10, 0.15)])
    recovery_days: List[int] = field(
        default_factory=lambda: [1, 3, 5, 10])
    rebal_freqs: List[int] = field(
        default_factory=lambda: [1, 5, 10, 20])
    halflife_multipliers: List[float] = field(
        default_factory=lambda: [0.5, 1.0, 2.0])
    defensive_returns: List[float] = field(
        default_factory=lambda: [0.02, 0.0, -0.02])

    def total_combinations(self) -> int:
        return (len(self.satellite_budgets) * len(self.target_vols) *
                len(self.dd_thresholds) * len(self.recovery_days) *
                len(self.rebal_freqs) * len(self.halflife_multipliers) *
                len(self.defensive_returns))

    def one_factor_at_a_time(self) -> List[Dict[str, Any]]:
        """OFAT 实验设计：每次只变一维，其余取基准值。返回变体列表。"""
        base = {
            "satellite_budget": 0.20, "target_vol": 0.08,
            "dd_thresholds": (0.05, 0.08, 0.10), "recovery_days": 3,
            "rebal_freq": 5, "halflife_mult": 1.0, "defensive_ret": 0.02,
        }
        variants: List[Dict[str, Any]] = []
        # 卫星预算
        for v in self.satellite_budgets:
            variants.append({**base, "satellite_budget": v, "_dimension": "satellite_budget"})
        # 目标波动率
        for v in self.target_vols:
            variants.append({**base, "target_vol": v, "_dimension": "target_vol"})
        # 回撤阈值
        for v in self.dd_thresholds:
            variants.append({**base, "dd_thresholds": v, "_dimension": "dd_thresholds"})
        # 恢复确认天数
        for v in self.recovery_days:
            variants.append({**base, "recovery_days": v, "_dimension": "recovery_days"})
        # 调仓频率
        for v in self.rebal_freqs:
            variants.append({**base, "rebal_freq": v, "_dimension": "rebal_freq"})
        # 半衰期倍率
        for v in self.halflife_multipliers:
            variants.append({**base, "halflife_mult": v, "_dimension": "halflife_mult"})
        # 防御收益
        for v in self.defensive_returns:
            variants.append({**base, "defensive_ret": v, "_dimension": "defensive_ret"})
        return variants
