# -*- coding: utf-8 -*-
import pytest
from pathlib import Path
from src.analysis.gold_backtest_runner import GoldBacktestRunner


def test_gold_backtest_runner_walk_forward():
    raw_dir = Path("data/raw/backtest_gold_2025q3_2026q8")
    assert raw_dir.exists(), "黄金物理隔离数据目录必须存在"

    runner = GoldBacktestRunner(raw_data_dir=raw_dir)
    res = runner.run_walk_forward_backtest()

    assert "metrics" in res
    assert "snapshots" in res
    assert "nav_series" in res

    metrics = res["metrics"]
    strat = metrics["strategy_stats"]
    assert strat["total_return"] > 0.0
    assert strat["sharpe_ratio"] > 0.5
    assert len(res["snapshots"]) >= 200
