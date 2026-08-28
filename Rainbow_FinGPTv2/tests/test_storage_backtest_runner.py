# -*- coding: utf-8 -*-
"""tests/test_storage_backtest_runner.py —— 存储市场物理隔离回测单元测试与边界路径健全性校验"""

import pytest
from pathlib import Path
import pandas as pd
from src.analysis.storage_backtest_runner import StorageBacktestRunner


def test_storage_backtest_runner_execution():
    """测试存储市场日频因果逐步推进回测执行与三级基准度量输出。"""
    raw_dir = Path("data/raw/backtest_storage_2025q2_2026q7")
    assert raw_dir.exists(), "必须先生成物理隔离原始数据"

    runner = StorageBacktestRunner(raw_data_dir=raw_dir)
    res = runner.run_walk_forward_backtest()

    assert "metrics" in res
    assert "snapshots" in res
    assert "nav_series" in res

    metrics = res["metrics"]
    strat_stats = metrics["strategy_stats"]
    storage_ew_stats = metrics["benchmark_storage_ew_stats"]

    # 1. 验证策略夏普比率与超额 Alpha 显著性 (闭环 GFCA + NALE 驱动)
    assert strat_stats["sharpe_ratio"] >= 2.0
    assert strat_stats["total_return"] > 2.0  # 300日累积总收益翻倍以上 (>200%)
    assert strat_stats["max_drawdown"] < 0.28  # Trend Gate 成功将最大回撤限制在 28% 以内 (远优于基准 54.1%)
    
    # 2. 验证相比存储等权买入持有策略，策略组最大回撤大幅减少 (>50% 压制)
    assert strat_stats["max_drawdown"] < storage_ew_stats["max_drawdown"] * 0.55

    # 3. 验证快照数量
    assert len(res["snapshots"]) >= 250


def test_storage_backtest_runner_boundary_and_c_wave_liquidation():
    """测试边界异常路径与极端行情下 Trend Gate 的硬切断行为。"""
    raw_dir = Path("data/raw/backtest_storage_2025q2_2026q7")
    runner = StorageBacktestRunner(raw_data_dir=raw_dir)
    res = runner.run_walk_forward_backtest()
    
    # 检查所有日频快照中，当标的 gate_open == False 时，持仓必须严格为 0.0
    for snapshot in res["snapshots"]:
        for ticker, is_open in snapshot.trend_gate_status.items():
            if not is_open:
                assert snapshot.active_holdings[ticker] == 0.0, f"{snapshot.date} {ticker} 破位但持仓非零: {snapshot.active_holdings[ticker]}"
