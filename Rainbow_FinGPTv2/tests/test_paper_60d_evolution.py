# -*- coding: utf-8 -*-
"""tests/test_paper_60d_evolution.py —— 60日202支股票全池回测与每周冠军演化单元测试"""

import pytest
from pathlib import Path
from src.pipeline.paper_60d_evolution_runner import Paper60dEvolutionRunner, AccuracyEvaluationResult


def test_paper_60d_evolution_runner_execution():
    """测试 60 天 202 支股票全池回测、每周冠军评选与四维准确率评估。"""
    raw_dir = Path("data/raw/backtest_paper_60d_202stocks")
    assert raw_dir.exists(), "必须先生成 202 支股票物理隔离原始数据"

    runner = Paper60dEvolutionRunner(raw_dir=raw_dir)
    res = runner.run_60d_simulation()

    assert "dates" in res
    assert len(res["dates"]) == 60
    assert "portfolio_navs" in res
    assert len(res["portfolio_navs"]) == 6
    assert "weekly_champions" in res
    assert len(res["weekly_champions"]) >= 10  # 60 天约 12 周

    acc = res["accuracy_report"]
    assert isinstance(acc, AccuracyEvaluationResult)
    assert acc.total_prediction_samples > 10000  # 60 天 x 202 支股票 = 12120 个预测样本
    assert acc.trade_win_rate > 0.40
    assert acc.directional_hit_rate_5d > 0.50
    assert acc.brier_calibration_score < 0.30
