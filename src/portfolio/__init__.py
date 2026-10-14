# -*- coding: utf-8 -*-
"""src/portfolio/__init__.py —— FOF 组合配置与风险预算系统

基于 NALE / T-NALE 信号的主动资产配置层。
包含：数据契约、信号适配器、资产配置器、风险预算管理、调仓执行与点时回测。
"""

from __future__ import annotations

from src.portfolio.contracts import (
    AssetInfo,
    AssetRole,
    AssetType,
    PointInTimeSignal,
    AggregationMethod,
    RiskState,
    RiskBudgetConfig,
    PortfolioWeights,
    BacktestTrade,
    BacktestLogEntry,
    PerformanceMetrics,
)
from src.portfolio.signal_adapter import NALESignalAdapter
from src.portfolio.allocator import FOFAllocator, AllocationConfig
from src.portfolio.risk_budget import RiskBudgetManager
from src.portfolio.rebalancer import RebalanceManager, RebalanceConfig
from src.portfolio.backtest import FOFBacktestEngine, BacktestConfig

__all__ = [
    "AssetInfo",
    "AssetRole",
    "AssetType",
    "PointInTimeSignal",
    "AggregationMethod",
    "RiskState",
    "RiskBudgetConfig",
    "PortfolioWeights",
    "BacktestTrade",
    "BacktestLogEntry",
    "PerformanceMetrics",
    "NALESignalAdapter",
    "FOFAllocator",
    "AllocationConfig",
    "RiskBudgetManager",
    "RebalanceManager",
    "RebalanceConfig",
    "FOFBacktestEngine",
    "BacktestConfig",
]
