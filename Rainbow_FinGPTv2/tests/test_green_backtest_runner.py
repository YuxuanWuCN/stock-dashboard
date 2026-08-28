# -*- coding: utf-8 -*-
import pytest
from pathlib import Path
from src.analysis.green_backtest_runner import GreenBacktestRunner


def test_green_backtest_runner_walk_forward():
    raw_dir = Path('data/raw/backtest_green_2025q3_2026q3')
    assert raw_dir.exists(), '绿电物理隔离数据目录必须存在'

    runner = GreenBacktestRunner(raw_data_dir=raw_dir)
    res = runner.run_walk_forward_backtest()

    assert 'metrics' in res
    assert 'snapshots' in res
    assert 'nav_series' in res

    metrics = res['metrics']
    strat = metrics['strategy_stats']
    etf = metrics['benchmark_green_etf_stats']
    
    assert strat['total_return'] > 0.0
    # 验证 Trend Gate 成功压制最大回撤 (回撤小于绿电ETF)
    assert strat['max_drawdown'] < etf['max_drawdown']
    assert len(res['snapshots']) >= 200
