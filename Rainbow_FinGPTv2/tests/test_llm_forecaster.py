# -*- coding: utf-8 -*-
"""tests/test_llm_forecaster.py —— 测试 v3 LLM 直接预测引擎"""

import pytest
from unittest.mock import MagicMock
from src.llm.llm_forecaster import LLMForecaster, _clean_and_clamp_forecast, _extract_json_payload

def test_extract_json_payload_markdown_fences():
    # 测试 Markdown 代码块包裹
    md_text = """```json
{
  "return_3d_pct": 3.5,
  "return_5d_pct": 6.2,
  "up_probability_3d_pct": 72.0,
  "up_probability_5d_pct": 68.0,
  "confidence": "high",
  "rationale": "多头共振",
  "risk_factors": ["乖离过大"],
  "risk_warning": "防回落"
}
```
额外说明文字"""
    payload = _extract_json_payload(md_text)
    assert payload is not None
    assert payload["return_3d_pct"] == 3.5
    assert payload["return_5d_pct"] == 6.2
    assert payload["risk_factors"] == ["乖离过大"]

def test_extract_json_payload_dirty_or_empty():
    assert _extract_json_payload("") is None
    assert _extract_json_payload("非合法JSON文本") is None

def test_clean_and_clamp_forecast_normal():
    raw = {
        "return_3d_pct": 2.5,
        "return_5d_pct": 4.8,
        "up_probability_3d_pct": 70.0,
        "up_probability_5d_pct": 65.0,
        "confidence": "high",
        "rationale": "突破均线，多头排列",
        "risk_factors": ["均线乖离较大", "板块分化"],
        "risk_warning": "冲高回落风险"
    }
    cleaned = _clean_and_clamp_forecast(raw, "gemini-3.7-flash")
    assert cleaned["return_3d_pct"] == 2.5
    assert cleaned["return_5d_pct"] == 4.8
    assert cleaned["up_probability_3d_pct"] == 70.0
    assert cleaned["confidence"] == "high"
    assert cleaned["risk_factors"] == ["均线乖离较大", "板块分化"]
    assert cleaned["source"] == "v3_llm_direct"
    assert cleaned["model"] == "gemini-3.7-flash"

def test_clean_and_clamp_forecast_clamps_extremes():
    # 测试极端防爆限幅
    raw = {
        "return_3d_pct": 45.0,     # 应截断至 15.0
        "return_5d_pct": -60.0,    # 应截断至 -20.0
        "up_probability_3d_pct": 99.9, # 应截断至 95.0
        "up_probability_5d_pct": 1.0,  # 应截断至 5.0
        "confidence": "invalid_conf"
    }
    cleaned = _clean_and_clamp_forecast(raw, "gemini-3.7-flash")
    assert cleaned["return_3d_pct"] == 15.0
    assert cleaned["return_5d_pct"] == -20.0
    assert cleaned["up_probability_3d_pct"] == 95.0
    assert cleaned["up_probability_5d_pct"] == 5.0
    assert cleaned["confidence"] == "medium"

def test_forecaster_mock_success():
    mock_client = MagicMock()
    mock_client.is_available = True
    mock_client.complete.return_value = '```json\n{"return_3d_pct": 3.1, "return_5d_pct": 5.2, "up_probability_3d_pct": 68.0, "up_probability_5d_pct": 72.0, "confidence": "high", "rationale": "动量突破", "risk_factors": ["大盘震荡"]}\n```'
    
    forecaster = LLMForecaster(client=mock_client)
    res = forecaster.forecast_single(
        item={"code": "000021", "name": "深科技", "category": "科技"},
        latest={"close": 37.5, "change_pct": 2.1, "ma5": 36.8, "ma20": 35.5, "ma60": 34.0},
        scores={"risk_adjusted": 65.0, "technical": 70.0, "risk": 35.0}
    )
    assert res["return_3d_pct"] == 3.1
    assert res["return_5d_pct"] == 5.2
    assert res["risk_factors"] == ["大盘震荡"]
    assert res["source"] == "v3_llm_direct"

def test_forecaster_fallback_on_error():
    mock_client = MagicMock()
    mock_client.is_available = True
    mock_client.complete.side_effect = RuntimeError("Network timeout")

    forecaster = LLMForecaster(client=mock_client)
    fallback_knn = {
        "horizon_3d": {"average_return_pct": 1.5, "up_probability_pct": 55.0},
        "horizon_5d": {"average_return_pct": 2.8, "up_probability_pct": 60.0},
        "confidence": "medium"
    }
    res = forecaster.forecast_single(
        item={"code": "000021", "name": "深科技"},
        latest={"close": 37.5},
        scores={},
        fallback_knn=fallback_knn
    )
    assert res["return_3d_pct"] == 1.5
    assert res["return_5d_pct"] == 2.8
    assert res["source"] == "knn_fallback"
