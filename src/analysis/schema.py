# analysis/schema.py —— 输出数据校验与 JSON Schema
#
# 对 ranking.json 和各个 {code}.json 做结构校验，
# 确保字段合约一致。不依赖 jsonschema 库，用纯 Python 实现。

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

try:
    from .config import RISK_LEVELS, SCORE_MAX, SCORE_MIN
except ImportError:
    from analysis.config import RISK_LEVELS, SCORE_MAX, SCORE_MIN

logger = logging.getLogger("stock-dashboard.schema")

VALID_LEVELS = {"low", "medium", "high"}
VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_REASON_TYPES = {"positive", "warning", "negative"}
VALID_TRENDS = {"strong_uptrend", "uptrend", "range", "rebound", "downtrend", "insufficient"}
VALID_REF_TYPES = {"industry", "index"}


# ============================================================
# 校验结果
# ============================================================

class ValidationError(Exception):
    """数据格式校验失败。"""
    pass


# ============================================================
# 整体排名文件校验
# ============================================================

def validate_ranking(data: dict) -> list[str]:
    """
    校验 ranking.json。返回错误消息列表，空列表表示通过。
    """
    errors = []

    # 顶层必填
    for key in ["schema_version", "generated_at", "trade_date", "horizons",
                "ranking_method", "status", "total", "succeeded", "failed", "items"]:
        if key not in data:
            errors.append(f"缺少顶层字段: {key}")

    if errors:
        return errors

    # 字段类型校验
    if not isinstance(data["schema_version"], str):
        errors.append("schema_version 必须是字符串")

    if data["status"] not in ("success", "partial"):
        errors.append(f"status 非法: {data['status']}")

    total = data.get("total", 0)
    succeeded = data.get("succeeded", 0)
    failed = data.get("failed", 0)
    actual = len(data.get("items", []))

    if succeeded + failed != total:
        errors.append(f"succeeded({succeeded}) + failed({failed}) != total({total})")

    if actual != total:
        errors.append(f"items 数量({actual}) != total({total})")

    # 校验 trade_date 不晚于北京时间当天
    trade_date_str = data.get("trade_date", "")
    if trade_date_str:
        try:
            td = date.fromisoformat(trade_date_str)
            # 使用系统日期检查（北京时间）
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            if td > today:
                errors.append(f"trade_date({trade_date_str}) 晚于今天")
        except ValueError:
            errors.append(f"trade_date 格式错误: {trade_date_str}")

    # 排名去重
    ranks = [item.get("rank") for item in data.get("items", [])]
    valid_ranks = [r for r in ranks if r is not None]
    if len(valid_ranks) != len(set(valid_ranks)):
        errors.append("排名有重复")

    # 校验每个 item
    for item in data.get("items", []):
        errors.extend(_validate_ranking_item(item))

    # errors 列表
    if "errors" in data:
        for err_item in data["errors"]:
            if "code" not in err_item:
                errors.append("error 项缺少 code")

    return errors


def _validate_ranking_item(item: dict) -> list[str]:
    errors = []
    for key in ["rank", "code", "name", "type", "risk_adjusted_score"]:
        if key not in item:
            errors.append(f"item 缺少字段: {key}")

    score = item.get("risk_adjusted_score")
    if score is not None and (not isinstance(score, (int, float)) or score < SCORE_MIN or score > SCORE_MAX):
        errors.append(f"risk_adjusted_score 越界: {score}")

    # risk
    risk = item.get("risk", {})
    if risk:
        errors.extend(_validate_risk_block(risk, "item.risk"))
    else:
        errors.append("item 缺少 risk 块")

    # forecast
    forecast = item.get("forecast", {})
    if forecast:
        errors.extend(_validate_forecast_block(forecast, "item.forecast"))
    else:
        errors.append("item 缺少 forecast 块")

    # reasons
    if "reasons" in item:
        errors.extend(_validate_reasons(item["reasons"]))

    return errors


# ============================================================
# 个股详情文件校验
# ============================================================

