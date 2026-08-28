# -*- coding: utf-8 -*-
"""tests/test_nowcasting_triangle.py —— Nowcasting 三角互证与二次减值惩罚单元测试 (Week 7)"""

import pytest
from src.nowcasting.triangle_validator import NowcastingTriangleValidator, TriangulationSignal


def test_nowcasting_impairment_penalty():
    """测试二次非对称减值惩罚函数的触发与数值响应。"""
    validator = NowcastingTriangleValidator(penalty_lambda=0.5)

    # 1. 正常盈利场景：现货价 120 > 锁价 100 -> 惩罚为 0
    p0 = validator.calculate_impairment_penalty(spot_price=120.0, prepay_cost=100.0)
    assert p0 == 0.0

    # 2. 轻微倒挂：现货价 90 < 锁价 100 (跌 10%) -> Drift = -0.5 * (0.1)^2 = -0.005
    p1 = validator.calculate_impairment_penalty(spot_price=90.0, prepay_cost=100.0)
    assert p1 == pytest.approx(-0.005, abs=1e-5)

    # 3. 严重倒挂：现货价 60 < 锁价 100 (跌 40%) -> Drift = -0.5 * (0.4)^2 = -0.080 (断崖惩罚)
    p2 = validator.calculate_impairment_penalty(spot_price=60.0, prepay_cost=100.0)
    assert p2 == pytest.approx(-0.080, abs=1e-5)
    assert abs(p2) > abs(p1) * 10  # 二次非线性断崖放大


def test_nowcasting_full_evaluation():
    """测试多源宏微观三角互证。"""
    validator = NowcastingTriangleValidator(penalty_lambda=0.5)

    signal = validator.evaluate_asset_nowcasting(
        ticker="001309",
        korea_customs_export_yoy=0.45,
        spot_dxi_price=85.0,
        lockin_prepay_cost=100.0,  # 发生减值
        downstream_capex_growth=0.40
    )

    assert isinstance(signal, TriangulationSignal)
    assert signal.is_impaired is True
    assert signal.impairment_penalty_drift < 0.0
    assert "减值预警" in signal.status_summary
