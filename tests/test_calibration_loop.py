# -*- coding: utf-8 -*-
"""tests/test_calibration_loop.py —— 贝叶斯闭环参数校准单元测试 (Spec-Kit 010)"""

import json
from pathlib import Path
import numpy as np
import pytest

from src.analysis.calibrate_weights import (
    load_duel_records,
    objective_loss,
    optimize_weights,
    update_strategy_config,
)


def test_objective_loss_finite():
    """测试复合校准损失函数的有限性与计算。"""
    records = [
        {"fundamental": 70, "technical": 80, "sentiment": 60, "leading": 75, "realized_up5": 1},
        {"fundamental": 40, "technical": 30, "sentiment": 50, "leading": 45, "realized_up5": 0},
    ]
    weights = np.array([0.35, 0.25, 0.20, 0.20])
    loss = objective_loss(weights, records)
    assert np.isfinite(loss)
    assert loss > 0


def test_optimize_weights_constraints():
    """测试贝叶斯/非线性优化权重的约束条件（和为 1.0，单项在界限内）。"""
    records = [
        {"fundamental": 85, "technical": 60, "sentiment": 40, "leading": 50, "realized_up5": 1},
        {"fundamental": 30, "technical": 80, "sentiment": 70, "leading": 40, "realized_up5": 0},
        {"fundamental": 90, "technical": 40, "sentiment": 30, "leading": 80, "realized_up5": 1},
        {"fundamental": 20, "technical": 30, "sentiment": 40, "leading": 20, "realized_up5": 0},
    ]
    opt_w = optimize_weights(records=records)

    total_weight = sum(opt_w.values())
    assert total_weight == pytest.approx(1.0, abs=1e-3)
    for k, v in opt_w.items():
        assert 0.04 <= v <= 0.65


def test_update_strategy_config_atomic(tmp_path):
    """测试策略配置文件的原子写入与更新。"""
    cfg_file = tmp_path / "strategy_params.json"
    new_w = {"fundamental": 0.4, "technical": 0.3, "sentiment": 0.15, "leading": 0.15}

    out_p = update_strategy_config(new_w, config_path=cfg_file)
    assert out_p.exists()

    with open(out_p, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["weights"]["fundamental"] == 0.4
    assert "last_calibrated_at" in data
