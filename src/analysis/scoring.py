# analysis/scoring.py —— 风险分、技术分、行业分、综合评分
#
# 所有分数 0-100，透明规则，输出 reasons。

from typing import Optional

import numpy as np
import pandas as pd

from .config import (
    RISK_WEIGHTS,
    RISK_LEVELS,
    OPPORTUNITY_WEIGHTS,
    RISK_PENALTY_FACTOR,
    SCORE_MIN,
    SCORE_MAX,
    TECHNICAL_SCORE_CONFIG as TECH,
    INDUSTRY_SCORE_CONFIG as IND,
    MAX_REASONS,
)


# ============================================================
# 1. 辅助函数
# ============================================================

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, round(value, 1)))


def _percentile_rank(values: list, target: float, higher_is_better: bool = True) -> float:
    """计算 target 在一组值中的百分位（0-100）。"""
    clean = [v for v in values if v is not None and not np.isnan(v)]
    if not clean or len(clean) < 2:
        return 50.0
    arr = np.array(clean)
    if higher_is_better:
        rank = (arr < target).sum() / len(arr) * 100.0
    else:
        rank = (arr > target).sum() / len(arr) * 100.0
    return round(float(rank), 1)


def _sub_score_percentile(
    value: float, all_values: list, invert: bool = False
) -> float:
    """
    将因子值转换为其在所有标的中百分位（已经是 0-100）。
    invert=True 表示值越低越好（如波动率、回撤）。
    """
    clean = [v for v in all_values if v is not None and not np.isnan(v)]
    if not clean or len(clean) < 2:
        return 50.0

    arr = np.array(clean)
    # 用经验分布
    if invert:
        # 越低分越好 → rank 越高
        rank = (arr > value).sum()
    else:
        rank = (arr < value).sum()

    pct = rank / len(arr) * 100.0
    return round(float(pct), 1)


def get_risk_level(score: float) -> tuple[str, str]:
    """根据风险分数返回 (level, label)。"""
    if score <= RISK_LEVELS["low"][1]:
        return "low", "低风险"
    elif score >= RISK_LEVELS["high"][0]:
        return "high", "高风险"
    else:
        return "medium", "中等风险"


# ============================================================
# 2. 风险分数
# ============================================================

def compute_risk_score(
    latest: dict,          # 单只股票最新指标值
    all_stocks_data: list,  # 所有股票的 latest dict 列表
) -> dict:
    """
    计算风险分数。
    latest 中至少包含: volatility_20d, max_drawdown_60d, atr14_pct, volume_ratio_5d

    返回:
    {
        "score": float,
        "level": "low"|"medium"|"high",
        "label": "低风险"|"中等风险"|"高风险",
        "annualized_volatility_20d_pct": float,
        "max_drawdown_60d_pct": float,
        "atr14_pct": float,
        "factors": [{"name": str, "score": float, "value": float}, ...]
    }
    """
    factors = []

    # 收集所有标的的各因子值（用于百分位转换）
    all_vol = [s.get("volatility_20d") for s in all_stocks_data]
    all_mdd = [s.get("max_drawdown_60d") for s in all_stocks_data]
    all_atr = [s.get("atr14_pct") for s in all_stocks_data]
    all_vratio = [s.get("volume_ratio_5d") for s in all_stocks_data]
    all_ind_vol = [s.get("industry_volatility_20d") for s in all_stocks_data]

    vol = latest.get("volatility_20d")
    mdd = latest.get("max_drawdown_60d")
    atr_pct = latest.get("atr14_pct")
    vr = latest.get("volume_ratio_5d")

    # 1. 波动率因子 (30%)
    if vol is not None:
        vol_sub = _sub_score_percentile(vol, all_vol, invert=True)
    else:
        vol_sub = 50.0
    factors.append({"name": "20日波动率", "score": round(vol_sub, 1), "value": round(vol, 2) if vol else None})

    # 2. 最大回撤因子 (25%)
    if mdd is not None:
        # max_drawdown 是负数，越小（越负）风险越大
        mdd_sub = _sub_score_percentile(abs(mdd), [abs(v) if v else 0 for v in all_mdd], invert=True)
    else:
        mdd_sub = 50.0
    factors.append({"name": "60日最大回撤", "score": round(mdd_sub, 1), "value": round(mdd, 2) if mdd else None})

    # 3. ATR 百分比因子 (20%)
    if atr_pct is not None:
        atr_sub = _sub_score_percentile(atr_pct, all_atr, invert=True)
    else:
        atr_sub = 50.0
    factors.append({"name": "ATR百分比", "score": round(atr_sub, 1), "value": round(atr_pct, 2) if atr_pct else None})

    # 4. 量价异常因子 (10%)
    if vr is not None:
        # 量比偏离 1.0 过多（无论方向）可能表示异常
        vr_deviation = abs(vr - 1.0) if vr else 0
        all_vr_dev = [abs(v - 1.0) if v else 0 for v in all_vratio]
        vr_sub = _sub_score_percentile(vr_deviation, all_vr_dev, invert=True)
    else:
        vr_sub = 50.0
    factors.append({"name": "量价异常", "score": round(vr_sub, 1), "value": round(vr, 2) if vr else None})

    # 5. 行业风险因子 (15%)
    ind_vol = latest.get("industry_volatility_20d")
    if ind_vol is not None:
        ind_sub = _sub_score_percentile(ind_vol, all_ind_vol, invert=True)
    else:
        ind_sub = 50.0
    factors.append({"name": "行业波动", "score": round(ind_sub, 1), "value": round(ind_vol, 2) if ind_vol else None})

    # 加权
    total_score = (
        RISK_WEIGHTS["volatility_20d"] * vol_sub
        + RISK_WEIGHTS["max_drawdown_60d"] * mdd_sub
        + RISK_WEIGHTS["atr_pct"] * atr_sub
        + RISK_WEIGHTS["volume_anomaly"] * vr_sub
        + RISK_WEIGHTS["industry_risk"] * ind_sub
    )

    score = _clamp(total_score)
    level, label = get_risk_level(score)

    return {
        "score": score,
        "level": level,
        "label": label,
        "annualized_volatility_20d_pct": round(vol, 2) if vol else None,
        "max_drawdown_60d_pct": round(mdd, 2) if mdd else None,
        "atr14_pct": round(atr_pct, 2) if atr_pct else None,
        "factors": factors,
    }


