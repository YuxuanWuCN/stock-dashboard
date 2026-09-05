"""src/analysis/scoring_v3.py —— 3.0 前沿信息主导评分引擎（彻底纠正后视镜偏差）

核心设计理念（彻底落实师叔 claw-quant 与老师指导）：
1. 【前沿信息主导】：前沿供需拐点（现货报价、海关出口、订单动能）权重占机会分 45%；
2. 【统计胜率结合】：KNN 相似走势 5 日预期收益与上涨概率占 30%；
3. 【技术形态辅助】：均线与量价作为择时与支撑位确认占 25%；
4. 【财报退为排雷门禁】：传统财务基本面不再给正向加分（彻底摒弃滞后 1~3 个月的财报后视镜），
   仅作为“安全底线门禁”（资不抵债/严重亏损一票否决淘汰）；
5. 【风险动态调整】：沿用 20 日波动率与 60 日最大回撤进行风险扣减。
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from .config import RISK_PENALTY_FACTOR
from .scoring import _clamp, _percentile_rank

# 3.0 机会分权重体系：彻底以前沿信息为主导
OPPORTUNITY_WEIGHTS_V3 = {
    "leading_score":   0.45,   # 前沿供需拐点（领先指标）
    "forecast_score":  0.30,   # KNN 历史统计收益与上涨概率
    "technical_score": 0.25,   # 技术形态与支撑确认（择时）
}

# 3.0 领先指标分档（遵循 Gu, Kelly, Xiu 2020 截面不确定性收缩与贝叶斯折价原理）
LEADING_SCORE_CONFIG_V3 = {
    "positive_reversal":  90.0,   # 领先指标触底反转（供需强烈向上）
    "accelerating":       75.0,   # 领先指标动能加速（订单与现货走强）
    "neutral":            50.0,   # 真实高频数据中性（无明显趋势信号）
    "synthetic_fallback": 20.0,   # 贝叶斯不确定性折价（缺失高频前沿数据惩罚，彻底阻断中性套利）
    "decelerating":       30.0,   # 领先指标动能减速
    "negative_reversal":  10.0,   # 领先指标见顶回落（供需向下拐点，风险提示）
}


def compute_leading_score_v3(leading_signal: Optional[dict] = None) -> dict:
    """计算 3.0 领先指标分 (0-100)。

    根据 Harvey-Liu (2016) 与 Gu-Kelly-Xiu (2020) 截面严谨性规范：
    - 拥有真实高频订单/现货数据且中性的标的赋 50.0 分；
    - 合成降级 / 缺失 / 未知来源的数据严格执行贝叶斯不确定性惩罚，折价至 20.0 分，
      彻底根除缺失数据标的（如恒生银行）凭借中性分虚假冲入全市场 Top 2 的数值倒错漏洞。
    """
    if not leading_signal:
        return {
            "score": LEADING_SCORE_CONFIG_V3["synthetic_fallback"],
            "inflection_flag": "none",
            "momentum": "flat",
            "data_source": "none",
            "reason": "缺失高频前沿数据（贝叶斯不确定性折价惩罚）",
            "uncertainty_discounted": True,
        }

    mm = leading_signal.get("momentum_metrics", {}) or {}
    inflection = mm.get("inflection_flag", "none")
    momentum = mm.get("momentum", "flat")
    data_source = leading_signal.get("data_source", "unknown")

    # 合成降级 / 缺失数据执行贝叶斯不确定性惩罚（Option A 规范）
    if data_source in ("synthetic_fallback", "none", "unknown", None, ""):
        return {
            "score": LEADING_SCORE_CONFIG_V3["synthetic_fallback"],
            "inflection_flag": inflection,
            "momentum": momentum,
            "data_source": data_source,
            "reason": "高频前沿数据缺失或降级（贝叶斯不确定性折价惩罚）",
            "uncertainty_discounted": True,
        }

    if inflection == "positive_reversal":
        return {
            "score": LEADING_SCORE_CONFIG_V3["positive_reversal"],
            "inflection_flag": inflection,
            "momentum": momentum,
            "data_source": data_source,
            "reason": "前沿领先指标触底反转（供需强劲向上拐点）",
        }
    if inflection == "negative_reversal":
        return {
            "score": LEADING_SCORE_CONFIG_V3["negative_reversal"],
            "inflection_flag": inflection,
            "momentum": momentum,
            "data_source": data_source,
            "reason": "前沿领先指标见顶回落（供需向下拐点，风险提示）",
        }
    if momentum == "accelerating":
        return {
            "score": LEADING_SCORE_CONFIG_V3["accelerating"],
            "inflection_flag": inflection,
            "momentum": momentum,
            "data_source": data_source,
            "reason": "前沿领先指标动能持续加速（现货与订单处于景气扩张期）",
        }
    if momentum == "decelerating":
        return {
            "score": LEADING_SCORE_CONFIG_V3["decelerating"],
            "inflection_flag": inflection,
            "momentum": momentum,
            "data_source": data_source,
            "reason": "前沿领先指标动能边际减速",
        }

    return {
        "score": LEADING_SCORE_CONFIG_V3["neutral"],
        "inflection_flag": inflection,
        "momentum": momentum,
        "data_source": data_source,
        "reason": None,
    }


def fundamental_safety_gate(fundamental: Optional[dict]) -> Tuple[bool, Optional[str]]:
    """3.0 传统基本面排雷门禁（一票否决制）。

    仅过滤极端财务恶化、资不抵债或造假嫌疑标的；
    通过门禁的标的不获得任何额外加分，防止历史财报后视镜扭曲前沿信号。
    """
    if not fundamental or not isinstance(fundamental, dict):
        return True, None  # 无财报数据（如 ETF/境外标的）默认放行

    # 1. 检查是否存在严重预警或极端低分（例如财务极度恶化）
    score = fundamental.get("score")
    if score is not None and score < 15.0:
        return False, "财务排雷未通过：历史财务指标处于极度恶化区间（评分 < 15）"

    # 2. 检查杠杆与偿债风险（若有细分指标）
    metrics = fundamental.get("metrics", {}) or {}
    debt_ratio = metrics.get("debt_to_assets") or metrics.get("asset_liability_ratio")
    if debt_ratio is not None and float(debt_ratio) > 95.0:
        return False, f"财务排雷未通过：资产负债率高危（{debt_ratio}% > 95%）"

    return True, None


def compute_composite_score_v3(
    risk_result: dict,
    technical_result: dict,
    industry_result: dict,
    similarity_result: dict,
    all_forecast_returns_5d: list,
    all_up_probabilities_5d: list,
    leading_signal: Optional[dict] = None,
    fundamental: Optional[dict] = None,
) -> dict:
    """计算 3.0 综合评分。

    返回:
    {
        "risk_adjusted": float,
        "opportunity": float,
        "leading": float,
        "forecast": float,
        "technical": float,
        "risk": float,
        "gate_passed": bool,
        "reject_reason": Optional[str],
        "leading_reason": Optional[str],
        "engine_version": "v3.0-leading"
    }
    """
    risk_score = float(risk_result.get("score", 50.0))
    tech_score = float(technical_result.get("score", 50.0))

    # 1. 执行财报安全门禁
    gate_passed, reject_reason = fundamental_safety_gate(fundamental)
    if not gate_passed:
        return {
            "risk_adjusted": 0.0,
            "opportunity": 0.0,
            "leading": 0.0,
            "forecast": 0.0,
            "technical": tech_score,
            "risk": risk_score,
            "gate_passed": False,
            "reject_reason": reject_reason,
            "leading_reason": None,
            "engine_version": "v3.0-leading",
        }

    # 2. 计算前沿领先分
    leading_res = compute_leading_score_v3(leading_signal)
    leading_score = leading_res["score"]

    # 3. 计算 KNN 统计胜率分
    forecast_5d = similarity_result.get("horizon_5d", {}).get("average_return_pct")
    up_prob_5d = similarity_result.get("horizon_5d", {}).get("up_probability_pct")

    fc_percentile = 50.0
    if forecast_5d is not None and all_forecast_returns_5d:
        fc_percentile = _percentile_rank(all_forecast_returns_5d, forecast_5d, higher_is_better=True)

    up_component = up_prob_5d if up_prob_5d is not None else 50.0
    forecast_score = 0.6 * fc_percentile + 0.4 * up_component

    # 4. 3.0 机会分（前沿 45% + 预测 30% + 技术 25%）
    opportunity = (
        OPPORTUNITY_WEIGHTS_V3["leading_score"] * leading_score
        + OPPORTUNITY_WEIGHTS_V3["forecast_score"] * forecast_score
        + OPPORTUNITY_WEIGHTS_V3["technical_score"] * tech_score
    )

    # 5. 风险调整（波动率与回撤惩罚）
    risk_adjusted = opportunity * (1.0 - RISK_PENALTY_FACTOR * risk_score / 100.0)
    risk_adjusted = _clamp(risk_adjusted)

    return {
        "risk_adjusted": risk_adjusted,
        "opportunity": round(opportunity, 1),
        "leading": round(leading_score, 1),
        "forecast": round(forecast_score, 1),
        "technical": round(tech_score, 1),
        "risk": round(risk_score, 1),
        "gate_passed": True,
        "reject_reason": None,
        "leading_reason": leading_res.get("reason"),
        "engine_version": "v3.0-leading",
    }
