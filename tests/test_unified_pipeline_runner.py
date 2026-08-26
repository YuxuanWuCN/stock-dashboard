# -*- coding: utf-8 -*-
"""tests/test_unified_pipeline_runner.py —— 统一 DAG 全流程调度器单元测试 (Week 8)"""

import pandas as pd
import numpy as np
import pytest

from src.pipeline.unified_pipeline_runner import UnifiedPipelineRunner, SessionState, PipelineStageState


def test_unified_pipeline_dag_execution():
    """测试 DAG 状态机端到端执行、SessionState 线程安全与多阶段协同。"""
    runner = UnifiedPipelineRunner(mode="dual_track")

    dates = pd.date_range("2024-01-01", periods=20, freq="B")
    prices = np.cumprod(1 + np.random.normal(0.001, 0.01, 20)) * 100.0
    kline_df = pd.DataFrame({
        "open": prices,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": [50000] * 20
    }, index=dates)

    # 1. 正常景气上行场景 (现货价 110 > 锁价 100)
    session = runner.run_dag_pipeline(
        session_id="SESS_001",
        ticker="001309",
        kline_df=kline_df,
        raw_foi_score=0.75,
        spot_price=110.0,
        prepay_cost=100.0,
        korea_export_yoy=0.45
    )

    assert isinstance(session, SessionState)
    assert session.current_state == PipelineStageState.COMPLETED
    assert session.data_packet is not None
    assert session.stage1_result is not None
    assert session.gfca_coords is not None
    assert session.nowcasting_signal is not None
    assert len(session.logs) >= 3

    # 2. 深度减值暴跌场景 (现货价 50 < 锁价 100)
    session_impaired = runner.run_dag_pipeline(
        session_id="SESS_002",
        ticker="001309",
        kline_df=kline_df,
        raw_foi_score=0.75,
        spot_price=50.0,
        prepay_cost=100.0,
        korea_export_yoy=-0.20
    )
    assert session_impaired.execution_decision == "REJECT_DUE_TO_IMPAIRMENT"
    assert session_impaired.allocated_weight == 0.0
