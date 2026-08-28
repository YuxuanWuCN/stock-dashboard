"""tests/test_scoring_leading.py —— 领先指标进评分（005 融合 US2）单元测试。"""

from src.analysis.scoring import compute_leading_score, compute_composite_score


def _base_inputs():
    risk = {"score": 30, "level": "low", "label": "低风险"}
    tech = {"score": 60, "trend": "uptrend", "rsi14": 55, "volume_ratio_5d": 1.2}
    ind = {"score": 55, "return_5d_pct": 1.0, "return_20d_pct": 3.0,
           "return_60d_pct": 8.0, "relative_strength_20d_pct": 1.0}
    sim = {"sample_size": 30, "confidence": "medium",
           "horizon_3d": {"average_return_pct": 1.0, "up_probability_pct": 58},
           "horizon_5d": {"average_return_pct": 2.0, "up_probability_pct": 60}}
    return risk, tech, ind, sim


def test_leading_positive_reversal_scores_high():
    sig = {"momentum_metrics": {"inflection_flag": "positive_reversal", "momentum": "accelerating"},
           "data_source": "akshare"}
    r = compute_leading_score(sig)
    assert r["score"] == 80.0
    assert r["reason"] is not None


def test_leading_negative_reversal_scores_low():
    sig = {"momentum_metrics": {"inflection_flag": "negative_reversal", "momentum": "decelerating"},
           "data_source": "akshare"}
    r = compute_leading_score(sig)
    assert r["score"] == 20.0


def test_leading_synthetic_fallback_is_neutral():
    sig = {"momentum_metrics": {"inflection_flag": "positive_reversal"},
           "data_source": "synthetic_fallback"}
    r = compute_leading_score(sig)
    assert r["score"] == 50.0
    assert r["reason"] is None


def test_leading_none_is_neutral():
    r = compute_leading_score(None)
    assert r["score"] == 50.0
    assert r["reason"] is None


def test_composite_leading_affects_rank():
    """相同技术/行业/预测下，正向拐点标的综合分高于负向拐点。"""
    risk, tech, ind, sim = _base_inputs()
    pos = {"momentum_metrics": {"inflection_flag": "positive_reversal"},
           "data_source": "akshare"}
    neg = {"momentum_metrics": {"inflection_flag": "negative_reversal"},
           "data_source": "akshare"}

    r_pos = compute_composite_score(risk, tech, ind, sim, [2.0, 1.0], [60, 50], leading_signal=pos)
    r_neg = compute_composite_score(risk, tech, ind, sim, [2.0, 1.0], [60, 50], leading_signal=neg)

    assert r_pos["leading"] == 80.0
    assert r_neg["leading"] == 20.0
    assert r_pos["opportunity"] > r_neg["opportunity"]


def test_composite_backward_compatible_no_leading():
    """不传 leading_signal 时向后兼容（中性 50，不报错）。"""
    risk, tech, ind, sim = _base_inputs()
    r = compute_composite_score(risk, tech, ind, sim, [2.0, 1.0], [60, 50])
    assert r["leading"] == 50.0
    assert 0 <= r["risk_adjusted"] <= 100
