# -*- coding: utf-8 -*-
"""tests/test_gfca_scoring.py —— GFCA (Geometric Factor Coordinate Alignment) 单元测试 (Week 4)"""

import pandas as pd
import numpy as np
import pytest

from src.analysis.scoringv3 import GFCAScoringEngine, GFCACoordinates


def test_gfca_coordinate_alignment():
    """测试多维因子向 [-1, 1]^K 空间的双曲正切 tanh 平滑映射与减值惩罚负漂移。"""
    engine = GFCAScoringEngine(tanh_scaling=1.5)

    # 构造测试标的与多维因子矩阵
    tickers = ["001309", "300475", "301308", "688008"]
    raw_df = pd.DataFrame({
        "MKT": [1.5, 0.8, 1.1, 2.8],  # 688008 存在高极端值
        "SMB": [0.4, 0.9, 0.2, -0.6],
        "HML": [-0.5, -0.2, 0.1, 0.4],
        "MOM": [0.8, 0.3, -0.4, 1.2]
    }, index=tickers)

    # 1. 基础 GFCA 坐标对齐
    gfca_map = engine.align_gfca_coordinates(raw_df)
    assert len(gfca_map) == 4
    for ticker, item in gfca_map.items():
        assert isinstance(item, GFCACoordinates)
        assert -1.0 <= item.composite_score <= 1.0
        for factor, val in item.coordinates.items():
            assert -1.0 <= val <= 1.0

    # 极端异常值通过 tanh 平滑压缩（2.8 -> < 1.0）
    assert gfca_map["688008"].coordinates["MKT"] < 1.0

    # 2. 注入 Nowcasting 减值惩罚负漂移
    penalties = {"301308": -0.35}
    gfca_penalized = engine.align_gfca_coordinates(raw_df, impairment_penalties=penalties)
    assert gfca_penalized["301308"].composite_score < gfca_map["301308"].composite_score
