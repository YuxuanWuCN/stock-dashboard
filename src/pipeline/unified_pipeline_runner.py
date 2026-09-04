# -*- coding: utf-8 -*-
"""src/pipeline/unified_pipeline_runner.py —— FinRobot 架构统一全流程 DAG 状态机调度器

依据规范：
1. 《StockDashboard v3.0 & Serenity Chokepoint 12-Week Roadmap》
2. 状态机流转：
   - 阶段 1: Qualitative FOI Discovery & Credibility Scoring & 数据多因子装配
   - 阶段 2: Pluggable Two-Stage Fama-MacBeth OLS & 因子正交化 & GFCA 坐标映射
   - 阶段 3: NALE 拓扑网络传导与 Nowcasting 二次减值惩罚
   - 阶段 4: Tactical Trend Gate™ 布尔硬门禁 & 市场状态机 (BULL/BEAR/SIDEWAYS) & Dynamic Bet Sizer
3. 线程安全 SessionState 上下文数据封包
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from src.data.adapter import UnifiedDataAdapter, MarketDataPacket
from src.analysis.famamacbethv3 import FamaMacBethV3Engine, Stage1Result, Stage2Result
from src.analysis.scoringv3 import GFCAScoringEngine, GFCACoordinates, NALEScoreResult
from src.graph.supply_chain_graph import SupplyChainGraph
from src.nowcasting.triangle_validator import NowcastingTriangleValidator, TriangulationSignal
from src.pricing.factor_orthogonalization import orthogonalize_factor
from src.risk.market_regime_detector import MarketRegimeDetector, RegimeType
from src.risk.dynamic_position_sizer import DynamicPositionSizer

logger = logging.getLogger("unified_pipeline")


class PipelineStageState(str, Enum):
    IDLE = "IDLE"
    PHASE1_QUALITATIVE_FOI = "PHASE1_QUALITATIVE_FOI"
    PHASE2_ECONOMETRIC_GFCA = "PHASE2_ECONOMETRIC_GFCA"
    PHASE3_NALE_NOWCASTING = "PHASE3_NALE_NOWCASTING"
    PHASE4_EXECUTION_BET_SIZING = "PHASE4_EXECUTION_BET_SIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class SessionState:
    """线程安全全流程状态上下文封包。"""
    session_id: str
    target_ticker: str
    current_state: PipelineStageState = PipelineStageState.IDLE
    data_packet: Optional[MarketDataPacket] = None
    stage1_result: Optional[Stage1Result] = None
    orthogonal_residual: Optional[pd.Series] = None
    orthogonal_exposures: Optional[Dict[str, float]] = None
    gfca_coords: Optional[GFCACoordinates] = None
    nale_result: Optional[NALEScoreResult] = None
    nowcasting_signal: Optional[TriangulationSignal] = None
    detected_regime: str = "SIDEWAYS"
    position_multiplier: float = 1.0
    trend_gate_passed: bool = True
    allocated_weight: float = 0.0
    execution_decision: str = "PENDING"
    logs: List[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def log(self, message: str) -> None:
        with self._lock:
            self.logs.append(message)


class UnifiedPipelineRunner:
    """DAG 状态机统一全流程调度器。"""

    def __init__(self, mode: str = "dual_track", penalty_lambda: float = 0.5):
        self.data_adapter = UnifiedDataAdapter(mode=mode)
        self.fm_engine = FamaMacBethV3Engine(t_stat_threshold=3.0)
        self.scoring_engine = GFCAScoringEngine(tanh_scaling=1.5, nale_alpha=0.4)
        self.nowcasting_validator = NowcastingTriangleValidator(penalty_lambda=penalty_lambda)
        self.graph = SupplyChainGraph()
        self.regime_detector = MarketRegimeDetector()
        self.position_sizer = DynamicPositionSizer()

    def run_dag_pipeline(
        self,
        session_id: str,
        ticker: str,
        kline_df: pd.DataFrame,
        raw_foi_score: float = 0.50,
        spot_price: float = 100.0,
        prepay_cost: float = 100.0,
        korea_export_yoy: float = 0.35,
        bet_type: str = "Catalyst Alpha"
    ) -> SessionState:
        """执行端到端 DAG 状态机调度。"""
        session = SessionState(session_id=session_id, target_ticker=ticker)
        session.current_state = PipelineStageState.PHASE1_QUALITATIVE_FOI
        session.log(f"启动 Pipeline [Session: {session_id}, 标的: {ticker}]")

        # 1. 组装数据封包
        data_packet = self.data_adapter.assemble_market_packet(ticker, kline_df, market="CN")
        session.data_packet = data_packet
        session.log("Phase 1: 数据封包与多因子矩阵装配完成")

        # 2. 计量时序回归 (Stage 1) 与 GFCA 坐标映射，前置执行因子正交化（若样本充足）
        session.current_state = PipelineStageState.PHASE2_ECONOMETRIC_GFCA
        s1_res = self.fm_engine.run_stage1_time_series(data_packet.returns, data_packet.factors, ticker=ticker)
        session.stage1_result = s1_res

        if len(data_packet.returns) >= 30 and data_packet.factors.shape[1] >= 1:
            try:
                orth_resid, orth_exp = orthogonalize_factor(
                    data_packet.returns,
                    data_packet.factors,
                    return_exposure=True
                )
                session.orthogonal_residual = orth_resid
                session.orthogonal_exposures = orth_exp
                session.log(f"Phase 2: 因子正交化完成 (R2={orth_exp.get('R2', 0.0):.4f})")
            except Exception as e:
                session.log(f"Phase 2: 因子正交化跳过: {e}")

        # 3. Nowcasting 减值惩罚计算
        session.current_state = PipelineStageState.PHASE3_NALE_NOWCASTING
        nowcast_sig = self.nowcasting_validator.evaluate_asset_nowcasting(
            ticker=ticker,
            korea_customs_export_yoy=korea_export_yoy,
            spot_dxi_price=spot_price,
            lockin_prepay_cost=prepay_cost
        )
        session.nowcasting_signal = nowcast_sig

        # 几何因子坐标对齐 (注入减值漂移)
        raw_betas_df = pd.DataFrame([s1_res.betas], index=[ticker])
        gfca_map = self.scoring_engine.align_gfca_coordinates(
            raw_betas_df,
            impairment_penalties={ticker: nowcast_sig.impairment_penalty_drift}
        )
        session.gfca_coords = gfca_map[ticker]
        session.log(f"Phase 2 & 3: GFCA 几何综合得分 = {session.gfca_coords.composite_score:.4f}, 减值漂移 = {nowcast_sig.impairment_penalty_drift:.4f}")

        # 4. 战术决策、市场状态机识别与动态仓位计算
        session.current_state = PipelineStageState.PHASE4_EXECUTION_BET_SIZING

        # 检测大盘/标的所处市场状态
        try:
            regime_series = self.regime_detector.detect_regime(kline_df)
            current_regime = regime_series.iloc[-1]
            regime_str = current_regime.value if hasattr(current_regime, "value") else str(current_regime)
        except Exception:
            regime_str = "SIDEWAYS"
        session.detected_regime = regime_str

        # 基于市场状态计算动态仓位调整系数
        pos_multiplier = self.position_sizer.calculate_position(
            regime=regime_str,
            current_drawdown=0.0,
            volatility=0.02
        )
        session.position_multiplier = pos_multiplier

        if nowcast_sig.is_impaired and abs(nowcast_sig.impairment_penalty_drift) > 0.05:
            session.trend_gate_passed = False
            session.allocated_weight = 0.0
            session.execution_decision = "REJECT_DUE_TO_IMPAIRMENT"
        elif session.gfca_coords.composite_score > 0.10:
            session.trend_gate_passed = True
            base_w = 0.10 if bet_type == "Catalyst Alpha" else 0.15
            # 乘以市场状态仓位乘数并进行上限截断
            session.allocated_weight = float(np.clip(base_w * pos_multiplier, 0.0, 1.0))
            session.execution_decision = "APPROVED_LONG"
        else:
            session.trend_gate_passed = True
            session.allocated_weight = 0.0
            session.execution_decision = "HOLD_WATCHLIST"

        session.current_state = PipelineStageState.COMPLETED
        session.log(
            f"Pipeline 执行完毕: 状态={regime_str}, 乘数={pos_multiplier:.2f}, "
            f"决策={session.execution_decision}, 最终权重={session.allocated_weight*100:.1f}%"
        )
        return session
