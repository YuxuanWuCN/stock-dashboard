"""tests/test_scoring_v3.py —— 3.0 前沿主导评分引擎单元测试。"""

import pytest
from src.analysis.scoring_v3 import (
    compute_composite_score_v3,
    compute_leading_score_v3,
    fundamental_safety_gate,
)


def _base_inputs():
    risk = {"score": 20, "level": "low", "label": "低风险"}
    tech = {"score": 70, "trend": "uptrend"}
    ind = {"score": 60}
    sim = {
        "horizon_5d": {
            "average_return_pct": 3.0,
            "up_probability_pct": 65.0,
        },
        "sample_size": 30,
    }
    return risk, tech, ind, sim


def test_leading_v3_positive_reversal_huge_boost():
    """前沿触底反转获得 90 分高分，并在机会分中占 45% 权重。"""
    risk, tech, ind, sim = _base_inputs()
    sig_pos = {
        "momentum_metrics": {"inflection_flag": "positive_reversal"},
        "data_source": "akshare",
    }
    sig_neutral = {
        "momentum_metrics": {"inflection_flag": "none"},
        "data_source": "synthetic_fallback",
    }
    r_pos = compute_composite_score_v3(risk, tech, ind, sim, [3.0, 1.0], [65.0, 50.0], leading_signal=sig_pos)
    r_neu = compute_composite_score_v3(risk, tech, ind, sim, [3.0, 1.0], [65.0, 50.0], leading_signal=sig_neutral)

    assert r_pos["leading"] == 90.0
    assert r_neu["leading"] == 50.0
    # 差 40 分的前沿分在 45% 权重下带来 18 分机会分差
    assert r_pos["opportunity"] - r_neu["opportunity"] == pytest.approx(18.0, abs=0.5)
    assert r_pos["risk_adjusted"] > r_neu["risk_adjusted"]


def test_leading_v3_synthetic_fallback_is_strict_neutral():
    """合成降级数据严格判为 50 中性，绝不给假数据打高分。"""
    sig_synthetic = {
        "momentum_metrics": {"inflection_flag": "positive_reversal"},
        "data_source": "synthetic_fallback",
    }
    res = compute_leading_score_v3(sig_synthetic)
    assert res["score"] == 50.0
    assert res["reason"] is None


def test_fundamental_safety_gate_rejects_distress():
    """财务极度恶化标的被安全门禁拦截，3.0 分数直接置 0。"""
    risk, tech, ind, sim = _base_inputs()
    distressed_fund = {"score": 10.0}
    r = compute_composite_score_v3(risk, tech, ind, sim, [3.0], [65.0], fundamental=distressed_fund)
    assert r["gate_passed"] is False
    assert r["risk_adjusted"] == 0.0
    assert "财务排雷未通过" in r["reject_reason"]


def test_fundamental_safety_gate_passes_without_adding_points():
    """正常基本面通过门禁，但不额外累加分数（避免财报后视镜偏差）。"""
    risk, tech, ind, sim = _base_inputs()
    good_fund = {"score": 85.0}
    no_fund = None

    r_good = compute_composite_score_v3(risk, tech, ind, sim, [3.0], [65.0], fundamental=good_fund)
    r_none = compute_composite_score_v3(risk, tech, ind, sim, [3.0], [65.0], fundamental=no_fund)

    assert r_good["gate_passed"] is True
    assert r_good["risk_adjusted"] == r_none["risk_adjusted"]
    assert r_good["opportunity"] == r_none["opportunity"]
