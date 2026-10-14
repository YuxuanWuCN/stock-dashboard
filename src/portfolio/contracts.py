# -*- coding: utf-8 -*-
"""src/portfolio/contracts.py —— FOF 组合配置数据与行为契约

定义组合资产分类、点时信号契约、权重约束、风险预算状态与回测记录模型。
严格遵循 fail-closed 原则，任何 NaN、Inf 或越界输入均抛出验证异常或显式拒识。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class AssetType(str, Enum):
    """资产基本类型。"""
    CASH = "cash"                      # 现金/货币基金
    BOND = "bond"                      # 纯债/政策金融债
    BROAD_EQUITY = "broad_equity"      # 宽基指数 ETF / 核心股票资产
    SECTOR_ETF = "sector_etf"          # 行业/主题 ETF
    MUTUAL_FUND = "mutual_fund"        # 主动权益公募基金


class AssetRole(str, Enum):
    """资产在 FOF 组合中的角色定位。"""
    CORE_DEFENSIVE = "core_defensive"  # 核心防御底仓 (提供安全垫，平抑回撤)
    CORE_BETA = "core_beta"            # 核心 Beta 底仓 (跟踪大盘基准收益)
    SATELLITE_ALPHA = "satellite_alpha"# 卫星 Alpha 仓位 (接收 NALE 信号主动超配)


class RiskState(str, Enum):
    """组合风险状态机层级。"""
    NORMAL = "normal"          # 正常状态：MaxDD < 5%，全额卫星风险预算
    WATCH = "watch"            # 观察预警状态：5% <= MaxDD < 8%，收缩卫星预算至 60%
    DEFENSIVE = "defensive"    # 防御降仓状态：8% <= MaxDD < 10%，收缩卫星预算至 20%
    PROTECTIVE = "protective"  # 极度保护状态：MaxDD >= 10%，卫星清零，100% 防御底仓


class AggregationMethod(str, Enum):
    """股票信号到行业/基金的聚合加权方法。"""
    EQUAL_WEIGHT = "equal_weight"            # 等权聚合
    MCAP_WEIGHT = "mcap_weight"              # 自由流通市值加权
    CONFIDENCE_WEIGHT = "confidence_weight"  # 置信度加权


@dataclass(frozen=True)
class AssetInfo:
    """组合标的元数据定义契约。"""
    ticker: str
    name: str
    asset_type: AssetType
    role: AssetRole
    sector: Optional[str] = None
    benchmark_weight: float = 0.0
    max_weight: float = 0.30
    min_weight: float = 0.0
    trading_fee_bps: float = 3.0    # 单边交易费用 (基点, 3 bps = 0.03%)
    slippage_bps: float = 2.0       # 单边滑点估算 (基点, 2 bps = 0.02%)

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ValueError("资产 ticker 不能为空")
        if not (0.0 <= self.min_weight <= self.max_weight <= 1.0):
            raise ValueError(f"资产 {self.ticker} 权重区间 [{self.min_weight}, {self.max_weight}] 不合法")
        if self.benchmark_weight < 0.0 or self.benchmark_weight > 1.0:
            raise ValueError(f"资产 {self.ticker} 基准权重 {self.benchmark_weight} 必须在 [0, 1]")


@dataclass
class PointInTimeSignal:
    """点时单标的配置信号。"""
    as_of_date: str
    ticker: str
    score: float                      # 规范化主动配置得分 [-1.0, 1.0]
    confidence: float                 # 置信度 [0.0, 1.0]
    source_method: str                # 信号生成来源 (如 static_nale, t_nale, sentiment_only)
    is_valid: bool = True             # 是否为有效信号
    refusal_reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if math.isnan(self.score) or math.isinf(self.score):
            self.score = 0.0
            self.is_valid = False
            self.refusal_reason = "Score contains NaN or Inf"
        if math.isnan(self.confidence) or math.isinf(self.confidence):
            self.confidence = 0.0
            self.is_valid = False
            self.refusal_reason = "Confidence contains NaN or Inf"
        self.score = max(-1.0, min(1.0, self.score))
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass(frozen=True)
class RiskBudgetConfig:
    """组合风险预算与动态门禁配置。"""
    target_volatility: float = 0.08          # 年化目标波动率 (如 8%)
    vol_lookback_days: int = 20              # 历史波动率估计窗口 (交易日)
    max_portfolio_volatility: float = 0.12   # 组合波动率硬上限
    max_satellite_budget: float = 0.25       # 正常状态卫星仓总预算上限 (如 25%)
    max_single_satellite: float = 0.10       # 单一卫星标的上限 (如 10%)
    max_sector_exposure: float = 0.15        # 单一行业最大暴露 (如 15%)
    min_defensive_weight: float = 0.40       # 最低防御底仓权重 (如 40%)
    # 分层回撤阶梯阈值 (候选参数，需回测检验)
    dd_threshold_watch: float = 0.05         # 触发 WATCH 预警的回撤深度
    dd_threshold_defensive: float = 0.08     # 触发 DEFENSIVE 防御的回撤深度
    dd_threshold_protective: float = 0.10    # 触发 PROTECTIVE 保护的回撤深度
    # 状态恢复确认天数 (避免假信号日内震荡)
    recovery_confirmation_days: int = 3


@dataclass
class PortfolioWeights:
    """组合在某调仓日的最终目标权重与风险诊断信息。"""
    trade_date: str
    weights: Dict[str, float]
    risk_state: RiskState
    satellite_budget_used: float
    volatility_scale: float
    active_constraints: List[str] = field(default_factory=list)
    cash_or_defensive_residual: float = 0.0

    def validate_weights(self, tolerance: float = 1e-4) -> None:
        """严格校验权重和必须为 1.0，所有单个权重在 [0, 1] 区间。"""
        total = sum(self.weights.values())
        if abs(total - 1.0) > tolerance:
            raise ValueError(f"组合权重和为 {total:.6f}，偏离 1.0 超过容差 {tolerance}")
        for ticker, w in self.weights.items():
            if w < -tolerance or w > 1.0 + tolerance:
                raise ValueError(f"标的 {ticker} 权重 {w:.6f} 越界 [0, 1]")
            if math.isnan(w) or math.isinf(w):
                raise ValueError(f"标的 {ticker} 权重包含 NaN 或 Inf")


@dataclass
class BacktestTrade:
    """调仓交易明细。"""
    trade_date: str
    ticker: str
    prior_weight: float
    target_weight: float
    delta_weight: float
    price: float
    cost_paid: float


@dataclass
class BacktestLogEntry:
    """逐日组合回测切片日志。"""
    trade_date: str
    nav: float
    daily_return: float
    benchmark_nav: float
    benchmark_daily_return: float
    drawdown: float
    peak_nav: float
    risk_state: str
    satellite_weight: float
    defensive_weight: float
    core_beta_weight: float
    weights: Dict[str, float]
    turnover: float
    total_fee: float
    active_signals: Dict[str, float]


@dataclass
class PerformanceMetrics:
    """回测业绩统计指标。"""
    start_date: str
    end_date: str
    trading_days: int
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    max_drawdown_duration_days: int
    monthly_win_rate: float
    negative_months_count: int
    total_turnover: float
    annualized_turnover: float
    total_trading_costs: float
    avg_defensive_weight: float
    avg_satellite_weight: float
    benchmark_annualized_return: float
    benchmark_annualized_vol: float
    benchmark_max_drawdown: float
    benchmark_sharpe: float
    alpha: float
    beta: float
    information_ratio: float