# ============================================================
# 3. 技术分数
# ============================================================

def compute_technical_score(latest: dict) -> dict:
    """
    计算技术分数 (0-100)，基于透明规则。

    latest 至少包含:
    close, ma5, ma10, ma20, ma60, rsi14, macd_dif, macd_dea,
    boll_position, volume_ratio_5d, return_5d, return_20d
    """
    score = TECH["baseline"]
    reasons = []

    close = latest.get("close")
    ma5 = latest.get("ma5")
    ma10 = latest.get("ma10")
    ma20 = latest.get("ma20")
    ma60 = latest.get("ma60")
    rsi = latest.get("rsi14")
    macd_dif = latest.get("macd_dif")
    macd_dea = latest.get("macd_dea")
    boll_pos = latest.get("boll_position")
    vr_5d = latest.get("volume_ratio_5d")
    ret_5d = latest.get("return_5d")
    ret_20d = latest.get("return_20d")

    # 1. 均线多头排列
    if all(v is not None for v in [ma5, ma10, ma20, ma60]):
        if ma5 > ma10 > ma20 > ma60:
            score += TECH["ma_bullish_bonus"]
            reasons.append({
                "type": "positive",
                "title": "均线多头排列",
                "detail": "MA5 > MA10 > MA20 > MA60，强势多头结构。",
                "contribution": TECH["ma_bullish_bonus"],
            })

    # 2. MA20 向上趋势（检查 5 日前对比）
    if close is not None and ma20 is not None and close > ma20:
        score += TECH["ma20_uptrend_bonus"]
        reasons.append({
            "type": "positive",
            "title": "中短期趋势向上",
            "detail": "收盘价位于20日均线上方。",
            "contribution": TECH["ma20_uptrend_bonus"],
        })

    # 3. RSI 中性区间
    if rsi is not None:
        if 40 <= rsi <= 60:
            score += TECH["rsi_neutral_bonus"]
            reasons.append({
                "type": "positive",
                "title": "RSI处于中性区间",
                "detail": f"RSI14={rsi:.1f}，未超买超卖。",
                "contribution": TECH["rsi_neutral_bonus"],
            })
        elif rsi > 80:
            score -= 5.0
            reasons.append({
                "type": "warning",
                "title": "RSI超买",
                "detail": f"RSI14={rsi:.1f}，处于超买区域。",
                "contribution": -5.0,
            })
        elif rsi < 20:
            score -= 5.0
            reasons.append({
                "type": "warning",
                "title": "RSI超卖",
                "detail": f"RSI14={rsi:.1f}，处于超卖区域。",
                "contribution": -5.0,
            })

    # 4. 布林带位置
    if boll_pos is not None:
        if 0.3 < boll_pos < 0.7:
            score += TECH["boll_upper_bonus"]
            reasons.append({
                "type": "positive",
                "title": "布林带位置适中",
                "detail": "价格位于布林带中间区域。",
                "contribution": TECH["boll_upper_bonus"],
            })
        elif boll_pos < 0.1:
            score -= 8.0
            reasons.append({
                "type": "warning",
                "title": "接近布林下轨",
                "detail": "价格接近布林带下轨，短期偏弱。",
                "contribution": -8.0,
            })

    # 5. 量价配合
    if vr_5d is not None:
        if 1.1 <= vr_5d <= 1.5 and ret_5d is not None and ret_5d > 0:
            score += TECH["volume_price_bonus"]
            reasons.append({
                "type": "positive",
                "title": "量价配合",
                "detail": f"近5日量能为前期{vr_5d:.2f}倍，放量上涨。",
                "contribution": TECH["volume_price_bonus"],
            })
        elif vr_5d >= 2.0:
            score -= 3.0
            reasons.append({
                "type": "warning",
                "title": "量能放大",
                "detail": f"近5日量能为前期{vr_5d:.2f}倍，关注是否异常。",
                "contribution": -3.0,
            })

    # 6. MACD 金叉
    if macd_dif is not None and macd_dea is not None:
        if macd_dif > macd_dea:
            score += TECH["macd_golden_cross_bonus"]
            reasons.append({
                "type": "positive",
                "title": "MACD偏多",
                "detail": "DIF位于DEA上方，动能偏多。",
                "contribution": TECH["macd_golden_cross_bonus"],
            })

    # 7. 短期动量
    if ret_5d is not None and ret_5d > 0:
        score += TECH["momentum_5d_positive_bonus"]
        reasons.append({
            "type": "positive",
            "title": "近5日正收益",
            "detail": f"近5日收益 {ret_5d:.2f}%。",
            "contribution": TECH["momentum_5d_positive_bonus"],
        })

    # 8. 中期动量
    if ret_20d is not None and ret_20d > 0:
        score += TECH["momentum_20d_positive_bonus"]
        reasons.append({
            "type": "positive",
            "title": "近20日正收益",
            "detail": f"近20日收益 {ret_20d:.2f}%。",
            "contribution": TECH["momentum_20d_positive_bonus"],
        })

    score = _clamp(score)

    # 按贡献绝对值排序，取前 MAX_REASONS
    reasons.sort(key=lambda r: abs(r["contribution"]), reverse=True)
    reasons = reasons[:MAX_REASONS]

    # 判断趋势
    trend = "range"
    if all(v is not None for v in [close, ma20, ma60]):
        if close > ma20 > ma60:
            trend = "uptrend"
        elif close < ma20 < ma60:
            trend = "downtrend"
        elif close < ma20 and close > ma60:
            trend = "rebound"
        elif close > ma20 and close < ma60:
            trend = "range"
    if close is None:
        trend = "insufficient"

    return {
        "score": score,
        "trend": trend,
        "rsi14": round(rsi, 1) if rsi is not None else None,
        "volume_ratio_5d": round(vr_5d, 2) if vr_5d is not None else None,
    }


