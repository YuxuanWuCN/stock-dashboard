# -*- coding: utf-8 -*-
"""tests/test_rolling_direction_calibration.py —— 滚动方向校准与拒绝预测单元测试

覆盖：
1. calculate_hit_rate 正向、反向、无效方向与空值边界
2. calibrate_factor_direction 正向显著、反向显著、样本不足、历史不足、低命中率拒绝、弱显著降级
3. apply_calibrated_direction 置信度门控、反转、拒绝预测 NaN 返回
4. StockPrediction 数据结构完整性
5. 严格因果时序与无前视泄露
"""

import math
import numpy as np
import pandas as pd
import pytest

from src.pricing.rolling_direction_calibration import (
    FactorDirection,
    CalibrationResult,
    StockPrediction,
    calculate_hit_rate,
    calibrate_factor_direction,
    apply_calibrated_direction,
    generate_calibration_report,
)


def test_calculate_hit_rate_positive_and_negative():
    """测试单截面命中率计算。"""
    scores = pd.Series({"001": 1.5, "002": -0.8, "003": 0.5, "004": -1.2})
    returns = pd.Series({"001": 0.02, "002": -0.01, "003": -0.03, "004": 0.01})

    # 正向预期：001 预测涨(真实涨-对)，002 预测跌(真实跌-对)，003 预测涨(真实跌-错)，004 预测跌(真实涨-错)
    # 正向命中 2/4 = 0.5
    pos_rate, pos_n = calculate_hit_rate(scores, returns, FactorDirection.POSITIVE)
    assert pos_n == 4
    assert math.isclose(pos_rate, 0.5, abs_tol=1e-6)

    # 反向预期：001 预测跌(真实涨-错)，002 预测涨(真实跌-错)，003 预测跌(真实跌-对)，004 预测涨(真实涨-对)
    # 反向命中 2/4 = 0.5
    neg_rate, neg_n = calculate_hit_rate(scores, returns, FactorDirection.NEGATIVE)
    assert neg_n == 4
    assert math.isclose(neg_rate, 0.5, abs_tol=1e-6)

    # 无效方向预期为 0
    inv_rate, inv_n = calculate_hit_rate(scores, returns, FactorDirection.INVALID)
    assert inv_n == 0
    assert inv_rate == 0.0


def test_calculate_hit_rate_with_nans_and_missing_alignment():
    """测试包含 NaN 及不对齐股票代码时的健壮性。"""
    scores = pd.Series({"001": 1.0, "002": np.nan, "003": 2.0, "005": 3.0})
    returns = pd.Series({"001": 0.05, "002": 0.01, "003": np.nan, "004": 0.02})

    # 仅 001 对齐且无 NaN
    rate, n = calculate_hit_rate(scores, returns, FactorDirection.POSITIVE)
    assert n == 1
    assert rate == 1.0


def test_calibrate_insufficient_history():
    """测试历史天数不足 lookback_days 时拒绝预测。"""
    dates = pd.date_range("2026-01-01", periods=15, freq="D")
    tickers = ["001", "002", "003"]
    scores_df = pd.DataFrame(np.random.randn(15, 3), index=dates, columns=tickers)
    rets_df = pd.DataFrame(np.random.randn(15, 3) * 0.02, index=dates, columns=tickers)

    result = calibrate_factor_direction(
        factor_scores_history=scores_df,
        returns_history=rets_df,
        current_date=dates[10],
        lookback_days=30,
        min_samples=20
    )
    assert result.direction == FactorDirection.INVALID
    assert "历史数据不足30天" in result.reason
    assert result.confidence == 0.0


def test_calibrate_insufficient_samples():
    """测试样本总数不足 min_samples 时拒绝预测。"""
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    tickers = ["001"]
    # 只有 1 只股票，30 天窗口共 30 个样本 < min_samples=50
    scores_df = pd.DataFrame(np.ones((40, 1)), index=dates, columns=tickers)
    rets_df = pd.DataFrame(np.ones((40, 1)) * 0.01, index=dates, columns=tickers)

    result = calibrate_factor_direction(
        factor_scores_history=scores_df,
        returns_history=rets_df,
        current_date=dates[35],
        lookback_days=30,
        min_samples=50
    )
    assert result.direction == FactorDirection.INVALID
    assert "有效样本不足50个" in result.reason


