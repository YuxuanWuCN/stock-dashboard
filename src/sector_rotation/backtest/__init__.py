# -*- coding: utf-8 -*-
"""src/sector_rotation/backtest/__init__.py —— 板块轮动回测子包

导出回测引擎、结果契约、绩效指标与可插拔情绪 provider。
数据诚实性：所有情绪输入必须来自带 sentiment_source 标注的 provider，
代理/夹具来源禁止进入报告路径（详见 DATA_FEASIBILITY.md 与 AGENTS.md）。
"""

from .backtest_engine import BacktestEngine, BacktestResult
from .performance_metrics import (
    PerformanceMetrics,
    annualized_return,
    compute_metrics,
    cost_ratio,
    daily_returns,
    max_drawdown,
    sharpe_ratio,
    total_return,
    win_rate,
)
from .sentiment_providers import (
    FrozenFixturesSentimentProvider,
    KlineStore,
    LLMReplaySentimentProvider,
    ProxyBreadthSentimentProvider,
    SentimentProvider,
    sector_daily_return,
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "PerformanceMetrics",
    "SentimentProvider",
    "ProxyBreadthSentimentProvider",
    "LLMReplaySentimentProvider",
    "FrozenFixturesSentimentProvider",
    "KlineStore",
    "sector_daily_return",
    "total_return",
    "daily_returns",
    "annualized_return",
    "sharpe_ratio",
    "max_drawdown",
    "win_rate",
    "cost_ratio",
    "compute_metrics",
]