# ============================================================
# 4. 行业分数
# ============================================================

def compute_industry_score(
    latest: dict,
    industry_data: dict,
    all_stocks_data: list,
) -> dict:
    """
    计算行业分数 (0-100)。

    industry_data 包含: return_5d_pct, return_20d_pct, return_60d_pct, relative_strength_20d_pct
    """
    score = IND["baseline"]
    reasons = []

    ind_ret_5 = industry_data.get("return_5d_pct")
    ind_ret_20 = industry_data.get("return_20d_pct")
    ind_ret_60 = industry_data.get("return_60d_pct")
    rs_20 = industry_data.get("relative_strength_20d_pct")

    # 行业相对强度
    if rs_20 is not None:
        if rs_20 > 1.0:
            bonus = min(15.0, rs_20 * 3.0)
            score += bonus
            reasons.append({
                "type": "positive",
                "title": "行业强于大盘",
                "detail": f"所属行业近20日跑赢大盘 {rs_20:.1f}%。",
                "contribution": round(bonus, 1),
            })
        elif rs_20 < -1.0:
            penalty = max(-15.0, rs_20 * 2.0)
            score += penalty
            reasons.append({
                "type": "negative",
                "title": "行业弱于大盘",
                "detail": f"所属行业近20日跑输大盘 {abs(rs_20):.1f}%。",
                "contribution": round(penalty, 1),
            })

    # 行业近期走势
    if ind_ret_20 is not None:
        if ind_ret_20 > 3.0:
            score += 8.0
            reasons.append({
                "type": "positive",
                "title": "行业20日趋势向好",
                "detail": f"行业近20日上涨 {ind_ret_20:.1f}%。",
                "contribution": 8.0,
            })
        elif ind_ret_20 < -3.0:
            score -= 8.0
            reasons.append({
                "type": "negative",
                "title": "行业20日趋势偏弱",
                "detail": f"行业近20日下跌 {abs(ind_ret_20):.1f}%。",
                "contribution": -8.0,
            })

    # 行业短期动量
    if ind_ret_5 is not None and ind_ret_5 > 1.0:
        score += 5.0
        reasons.append({
            "type": "positive",
            "title": "行业短期走强",
            "detail": f"行业近5日上涨 {ind_ret_5:.1f}%。",
            "contribution": 5.0,
        })

    score = _clamp(score)
    reasons.sort(key=lambda r: abs(r["contribution"]), reverse=True)

    return {
        "score": score,
        "return_5d_pct": round(ind_ret_5, 2) if ind_ret_5 is not None else None,
        "return_20d_pct": round(ind_ret_20, 2) if ind_ret_20 is not None else None,
        "return_60d_pct": round(ind_ret_60, 2) if ind_ret_60 is not None else None,
        "relative_strength_20d_pct": round(rs_20, 2) if rs_20 is not None else None,
    }


