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

from src.portfolio.contracts import PointInTimeSignal
from src.portfolio.signal_adapter import NALESignalAdapter

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


# ============================================================================
# 5. 异质半衰期先验与点时压力信号引擎
# ============================================================================

# 行业/主题 ETF 先验信息半衰期（交易日，对齐 tools/run_fof_pipeline.py 与产业链物理流转）
SECTOR_HALF_LIVES: Dict[str, float] = {
    "512760": 12.0,  # 芯片/半导体: 产业链库存时滞长，半衰期 12 天
    "515790": 8.0,   # 光伏/新能源: 产能周期中等，半衰期 8 天
    "518880": 3.0,   # 黄金: 宏观地缘突发脉冲，时效性极强，半衰期 3 天
    "512010": 15.0,  # 医药: 政策/集采长周期慢变量，半衰期 15 天
    "512690": 10.0,  # 酒/消费: 渠道库存与动销周期，半衰期 10 天
    "588000": 4.0,   # 科创50: 高 Beta 成长情绪脉冲，半衰期 4 天
    "515030": 8.0,   # 新能车: 产能排产周期，半衰期 8 天
    "512880": 5.0,   # 证券: 市场交易量高频情绪，半衰期 5 天
    "512660": 6.0,   # 军工: 订单驱动脉冲，半衰期 6 天
    "512100": 5.0,   # 中证1000: 小盘成长情绪，半衰期 5 天
    "515050": 10.0,  # 5G通信: 算力光模块与通信设备周期，半衰期 10 天
}