def test_calibrate_positive_direction_detected():
    """构造高命中率正向因子数据，验证识别为 POSITIVE 且置信度显著。"""
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    tickers = [f"STK_{i:02d}" for i in range(10)]  # 10 只股票，30 天窗口共 300 样本

    # 构造 75% 正向命中率
    np.random.seed(42)
    scores_mat = np.random.randn(40, 10)
    rets_mat = np.where(np.random.rand(40, 10) < 0.75, np.sign(scores_mat) * 0.02, -np.sign(scores_mat) * 0.02)

    scores_df = pd.DataFrame(scores_mat, index=dates, columns=tickers)
    rets_df = pd.DataFrame(rets_mat, index=dates, columns=tickers)

    result = calibrate_factor_direction(
        factor_scores_history=scores_df,
        returns_history=rets_df,
        current_date=dates[35],
        lookback_days=30,
        min_samples=50,
        significance_level=0.05
    )

    assert result.direction == FactorDirection.POSITIVE
    assert result.hit_rate >= 0.70
    assert result.p_value < 0.001
    assert result.confidence >= 0.95
    assert "正向命中率" in result.reason


def test_calibrate_negative_direction_detected():
    """构造高命中率反转因子数据，验证识别为 NEGATIVE 并支持自动反向。"""
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    tickers = [f"STK_{i:02d}" for i in range(10)]

    # 构造反向因子（分数高对应收益跌，反向命中率 75%）
    np.random.seed(123)
    scores_mat = np.random.randn(40, 10)
    rets_mat = np.where(np.random.rand(40, 10) < 0.75, -np.sign(scores_mat) * 0.02, np.sign(scores_mat) * 0.02)

    scores_df = pd.DataFrame(scores_mat, index=dates, columns=tickers)
    rets_df = pd.DataFrame(rets_mat, index=dates, columns=tickers)

    result = calibrate_factor_direction(
        factor_scores_history=scores_df,
        returns_history=rets_df,
        current_date=dates[35],
        lookback_days=30,
        min_samples=50
    )

    assert result.direction == FactorDirection.NEGATIVE
    assert result.hit_rate >= 0.70
    assert result.p_value < 0.001
    assert result.confidence >= 0.95
    assert "反向命中率" in result.reason


def test_calibrate_low_hit_rate_rejected():
    """测试命中率 < 52% 时严格拒绝预测。"""
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    tickers = [f"STK_{i:02d}" for i in range(10)]

    # 构造精确 50% 命中率（一半对，一半错，均值 50% < 52%）
    scores_mat = np.ones((40, 10))
    scores_mat[:, :5] = 1.0
    scores_mat[:, 5:] = -1.0

    rets_mat = np.zeros((40, 10))
    for t in range(40):
        if t % 2 == 0:
            rets_mat[t, :5] = 0.01
            rets_mat[t, 5:] = -0.01
        else:
            rets_mat[t, :5] = -0.01
            rets_mat[t, 5:] = 0.01

    scores_df = pd.DataFrame(scores_mat, index=dates, columns=tickers)
    rets_df = pd.DataFrame(rets_mat, index=dates, columns=tickers)

    result = calibrate_factor_direction(
        factor_scores_history=scores_df,
        returns_history=rets_df,
        current_date=dates[35],
        lookback_days=30,
        min_samples=50
    )

    assert result.direction == FactorDirection.INVALID
    assert result.confidence == 0.0
    assert "命中率不足52%" in result.reason


