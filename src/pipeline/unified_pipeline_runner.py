# -*- coding: utf-8 -*-
"""src/pipeline/unified_pipeline_runner.py —— FinRobot 架构统一全流程 DAG 状态机调度器 (Week 8)

依据规范：
1. 《StockDashboard v3.0 & Serenity Chokepoint 12-Week Roadmap》Phase II: Week 8
2. 状态机流转：
   - 阶段 1: Qualitative FOI Discovery & Credibility Scoring
   - 阶段 2: Pluggable Two-Stage Fama-MacBeth OLS & GFCA Coordinate Alignment
   - 阶段 3: NALE 拓扑网络传导与 Nowcasting 二次减值惩罚
   - 阶段 4: Tactical Trend Gate™ 布尔硬门禁 & Dynamic Bet Allocator
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
    gfca_coords: Optional[GFCACoordinates] = None
    nale_result: Optional[NALEScoreResult] = None
    nowcasting_signal: Optional[TriangulationSignal] = None
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

        # 2. 计量时序回归 (Stage 1) 与 GFCA 坐标映射
        session.current_state = PipelineStageState.PHASE2_ECONOMETRIC_GFCA
        s1_res = self.fm_engine.run_stage1_time_series(data_packet.returns, data_packet.factors, ticker=ticker)
        session.stage1_result = s1_res

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

        # 4. 战术决策与头寸计算
        session.current_state = PipelineStageState.PHASE4_EXECUTION_BET_SIZING
        if nowcast_sig.is_impaired and abs(nowcast_sig.impairment_penalty_drift) > 0.05:
            session.trend_gate_passed = False
            session.allocated_weight = 0.0
            session.execution_decision = "REJECT_DUE_TO_IMPAIRMENT"
        elif session.gfca_coords.composite_score > 0.10:
            session.trend_gate_passed = True
            session.allocated_weight = 0.10 if bet_type == "Catalyst Alpha" else 0.15
            session.execution_decision = "APPROVED_LONG"
        else:
            session.trend_gate_passed = True
            session.allocated_weight = 0.0
            session.execution_decision = "HOLD_WATCHLIST"

        session.current_state = PipelineStageState.COMPLETED
        session.log(f"Pipeline 执行完毕: 决策 = {session.execution_decision}, 权重 = {session.allocated_weight*100:.1f}%")
        return session
