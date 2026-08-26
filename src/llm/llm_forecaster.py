# -*- coding: utf-8 -*-
"""src/llm/llm_forecaster.py —— v3 版本直接 LLM 量化预测引擎

基于 Google Gemini 3.7 Flash（OpenAI 兼容接口），综合多因子打分、K线量价特征、
题材动量与领先指标，直接输出 3日/5日 预期收益率、看涨置信胜率与研判依据。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

import numpy as np

from .llm_client import LLMClient

logger = logging.getLogger("stock-dashboard.llm.forecaster")

# 预测专用系统提示词
_FORECASTER_SYSTEM_PROMPT = (
    "你是一个专业的量化策略师与多因子资产定价专家。\n"
    "你的任务是根据提供的个股技术面、多因子评分、量价特征与行业题材数据，直接给出未来 3 个交易日（3d）和 5 个交易日（5d）的量化预期走势预测。\n"
    "要求：\n"
    "1. 预测必须客观、严谨，结合均线偏离、量比与动量特征。\n"
    "2. 输出必须是严格的单层合法 JSON 格式，不要包含 Markdown 标记或任何其他多余文本。\n"
    "3. JSON 字段必须包含：\n"
    '   - "return_3d_pct": float（未来 3 日预期收益率百分比，如 2.5 或 -1.8）\n'
    '   - "return_5d_pct": float（未来 5 日预期收益率百分比，如 4.2 或 -2.5）\n'
    '   - "up_probability_3d_pct": float（3 日上涨置信胜率，5.0 到 95.0 之间）\n'
    '   - "up_probability_5d_pct": float（5 日上涨置信胜率，5.0 到 95.0 之间）\n'
    '   - "confidence": string（"high" | "medium" | "low"）\n'
    '   - "rationale": string（中文简短研判依据，50字以内）\n'
    '   - "risk_factors": list[str]（主要潜在风险因素列表，如 ["均线乖离过大", "板块资金分化"]）\n'
    '   - "risk_warning": string（主要潜在风险提示，30字以内）\n'
)


def _build_forecast_prompt(
    item: dict[str, Any],
    latest: dict[str, Any],
    scores: dict[str, Any],
    leading: Optional[dict[str, Any]] = None,
    sentiment: Optional[dict[str, Any]] = None,
) -> str:
    """构建用于大模型推断的特征提示词。"""
    code = item.get("code", "")
    name = item.get("name", "")
    category = item.get("category", "通用")
    close = latest.get("close", 0.0) or 0.0
    change_pct = latest.get("change_pct", 0.0) or 0.0
    ma5 = latest.get("ma5", close) or close
    ma20 = latest.get("ma20", close) or close
    ma60 = latest.get("ma60", close) or close

    dev_ma5 = round((close - ma5) / ma5 * 100, 2) if ma5 else 0.0
    dev_ma20 = round((close - ma20) / ma20 * 100, 2) if ma20 else 0.0
    dev_ma60 = round((close - ma60) / ma60 * 100, 2) if ma60 else 0.0
    rsi = latest.get("rsi14", 50.0) or 50.0
    ret_5d = latest.get("return_5d_pct") if latest.get("return_5d_pct") is not None else latest.get("return_5d", 0.0)
    ret_20d = latest.get("return_20d_pct") if latest.get("return_20d_pct") is not None else latest.get("return_20d", 0.0)
    vol_ratio = latest.get("volume_ratio_5d", 1.0) or 1.0
    atr_pct = latest.get("atr14_pct", 3.0) or 3.0
    macd_hist = latest.get("macd_hist", 0.0) or 0.0
    trend = latest.get("trend", "震荡")

    risk_adj = scores.get("risk_adjusted", 50.0) or 50.0
    tech_score = scores.get("technical", 50.0) or 50.0
    risk_score = scores.get("risk", 50.0) or 50.0

    lead_info = "无"
    if leading and leading.get("data_source") == "akshare":
        lead_info = f"{leading.get('source_name', '')} (动能: {leading.get('momentum_metrics', {}).get('momentum', '中性')})"

    senti_info = "中性"
    if sentiment:
        senti_info = sentiment.get("label", "中性")

    prompt = (
        f"标的信息：{name} ({code})，所属题材：{category}\n"
        f"当前行情：最新价 {close:.2f} 元，当日涨跌幅 {change_pct:+.2f}%，技术趋势：{trend}\n"
        f"技术指标：近5日涨幅 {ret_5d:+.2f}%，近20日涨幅 {ret_20d:+.2f}%，5日量比 {vol_ratio:.2f}，RSI(14) {rsi:.1f}，ATR波动率 {atr_pct:.2f}%，MACD柱 {macd_hist:+.2f}\n"
        f"均线乖离：MA5偏离 {dev_ma5:+.2f}%，MA20偏离 {dev_ma20:+.2f}%，MA60偏离 {dev_ma60:+.2f}%\n"
        f"多因子评分：综合风险收益分 {risk_adj:.1f}/100，技术分 {tech_score:.1f}/100，风险分 {risk_score:.1f}/100\n"
        f"舆情与前沿：市场情绪 {senti_info}，行业领先指标 {lead_info}\n\n"
        f"请基于上述多维量化特征，预测未来 3 日与 5 日的预期收益率（%）、上涨胜率（%）、核心研判依据与风险因素，并输出严格 JSON。"
    )
    return prompt


def _clean_and_clamp_forecast(raw_data: dict[str, Any], model_name: str) -> dict[str, Any]:
    """清洗并施加安全防爆限幅。"""
    ret_3d = float(raw_data.get("return_3d_pct", 0.0))
    ret_5d = float(raw_data.get("return_5d_pct", 0.0))
    up_3d = float(raw_data.get("up_probability_3d_pct", 50.0))
    up_5d = float(raw_data.get("up_probability_5d_pct", 50.0))

    # 安全限幅：3d [-15%, +15%], 5d [-20%, +20%], 概率 [5%, 95%]
    ret_3d_clamped = round(float(np.clip(ret_3d, -15.0, 15.0)), 2)
    ret_5d_clamped = round(float(np.clip(ret_5d, -20.0, 20.0)), 2)
    up_3d_clamped = round(float(np.clip(up_3d, 5.0, 95.0)), 1)
    up_5d_clamped = round(float(np.clip(up_5d, 5.0, 95.0)), 1)

    confidence = str(raw_data.get("confidence", "medium")).lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    rationale = str(raw_data.get("rationale", "大模型多因子综合推断"))[:100]
    
    raw_risks = raw_data.get("risk_factors")
    if isinstance(raw_risks, list):
        risk_factors = [str(r)[:40] for r in raw_risks if r][:4]
    else:
        risk_factors = ["注意短线波动与大盘风格切换"]

    risk_warning = str(raw_data.get("risk_warning", risk_factors[0] if risk_factors else "注意短线波动"))[:60]

    return {
        "return_3d_pct": ret_3d_clamped,
        "return_5d_pct": ret_5d_clamped,
        "up_probability_3d_pct": up_3d_clamped,
        "up_probability_5d_pct": up_5d_clamped,
        "confidence": confidence,
        "rationale": rationale,
        "risk_factors": risk_factors,
        "risk_warning": risk_warning,
        "source": "v3_llm_direct",
        "model": model_name,
    }


def _extract_json_payload(raw_text: str) -> Optional[dict]:
    """鲁棒提取大模型返回的 JSON 对象。"""
    if not raw_text:
        return None
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        chunk = text[start:end+1]
        try:
            return json.loads(chunk)
        except Exception:
            pass

    if start != -1:
        for p in range(len(text) - 1, start, -1):
            if text[p] == "}":
                try:
                    return json.loads(text[start:p+1])
                except Exception:
                    continue
    return None


class LLMForecaster:
    """v3 版本的直接 LLM 预测器。"""

    def __init__(self, client: Optional[LLMClient] = None) -> None:
        self.client = client or LLMClient()
        self.model_name = getattr(self.client, "model", "gemini-3.7-flash")

    def forecast_single(
        self,
        item: dict[str, Any],
        latest: dict[str, Any],
        scores: dict[str, Any],
        leading: Optional[dict[str, Any]] = None,
        fallback_knn: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """对单只股票执行 LLM 直接预测。若大模型不可用或解析失败，安全回退至 fallback_knn。"""
        if not self.client.is_available:
            logger.info("LLM 不可用，使用统计回退预测")
            return self._build_fallback(fallback_knn)

        user_prompt = _build_forecast_prompt(item, latest, scores, leading)
        try:
            raw_text = self.client.complete(
                system_prompt=_FORECASTER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=300,
                temperature=0.2,
            )
            payload = _extract_json_payload(raw_text)
            if payload and isinstance(payload, dict):
                return _clean_and_clamp_forecast(payload, self.model_name)
            else:
                logger.warning("LLM 未返回有效 JSON 格式: %s", raw_text[:100])
                return self._build_fallback(fallback_knn)
        except Exception as exc:
            logger.warning("LLM 预测调用异常: %s，执行安全降级", exc)
            return self._build_fallback(fallback_knn)

    def _build_fallback(self, fallback_knn: Optional[dict[str, Any]]) -> dict[str, Any]:
        """构建安全回退结果。"""
        if fallback_knn:
            h3 = fallback_knn.get("horizon_3d", {})
            h5 = fallback_knn.get("horizon_5d", {})
            r3 = h3.get("average_return_pct")
            r5 = h5.get("average_return_pct")
            u3 = h3.get("up_probability_pct")
            u5 = h5.get("up_probability_pct")
            return {
                "return_3d_pct": r3,
                "return_5d_pct": r5,
                "up_probability_3d_pct": u3,
                "up_probability_5d_pct": u5,
                "confidence": fallback_knn.get("confidence", "low"),
                "rationale": "基于历史量价形态 KNN 相似走势统计推断",
                "risk_warning": "样本统计仅供参考，注意防范市场系统性风险",
                "source": "knn_fallback",
                "model": "knn_v1",
            }
        return {
            "return_3d_pct": 0.0,
            "return_5d_pct": 0.0,
            "up_probability_3d_pct": 50.0,
            "up_probability_5d_pct": 50.0,
            "confidence": "low",
            "rationale": "暂无足够预测样本",
            "risk_warning": "请结合技术均线与大盘走势综合研判",
            "source": "default_fallback",
            "model": "rule_v1",
        }