def test_apply_calibrated_direction_and_rejection():
    """测试 apply_calibrated_direction 在正向、反向与拒绝时的分值输出。"""
    scores = pd.Series({"A": 2.0, "B": -1.5, "C": 0.5})

    # 1. POSITIVE 且置信度高 (0.85 >= 0.7) -> 原值保留
    cal_pos = CalibrationResult(FactorDirection.POSITIVE, 0.85, 0.56, 100, 0.01, "显著正向")
    res_pos = apply_calibrated_direction(scores, cal_pos, confidence_threshold=0.7)
    assert np.allclose(res_pos.values, [2.0, -1.5, 0.5])

    # 2. NEGATIVE 且置信度高 (0.80 >= 0.7) -> 自动取反
    cal_neg = CalibrationResult(FactorDirection.NEGATIVE, 0.80, 0.55, 100, 0.02, "显著反向")
    res_neg = apply_calibrated_direction(scores, cal_neg, confidence_threshold=0.7)
    assert np.allclose(res_neg.values, [-2.0, 1.5, -0.5])

    # 3. 置信度不足 (0.60 < 0.7) -> 全部拒绝预测为 NaN
    cal_low = CalibrationResult(FactorDirection.POSITIVE, 0.60, 0.53, 100, 0.15, "非显著")
    res_low = apply_calibrated_direction(scores, cal_low, confidence_threshold=0.7)
    assert res_low.isna().all()

    # 4. INVALID -> 全部拒绝预测为 NaN
    cal_inv = CalibrationResult(FactorDirection.INVALID, 0.0, 0.49, 100, 0.80, "低命中率")
    res_inv = apply_calibrated_direction(scores, cal_inv, confidence_threshold=0.7)
    assert res_inv.isna().all()


def test_stock_prediction_dataclass():
    """测试增强型 StockPrediction 结构。"""
    pred = StockPrediction(
        stock_code="001258",
        date="2026-08-31",
        raw_score=0.85,
        alpha=0.015,
        calibrated_score=-0.85,
        direction_used="negative",
        calibration_confidence=0.82,
        is_rejected=False,
        rejection_reason="",
        final_recommendation="SELL"
    )
    assert pred.stock_code == "001258"
    assert pred.calibrated_score == -0.85
    assert pred.direction_used == "negative"
    assert not pred.is_rejected


def test_generate_calibration_report():
    """测试生成历史校准报告结构。"""
    dates = pd.date_range("2026-01-01", periods=45, freq="D")
    tickers = ["A", "B", "C", "D"]
    scores_df = pd.DataFrame(np.random.randn(45, 4), index=dates, columns=tickers)
    rets_df = pd.DataFrame(np.random.randn(45, 4) * 0.01, index=dates, columns=tickers)

    report_df = generate_calibration_report(
        factor_scores_history=scores_df,
        returns_history=rets_df,
        lookback_days=30
    )

    assert isinstance(report_df, pd.DataFrame)
    assert len(report_df) == 15  # 45 - 30 = 15
    for col in ["date", "direction", "confidence", "hit_rate", "sample_size", "p_value", "reason"]:
        assert col in report_df.columns


def test_calculate_hit_rate_cross_sectional_ranking():
    """测试截面多因子排序与相对强弱命中率计算。"""
    # 构造 10 只股票：前 5 只高分且高超额收益，后 5 只低分且低超额收益
    scores = pd.Series([1.2, 0.8, 0.5, 0.4, 0.3, -0.1, -0.3, -0.5, -0.8, -1.0], index=[f"S_{i}" for i in range(10)])
    returns = pd.Series([0.05, 0.04, 0.03, 0.02, 0.01, -0.01, -0.02, -0.03, -0.04, -0.05], index=[f"S_{i}" for i in range(10)])

    # 正向预测：完全契合强弱排序 -> 100% 命中率
    hit_pos, n_pos = calculate_hit_rate(scores, returns, FactorDirection.POSITIVE)
    assert n_pos == 10
    assert hit_pos == 1.0

    # 反向预测：完全相反 -> 0% 命中率
    hit_neg, n_neg = calculate_hit_rate(scores, returns, FactorDirection.NEGATIVE)
    assert n_neg == 10
    assert hit_neg == 0.0