def validate_stock_detail(data: dict) -> list[str]:
    errors = []

    for key in ["schema_version", "generated_at", "trade_date", "code",
                "name", "type", "scores", "risk", "forecast",
                "technical", "industry", "similarity", "reasons"]:
        if key not in data:
            errors.append(f"缺少字段: {key}")

    if errors:
        return errors

    # scores
    scores = data.get("scores", {})
    for sk in ["risk_adjusted", "risk", "technical", "industry"]:
        val = scores.get(sk)
        if val is not None and (val < SCORE_MIN or val > SCORE_MAX):
            errors.append(f"scores.{sk} 越界: {val}")

    # risk block: for stock detail, score is in scores.risk
    # _validate_risk_block checks for risk.score which may be absent in stock detail
    # (stock detail uses scores.risk instead)
    risk = data.get("risk", {})
    errors.extend(_validate_risk_block(risk, "risk", allow_missing_score=True))
    # Also verify risk.level matches scores.risk (stock detail only)
    scores = data.get("scores", {})
    risk_score_val = scores.get("risk")
    if risk_score_val is not None and risk.get("level"):
        expected_level, _ = _get_level_from_score(risk_score_val)
        if risk.get("level") != expected_level:
            errors.append(
                f"risk.level({risk.get('level')}) 与 scores.risk({risk_score_val}) 不一致，期望 {expected_level}"
            )

    # forecast
    errors.extend(_validate_forecast_block(data.get("forecast", {}), "forecast"))

    # technical
    tech = data.get("technical", {})
    if tech:
        trend = tech.get("trend")
        if trend and trend not in VALID_TRENDS:
            errors.append(f"technical.trend 非法: {trend}")

    # industry
    ind = data.get("industry", {})
    if ind:
        ref_type = ind.get("reference_type")
        if ref_type and ref_type not in VALID_REF_TYPES:
            errors.append(f"industry.reference_type 非法: {ref_type}")

    # similarity
    sim = data.get("similarity", {})
    if sim:
        errors.extend(_validate_similarity_block(sim))

    # reasons
    errors.extend(_validate_reasons(data.get("reasons", [])))

    return errors


# ============================================================
# 分块校验
# ============================================================

def _validate_risk_block(risk: dict, prefix: str, allow_missing_score: bool = False) -> list[str]:
    errors = []
    if "score" not in risk:
        if not allow_missing_score:
            errors.append(f"{prefix}.score 缺失")
    else:
        s = risk["score"]
        if s is not None and (s < SCORE_MIN or s > SCORE_MAX):
            errors.append(f"{prefix}.score 越界: {s}")

    level = risk.get("level")
    if level and level not in VALID_LEVELS:
        errors.append(f"{prefix}.level 非法: {level}")

    # 校验 risk_level 与 score 是否一致
    score_val = risk.get("score")
    if score_val is not None and level:
        expected_level, _ = _get_level_from_score(score_val)
        if level != expected_level:
            errors.append(f"{prefix}.level({level}) 与 score({score_val}) 不一致，期望 {expected_level}")

    return errors


def _validate_forecast_block(forecast: dict, prefix: str) -> list[str]:
    errors = []
    conf = forecast.get("confidence")
    if conf and conf not in VALID_CONFIDENCE:
        errors.append(f"{prefix}.confidence 非法: {conf}")

    for fk in ["return_3d_pct", "return_5d_pct", "up_probability_3d_pct", "up_probability_5d_pct"]:
        if fk not in forecast:
            errors.append(f"{prefix} 缺少 {fk}")
        else:
            val = forecast[fk]
            if val is not None and not isinstance(val, (int, float)):
                errors.append(f"{prefix}.{fk} 类型非法: {type(val)}")

    return errors


def _validate_similarity_block(sim: dict) -> list[str]:
    errors = []
    conf = sim.get("confidence")
    if conf and conf not in VALID_CONFIDENCE:
        errors.append(f"similarity.confidence 非法: {conf}")

    for h in [3, 5]:
        key = f"horizon_{h}d"
        if key in sim:
            h_data = sim[key]
            if not isinstance(h_data, dict):
                errors.append(f"similarity.{key} 必须是对象")
    return errors


def _validate_reasons(reasons: list) -> list[str]:
    errors = []
    if not isinstance(reasons, list):
        return ["reasons 必须是数组"]
    for i, r in enumerate(reasons):
        if not isinstance(r, dict):
            errors.append(f"reasons[{i}] 必须是对象")
            continue
        typ = r.get("type")
        if typ and typ not in VALID_REASON_TYPES:
            errors.append(f"reasons[{i}].type 非法: {typ}")
    return errors


def _get_level_from_score(score: float) -> tuple[str, str]:
    if score <= RISK_LEVELS["low"][1]:
        return "low", "低风险"
    elif score >= RISK_LEVELS["high"][0]:
        return "high", "高风险"
    else:
        return "medium", "中等风险"


# ============================================================
# 兼容性校验
# ============================================================

def check_schema_version(data: dict, expected: str = "2.0") -> bool:
    """检查 schema_version 是否兼容。"""
    version = data.get("schema_version", "")
    if not version:
        return False
    # 主版本一致即兼容
    data_major = version.split(".")[0]
    expected_major = expected.split(".")[0]
    return data_major == expected_major
