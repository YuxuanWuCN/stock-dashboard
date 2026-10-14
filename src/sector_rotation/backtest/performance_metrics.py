# -*- coding: utf-8 -*-
"""src/sector_rotation/backtest/performance_metrics.py —— 回测绩效指标纯函数集

全部指标为无副作用纯函数（AGENTS.md 第3条：每项可独立手算复核），
输入统一为净值序列 nav (List[float]，按交易日升序) 与交易/轮动记录。

年化口径声明：
- 年化收益率与 Sharpe 均按 252 交易日年化：ann_factor = 252 / n_obs。
- Sharpe = mean(daily_returns) / std(daily_returns, ddof=1) * sqrt(252)，无风险利率默认 0。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

ANNUAL_TRADING_DAYS = 252.0


def total_return(nav: Sequence[float]) -> float:
    """总收益率 = nav[-1]/nav[0] - 1。序列不足 2 点返回 0.0。"""
    if len(nav) < 2 or nav[0] == 0.0:
        return 0.0
    return nav[-1] / nav[0] - 1.0


def daily_returns(nav: Sequence[float]) -> List[float]:
    """逐日简单收益率序列 r_t = nav[t]/nav[t-1] - 1。"""
    out: List[float] = []
    for i in range(1, len(nav)):
        prev = nav[i - 1]
        if prev == 0.0:
            out.append(0.0)
            continue
        out.append(nav[i] / prev - 1.0)
    return out


def annualized_return(nav: Sequence[float], trading_days: Optional[int] = None) -> float:
    """年化收益率（几何）：(1+total)^(252/n) - 1，n 为区间交易日数。"""
    if len(nav) < 2:
        return 0.0
    n = int(trading_days) if trading_days else len(nav) - 1
    if n <= 0:
        return 0.0
    tr = total_return(nav)
    if tr <= -1.0:
        return -1.0
    return (1.0 + tr) ** (ANNUAL_TRADING_DAYS / n) - 1.0


def sharpe_ratio(daily_ret: Sequence[float], risk_free: float = 0.0) -> Optional[float]:
    """年化 Sharpe：mean/std(ddof=1)*sqrt(252)。

    Returns:
        float 或 None（样本 < 2 或零波动时不可计算，返回 None 而非 0，
        避免把"无法评估"伪装成"表现为零"）。
    """
    rets = [r - risk_free for r in daily_ret]
    n = len(rets)
    if n < 2:
        return None
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    if var <= 0.0:
        return None
    return (mean / math.sqrt(var)) * math.sqrt(ANNUAL_TRADING_DAYS)


def max_drawdown(nav: Sequence[float]) -> float:
    """最大回撤（正数比例）：max(1 - nav[t]/peak_{<=t})。"""
    if len(nav) < 2:
        return 0.0
    peak = nav[0]
    mdd = 0.0
    for v in nav:
        if v > peak:
            peak = v
        if peak > 0:
            dd = 1.0 - v / peak
            if dd > mdd:
                mdd = dd
    return mdd


def win_rate(trade_returns: Sequence[float]) -> Optional[float]:
    """按笔胜率：收益 > 0 的笔数 / 有效笔数。无交易返回 None。"""
    valid = [r for r in trade_returns if r is not None]
    if not valid:
        return None
    return sum(1 for r in valid if r > 0.0) / len(valid)


def rotation_count(decisions: Sequence[Dict[str, Any]]) -> int:
    """轮动次数。

    若任一决策行带 rotation_accepted 标记（回测引擎在轮动被实际接受时写入），
    以被接受的轮动为准；否则降级按 should_rotate 口径（保持纯函数可独立使用）。
    """
    if any("rotation_accepted" in d for d in decisions):
        return sum(1 for d in decisions if d.get("rotation_accepted"))
    return sum(1 for d in decisions if d.get("should_rotate"))


def average_holding_days(holding_day_series: Sequence[int]) -> Optional[float]:
    """平均持仓天数（完成轮动段的持仓长度均值的便捷口径：传入各段持仓天数列表）。"""
    vals = [int(x) for x in holding_day_series if x is not None and int(x) > 0]
    if not vals:
        return None
    return sum(vals) / len(vals)


def cost_ratio(total_cost: float, initial_capital: float) -> float:
    """成本占比 = 累计交易成本 / 初始资金。"""
    if initial_capital <= 0:
        return 0.0
    return float(total_cost) / float(initial_capital)


@dataclass
class PerformanceMetrics:
    """绩效指标汇总契约（可序列化为 metrics.json）"""
    total_return: float
    annualized_return: float
    sharpe: Optional[float]
    max_drawdown: float
    win_rate: Optional[float]
    rotations: int
    avg_holding_days: Optional[float]
    cost_ratio: float
    n_observations: int
    sharpe_annualization: str = "mean/std(ddof=1)*sqrt(252), rf=0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_return": round(self.total_return, 6),
            "annualized_return": round(self.annualized_return, 6),
            "sharpe": round(self.sharpe, 4) if self.sharpe is not None else None,
            "max_drawdown": round(self.max_drawdown, 6),
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "rotations": self.rotations,
            "avg_holding_days": round(self.avg_holding_days, 2) if self.avg_holding_days is not None else None,
            "cost_ratio": round(self.cost_ratio, 6),
            "n_observations": self.n_observations,
            "sharpe_annualization": self.sharpe_annualization,
        }


def compute_metrics(
    nav: Sequence[float],
    decisions: Sequence[Dict[str, Any]],
    trade_returns: Sequence[float],
    holding_segments: Sequence[int],
    total_cost: float,
    initial_capital: float,
) -> PerformanceMetrics:
    """由原始回测序列汇聚标准绩效指标包。"""
    return PerformanceMetrics(
        total_return=total_return(nav),
        annualized_return=annualized_return(nav),
        sharpe=sharpe_ratio(daily_returns(nav)),
        max_drawdown=max_drawdown(nav),
        win_rate=win_rate(trade_returns),
        rotations=rotation_count(decisions),
        avg_holding_days=average_holding_days(holding_segments),
        cost_ratio=cost_ratio(total_cost, initial_capital),
        n_observations=len(nav),
    )