def compute_point_in_time_stress_signals(
    returns_df: pd.DataFrame,
    candidate_tickers: List[str],
    mode: str,
    alpha: float = 0.4,
    halflife_mult: float = 1.0,
) -> Dict[str, Dict[str, PointInTimeSignal]]:
    """为各策略模式计算严格点时（Point-in-Time）的配置信号，无未来函数。

    依据普通 FOF 回测流水线（tools/run_fof_pipeline.py）标准复用：
    1. baseline / defensive_only: 无卫星信号（返回空字典）；
    2. sentiment_only: 仅包含截至 t-1 的滚动动量/夏普打分，无网络拓扑与时效衰减；
    3. nale / risk_constrained_nale: 静态 NALE（通过行业拓扑邻接矩阵静态传导，无时效衰减）；
    4. t_nale: 异质时效 T-NALE，各行业先验半衰期（SECTOR_HALF_LIVES）与动量极性切换
       动态信息年龄（node_ages）截面衰减，再经动态 Alpha 拓扑传导。
    """
    def _norm_date(val: Any) -> str:
        s = str(val)
        return s[:10] if " " in s else s

    dates = list(returns_df.index)
    sat_cols = [c for c in returns_df.columns if c in candidate_tickers]
    signals: Dict[str, Dict[str, PointInTimeSignal]] = {}

    if mode in ("baseline", "defensive_only") or not sat_cols:
        for d in dates:
            signals[_norm_date(d)] = {}
        return signals

    n_sat = len(sat_cols)
    adapter = NALESignalAdapter(default_alpha=alpha)

    # 构造行业拓扑邻接矩阵 W（对齐 tools/run_fof_pipeline.py 先验）
    base_adj = np.eye(n_sat)
    for i in range(n_sat):
        for j in range(n_sat):
            if i != j:
                c1, c2 = sat_cols[i], sat_cols[j]
                if c1 in ["512760", "588000"] and c2 in ["512760", "588000"]:
                    base_adj[i, j] = 0.6
                elif c1 in ["515790", "512760"] and c2 in ["515790", "512760"]:
                    base_adj[i, j] = 0.4
                elif c1 == "518880" or c2 == "518880":
                    base_adj[i, j] = 0.1
                else:
                    base_adj[i, j] = 0.2

    node_ages: Dict[str, float] = {c: 0.0 for c in sat_cols}
    prev_signs: Dict[str, float] = {c: 0.0 for c in sat_cols}

    for t_idx in range(len(dates)):
        curr_date = _norm_date(dates[t_idx])
        if t_idx == 0:
            signals[curr_date] = {
                tk: PointInTimeSignal(
                    as_of_date=curr_date,
                    ticker=tk,
                    score=0.0,
                    confidence=0.5,
                    source_method=mode,
                    is_valid=True,
                    details={"node_age": 0.0, "sector_half_life": SECTOR_HALF_LIVES.get(tk, 7.0)},
                )
                for tk in sat_cols
            }
            continue

        # 截至 t-1 的历史滚动窗口 (严格点时，长度最多 20 日)
        lookback_slice = returns_df.iloc[max(0, t_idx - 20):t_idx]

        raw_scores: Dict[str, float] = {}
        for c in sat_cols:
            m_ret = float(lookback_slice[c].mean())
            m_std = float(lookback_slice[c].std(ddof=1)) if len(lookback_slice) > 1 else 0.01
            if math.isnan(m_std) or m_std < 1e-6:
                m_std = 1e-6
            sharpe_proxy = m_ret / m_std
            score_val = float(np.tanh(sharpe_proxy * 1.5))
            raw_scores[c] = score_val

            # 动态跟踪节点信息年龄（自最近一次动量极性切换起计算）
            curr_sign = float(np.sign(score_val))
            if curr_sign != prev_signs[c] or prev_signs[c] == 0.0:
                node_ages[c] = 0.0
                prev_signs[c] = curr_sign
            else:
                node_ages[c] += 1.0

        if mode == "sentiment_only":
            signals[curr_date] = {
                tk: PointInTimeSignal(
                    as_of_date=curr_date,
                    ticker=tk,
                    score=raw_scores[tk],
                    confidence=0.8,
                    source_method="sentiment_only",
                    is_valid=True,
                    details={"node_age": node_ages[tk], "sector_half_life": SECTOR_HALF_LIVES.get(tk, 7.0)},
                )
                for tk in sat_cols
            }
        elif mode in ("nale", "risk_constrained_nale"):
            propagated_scores = adapter.compute_static_nale(
                node_scores=raw_scores,
                adjacency_matrix=base_adj,
                ticker_list=sat_cols,
                alpha=alpha,
            )
            signals[curr_date] = {
                tk: PointInTimeSignal(
                    as_of_date=curr_date,
                    ticker=tk,
                    score=propagated_scores[tk],
                    confidence=0.9,
                    source_method=mode,
                    is_valid=True,
                    details={"node_age": node_ages[tk], "sector_half_life": SECTOR_HALF_LIVES.get(tk, 7.0)},
                )
                for tk in sat_cols
            }
        elif mode == "t_nale":
            # 异质时效 T-NALE：各标的异质半衰期与动态年龄分化
            decayed_s0: Dict[str, float] = {}
            decay_factors: Dict[str, float] = {}
            for c in sat_cols:
                h_i = SECTOR_HALF_LIVES.get(c, 7.0) * max(halflife_mult, 0.1)
                age_i = node_ages[c]
                decay_i = math.exp(-math.log(2.0) / max(h_i, 0.1) * age_i)
                decayed_s0[c] = raw_scores[c] * decay_i
                decay_factors[c] = decay_i

            avg_age = sum(node_ages.values()) / max(1, len(node_ages))
            dyn_alpha = alpha * math.exp(-0.03 * avg_age)

            propagated_scores = adapter.compute_static_nale(
                node_scores=decayed_s0,
                adjacency_matrix=base_adj,
                ticker_list=sat_cols,
                alpha=dyn_alpha,
            )
            signals[curr_date] = {
                tk: PointInTimeSignal(
                    as_of_date=curr_date,
                    ticker=tk,
                    score=propagated_scores[tk],
                    confidence=0.9,
                    source_method="t_nale",
                    is_valid=True,
                    details={
                        "node_age": node_ages[tk],
                        "t_nale_age": node_ages[tk],
                        "sector_half_life": SECTOR_HALF_LIVES.get(tk, 7.0),
                        "t_nale_factor": decay_factors[tk],
                        "is_t_nale_decayed": True,
                    },
                )
                for tk in sat_cols
            }
        else:
            raise ValueError(f"未知信号模式: {mode}")

    return signals

