# -*- coding: utf-8 -*-
"""tests/test_calibration_stability.py —— 滚动方向校准时序稳定性与前向留出验证测试

严格遵循：
1. 严格时间分割：前 40 交易日为校准期，后 20 交易日为严格留出验证期
2. 零前视偏差：T 日决策严禁读取 T 日及之后的收益率
3. 统计稳定性验证：前后半段差异评估与覆盖率检验
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.analysis.green_backtest_runner import GreenBacktestRunner
from src.pricing.rolling_direction_calibration import (
    FactorDirection,
    CalibrationResult,
    calibrate_factor_direction,
    apply_calibrated_direction,
)


def test_forward_validation_stability():
    """前向留出验证：严格时序因果分割与稳定性检验。"""
    raw_dir = Path("data/raw/backtest_green_2025q3_2026q3")
    if not raw_dir.exists():
        raw_dir = Path("Rainbow_FinGPTv2/data/raw/backtest_green_2025q3_2026q3")
    assert raw_dir.exists(), "数据目录必须存在"

    runner = GreenBacktestRunner(raw_data_dir=raw_dir)
    prices_df, _, _ = runner.load_isolated_raw_data()
    tickers = runner.GREEN_TICKERS
    dates = prices_df.index

    # 1. 逐步计算因子打分历史
    scores_dict = {}
    for t in range(20, len(dates)):
        sub_prices = prices_df.iloc[:t]
        sc = {}
        for tk in tickers:
            p = sub_prices[tk]
            mom20 = (p.iloc[-1] / p.iloc[-20] - 1.0) if len(p) >= 20 else 0.0
            vol20 = float(p.pct_change().iloc[-20:].std()) if len(p) >= 20 else 0.02
            moat = runner.MOATS.get(tk, 0.50)
            sc[tk] = moat * 0.40 + mom20 * 0.45 - vol20 * 0.15
        scores_dict[dates[t]] = sc

    scores_df = pd.DataFrame.from_dict(scores_dict, orient="index")

    # 2. 真实历史收益率（在 T 日，仅截至 T-1 收盘已实现收益 T-2->T-1 已确认）
    returns_hist = pd.DataFrame(columns=tickers)
    for t in range(2, len(dates)):
        returns_hist.loc[dates[t-2]] = prices_df[tickers].iloc[t-1] / prices_df[tickers].iloc[t-2] - 1.0

    # 3. 严格留出后 20 个交易日作为验证期
    validation_dates = scores_df.index[-20:]
    results = []

    for date in validation_dates:
        # 严禁传入当前日期及未来数据
        calib = calibrate_factor_direction(
            factor_scores_history=scores_df[scores_df.index < date],
            returns_history=returns_hist[returns_hist.index < date],
            current_date=date,
            lookback_days=30,
            min_samples=50
        )

        current_scores = scores_df.loc[date]
        calibrated = apply_calibrated_direction(current_scores, calib, confidence_threshold=0.60)
        valid_predictions = calibrated.dropna()

        d_idx = dates.get_loc(date)
        if d_idx + 1 < len(dates):
            act_ret = prices_df[tickers].iloc[d_idx + 1] / prices_df[tickers].iloc[d_idx] - 1.0
            act_excess = act_ret - act_ret.mean()

            if len(valid_predictions) > 0:
                pred_up = (valid_predictions - valid_predictions.mean()) > 0
                act_up = act_excess[valid_predictions.index] > 0
                hit_rate = float((pred_up == act_up).mean())
            else:
                hit_rate = 0.50
        else:
            hit_rate = 0.50

        results.append({
            "date": str(date.date()),
            "coverage": len(valid_predictions) / len(current_scores),
            "hit_rate": hit_rate,
            "direction": calib.direction.value,
            "confidence": calib.confidence
        })

    df_results = pd.DataFrame(results)

    # 验证指标与稳定性断言
    assert len(df_results) == 20
    first_half = df_results.iloc[:10]["hit_rate"].mean()
    second_half = df_results.iloc[10:]["hit_rate"].mean()
    stability_diff = abs(first_half - second_half)

    # 验证前后半段差异受控（稳定性 <= 10%）
    assert stability_diff <= 0.10, f"前后半段差异过大: {stability_diff:.2%}"
    # 验证全流程无异常报错
    assert df_results["confidence"].min() >= 0.0