# ============================================================
# 5. 综合评分
# ============================================================

def compute_composite_score(
    risk_result: dict,
    technical_result: dict,
    industry_result: dict,
    similarity_result: dict,
    all_forecast_returns_5d: list,      # 所有标的的 forecast.return_5d_pct
    all_up_probabilities_5d: list,       # 所有标的的 forecast.up_probability_5d_pct
) -> dict:
    """
    计算机会分 + 风险调整后综合评分。

    返回:
    {
        "risk_adjusted": float,
        "risk": float,
        "technical": float,
        "industry": float,
        "opportunity": float,
    }
    """
    risk_score = risk_result["score"]
    tech_score = technical_result["score"]
    ind_score = industry_result["score"]

    # 提取预测值
    forecast_5d = similarity_result.get("horizon_5d", {}).get("average_return_pct")
    up_prob_5d = similarity_result.get("horizon_5d", {}).get("up_probability_pct")
    sample_size = similarity_result.get("sample_size", 0)

    # 预测百分位（收益越高越好）
    fc_percentile = 50.0
    if forecast_5d is not None and all_forecast_returns_5d:
        fc_percentile = _percentile_rank(all_forecast_returns_5d, forecast_5d, higher_is_better=True)

    # 上涨比例百分位
    up_percentile = 50.0
    if up_prob_5d is not None and all_up_probabilities_5d:
        up_percentile = _percentile_rank(all_up_probabilities_5d, up_prob_5d, higher_is_better=True)

    # 截断：取排行百分位（超过 50 的部分）
    fc_component = fc_percentile

    # 上涨比例（转为百分制）
    up_component = up_prob_5d if up_prob_5d is not None else 50.0

    # 机会分
    opportunity = (
        OPPORTUNITY_WEIGHTS["forecast_percentile"] * fc_component
        + OPPORTUNITY_WEIGHTS["up_probability_5d"] * up_component
        + OPPORTUNITY_WEIGHTS["technical_score"] * tech_score
        + OPPORTUNITY_WEIGHTS["industry_score"] * ind_score
    )

    # 风险调整
    risk_adjusted = opportunity * (1.0 - RISK_PENALTY_FACTOR * risk_score / 100.0)
    risk_adjusted = _clamp(risk_adjusted)

    opportunity = round(opportunity, 1)
    risk_adjusted = round(risk_adjusted, 1)

    return {
        "risk_adjusted": risk_adjusted,
        "risk": risk_score,
        "technical": tech_score,
        "industry": ind_score,
        "opportunity": round(opportunity, 1),
    }