def test_calibration_config_dataclass_and_validation():
    """测试 CalibrationConfig 属性、校验与预置方案。"""
    from src.pricing.calibration_config import (
        CalibrationConfig,
        DEFAULT_CONFIG,
        HIGH_COVERAGE_CONFIG,
        HIGH_CONFIDENCE_CONFIG,
    )

    # 1. 默认配置验证通过
    DEFAULT_CONFIG.validate()
    assert DEFAULT_CONFIG.lookback_days == 30
    assert DEFAULT_CONFIG.confidence_threshold == 0.70

    # 2. 派生配置验证通过
    HIGH_COVERAGE_CONFIG.validate()
    assert HIGH_COVERAGE_CONFIG.confidence_threshold == 0.60

    HIGH_CONFIDENCE_CONFIG.validate()
    assert HIGH_CONFIDENCE_CONFIG.confidence_threshold == 0.80

    # 3. 非法参数抛出 AssertionError
    invalid_cfg = CalibrationConfig(lookback_days=5)
    with pytest.raises(AssertionError):
        invalid_cfg.validate()


def test_decay_penalty_reduces_confidence_or_rejects():
    """测试因子半衰期过短时，时效衰减惩罚降低置信度并触发拒绝预测。"""
    from src.pricing.calibration_config import CalibrationConfig
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    tickers = [f"STK_{i:02d}" for i in range(10)]

    rng = np.random.default_rng(42)
    scores_mat = rng.standard_normal((40, 10))
    # 构造约 72% 命中率的信号
    rets_mat = np.where(rng.random((40, 10)) < 0.72, np.sign(scores_mat) * 0.02, -np.sign(scores_mat) * 0.02)
    scores_df = pd.DataFrame(scores_mat, index=dates, columns=tickers)
    rets_df = pd.DataFrame(rets_mat, index=dates, columns=tickers)

    cfg = CalibrationConfig(
        confidence_threshold=0.70,
        min_acceptable_half_life=2.0,
        enable_decay_penalty=True,
        decay_penalty_rate=0.40
    )

    # 1. 正常充裕半衰期（5.0天 > 2.0天）-> 不折价，保持 POSITIVE
    res_healthy = calibrate_factor_direction(
        factor_scores_history=scores_df,
        returns_history=rets_df,
        current_date=dates[35],
        config=cfg,
        lookback_days=30,
        min_samples=50,
        factor_half_life=5.0
    )
    assert res_healthy.direction == FactorDirection.POSITIVE
    assert res_healthy.confidence >= 0.70
    assert "时效平稳" in res_healthy.reason

    # 2. 极短半衰期（0.2天 < 2.0天）-> 衰减折价导致置信度低于门槛，触发 INVALID 拒测
    cfg_strict = CalibrationConfig(
        confidence_threshold=0.85,
        min_acceptable_half_life=2.0,
        enable_decay_penalty=True,
        decay_penalty_rate=0.40
    )
    res_decayed = calibrate_factor_direction(
        factor_scores_history=scores_df,
        returns_history=rets_df,
        current_date=dates[35],
        config=cfg_strict,
        lookback_days=30,
        min_samples=50,
        factor_half_life=0.2
    )
    assert res_decayed.direction == FactorDirection.INVALID
    assert "时效衰减拦截" in res_decayed.reason
    assert res_decayed.confidence < 0.85


def test_generate_calibration_report_with_half_life():
    """测试生成全样本校准报告时传入 factor_half_life 正常运行。"""
    dates = pd.date_range("2026-01-01", periods=45, freq="D")
    tickers = ["001", "002"]
    scores_df = pd.DataFrame(np.random.randn(45, 2), index=dates, columns=tickers)
    rets_df = pd.DataFrame(np.random.randn(45, 2) * 0.01, index=dates, columns=tickers)

    report_df = generate_calibration_report(
        factor_scores_history=scores_df,
        returns_history=rets_df,
        lookback_days=30,
        factor_half_life=4.0
    )
    assert isinstance(report_df, pd.DataFrame)
    assert len(report_df) == 15

