"""Offline integration test for the stock analysis pipeline."""

import numpy as np
import pandas as pd

from src.analysis.indicators import compute_all_indicators, get_latest_value
from src.analysis.scoring import (
    compute_composite_score,
    compute_industry_score,
    compute_risk_score,
    compute_technical_score,
)
from src.analysis.similarity import find_similar_samples


def make_ohlcv(rows: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(20260807)
    dates = pd.date_range("2025-01-01", periods=rows, freq="B")
    close = 100 + np.cumsum(rng.normal(0.08, 1.0, rows))
    return pd.DataFrame({
        "date": dates.date,
        "open": close - 0.2,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": rng.integers(100_000, 900_000, rows),
    })


def test_offline_pipeline_produces_bounded_scores_and_forecast_contract():
    data = compute_all_indicators(make_ohlcv())
    latest = {
        "close": get_latest_value(data["close"]),
        "ma5": get_latest_value(data["ma5"]),
        "ma10": get_latest_value(data["ma10"]),
        "ma20": get_latest_value(data["ma20"]),
        "ma60": get_latest_value(data["ma60"]),
        "rsi14": get_latest_value(data["rsi14"]),
        "macd_dif": get_latest_value(data["macd_dif"]),
        "macd_dea": get_latest_value(data["macd_dea"]),
        "boll_position": get_latest_value(data["boll_position"]),
        "volume_ratio_5d": get_latest_value(data["volume_ratio_5d"]),
        "volatility_20d": get_latest_value(data["volatility_20d"]),
        "max_drawdown_60d": get_latest_value(data["max_drawdown_60d"]),
        "atr14_pct": get_latest_value(data["atr14_pct"]),
        "return_5d": get_latest_value(data["return_5d"]),
        "return_20d": get_latest_value(data["return_20d"]),
        "return_60d": get_latest_value(data["return_60d"]),
        "industry_volatility_20d": 20.0,
        "industry_rs_20d": 0.0,
    }
    all_latest = [latest.copy() for _ in range(10)]
    risk = compute_risk_score(latest, all_latest)
    technical = compute_technical_score(latest)
    industry = compute_industry_score(latest, {"relative_strength_20d_pct": 0.0}, all_latest)
    industry.pop("_reasons", None)
    similarity = find_similar_samples(data)
    composite = compute_composite_score(risk, technical, industry, similarity, [], [])

    assert 0 <= risk["score"] <= 100
    assert 0 <= technical["score"] <= 100
    assert 0 <= industry["score"] <= 100
    assert 0 <= composite["risk_adjusted"] <= 100
    assert "horizon_5d" in similarity
