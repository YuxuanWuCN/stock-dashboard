# -*- coding: utf-8 -*-
r"""src/portfolio/rebalancer.py —— 调仓执行器、死区控制与交易费用核算

依据《FOF 组合配置改造意见》§5 & §7：
1. 调仓死区 (Deadband)：单标的偏离小于死区阈值 (如 1.5%) 时不调仓，抑制由高频情绪噪声引发的无谓换手。
2. 换手率与摩擦成本：
   - 换手率 Turnover = 0.5 * \sum |w_new - w_old|
   - 考虑佣金 (fees) 与冲击滑点 (slippage)
3. 严格全额归一与防御底仓平抑。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.portfolio.contracts import (
    AssetInfo,
    BacktestTrade,
    PortfolioWeights,
)

logger = logging.getLogger("portfolio.rebalancer")


@dataclass(frozen=True)
class RebalanceConfig:
    """调仓执行规则。"""
    deadband_threshold: float = 0.015     # 调仓死区阈值 (如 1.5%)
    min_trade_weight: float = 0.005       # 最小交易调仓幅度 (小于 0.5% 不下单)
    max_single_day_turnover: float = 0.35 # 单日换手率硬上限 (如 35%)


class RebalanceManager:
    """调仓死区过滤与交易执行器。"""

    def __init__(
        self,
        assets: Dict[str, AssetInfo],
        config: Optional[RebalanceConfig] = None,
    ):
        self.assets = assets
        self.config = config or RebalanceConfig()

    def apply_deadband_and_execute(
        self,
        trade_date: str,
        current_weights: Dict[str, float],
        target_weights: PortfolioWeights,
        asset_prices: Optional[Dict[str, float]] = None,
    ) -> Tuple[Dict[str, float], float, float, List[BacktestTrade]]:
        """应用调仓死区、换手限制并计算交易费用。

        返回: (执行后实际权重, 本次换手率, 本次交易总成本, 交易明细列表)
        """
        prices = asset_prices or {}
        raw_targets = target_weights.weights
        post_deadband_weights: Dict[str, float] = {}

        # 1. 逐标的死区过滤
        for ticker in self.assets:
            w_curr = current_weights.get(ticker, 0.0)
            w_tgt = raw_targets.get(ticker, 0.0)
            diff = abs(w_tgt - w_curr)

            # 若变化极小且处于死区内，保持现状
            if diff < self.config.deadband_threshold:
                post_deadband_weights[ticker] = w_curr
            else:
                post_deadband_weights[ticker] = w_tgt

        # 2. 重新归一化 (防御资产吸收死区带来的漂移)
        defensive_tickers = [
            t for t, a in self.assets.items() if a.role.value == "core_defensive"
        ]
        primary_def = defensive_tickers[0] if defensive_tickers else list(self.assets.keys())[0]

        total_non_def = sum(
            w for t, w in post_deadband_weights.items() if t != primary_def
        )
        post_deadband_weights[primary_def] = max(0.0, 1.0 - total_non_def)

        # 3. 单日换手率约束检查与缩放
        raw_turnover = 0.5 * sum(
            abs(post_deadband_weights.get(t, 0.0) - current_weights.get(t, 0.0))
            for t in self.assets
        )

        executed_weights: Dict[str, float] = {}
        if raw_turnover > self.config.max_single_day_turnover and raw_turnover > 1e-6:
            scale = self.config.max_single_day_turnover / raw_turnover
            for t in self.assets:
                w_c = current_weights.get(t, 0.0)
                w_t = post_deadband_weights.get(t, 0.0)
                executed_weights[t] = w_c + (w_t - w_c) * scale
            executed_turnover = self.config.max_single_day_turnover
        else:
            executed_weights = post_deadband_weights
            executed_turnover = raw_turnover

        # 确保精确归一化
        sum_exec = sum(executed_weights.values())
        if abs(sum_exec - 1.0) > 1e-6:
            executed_weights[primary_def] += (1.0 - sum_exec)

        # 4. 计算费用与生成交易订单
        trades: List[BacktestTrade] = []
        total_cost = 0.0

        for ticker in self.assets:
            w_c = current_weights.get(ticker, 0.0)
            w_e = executed_weights.get(ticker, 0.0)
            delta = w_e - w_c
            if abs(delta) >= self.config.min_trade_weight:
                asset_meta = self.assets[ticker]
                fee_rate = (asset_meta.trading_fee_bps + asset_meta.slippage_bps) * 1e-4
                trade_cost = abs(delta) * fee_rate
                total_cost += trade_cost

                trades.append(
                    BacktestTrade(
                        trade_date=trade_date,
                        ticker=ticker,
                        prior_weight=w_c,
                        target_weight=w_e,
                        delta_weight=delta,
                        price=prices.get(ticker, 1.0),
                        cost_paid=trade_cost,
                    )
                )

        return executed_weights, executed_turnover, total_cost, trades
