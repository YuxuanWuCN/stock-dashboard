# -*- coding: utf-8 -*-
"""
Dataset & Process API v1 —— 面向前端的数据集查询与处理接口

设计目标
--------
1. ``GET  /api/v1/dataset``  把看板的「标的排行榜」数据集以分页 + 过滤 + 排序的方式暴露，
   JSON 做扁平化与数值定点化，前端可直接绑定表格 / 卡片列表。
2. ``POST /api/v1/process``  接收前端的处理请求（选股 / 组合权重分配 / 聚合统计），
   复用同一套数据集逻辑，保证两个端口径完全一致。
3. ``GET  /api/v1/openapi.json``  OpenAPI 3.0 规格（来自 openapi_spec.py 单一来源）。

数据来源（只读，不修改任何数据文件）
------------------------------------
- ``docs/data/analysis/ranking_v3.json``  主表（缺失时回退 ``analysis/ranking.json``）
- ``docs/data/summary.json``              行情快照，按 code 关联
- ``docs/data/fundamental/<code>.json``   基本面明细，按需懒加载（仅当前页）

与既有接口的关系
----------------
``src/data_api.py`` 提供的是 1:1 透传的数据网关（``/api/data/**``）；
本模块在其之上再封装一层面向业务的 v1 数据集接口，不修改、不替代原有接口。
错误响应沿用本项目的既有风格：``{"error": "...", "detail": "..."}``。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from flask import Blueprint, jsonify, make_response, request
from werkzeug.exceptions import HTTPException

try:  # 包内导入（gunicorn --chdir src server:app）
    from .data_store import DATA_ROOT, get as _get, integer as _int, load_json as _load_json
    from .data_store import num as _num, pick as _pick, text as _text
    from .openapi_spec import render_openapi_json
except ImportError:  # 直接以脚本方式运行 src/ 下的模块
    from data_store import DATA_ROOT, get as _get, integer as _int, load_json as _load_json
    from data_store import num as _num, pick as _pick, text as _text
    from openapi_spec import render_openapi_json

# ---------------------------------------------------------------- 常量

RANKING_CANDIDATES = ("analysis/ranking_v3.json", "analysis/ranking.json")
SUMMARY_PATH = "summary.json"

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200
DEFAULT_TOP_N = 20
MAX_TOP_N = 200

bp = Blueprint("dataset_api_v1", __name__, url_prefix="/api/v1")

logger = logging.getLogger("dataset_api")


class ApiError(Exception):
    """带 HTTP 状态码的业务异常，统一转成 {"error", "detail"} 响应。"""

    def __init__(self, status: int, message: str, detail: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


# ---------------------------------------------------------------- 取值工具
# _pick / _num / _int / _text / _get 统一由 data_store 提供（见文件头 import 处的别名）。


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 数据加载
# _load_json 由 data_store 提供（按 mtime 缓存）。


def _load_dataset() -> Dict[str, Any]:
    """加载主表 + 行情快照，返回统一的数据集上下文。"""
    for rel in RANKING_CANDIDATES:
        payload = _load_json(DATA_ROOT / rel)
        if isinstance(payload, Mapping) and isinstance(payload.get("items"), list):
            ranking_rel = rel
            ranking = payload
            break
    else:
        raise ApiError(500, "数据集不可用：未找到排行榜数据文件", "已尝试 " + "、".join(RANKING_CANDIDATES))

    summary = _load_json(DATA_ROOT / SUMMARY_PATH)
    quotes: Dict[str, Mapping[str, Any]] = {}
    if isinstance(summary, Mapping):
        for item in summary.get("items") or []:
            code = _text(_get(item, "code"))
            if code:
                quotes[code] = item

    items = [item for item in ranking["items"] if isinstance(item, Mapping)]

    return {
        "items": items,
        "quotes": quotes,
        "source": ranking_rel,
        "trade_date": _text(ranking.get("trade_date")) or "",
        "generated_at": _text(ranking.get("generated_at")) or "",
        "engine": _text(ranking.get("engine")) or _text(ranking.get("ranking_method")) or "",
        "formula": _text(ranking.get("formula")) or "",
        "total": _int(ranking.get("total")) or len(items),
    }


def _load_fundamental(code: str) -> Optional[Dict[str, Any]]:
    """按需读取单只标的基本面明细（仅当前页命中时才读文件）。"""
    if not code:
        return None
    payload = _load_json(DATA_ROOT / "fundamental" / f"{code}.json")
    if not isinstance(payload, Mapping):
        return None
    dimensions = payload.get("dimensions") or {}
    return {
        "score": _num(payload.get("score")),
        "report_date": _text(payload.get("report_date")),
        "dimensions": {
            "asset_quality": _num(dimensions.get("asset_quality")),
            "liability_safety": _num(dimensions.get("liability_safety")),
            "profit_quality": _num(dimensions.get("profit_quality")),
            "cash_health": _num(dimensions.get("cash_health")),
        },
        "positive_view": _text(_get(payload, "dual_view", "positive_view")),
        "negative_view": _text(_get(payload, "dual_view", "negative_view")),
    }


# ---------------------------------------------------------------- 行构建


def _market_block(quote: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(quote, Mapping):
        return None
    return {
        "last_close": _num(quote.get("last_close")),
        "change_pct": _num(quote.get("change_pct")),
        "change_amt": _num(quote.get("change_amt")),
        "last_date": _text(quote.get("last_date")),
        "status": _text(quote.get("status")),
    }


def _risk_factor(risk: Mapping[str, Any], name: str) -> Any:
    """从 risk.factors 明细里取某个风险因子的 value。

    排行榜主表的 risk 块只带 score/level/label 与 factors 明细，
    年化波动率、最大回撤等指标需要在 factors 里按名称取。
    """
    for factor in risk.get("factors") or []:
        if isinstance(factor, Mapping) and _text(factor.get("name")) == name:
            return factor.get("value")
    return None


def _build_row(
    item: Mapping[str, Any],
    quote: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """把排行榜的一行（含大量嵌套对象）压成面向前端的扁平结构。"""
    scores = item.get("scores") or {}
    risk = item.get("risk") or {}
    tech = item.get("technical") or {}
    industry = item.get("industry") or {}
    forecast = item.get("forecast") or {}
    leading = item.get("leading") or {}
    nale = item.get("nale_network") or {}
    gate = item.get("fundamental_gate") or {}
    rec = item.get("strategy_recommendation") or {}
    bet_metrics = item.get("bet_type_metrics") or {}

    row = {
        "rank": _int(item.get("rank")),
        "code": _text(item.get("code")) or "",
        "name": _text(item.get("name")) or "",
        "type": (_text(item.get("type")) or "stock").lower(),
        "category": _text(item.get("category")) or "",
        "trade_date": _text(item.get("trade_date")) or "",
        "stale": bool(item.get("stale")) if item.get("stale") is not None else False,
        "scores": {
            "total": _num(_pick(item.get("total_score"), scores.get("total"))),
            "risk_adjusted": _num(_pick(item.get("risk_adjusted_score"), scores.get("risk_adjusted"))),
            "fundamental": _num(_pick(item.get("fundamental_score"), scores.get("fundamental"))),
            "technical": _num(_pick(tech.get("score"), scores.get("technical"))),
            "industry": _num(_pick(industry.get("score"), scores.get("industry"))),
            "leading": _num(_pick(leading.get("score"), scores.get("leading"))),
        },
        "market": _market_block(quote),
        "risk": {
            "level": _text(risk.get("level")) or "unknown",
            "label": _text(risk.get("label")) or "",
            "score": _num(risk.get("score")),
            "annualized_volatility_20d_pct": _num(
                _pick(risk.get("annualized_volatility_20d_pct"), _risk_factor(risk, "20日波动率"))
            ),
            "max_drawdown_60d_pct": _num(
                _pick(risk.get("max_drawdown_60d_pct"), _risk_factor(risk, "60日最大回撤"))
            ),
            "atr14_pct": _num(_pick(risk.get("atr14_pct"), _risk_factor(risk, "ATR百分比"))),
        },
        "forecast": {
            "return_3d_pct": _num(forecast.get("return_3d_pct")),
            "return_5d_pct": _num(forecast.get("return_5d_pct")),
            "up_probability_3d_pct": _num(forecast.get("up_probability_3d_pct")),
            "up_probability_5d_pct": _num(forecast.get("up_probability_5d_pct")),
            "confidence": _text(forecast.get("confidence")),
            "optimal_holding_days": _num(forecast.get("optimal_holding_days")),
        },
        "technical": {
            "trend": _text(tech.get("trend")),
            "rsi14": _num(tech.get("rsi14")),
            "volume_ratio_5d": _num(tech.get("volume_ratio_5d")),
            "return_5d_pct": _num(tech.get("return_5d_pct")),
            "return_20d_pct": _num(tech.get("return_20d_pct")),
        },
        "industry": {
            "name": _text(industry.get("name")),
            "return_5d_pct": _num(industry.get("return_5d_pct")),
            "return_20d_pct": _num(industry.get("return_20d_pct")),
            "relative_strength_20d_pct": _num(industry.get("relative_strength_20d_pct")),
        },
        "sector": {
            "name": _text(nale.get("sector_name")),
            "tier_role": _text(nale.get("tier_role")),
            "breadth_pct": _num(nale.get("sector_breadth_pct")),
            "has_limit_up_resonance": bool(nale.get("has_limit_up_resonance")) if nale else None,
            "co_movement_peers": len(nale.get("co_movement_peers") or []) if nale else None,
        },
        "signal": {
            "bet_type": _text(item.get("bet_type")),
            "fundamental_gate_passed": gate.get("passed"),
            "fundamental_gate_reason": _text(gate.get("reject_reason")),
            "holding_period": _int(rec.get("holding_period")),
            "trade_frequency": _text(rec.get("trade_frequency")),
            "recommendation": _text(rec.get("description")),
            "monster_score": _num(bet_metrics.get("monster_score")),
            "volatility_annual": _num(bet_metrics.get("volatility_annual"), 4),
        },
        # 基本面明细默认不返回，需要时通过 include_fundamental=1 打开（逐行懒加载）
        "fundamental": None,
        "reasons": [
            {
                "type": _text(reason.get("type")),
                "title": _text(reason.get("title")),
                "detail": _text(reason.get("detail")),
                "contribution": _num(reason.get("contribution")),
            }
            for reason in (item.get("reasons") or [])
            if isinstance(reason, Mapping)
        ],
    }
    return row


# ---------------------------------------------------------------- 查询参数解析

#: 可排序字段 → (类型, 取值函数)。类型用于决定降序时怎么取反。
_SORTABLE: Dict[str, Tuple[str, Callable[[Mapping[str, Any]], Any]]] = {
    "rank": ("int", lambda r: _get(r, "rank")),
    "code": ("str", lambda r: _get(r, "code")),
    "name": ("str", lambda r: _get(r, "name")),
    "trade_date": ("str", lambda r: _get(r, "trade_date")),
    "total_score": ("num", lambda r: _get(r, "scores", "total")),
    "risk_adjusted_score": ("num", lambda r: _get(r, "scores", "risk_adjusted")),
    "fundamental_score": ("num", lambda r: _get(r, "scores", "fundamental")),
    "technical_score": ("num", lambda r: _get(r, "scores", "technical")),
    "industry_score": ("num", lambda r: _get(r, "scores", "industry")),
    "leading_score": ("num", lambda r: _get(r, "scores", "leading")),
    "last_close": ("num", lambda r: _get(r, "market", "last_close")),
    "change_pct": ("num", lambda r: _get(r, "market", "change_pct")),
    "volatility_20d_pct": ("num", lambda r: _get(r, "risk", "annualized_volatility_20d_pct")),
    "max_drawdown_60d_pct": ("num", lambda r: _get(r, "risk", "max_drawdown_60d_pct")),
    "return_5d_pct": ("num", lambda r: _get(r, "forecast", "return_5d_pct")),
    "up_probability_5d_pct": ("num", lambda r: _get(r, "forecast", "up_probability_5d_pct")),
    "rsi14": ("num", lambda r: _get(r, "technical", "rsi14")),
}

#: 前端可通过 fields= 做字段裁剪的顶层字段
_ROW_FIELDS: Tuple[str, ...] = (
    "rank", "code", "name", "type", "category", "trade_date", "stale",
    "scores", "market", "risk", "forecast", "technical", "industry", "sector",
    "signal", "fundamental", "reasons",
)

_FILTER_KEYS = (
    "q", "codes", "type", "category", "risk_level", "trend",
    "stale", "min_score", "max_score",
)

_MULTI_VALUE_KEYS = ("codes", "type", "category", "risk_level", "trend", "fields")


def _as_list(value: Any) -> List[str]:
    """把 "a,b" 或 ["a","b"] 统一成去重后的字符串列表。"""
    if value is None:
        return []
    raw: Iterable[Any]
    if isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = str(value).split(",")

    result: List[str] = []
    for entry in raw:
        text = _text(entry)
        if text and text not in result:
            result.append(text)
    return result


def _as_bool(value: Any, name: str) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ApiError(400, f"参数 {name} 需要布尔值", f"收到 {value!r}，可用 1/0、true/false")


def _as_int(value: Any, name: str, *, minimum: int, maximum: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ApiError(400, f"参数 {name} 需要整数", f"收到 {value!r}")
    if number < minimum or number > maximum:
        raise ApiError(400, f"参数 {name} 超出取值范围", f"应在 [{minimum}, {maximum}] 之间，收到 {number}")
    return number


def _as_float(value: Any, name: str) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        raise ApiError(400, f"参数 {name} 需要数值", f"收到 {value!r}")
    if not math.isfinite(number):
        raise ApiError(400, f"参数 {name} 需要有限数值", f"收到 {value!r}")
    return number


def _parse_sort(raw: Any, default: str = "rank") -> Tuple[str, bool]:
    """解析排序参数，支持 ``rank`` / ``-total_score`` / ``total_score:desc``。"""
    text = _text(raw) or default
    descending = False
    if text.startswith("-"):
        descending, text = True, text[1:]
    elif ":" in text:
        text, _, direction = text.partition(":")
        direction = direction.strip().lower()
        if direction in ("desc", "descending", "-1"):
            descending = True
        elif direction in ("asc", "ascending", "1"):
            descending = False
        else:
            raise ApiError(400, "参数 sort 的方向不合法", f"方向 {direction!r} 不是 asc/desc")
    elif text.endswith(" desc") or text.endswith(" asc"):
        text, _, direction = text.rpartition(" ")
        descending = direction == "desc"

    text = text.strip()
    if text not in _SORTABLE:
        raise ApiError(
            400,
            "参数 sort 指定的字段不可排序",
            f"{text!r} 不在可排序字段内：" + ", ".join(sorted(_SORTABLE)),
        )
    return text, descending


def _parse_spec(raw: Mapping[str, Any], *, for_process: bool = False) -> Dict[str, Any]:
    """把 GET 查询串 / POST filters 统一解析成内部查询规格。"""
    spec: Dict[str, Any] = {
        "q": _text(raw.get("q")),
        "codes": _as_list(raw.get("codes")),
        "type": [t.lower() for t in _as_list(raw.get("type"))],
        "category": _as_list(raw.get("category")),
        "risk_level": [t.lower() for t in _as_list(raw.get("risk_level"))],
        "trend": [t.lower() for t in _as_list(raw.get("trend"))],
        "stale": _as_bool(raw.get("stale"), "stale"),
        "min_score": _as_float(raw.get("min_score"), "min_score"),
        "max_score": _as_float(raw.get("max_score"), "max_score"),
        "include_fundamental": _as_bool(raw.get("include_fundamental"), "include_fundamental") or False,
        "with_facets": _as_bool(raw.get("with_facets"), "with_facets") or False,
        "sort": _parse_sort(raw.get("sort")),
    }

    fields = _as_list(raw.get("fields"))
    if fields:
        unknown = [f for f in fields if f not in _ROW_FIELDS]
        if unknown:
            raise ApiError(
                400,
                "参数 fields 包含未知字段",
                f"未知字段：{', '.join(unknown)}；可选：{', '.join(_ROW_FIELDS)}",
            )
        spec["fields"] = fields
    else:
        spec["fields"] = None

    if spec["min_score"] is not None and spec["max_score"] is not None:
        if spec["min_score"] > spec["max_score"]:
            raise ApiError(400, "参数 min_score 不能大于 max_score")

    if for_process:
        spec["top_n"] = _as_int(raw.get("top_n", DEFAULT_TOP_N), "top_n", minimum=1, maximum=MAX_TOP_N)
        spec["page"] = 1
        spec["page_size"] = spec["top_n"]
    else:
        spec["page"] = _as_int(raw.get("page", 1), "page", minimum=1, maximum=10_000)
        spec["page_size"] = _as_int(raw.get("page_size", DEFAULT_PAGE_SIZE), "page_size",
                                    minimum=1, maximum=MAX_PAGE_SIZE)
    return spec


# ---------------------------------------------------------------- 过滤 / 排序 / 分页


def _apply_filters(rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    keyword = (spec.get("q") or "").lower()
    codes = set(spec.get("codes") or [])
    types = set(spec.get("type") or [])
    categories = set(spec.get("category") or [])
    risk_levels = set(spec.get("risk_level") or [])
    trends = set(spec.get("trend") or [])
    stale = spec.get("stale")
    min_score = spec.get("min_score")
    max_score = spec.get("max_score")

    result: List[Mapping[str, Any]] = []
    for row in rows:
        if keyword:
            # 关键词同时匹配代码、名称与分类，避免搜「存储」时漏掉名字里没有该词的标的
            haystack = " ".join(str(part or "") for part in (
                _get(row, "code"), _get(row, "name"), _get(row, "category"),
            )).lower()
            if keyword not in haystack:
                continue
        if codes and _get(row, "code") not in codes:
            continue
        if types and (_get(row, "type") or "").lower() not in types:
            continue
        if categories and _get(row, "category") not in categories:
            continue
        if risk_levels and (_get(row, "risk", "level") or "unknown").lower() not in risk_levels:
            continue
        if trends:
            trend = (_get(row, "technical", "trend") or "").lower()
            if trend not in trends:
                continue
        if stale is not None and bool(_get(row, "stale")) != stale:
            continue
        score = _get(row, "scores", "total")
        if min_score is not None and (score is None or score < min_score):
            continue
        if max_score is not None and (score is None or score > max_score):
            continue
        result.append(row)
    return result


def _apply_sort(rows: List[Mapping[str, Any]], spec: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    field, descending = spec["sort"]
    kind, accessor = _SORTABLE[field]

    def key(row: Mapping[str, Any]) -> Tuple[bool, Any]:
        value = accessor(row)
        if value is None:
            # 空值统一排在最后（True 比 False 大）
            return True, 0
        if kind == "num" or kind == "int":
            return False, -value if descending else value
        return False, str(value)

    return sorted(rows, key=key, reverse=(descending and kind == "str"))


def _paginate(rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]) -> Tuple[List[Mapping[str, Any]], Dict[str, Any]]:
    page_size = spec["page_size"]
    total = len(rows)
    total_pages = max(1, math.ceil(total / page_size)) if total else 1
    page = min(spec["page"], total_pages)
    start = (page - 1) * page_size
    window = list(rows[start:start + page_size])
    meta = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
        "returned": len(window),
    }
    return window, meta


def _project(row: Mapping[str, Any], fields: Optional[Sequence[str]]) -> Dict[str, Any]:
    if not fields:
        return dict(row)
    return {key: row.get(key) for key in fields}


def _build_facets(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """给前端筛选器用的取值分布（基于过滤后的结果集，不含分页）。"""
    types: Dict[str, int] = {}
    categories: Dict[str, int] = {}
    risk_levels: Dict[str, int] = {}
    trends: Dict[str, int] = {}

    for row in rows:
        row_type = _get(row, "type") or "stock"
        types[row_type] = types.get(row_type, 0) + 1
        category = _get(row, "category") or "未分类"
        categories[category] = categories.get(category, 0) + 1
        level = _get(row, "risk", "level") or "unknown"
        risk_levels[level] = risk_levels.get(level, 0) + 1
        trend = _get(row, "technical", "trend") or "unknown"
        trends[trend] = trends.get(trend, 0) + 1

    def as_sorted(mapping: Dict[str, int]) -> List[Dict[str, Any]]:
        return [{"value": k, "count": v} for k, v in sorted(mapping.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {
        "type": as_sorted(types),
        "category": as_sorted(categories),
        "risk_level": as_sorted(risk_levels),
        "trend": as_sorted(trends),
    }


# ---------------------------------------------------------------- 数据集查询（两个接口共用）


def _select(spec: Mapping[str, Any]) -> Dict[str, Any]:
    """核心数据集逻辑：加载 → 过滤 → 排序 → 分页 → 投影。"""
    dataset = _load_dataset()
    quotes = dataset["quotes"]

    rows = [_build_row(item, quotes.get(_text(item.get("code")) or "")) for item in dataset["items"]]
    matched = _apply_filters(rows, spec)
    ordered = _apply_sort(matched, spec)
    window, page_meta = _paginate(ordered, spec)

    if spec.get("include_fundamental"):
        for row in window:
            row["fundamental"] = _load_fundamental(row["code"])

    return {
        "dataset": dataset,
        "matched": ordered,
        "window": window,
        "meta": page_meta,
    }


def _dataset_meta(selection: Mapping[str, Any], spec: Mapping[str, Any]) -> Dict[str, Any]:
    dataset = selection["dataset"]
    field, descending = spec["sort"]
    meta = {
        "source": dataset["source"],
        "trade_date": dataset["trade_date"],
        "generated_at": dataset["generated_at"],
        "engine": dataset["engine"],
        "formula": dataset["formula"],
        "sort": f"{field}:{'desc' if descending else 'asc'}",
        "filters": {
            "q": spec.get("q"),
            "codes": spec.get("codes") or [],
            "type": spec.get("type") or [],
            "category": spec.get("category") or [],
            "risk_level": spec.get("risk_level") or [],
            "trend": spec.get("trend") or [],
            "stale": spec.get("stale"),
            "min_score": spec.get("min_score"),
            "max_score": spec.get("max_score"),
        },
    }
    meta.update(selection["meta"])
    if spec.get("with_facets"):
        meta["facets"] = _build_facets(selection["matched"])
    return meta


# ---------------------------------------------------------------- 组合统计与权重


def _summarize(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """对选中标的做聚合统计（评分 / 风险 / 行业 / 预测）。"""
    if not rows:
        return {
            "count": 0, "score": None, "risk": None, "type_distribution": [],
            "category_top": [], "trend_distribution": [], "forecast": None, "stale_count": 0,
        }

    def collect(path: Tuple[str, ...]) -> List[float]:
        values = []
        for row in rows:
            value = _get(row, *path)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
        return values

    def describe(values: List[float]) -> Optional[Dict[str, Any]]:
        if not values:
            return None
        ordered = sorted(values)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        return {
            "avg": round(sum(values) / len(values), 2),
            "median": round(median, 2),
            "min": round(ordered[0], 2),
            "max": round(ordered[-1], 2),
        }

    def distribution(path: Tuple[str, ...], fallback: str) -> List[Dict[str, Any]]:
        bucket: Dict[str, int] = {}
        for row in rows:
            key = _text(_get(row, *path)) or fallback
            bucket[key] = bucket.get(key, 0) + 1
        return [{"value": k, "count": v} for k, v in sorted(bucket.items(), key=lambda kv: (-kv[1], kv[0]))]

    # 行业分布：带上该行业的平均总分，便于前端直接画图
    category_stats: Dict[str, Dict[str, float]] = {}
    for row in rows:
        category = _get(row, "category") or "未分类"
        entry = category_stats.setdefault(category, {"count": 0, "score_sum": 0.0, "score_n": 0})
        entry["count"] += 1
        score = _get(row, "scores", "total")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            entry["score_sum"] += float(score)
            entry["score_n"] += 1

    category_top = [
        {
            "category": name,
            "count": int(entry["count"]),
            "avg_score": round(entry["score_sum"] / entry["score_n"], 2) if entry["score_n"] else None,
        }
        for name, entry in sorted(category_stats.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
    ][:10]

    return {
        "count": len(rows),
        "score": describe(collect(("scores", "total"))),
        "risk_score": describe(collect(("risk", "score"))),
        "volatility_20d_pct": describe(collect(("risk", "annualized_volatility_20d_pct"))),
        "max_drawdown_60d_pct": describe(collect(("risk", "max_drawdown_60d_pct"))),
        "forecast": {
            "return_5d_pct": describe(collect(("forecast", "return_5d_pct"))),
            "up_probability_5d_pct": describe(collect(("forecast", "up_probability_5d_pct"))),
        },
        "risk_level_distribution": distribution(("risk", "level"), "unknown"),
        "type_distribution": distribution(("type",), "stock"),
        "trend_distribution": distribution(("technical", "trend"), "unknown"),
        "category_top": category_top,
        "stale_count": sum(1 for row in rows if _get(row, "stale")),
    }


def _weight_series(rows: Sequence[Mapping[str, Any]], method: str) -> Dict[str, float]:
    """按指定方法算出未封顶的初始权重（和为 1）。"""
    count = len(rows)
    if count == 0:
        return {}
    if method == "equal":
        return {row["code"]: 1.0 / count for row in rows}

    if method == "score":
        raw = []
        for row in rows:
            score = _get(row, "scores", "total")
            raw.append(float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else 0.0)
        # 分数全为正时直接按比例分配；存在非正分数时先整体平移成非负，避免出现 0 权重持仓
        floor = min(raw)
        shift = (-floor + 1e-6) if floor <= 0 else 0.0
        shifted = [value + shift for value in raw]
        total = sum(shifted)
        if total <= 0:
            return {row["code"]: 1.0 / count for row in rows}
        return {row["code"]: shifted[i] / total for i, row in enumerate(rows)}

    if method == "risk_inverse":
        inverses = []
        for row in rows:
            volatility = _get(row, "risk", "annualized_volatility_20d_pct")
            if not isinstance(volatility, (int, float)) or isinstance(volatility, bool) or volatility <= 0:
                volatility = _get(row, "risk", "atr14_pct")
            inverses.append(1.0 / float(volatility) if isinstance(volatility, (int, float))
                            and not isinstance(volatility, bool) and volatility > 0 else 0.0)
        total = sum(inverses)
        if total <= 0:
            return {row["code"]: 1.0 / count for row in rows}
        return {row["code"]: inverses[i] / total for i, row in enumerate(rows)}

    raise ApiError(400, f"不支持的 weighting: {method}", "可选 equal / score / risk_inverse")


def _cap_weights(weights: Dict[str, float], cap: float) -> Tuple[Dict[str, float], List[str]]:
    """单标的上限约束：超过上限的部分按比例回填给未触顶的标的（water-filling）。"""
    notes: List[str] = []
    if not weights:
        return {}, notes

    capped = dict(weights)
    for _ in range(64):
        over = {code: w for code, w in capped.items() if w > cap + 1e-12}
        if not over:
            break
        excess = sum(w - cap for w in over.values())
        for code in over:
            capped[code] = cap
        free = {code: w for code, w in capped.items() if w < cap - 1e-12}
        pool = sum(free.values())
        if pool <= 1e-12:
            notes.append(f"标的数量不足，无法在 max_weight={cap} 下用满仓位，剩余记为现金")
            break
        for code, weight in free.items():
            capped[code] = weight + excess * (weight / pool)

    total = sum(capped.values())
    if total > 1:
        capped = {code: w / total for code, w in capped.items()}
    return capped, notes


def _allocate(rows: Sequence[Mapping[str, Any]], method: str, max_weight: float) -> Dict[str, Any]:
    weights = _weight_series(rows, method)
    weights, notes = _cap_weights(weights, max_weight)

    # 权重先定点到 4 位，再把舍入残差补到最大的一档 ——
    # 否则 10 个标的各舍入一次，权重合计会漂到 1.0001，前端显示成 100.01%
    rounded = {code: round(weight, 4) for code, weight in weights.items()}
    if rounded:
        residual = round(sum(weights.values()) - sum(rounded.values()), 4)
        if residual:
            top = max(rounded, key=lambda code: rounded[code])
            rounded[top] = round(rounded[top] + residual, 4)
    invested = round(sum(rounded.values()), 4)

    positions = []
    for row in rows:
        code = row["code"]
        positions.append({
            "code": code,
            "name": row["name"],
            "category": row["category"],
            "weight": rounded.get(code, 0.0),
            "amount_pct": round(rounded.get(code, 0.0) * 100, 2),
            "score": _get(row, "scores", "total"),
            "risk_level": _get(row, "risk", "level"),
            "volatility_20d_pct": _get(row, "risk", "annualized_volatility_20d_pct"),
        })
    positions.sort(key=lambda p: (-p["weight"], p["code"]))

    return {
        "method": method,
        "max_weight": max_weight,
        "invested_weight": invested,
        "cash_weight": round(max(0.0, 1.0 - invested), 4),
        "positions": positions,
        "notes": notes,
    }


# ---------------------------------------------------------------- 路由


def _args_mapping(args: Mapping[str, Any]) -> Dict[str, Any]:
    """把 Flask 的 query string 转成普通 dict；多值参数保留列表。"""
    mapping: Dict[str, Any] = {}
    for key in set(args.keys()):
        values = args.getlist(key) if hasattr(args, "getlist") else [args.get(key)]
        if len(values) > 1 and key in _MULTI_VALUE_KEYS:
            mapping[key] = values
        else:
            mapping[key] = values[0] if len(values) == 1 else values
    return mapping


def _unknown_keys(raw: Mapping[str, Any], allowed: Iterable[str]) -> List[str]:
    allowed_set = set(allowed)
    return [key for key in raw if key not in allowed_set]


def _no_store(payload: Any, status: int = 200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/dataset", methods=["GET"])
def api_dataset():
    """分页查询数据集：过滤 → 排序 → 分页，返回干净的扁平 JSON。"""
    raw = _args_mapping(request.args)
    allowed = set(_FILTER_KEYS) | {
        "sort", "page", "page_size", "fields", "include_fundamental", "with_facets",
    }
    unknown = _unknown_keys(raw, allowed)
    if unknown:
        raise ApiError(
            400,
            "存在不认识的查询参数",
            f"未知参数：{', '.join(unknown)}；可用参数：{', '.join(sorted(allowed))}",
        )

    spec = _parse_spec(raw)
    selection = _select(spec)
    items = [_project(row, spec["fields"]) for row in selection["window"]]
    meta = _dataset_meta(selection, spec)

    response = _no_store({"meta": meta, "items": items})
    response.headers["X-Total-Count"] = str(meta["total"])
    return response


@bp.route("/process", methods=["POST"])
def api_process():
    """处理前端请求：screen（选股）/ allocate（组合权重）/ stats（聚合统计）。"""
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError(400, "请求体必须是合法 JSON", "Content-Type 请使用 application/json")
    if not isinstance(payload, Mapping):
        raise ApiError(400, "请求体必须是 JSON 对象", f"收到 {type(payload).__name__}")

    allowed_top = {"operation", "filters", "top_n", "weighting", "max_weight",
                   "sort", "page", "page_size", "fields",
                   "include_fundamental", "with_facets"}
    unknown_top = _unknown_keys(payload, allowed_top)
    if unknown_top:
        raise ApiError(
            400,
            "请求体存在未知字段",
            f"未知字段：{', '.join(unknown_top)}；可用字段：{', '.join(sorted(allowed_top))}",
        )

    operation = (_text(payload.get("operation")) or "screen").lower()
    if operation not in ("screen", "allocate", "stats"):
        raise ApiError(400, f"不支持的 operation: {operation}", "可选 screen / allocate / stats")

    filters = payload.get("filters") or {}
    if not isinstance(filters, Mapping):
        raise ApiError(400, "filters 必须是 JSON 对象", f"收到 {type(filters).__name__}")
    unknown_filters = _unknown_keys(filters, _FILTER_KEYS)
    if unknown_filters:
        raise ApiError(
            400,
            "filters 存在未知字段",
            f"未知字段：{', '.join(unknown_filters)}；可用字段：{', '.join(_FILTER_KEYS)}",
        )

    merged: Dict[str, Any] = dict(filters)
    for key in ("sort", "page", "page_size", "fields", "include_fundamental", "with_facets", "top_n"):
        if key in payload and payload[key] is not None:
            merged[key] = payload[key]

    spec = _parse_spec(merged, for_process=True)
    selection = _select(spec)
    rows = selection["window"]
    items = [_project(row, spec["fields"]) for row in rows]

    result: Dict[str, Any] = {
        "operation": operation,
        "generated_at": _now_iso(),
        "matched": selection["meta"]["total"],
        "selected_count": len(rows),
        "meta": _dataset_meta(selection, spec),
        "stats": _summarize(rows),
        "items": items,
    }

    if operation == "allocate":
        raw_weighting = payload.get("weighting")
        weighting = (_text(raw_weighting) or "equal").lower()
        if weighting not in ("equal", "score", "risk_inverse"):
            raise ApiError(400, f"不支持的 weighting: {weighting}", "可选 equal / score / risk_inverse")
        max_weight_raw = payload.get("max_weight")
        max_weight = 0.25 if max_weight_raw is None else _as_float(max_weight_raw, "max_weight")
        if max_weight is None or max_weight <= 0 or max_weight > 1:
            raise ApiError(400, "参数 max_weight 取值不合法", "应落在 (0, 1] 区间")
        result["allocation"] = _allocate(rows, weighting, max_weight)

    return _no_store(result)


@bp.route("/openapi.json", methods=["GET"])
def api_openapi():
    """OpenAPI 3.0 规格（由 openapi_spec.py 单一来源生成，永远与路由保持一致）。

    直接返回可读的 UTF-8 文本（缩进 2、中文不转义），
    使 ``curl .../api/v1/openapi.json -o openapi.json`` 的结果可以直接提交进仓库。
    """
    response = make_response(render_openapi_json())
    response.mimetype = "application/json"
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------- 统一错误处理


@bp.errorhandler(ApiError)
def _handle_api_error(error: ApiError):
    payload: Dict[str, Any] = {"error": error.message}
    if error.detail:
        payload["detail"] = error.detail
    return _no_store(payload, error.status)


@bp.errorhandler(Exception)
def _handle_unexpected(error: Exception):
    if isinstance(error, HTTPException):
        return _no_store({"error": error.description}, error.code or 500)
    logger.exception("dataset api 未处理异常", exc_info=error)
    return _no_store({"error": "服务器内部错误，请稍后重试"}, 500)
