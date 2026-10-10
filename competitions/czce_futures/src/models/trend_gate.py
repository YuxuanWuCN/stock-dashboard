# -*- coding: utf-8 -*-
"""
因果趋势门控状态机 (Trend Gate™ State Machine)
---------------------------------------------
基于纯碱价格动力学、已实现波动率通道与 Temporal NALE 产业链先行利润压力信号，
在无未来函数因果约束下，输出自适应套期保值对冲比率与状态阶跃信号。
"""

from enum import Enum
from typing import Optional, Tuple
import numpy as np
import pandas as pd


class MarketRegime(Enum):
    """市场所处结构性状态"""
    CONSOLIDATION = 0   # 震荡/反弹/利润修复区间 (低对冲 + Collar 领子兜底)
    BREAKDOWN_TREND = 1 # 破位主跌/利润坍塌主浪 (满额期货空头对冲)


class TrendGateMachine:
    """自适应趋势门控状态机引擎 (升级支持期限结构动量与主动防御)"""

    DEFAULT_W_PRICE: float = 0.45
    DEFAULT_W_NALE: float = 0.35
    DEFAULT_W_TS: float = 0.20

    def __init__(
        self,
        fast_span: int = 20,
        slow_span: int = 60,
        hysteresis_window: int = 3,
        nale_weight: float = 0.35,
        tsmom_weight: float = 0.20,
        price_weight: Optional[float] = None,
        active_defense: bool = True,
        threshold: float = 0.50
    ):
        """
        参数:
        - fast_span: 快速指数移动均线窗口 (EMA_fast)
        - slow_span: 慢速指数移动均线窗口 (EMA_slow)
        - hysteresis_window: 状态确认滤波窗口（防止假突破高频切换损耗）
        - nale_weight: Temporal NALE 产业链先行信号权重 (默认 0.35)
        - tsmom_weight: 期限结构动量信号权重 (默认 0.20)
        - price_weight: 价格趋势因子权重 (若未指定，自动由 1.0 - nale_weight - tsmom_weight 归一化为 0.45)
        - active_defense: 是否启用深贴水主动防御机制 (抑制假突破追空)
        - threshold: 状态机下行破位压力得分触发阈值 (默认 0.50)
        """
        self.fast_span = fast_span
        self.slow_span = slow_span
        self.hysteresis = hysteresis_window
        self.nale_weight = nale_weight
        self.tsmom_weight = tsmom_weight
        self.price_weight = (
            max(0.0, 1.0 - self.nale_weight - self.tsmom_weight)
            if price_weight is None
            else price_weight
        )
        self.active_defense = active_defense
        self.threshold = threshold

    def evaluate_regime(
        self,
        prices: pd.Series,
        volatilities: Optional[pd.Series] = None,
        nale_signals: Optional[pd.Series] = None,
        tsmom_signals: Optional[pd.Series] = None
    ) -> pd.DataFrame:
        """
        对价格序列进行因果状态机判定并输出动态对冲比率
        返回 DataFrame 包含:
        - trend_gate: 状态标记 (0.0 = CONSOLIDATION, 1.0 = BREAKDOWN_TREND)
        - dynamic_hedge_ratio: 建议期货端对冲比率 h* (0.25 或 0.95)
        - composite_score: 综合下行破位压力得分
        """
        n = len(prices)
        res = pd.DataFrame(index=prices.index)
        
        # 1. 价格动量与均线发散指标
        ema_fast = prices.ewm(span=self.fast_span, adjust=False).mean()
        ema_slow = prices.ewm(span=self.slow_span, adjust=False).mean()
        
        # 价格位于均线下方程度
        trend_score = np.where((prices < ema_fast) & (ema_fast < ema_slow), 1.0, 0.0)
        
        # 2. 统一单一路经打分与中性填补 (T5 / B3 修复)
        # 固定基准权重 (0.45, 0.35, 0.20)，缺失信号按中性 0.0 填补，严格不改变分母
        w_price = self.price_weight
        w_nale = self.nale_weight
        w_ts = self.tsmom_weight

        nale_factor = (
            np.zeros(n, dtype=np.float64)
            if nale_signals is None
            else nale_signals.fillna(0.0).clip(-1.0, 1.0).values.astype(np.float64)
        )
        tsmom_factor = (
            np.zeros(n, dtype=np.float64)
            if tsmom_signals is None
            else tsmom_signals.fillna(0.0).clip(-1.0, 1.0).values.astype(np.float64)
        )

        composite_score = (
            w_price * trend_score
            + w_nale * np.maximum(nale_factor, 0.0)
            + w_ts * np.maximum(tsmom_factor, 0.0)
        )

        # 主动防御机制 (Active Defense):
        # 当期限结构处于深度 Backwardation (TSMOM < -0.2) 时，现货偏紧挺价，基差有向上拉动期货动力
        # 此时抑制微幅跌破均线的追空假信号，防止在深贴水割肉 (Anti-whipsaw)
        if self.active_defense:
            defense_mask = tsmom_factor < -0.2
            suppression_factor = np.where(defense_mask, 1.0 + 0.5 * tsmom_factor, 1.0)
            composite_score = composite_score * suppression_factor

        # 3. 施加滞后滤波与状态确认 (Hysteresis Filter，必须连续 N 天维持信号才触发阶跃)
        raw_trigger = composite_score >= self.threshold
        smoothed_gate = pd.Series(raw_trigger, index=prices.index).rolling(self.hysteresis).sum() >= (self.hysteresis - 1)
        gate_series = smoothed_gate.astype(float).fillna(0.0)
        
        # 4. 生成阶跃动态套保比率: 震荡期 0.25 (其余由 Collar 吸收), 主跌浪 0.95 (接近 100% 满额锁仓)
        hedge_ratio = np.where(gate_series == 1.0, 0.95, 0.25)
        
        res["ema_fast"] = ema_fast
        res["ema_slow"] = ema_slow
        res["composite_score"] = composite_score
        res["trend_gate"] = gate_series
        res["dynamic_hedge_ratio"] = hedge_ratio
        
        return res

    def generate_states(self, features_df: pd.DataFrame) -> pd.Series:
        """
        满足 PROJECT.md M3 <-> M4 跨模块接口规范:
        输入特征 DataFrame，输出状态机序列 trend_gate in {0.0, 1.0}。
        """
        prices = features_df["close_sa"] if "close_sa" in features_df.columns else features_df["close"]
        volatilities = features_df.get("vol_20d_sa", None)
        nale_signals = features_df.get("nale_leading_signal", features_df.get("crush_spread", None))
        tsmom_signals = features_df.get("tsmom_sa", None)
        res = self.evaluate_regime(
            prices=prices,
            volatilities=volatilities,
            nale_signals=nale_signals,
            tsmom_signals=tsmom_signals
        )
        return res["trend_gate"]


# PROJECT.md 接口契约别名
TrendGateStateMachine = TrendGateMachine

