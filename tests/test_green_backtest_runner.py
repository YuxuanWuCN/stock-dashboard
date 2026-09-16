# -*- coding: utf-8 -*-
"""tests/test_green_backtest_runner.py —— 绿电公用事业与新能源物理隔离逐步推进回测与方向校准测试"""

from pathlib import Path
import pytest
from src.analysis.green_backtest_runner import GreenBacktestRunner


def test_green_backtest_runner_walk_forward():
    raw_dir = Path("data/raw/backtest_green_2025q3_2026q3")
    if not raw_dir.exists():
        raw_dir = Path("Rainbow_FinGPTv2/data/raw/backtest_green_2025q3_2026q3")
    assert raw_dir.exists(), "绿电物理隔离数据目录必须存在"

    runner = GreenBacktestRunner(raw_data_dir=raw_dir)
    res = runner.run_walk_forward_backtest()

    assert "metrics" in res
    assert "snapshots" in res
    assert "nav_series" in res
    assert "calibration_records" in res

    metrics = res["metrics"]
    strat = metrics["strategy_stats"]
    etf = metrics["benchmark_green_etf_stats"]

    assert strat["total_return"] > 0.0
    # 验证 Trend Gate 与方向校准成功压制最大回撤 (回撤小于绿电ETF)
    assert strat["max_drawdown"] < etf["max_drawdown"]
    assert len(res["snapshots"]) >= 200

    # 验证预测覆盖率与校准性能统计结构
    assert "prediction_coverage" in metrics
    assert "prediction_performance" in metrics
    cov = metrics["prediction_coverage"]
    assert "total_opportunities" in cov
    assert "valid_predictions" in cov
    assert "rejected_predictions" in cov
    assert "coverage_rate" in cov
    assert cov["coverage_rate"] > 0.0

    # 验证快照中包含校准状态
    snap = res["snapshots"][-1]
    assert hasattr(snap, "calibration_direction")
    assert hasattr(snap, "coverage_rate")
