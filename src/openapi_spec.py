# -*- coding: utf-8 -*-
"""
OpenAPI 3.0 规格 —— Dataset & Process API v1

单一来源：本模块用 Python 字典描述规格，``GET /api/v1/openapi.json`` 在运行时直接返回它，
因此接口文档永远与 dataset_api.py 的路由保持一致，不存在手写 spec 与代码脱节的问题。

需要落成静态文件时执行：
    curl -s http://127.0.0.1:5000/api/v1/openapi.json -o openapi-v1.json
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _num(desc: str, example: Any = None, *, nullable: bool = False,
         fmt: Optional[str] = "double", minimum: Any = None, maximum: Any = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "number", "description": desc}
    if fmt:
        schema["format"] = fmt
    if example is not None:
        schema["example"] = example
    if nullable:
        schema["nullable"] = True
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    return schema


def _int(desc: str, example: Any = None, *, nullable: bool = False) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "integer", "format": "int32", "description": desc}
    if example is not None:
        schema["example"] = example
    if nullable:
        schema["nullable"] = True
    return schema


def _str(desc: str, example: Any = None, *, nullable: bool = False,
         enum: Optional[List[str]] = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "string", "description": desc}
    if example is not None:
        schema["example"] = example
    if nullable:
        schema["nullable"] = True
    if enum:
        schema["enum"] = enum
    return schema


def _bool(desc: str, example: Any = None, *, nullable: bool = False) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "boolean", "description": desc}
    if example is not None:
        schema["example"] = example
    if nullable:
        schema["nullable"] = True
    return schema


def _ref(name: str) -> Dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _arr(desc: str, items: Dict[str, Any], example: Any = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "array", "description": desc, "items": items}
    if example is not None:
        schema["example"] = example
    return schema


SORTABLE_FIELDS = [
    "rank", "code", "name", "trade_date", "total_score", "risk_adjusted_score",
    "fundamental_score", "technical_score", "industry_score", "leading_score",
    "last_close", "change_pct", "volatility_20d_pct", "max_drawdown_60d_pct",
    "return_5d_pct", "up_probability_5d_pct", "rsi14",
]

ROW_FIELDS = [
    "rank", "code", "name", "type", "category", "trade_date", "stale", "scores",
    "market", "risk", "forecast", "technical", "industry", "sector", "signal",
    "fundamental", "reasons",
]


def _query_params() -> List[Dict[str, Any]]:
    return [
        {
            "name": "q", "in": "query", "required": False,
            "description": "关键词模糊匹配：同时匹配股票代码、名称与分类（不区分大小写）。例如 `600519`、`茅台`、`存储`。",
            "schema": {"type": "string", "example": "存储"},
        },
        {
            "name": "codes", "in": "query", "required": False,
            "style": "form", "explode": False,
            "description": "按标的代码精确过滤。多个代码用英文逗号分隔，如 `codes=600519,300750`。",
            "schema": {"type": "array", "items": {"type": "string", "example": "600519"},
                       "example": ["600519", "300750"]},
        },
        {
            "name": "type", "in": "query", "required": False,
            "style": "form", "explode": False,
            "description": "按标的类型过滤。多个类型用英文逗号分隔，如 `type=stock,etf`。",
            "schema": {"type": "array", "items": {"type": "string", "enum": ["stock", "etf"]},
                       "example": ["stock"]},
        },
        {
            "name": "category", "in": "query", "required": False,
            "style": "form", "explode": False,
            "description": "按分类 / 行业过滤（精确匹配）。多个分类用英文逗号分隔；取值可先用 `with_facets=1` 拉取。",
            "schema": {"type": "array", "items": {"type": "string", "example": "存储"},
                       "example": ["存储"]},
        },
        {
            "name": "risk_level", "in": "query", "required": False,
            "style": "form", "explode": False,
            "description": "按风险等级过滤。多个等级用英文逗号分隔，如 `risk_level=low,medium`。",
            "schema": {"type": "array", "items": {"type": "string", "enum": ["low", "medium", "high"]},
                       "example": ["low", "medium"]},
        },
        {
            "name": "trend", "in": "query", "required": False,
            "style": "form", "explode": False,
            "description": (
                "按技术面趋势过滤。多个取值用英文逗号分隔。取值来自数据集自身的技术面判断："
                "`uptrend` 上行、`downtrend` 下行、`range` 区间震荡、`rebound` 反弹；"
                "流水线新增取值时本参数同样接受。可用 `with_facets=1` 获取当前真实分布。"
            ),
            "schema": {"type": "array",
                       "items": {"type": "string", "enum": ["uptrend", "downtrend", "range", "rebound"]},
                       "example": ["uptrend"]},
        },
        {
            "name": "stale", "in": "query", "required": False,
            "description": "是否只看数据过期（`true`）或未过期（`false`）的标的；不传则不过滤。",
            "schema": {"type": "boolean", "example": False},
        },
        {
            "name": "min_score", "in": "query", "required": False,
            "description": "总分（`scores.total`）下限，闭区间。",
            "schema": {"type": "number", "format": "double", "example": 30},
        },
        {
            "name": "max_score", "in": "query", "required": False,
            "description": "总分（`scores.total`）上限，闭区间。",
            "schema": {"type": "number", "format": "double", "example": 60},
        },
        {
            "name": "sort", "in": "query", "required": False,
            "description": (
                "排序字段，默认 `rank` 升序。降序支持 `-total_score` 或 `total_score:desc` 两种写法。"
                f"可排序字段：{', '.join(SORTABLE_FIELDS)}。空值一律排在最后。"
            ),
            "schema": {"type": "string", "default": "rank", "example": "-total_score"},
        },
        {
            "name": "page", "in": "query", "required": False,
            "description": "页码，从 1 开始；超出总页数时自动返回最后一页。",
            "schema": {"type": "integer", "minimum": 1, "default": 1, "example": 1},
        },
        {
            "name": "page_size", "in": "query", "required": False,
            "description": "每页条数，1–200，默认 20。",
            "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20, "example": 20},
        },
        {
            "name": "fields", "in": "query", "required": False,
            "style": "form", "explode": False,
            "description": (
                "字段裁剪：只返回指定顶层字段，逗号分隔，用于减小响应体积。"
                f"可选：{', '.join(ROW_FIELDS)}。\n\n"
                "⚠️ 使用本参数后，`items` 是**稀疏对象**：只有被选中的字段存在，"
                "不再满足 `DatasetRow` 的全部必填约束。前端应把返回项按 `Partial<DatasetRow>` 处理"
                "（本项目 `fetchDataset` 已为重载，传 `fields` 时自动返回 `Partial<DatasetRow>[]`），"
                "不要直接访问未选中的字段。"
            ),
            "schema": {"type": "array", "items": {"type": "string", "example": "code"},
                       "example": ["code", "name", "scores"]},
        },
        {
            "name": "include_fundamental", "in": "query", "required": False,
            "description": "是否附带基本面明细（逐行读取 `docs/data/fundamental/<code>.json`，只读当前页）。默认关闭。",
            "schema": {"type": "boolean", "default": False, "example": True},
        },
        {
            "name": "with_facets", "in": "query", "required": False,
            "description": "是否在 `meta.facets` 中返回各筛选维度的取值分布（基于过滤后的全量结果，不受分页影响），便于前端渲染筛选器。",
            "schema": {"type": "boolean", "default": False, "example": True},
        },
    ]


def render_openapi_json() -> str:
    """把规格序列化成可直接落盘的 UTF-8 JSON 文本。

    - ``ensure_ascii=False``：中文描述原样输出，而不是一堆 ``\\uXXXX``；
    - ``indent=2``：可读、可评审，git diff 只显示真正改动的行；
    - 不排序键：保持 ``openapi → info → servers → tags → paths → components``
      的常规阅读顺序。

    因此 ``curl .../api/v1/openapi.json -o openapi.json`` 拿到的文件，
    与仓库里提交的那一份逐字节一致。
    """
    return json.dumps(build_openapi_spec(), ensure_ascii=False, indent=2) + "\n"


def build_openapi_spec() -> Dict[str, Any]:
    """构建并返回完整的 OpenAPI 3.0.3 规格字典。"""
    schemas: Dict[str, Any] = {
        "Error": {
            "type": "object",
            "description": "统一错误响应体，沿用本项目的既有风格。",
            "required": ["error"],
            "properties": {
                "error": _str("错误描述，可直接展示给用户或用于日志检索。", "参数 page_size 超出取值范围"),
                "detail": _str("可选的补充说明，包含具体取值 / 允许范围等排障信息。", "应在 [1, 200] 之间，收到 500"),
            },
            "example": {"error": "参数 page_size 超出取值范围", "detail": "应在 [1, 200] 之间，收到 500"},
        },
        "Scores": {
            "type": "object",
            "description": "各维度评分。总分 `total` 是前端列表默认的排序依据；缺失维度为 null。",
            "required": ["total", "risk_adjusted", "fundamental", "technical", "industry", "leading"],
            "properties": {
                "total": _num("综合总分（v3 引擎为风险调整后总分），列表默认按它排序。", 45.7, nullable=True),
                "risk_adjusted": _num("风险调整后得分，与总分同源。", 45.7, nullable=True),
                "fundamental": _num("基本面评分（基本面作为门禁，未覆盖时为 null）。", 59.5, nullable=True),
                "technical": _num("技术面评分，0–100。", 100.0, nullable=True),
                "industry": _num("行业轮动评分，0–100。", 57.0, nullable=True),
                "leading": _num("领先指标评分，0–100。", 20.0, nullable=True),
            },
        },
        "Market": {
            "type": "object",
            "nullable": True,
            "description": "行情快照，来自 `docs/data/summary.json`；该标的没有行情记录时为 null。",
            "required": ["last_close", "change_pct", "change_amt", "last_date", "status"],
            "properties": {
                "last_close": _num("最新收盘价（元）。", 351.0, nullable=True),
                "change_pct": _num("最新交易日涨跌幅（%），正数为上涨。", 0.43, nullable=True),
                "change_amt": _num("最新交易日涨跌额（元）。", 1.5, nullable=True),
                "last_date": _str("行情对应交易日（YYYY-MM-DD）。", "2026-09-04", nullable=True),
                "status": _str("行情抓取状态，`ok` 表示正常。", "ok", nullable=True),
            },
        },
        "Risk": {
            "type": "object",
            "description": "风险画像。",
            "required": ["level", "label", "score",
                         "annualized_volatility_20d_pct", "max_drawdown_60d_pct", "atr14_pct"],
            "properties": {
                "level": _str("风险等级；数据缺失时为 `unknown`。", "low",
                              enum=["low", "medium", "high", "unknown"]),
                "label": _str("风险等级的中文标签。", "低风险"),
                "score": _num("风险得分，数值越高代表风险越大。", 19.0, nullable=True),
                "annualized_volatility_20d_pct": _num("20 日年化波动率（%）。", 20.98, nullable=True),
                "max_drawdown_60d_pct": _num("60 日最大回撤（%），通常为负值。", -8.73, nullable=True),
                "atr14_pct": _num("ATR(14) 占价格百分比（%），衡量短期波动。", 1.97, nullable=True),
            },
        },
        "Forecast": {
            "type": "object",
            "description": "短周期收益预测（KNN / 领先指标模型）。",
            "required": ["return_3d_pct", "return_5d_pct", "up_probability_3d_pct",
                         "up_probability_5d_pct", "confidence", "optimal_holding_days"],
            "properties": {
                "return_3d_pct": _num("未来 3 日预测收益率（%）。", -0.37, nullable=True),
                "return_5d_pct": _num("未来 5 日预测收益率（%）。", 0.12, nullable=True),
                "up_probability_3d_pct": _num("未来 3 日上涨概率（%）。", 26.7, nullable=True),
                "up_probability_5d_pct": _num("未来 5 日上涨概率（%）。", 46.7, nullable=True),
                "confidence": _str("预测置信度，`low` / `medium` / `high`。", "medium", nullable=True),
                "optimal_holding_days": _num("模型给出的建议持有天数。", 5.0, nullable=True),
            },
        },
        "Technical": {
            "type": "object",
            "description": "技术面指标。",
            "required": ["trend", "rsi14", "volume_ratio_5d", "return_5d_pct", "return_20d_pct"],
            "properties": {
                "trend": _str("趋势方向。", "uptrend", nullable=True,
                              enum=["uptrend", "downtrend", "range", "rebound", "unknown"]),
                "rsi14": _num("14 日相对强弱指标，0–100，大于 70 通常视为超买。", 74.2, nullable=True),
                "volume_ratio_5d": _num("5 日量比，大于 1 表示放量。", 1.92, nullable=True),
                "return_5d_pct": _num("近 5 日收益率（%）。", 2.51, nullable=True),
                "return_20d_pct": _num("近 20 日收益率（%）。", 1.59, nullable=True),
            },
        },
        "Industry": {
            "type": "object",
            "description": "所属行业 / 板块的相对表现。",
            "required": ["name", "return_5d_pct", "return_20d_pct", "relative_strength_20d_pct"],
            "properties": {
                "name": _str("行业或板块名称。", "农产品大宗", nullable=True),
                "return_5d_pct": _num("行业近 5 日收益率（%）。", -3.02, nullable=True),
                "return_20d_pct": _num("行业近 20 日收益率（%）。", -3.44, nullable=True),
                "relative_strength_20d_pct": _num("相对基准指数的 20 日超额收益（%）。", 16.17, nullable=True),
            },
        },
        "Sector": {
            "type": "object",
            "description": "板块网络（NALE）位置，用于判断标的在产业链中的角色与共振强度。",
            "required": ["name", "tier_role", "breadth_pct", "has_limit_up_resonance", "co_movement_peers"],
            "properties": {
                "name": _str("板块名称。", "贵金属弹性", nullable=True),
                "tier_role": _str("产业链层级角色，如 `core_mid` / `neutral`。", "core_mid", nullable=True),
                "breadth_pct": _num("板块内上涨标的占比（%）。", 100.0, nullable=True),
                "has_limit_up_resonance": _bool("板块内是否存在涨停共振。", False, nullable=True),
                "co_movement_peers": _int("同涨同跌的关联标的数量。", 3, nullable=True),
            },
        },
        "Signal": {
            "type": "object",
            "description": "交易信号与操作建议，前端可直接映射成标签或提示语。",
            "required": ["bet_type", "fundamental_gate_passed", "fundamental_gate_reason",
                         "holding_period", "trade_frequency", "recommendation",
                         "monster_score", "volatility_annual"],
            "properties": {
                "bet_type": _str("赔率类型，如 `range_bound`（震荡）/ `trend_up`（趋势上行）。",
                                 "range_bound", nullable=True),
                "fundamental_gate_passed": _bool("是否通过基本面门禁；未通过通常不建议纳入组合。", True, nullable=True),
                "fundamental_gate_reason": _str("未通过门禁时的原因。", None, nullable=True),
                "holding_period": _int("建议持有天数。", 20, nullable=True),
                "trade_frequency": _str("建议交易频率，`low` / `medium` / `high`。", "medium", nullable=True),
                "recommendation": _str("一句话操作建议。", "震荡股：均值回归或观望，避免追涨杀跌", nullable=True),
                "monster_score": _num("异动强度得分。", 18.8, nullable=True),
                "volatility_annual": _num("年化波动率（小数形式，0.4344 即 43.44%）。", 0.4344, nullable=True),
            },
        },
        "Fundamental": {
            "type": "object",
            "nullable": True,
            "description": "基本面明细，仅当 `include_fundamental=true` 时返回；无数据时为 null。",
            "required": ["score", "report_date", "dimensions", "positive_view", "negative_view"],
            "properties": {
                "score": _num("基本面总分。", 59.5, nullable=True),
                "report_date": _str("财报报告期（YYYY-MM-DD）。", "2026-03-31", nullable=True),
                "dimensions": {
                    "type": "object",
                    "description": "四个基本面维度的得分（0–100）。",
                    "required": ["asset_quality", "liability_safety", "profit_quality", "cash_health"],
                    "properties": {
                        "asset_quality": _num("资产质量得分。", 50.0, nullable=True),
                        "liability_safety": _num("负债安全性得分。", 63.0, nullable=True),
                        "profit_quality": _num("盈利质量得分。", 73.0, nullable=True),
                        "cash_health": _num("现金流健康度得分。", 52.6, nullable=True),
                    },
                },
                "positive_view": _str("正面解读。", "净利润同比 +1.4%", nullable=True),
                "negative_view": _str("反面解读 / 风险提示。", "经营现金流/净利润 0.99，利润兑现存疑", nullable=True),
            },
        },
        "Reason": {
            "type": "object",
            "description": "评分归因明细，解释分数是怎么来的。",
            "required": ["type", "title", "detail", "contribution"],
            "properties": {
                # 不锁枚举：真实数据已出现 positive / negative / warning 与 null，
                # 且流水线会持续新增取值，写死枚举会让前端类型在数据更新后失效。
                "type": _str("归因方向。当前数据集出现 positive / negative / warning，可能为 null；"
                             "流水线新增取值时同样返回。",
                             "positive", nullable=True),
                "title": _str("归因标题。", "中短期趋势向上"),
                "detail": _str("归因说明。", "收盘价位于20日和60日均线上方。"),
                "contribution": _num("对总分的贡献值，负数为扣分。", 8.0, nullable=True),
            },
        },
        "DatasetRow": {
            "type": "object",
            "description": (
                "数据集中的一行（一只标的）。由排行榜主表、行情快照与基本面按 code 关联后"
                "扁平化得到；所有缺失值统一为 null，浮点数已定点到两位小数。"
            ),
            "required": ["rank", "code", "name", "type", "category", "trade_date", "stale",
                         "scores", "market", "risk", "forecast", "technical", "industry",
                         "sector", "signal", "fundamental", "reasons"],
            "properties": {
                "rank": _int("榜单排名，从 1 开始。", 1),
                "code": _str("标的代码，如 600519 / 510300 / MU。", "159562"),
                "name": _str("标的名称。", "黄金股ETF"),
                "type": _str("标的类型。", "etf", enum=["stock", "etf"]),
                "category": _str("分类 / 行业标签。", "贵金属弹性"),
                "trade_date": _str("评分对应的交易日（YYYY-MM-DD）。", "2026-09-04"),
                "stale": _bool("该行数据是否已过期（当日流水线未更新则为 true）。", False),
                "scores": _ref("Scores"),
                "market": _ref("Market"),
                "risk": _ref("Risk"),
                "forecast": _ref("Forecast"),
                "technical": _ref("Technical"),
                "industry": _ref("Industry"),
                "sector": _ref("Sector"),
                "signal": _ref("Signal"),
                "fundamental": _ref("Fundamental"),
                "reasons": _arr("评分归因列表。", _ref("Reason")),
            },
        },
        "FacetValue": {
            "type": "object",
            "description": "筛选维度的一个取值及其命中数量。",
            "required": ["value", "count"],
            "properties": {
                "value": _str("取值。", "存储"),
                "count": _int("命中的标的数量。", 9),
            },
        },
        "Facets": {
            "type": "object",
            "description": "筛选器取值分布，基于过滤后的全量结果（不受分页影响），按数量降序。",
            "required": ["type", "category", "risk_level", "trend"],
            "properties": {
                "type": _arr("标的类型分布。", _ref("FacetValue")),
                "category": _arr("分类分布。", _ref("FacetValue")),
                "risk_level": _arr("风险等级分布。", _ref("FacetValue")),
                "trend": _arr("趋势分布。", _ref("FacetValue")),
            },
        },
        "DatasetFilter": {
            "type": "object",
            "description": "过滤条件，字段与 `GET /api/v1/dataset` 的查询参数一一对应。",
            "properties": {
                "q": _str("关键词，匹配代码、名称或分类。", "存储"),
                "codes": _arr("标的代码白名单。", {"type": "string", "example": "600519"},
                              ["600519", "300750"]),
                "type": _arr("标的类型白名单。", {"type": "string", "enum": ["stock", "etf"]}, ["stock"]),
                "category": _arr("分类白名单（精确匹配）。", {"type": "string", "example": "存储"}, ["存储", "科技"]),
                "risk_level": _arr("风险等级白名单。", {"type": "string", "enum": ["low", "medium", "high"]}, ["low"]),
                "trend": _arr("趋势白名单。", {"type": "string", "enum": ["uptrend", "downtrend", "range", "rebound"]},
                              ["uptrend"]),
                "stale": _bool("只保留已过期 / 未过期的数据。", False),
                "min_score": _num("总分下限。", 30),
                "max_score": _num("总分上限。", 60),
            },
        },
        "DatasetMeta": {
            "type": "object",
            "description": "分页与数据源元信息。",
            "required": ["source", "trade_date", "generated_at", "sort", "filters",
                         "total", "page", "page_size", "total_pages", "has_next", "has_prev", "returned"],
            "properties": {
                "source": _str("主表相对路径。", "analysis/ranking_v3.json"),
                "trade_date": _str("数据集对应的交易日。", "2026-09-04"),
                "generated_at": _str("流水线生成该数据集的时间。", "2026-09-06 00:17:35+08:00"),
                "engine": _str("生成该数据集的引擎版本。", "v3.0-leading-first"),
                "formula": _str("总分计算公式说明。", "Opportunity = 0.45*Leading + 0.30*KNN + 0.25*Tech, Fundamental=Gatekeeper"),
                "sort": _str("实际生效的排序，格式为 `字段:方向`。", "rank:asc"),
                "filters": {"type": "object", "description": "回显本次生效的过滤条件，便于前端对齐状态。",
                            "additionalProperties": True},
                "total": _int("过滤后的命中总条数（不受分页影响）。", 156),
                "page": _int("当前页码（超出总页数时已被收敛到最后一页）。", 1),
                "page_size": _int("每页条数。", 20),
                "total_pages": _int("总页数。", 8),
                "has_next": _bool("是否存在下一页。", True),
                "has_prev": _bool("是否存在上一页。", False),
                "returned": _int("本页实际返回的条数。", 20),
                "facets": _ref("Facets"),
            },
        },
        "DatasetResponse": {
            "type": "object",
            "description": "分页数据集响应。",
            "required": ["meta", "items"],
            "properties": {
                "meta": _ref("DatasetMeta"),
                "items": _arr("当前页的数据行。", _ref("DatasetRow")),
            },
        },
        "Describe": {
            "type": "object",
            "nullable": True,
            "description": "一组数值的分布摘要；无有效数值时为 null。",
            "required": ["avg", "median", "min", "max"],
            "properties": {
                "avg": _num("平均值。", 27.34),
                "median": _num("中位数。", 25.9),
                "min": _num("最小值。", 3.2),
                "max": _num("最大值。", 45.7),
            },
        },
        "CategoryStat": {
            "type": "object",
            "description": "分类维度的统计结果。",
            "required": ["category", "count", "avg_score"],
            "properties": {
                "category": _str("分类名称。", "存储"),
                "count": _int("该分类下命中的标的数量。", 9),
                "avg_score": _num("该分类下的平均总分。", 23.4, nullable=True),
            },
        },
        "Stats": {
            "type": "object",
            "description": "对选中标的的聚合统计，用于面板顶部的总览卡片。",
            "required": ["count", "risk_level_distribution", "type_distribution",
                         "trend_distribution", "category_top", "stale_count"],
            "properties": {
                "count": _int("参与统计的标的数量。", 10),
                "score": _ref("Describe"),
                "risk_score": _ref("Describe"),
                "volatility_20d_pct": _ref("Describe"),
                "max_drawdown_60d_pct": _ref("Describe"),
                "forecast": {
                    "type": "object",
                    "description": "预测维度的统计摘要。",
                    "properties": {
                        "return_5d_pct": _ref("Describe"),
                        "up_probability_5d_pct": _ref("Describe"),
                    },
                },
                "risk_level_distribution": _arr("风险等级分布。", _ref("FacetValue")),
                "type_distribution": _arr("标的类型分布。", _ref("FacetValue")),
                "trend_distribution": _arr("趋势分布。", _ref("FacetValue")),
                "category_top": _arr("分类统计，按数量降序取前 10。", _ref("CategoryStat")),
                "stale_count": _int("其中数据已过期的标的数量。", 0),
            },
        },
        "Position": {
            "type": "object",
            "description": "组合中的一个持仓建议。",
            "required": ["code", "name", "category", "weight", "amount_pct",
                         "score", "risk_level", "volatility_20d_pct"],
            "properties": {
                "code": _str("标的代码。", "159562"),
                "name": _str("标的名称。", "黄金股ETF"),
                "category": _str("分类 / 行业。", "贵金属弹性"),
                "weight": _num("目标权重（0–1 的小数）。", 0.125),
                "amount_pct": _num("目标权重（百分比形式，便于直接展示）。", 12.5),
                "score": _num("该标的的总分。", 45.7, nullable=True),
                "risk_level": _str("风险等级。", "low"),
                "volatility_20d_pct": _num("20 日年化波动率（%）。", 20.98, nullable=True),
            },
        },
        "Allocation": {
            "type": "object",
            "description": "组合权重分配结果（仅 `operation=allocate` 返回）。",
            "required": ["method", "max_weight", "invested_weight", "cash_weight", "positions", "notes"],
            "properties": {
                "method": _str("权重方法。", "score", enum=["equal", "score", "risk_inverse"]),
                "max_weight": _num("单标的上限。", 0.25),
                "invested_weight": _num("已分配的总权重，正常情况下为 1。", 1.0),
                "cash_weight": _num("剩余现金权重；因上限约束无法满仓时大于 0。", 0.0),
                "positions": _arr("持仓建议，按权重降序。", _ref("Position")),
                "notes": _arr("分配过程中的提示，例如上限约束不可行时的说明。", {"type": "string"},
                              ["标的数量不足，无法在 max_weight=0.05 下用满仓位，剩余记为现金"]),
            },
        },
        "ProcessRequest": {
            "type": "object",
            "description": (
                "处理请求。`operation=screen` 只做筛选排序；`allocate` 额外给出组合权重；"
                "`stats` 只看聚合统计。三者共用同一套数据集逻辑，结果口径完全一致。"
            ),
            "properties": {
                "operation": _str("处理类型，默认 `screen`。", "allocate",
                                  enum=["screen", "allocate", "stats"]),
                "filters": _ref("DatasetFilter"),
                "top_n": _int("取前 N 只标的，1–200，默认 20。", 10),
                "weighting": _str(
                    "权重方法，仅 `allocate` 有效：`equal` 等权、`score` 按总分比例、"
                    "`risk_inverse` 按波动率倒数（风险平价）。",
                    "risk_inverse", enum=["equal", "score", "risk_inverse"],
                ),
                "max_weight": _num("单标的上限（0–1]，默认 0.25；超出部分按比例回填给未触顶的标的。", 0.25),
                "sort": _str("排序字段，写法同 GET 接口的 `sort`。", "-total_score"),
                "fields": _arr("字段裁剪，只返回指定顶层字段。", {"type": "string", "example": "code"},
                               ["code", "name", "scores", "risk"]),
                "include_fundamental": _bool("是否附带基本面明细。", False),
                "with_facets": _bool("是否在 meta 中返回筛选器取值分布。", False),
            },
            "example": {
                "operation": "allocate",
                "filters": {"type": ["stock"], "risk_level": ["low", "medium"], "min_score": 30},
                "top_n": 10,
                "weighting": "risk_inverse",
                "max_weight": 0.25,
            },
        },
        "ProcessResponse": {
            "type": "object",
            "description": "处理结果。",
            "required": ["operation", "generated_at", "matched", "selected_count",
                         "meta", "stats", "items"],
            "properties": {
                "operation": _str("本次实际执行的 operation（已回显）。", "allocate"),
                "generated_at": _str("服务端处理时间（ISO 8601，带时区）。", "2026-09-27T12:00:00+08:00"),
                "matched": _int("过滤后命中的总条数。", 42),
                "selected_count": _int("本次实际送入处理的条数（≤ top_n）。", 10),
                "meta": _ref("DatasetMeta"),
                "stats": _ref("Stats"),
                "allocation": _ref("Allocation"),
                "items": _arr("选中的标的行，结构与 GET 接口一致。", _ref("DatasetRow")),
            },
        },

        # ---------------- 首页视图模型（GET /api/v1/homepage） ----------------
        "HeroMetric": {
            "type": "object",
            "description": "Hero 区的一项核心指标。数值已由后端格式化，前端直接渲染。",
            "required": ["id", "icon", "label", "value", "tone", "caption"],
            "properties": {
                "id": _str("指标标识，用于 React key 与埋点。", "safety"),
                "icon": _str("图标类型。", "shield", enum=["shield", "rise"]),
                "label": _str("指标名称。", "资产安全评级"),
                "value": _str("指标展示值（字符串，含符号与单位）。", "AAA"),
                "tone": _str("语义色，对应前端五色系统。", "green",
                             enum=["green", "red", "blue", "gold", "orange"]),
                "caption": _str("指标补充说明。", "极高防御"),
                "tip": _str("悬浮提示：该指标的计算口径。",
                            "按组合年化波动率与历史最大回撤映射：回撤 ≤5% 且波动 ≤15% 为 AAA"),
            },
        },
        "HealthGauge": {
            "type": "object",
            "description": "资产健康晴雨表：由市场温度模型推导的建议仓位。",
            "required": ["title", "level", "desc", "percent"],
            "properties": {
                "title": _str("卡片标题。", "资产健康晴雨表"),
                "level": _str("仪表主结论。", "市场温度 70.2"),
                "desc": _str("补充说明。", "正常 ｜ 建议仓位 75.3%"),
                "percent": _num("防御充分度 0–1，决定仪表绿色弧线长度。", 0.753),
                "tip": _str("悬浮提示。", "由市场温度模型给出的建议仓位比例，越高代表防御系统越有加仓空间"),
            },
        },
        "HeroBlock": {
            "type": "object",
            "description": "02 Hero 区块。",
            "required": ["title", "subtitle", "metrics", "gauge"],
            "properties": {
                "title": _str("主标题。", "您好！让财富为您的晚年生活保驾护航"),
                "subtitle": _str("副标题。", "专业的养老金融解决方案，稳健增值，安心相伴"),
                "metrics": _arr("三项核心指标。", _ref("HeroMetric")),
                "gauge": _ref("HealthGauge"),
            },
        },
        "CurveSeries": {
            "type": "object",
            "description": "一条收益曲线。",
            "required": ["name", "returnLabel", "series"],
            "properties": {
                "name": _str("曲线名称（组合名 / 基准名）。", "稳健组合-防守型"),
                "returnLabel": _str("区间收益的展示文案。", "+12.63%"),
                "returnPct": _num("区间累计收益率（%）。", 12.63, nullable=True),
                "series": _arr("与 equityCurve.dates 等长的累计收益率（%）。",
                               {"type": "number", "format": "double", "example": 5.37}),
            },
        },
        "BenchmarkSeries": {
            "type": "object",
            "description": "基准收益曲线。相比 CurveSeries 多一个必填的 note 标注。",
            "required": ["name", "note", "returnLabel", "series"],
            "properties": {
                "name": _str("基准名称。", "全池等权基准"),
                "note": _str("基准的补充标注。", "同期"),
                "returnLabel": _str("区间收益的展示文案。", "-6.20%"),
                "returnPct": _num("区间累计收益率（%）。", -6.2, nullable=True),
                "series": _arr("与 equityCurve.dates 等长的累计收益率（%）。",
                               {"type": "number", "format": "double", "example": 1.8}),
            },
        },
        "CurveStats": {
            "type": "object",
            "description": "组合风险指标，用于填充 Hero 的三项指标。",
            "required": ["maxDrawdownPct", "volatilityPct", "excessPct", "samples", "convention"],
            "properties": {
                "maxDrawdownPct": _num("区间最大回撤（%，非正数）。", -4.22, nullable=True),
                "volatilityPct": _num("年化波动率（%），按 252 个交易日。", 14.38, nullable=True),
                "excessPct": _num("相对同期基准的超额收益（%）。", 18.83, nullable=True),
                "samples": _int("返回的采样点数。", 21),
                "convention": _str("累计收益口径。", "running_sum_of_daily_returns"),
            },
        },
        "EquityCurveBlock": {
            "type": "object",
            "description": "03 绝对收益曲线区块。累计收益沿用项目既有口径：对日收益率做累加。",
            "required": ["dates", "portfolio", "benchmark"],
            "properties": {
                "dates": _arr("X 轴日期标签（MM-DD）。", {"type": "string", "example": "06-01"}),
                "portfolio": _ref("CurveSeries"),
                "benchmark": _ref("BenchmarkSeries"),
                "stats": _ref("CurveStats"),
            },
        },
        "AllocationSegment": {
            "type": "object",
            "description": "资产配置环图的一段（一只持仓或现金）。",
            "required": ["key", "name", "weight", "color"],
            "properties": {
                "key": _str("分段标识，持仓为标的代码，现金为 `cash`。", "300750"),
                "name": _str("分段名称。", "宁德时代"),
                "weight": _num("权重（%），所有分段合计精确等于 100。", 18.1),
                "color": _str("分段颜色（十六进制）。", "#F08634"),
                "reason": _str("入选理由（来自分片数据）。", "综合分54.3 | 风险33 | 波动平价11.4%", nullable=True),
            },
        },
        "CashNote": {
            "type": "object",
            "description": "现金策略说明面板。",
            "required": ["title", "body", "details"],
            "properties": {
                "title": _str("面板标题。", "为什么留 36% 现金？"),
                "body": _str("正文。", "当前现金 360,000 元，占总资产 36.0%。因为要确保您随时有应急资金，且在市场风险期不上杠杆。"),
                "details": _arr("展开后的补充说明。", {"type": "string", "example": "应急储备：突发医疗或家庭支出时无需被动赎回。"}),
            },
        },
        "RiskEvent": {
            "type": "object",
            "description": "05 产业链避险的一张事件卡。",
            "required": ["id", "tone", "icon", "title", "timeAgo", "content"],
            "properties": {
                "id": _str("事件标识。", "sentiment-watch"),
                "tone": _str("语义色。", "green", enum=["green", "red", "blue", "gold", "orange"]),
                "icon": _str("图标类型。", "shield", enum=["shield", "arrowUp"]),
                "title": _str("事件标题。", "情绪面监测"),
                "timeAgo": _str("相对时间文案。", "1个月前"),
                "content": _str("事件正文。", "已跟踪 144 个事件样本：正向超预期 26 次、负向意外 10 次，整体情绪偏中性。"),
            },
        },
        "StrategyRow": {
            "type": "object",
            "description": "单个策略的表现（来自 quantitative/latest_evolution.json）。",
            "required": ["key", "name", "cumulativeReturnPct", "sharpe", "maxDrawdownPct",
                         "winRatePct", "score", "tradingDays", "isChampion", "rank", "rankText"],
            "properties": {
                "key": _str("策略标识。", "aggressive_v2"),
                "name": _str("策略显示名。", "动态止盈止损优化版"),
                "cumulativeReturnPct": _num("累计收益率（%）。", 6.52, nullable=True),
                "sharpe": _num("夏普比率。", 0.55, nullable=True),
                "maxDrawdownPct": _num("最大回撤（%）。", 1.25, nullable=True),
                "winRatePct": _num("胜率（%）。", 57.1, nullable=True),
                "score": _num("综合评分，策略排名的依据。", 10.61, nullable=True),
                "tradingDays": _int("回测交易日数。", 7, nullable=True),
                "isChampion": _bool("是否为当周冠军策略。", True),
                "rank": _int("排名（从 1 开始）。", 1),
                "rankText": _str("排名的展示文案。", "1/15"),
            },
        },
        "StrategyNavSeries": {
            "type": "object",
            "description": "策略净值曲线的一条序列。",
            "required": ["key", "label", "color", "series", "returnPct"],
            "properties": {
                "key": _str("序列标识。", "nav_dynamic_alpha_tnale"),
                "label": _str("序列显示名。", "动态 Alpha"),
                "color": _str("线色（十六进制）。", "#E9A93B"),
                "series": _arr("与 expert.nav.dates 等长的累计收益率（%）。",
                               {"type": "number", "format": "double", "example": 148.68}),
                "returnPct": _num("区间累计收益率（%）。", 169.16, nullable=True),
            },
        },
        "CorrelationMatrix": {
            "type": "object",
            "description": "相关性矩阵：由策略日收益现算，N×N 对称，主对角线为 1。",
            "required": ["labels", "matrix"],
            "properties": {
                "labels": _arr("行列标签。", {"type": "string", "example": "动态 Alpha"}),
                "matrix": _arr("相关系数矩阵，取值 -1 ~ 1。",
                               _arr("一行。", {"type": "number", "format": "double", "example": 0.9387})),
            },
        },
        "ExpertBlock": {
            "type": "object",
            "description": "06 机构量化研报模式（策略表现）区块。",
            "required": ["strategies", "strategyTotal", "nav", "correlation"],
            "properties": {
                "strategies": _arr("策略对比表（按综合评分降序，取前 4）。", _ref("StrategyRow")),
                "strategyTotal": _int("参与排名的策略总数。", 15),
                "nav": {
                    "type": "object",
                    "description": "策略净值走势。",
                    "required": ["dates", "series"],
                    "properties": {
                        "dates": _arr("X 轴日期标签（MM-DD）。", {"type": "string", "example": "03-26"}),
                        "series": _arr("策略与基准的净值序列。", _ref("StrategyNavSeries")),
                    },
                },
                # 回测数据缺失时返回 null，前端需按可空处理。
                # $ref 在同级不能带 nullable（3.0 会忽略兄弟键），故用 allOf 包裹。
                "correlation": {"allOf": [_ref("CorrelationMatrix")], "nullable": True},
            },
        },
        "HomepageResponse": {
            "type": "object",
            "description": (
                "首页视图模型：一次请求返回 02–06 五个区块的全部动态数据。\n\n"
                "字段与前端各组件的 props 一一对应，前端取到后可直接下传，"
                "不必在浏览器里再做聚合。任一数据源缺失时对应区块退化为空/兜底值，"
                "而不是整页 500。"
            ),
            "required": ["generated_at", "hero", "equityCurve", "allocation", "cashNote", "riskEvents", "expert"],
            "properties": {
                "generated_at": _str("服务端组装时间（ISO 8601，带时区）。", "2026-09-27T14:05:00+08:00"),
                "hero": _ref("HeroBlock"),
                "equityCurve": _ref("EquityCurveBlock"),
                "allocation": _arr("资产配置分段（持仓 + 现金），权重合计 100。", _ref("AllocationSegment")),
                "cashNote": _ref("CashNote"),
                "riskEvents": _arr("产业链避险事件卡（最多 3 张）。", _ref("RiskEvent")),
                "expert": _ref("ExpertBlock"),
                "meta": {
                    "type": "object",
                    "description": "采样参数与数据来源，便于排查数字出处。",
                    "properties": {
                        "points": _int("收益曲线采样点数。", 21),
                        "sources": {"type": "object", "description": "各区块的数据来源文件（区块名 → 文件路径）。",
                                    "additionalProperties": {"type": "string"}},
                    },
                },
            },
        },
    }

    error_examples = {
        "invalidPageSize": {
            "summary": "分页参数越界",
            "value": {"error": "参数 page_size 超出取值范围", "detail": "应在 [1, 200] 之间，收到 500"},
        },
        "unknownSort": {
            "summary": "排序字段不可用",
            "value": {"error": "参数 sort 指定的字段不可排序",
                      "detail": "'roi' 不在可排序字段内：change_pct, code, ..."},
        },
        "unknownOperation": {
            "summary": "operation 取值不支持",
            "value": {"error": "不支持的 operation: backtest", "detail": "可选 screen / allocate / stats"},
        },
        "serverError": {
            "summary": "数据集文件缺失或损坏",
            "value": {"error": "服务器内部错误，请稍后重试"},
        },
    }

    bad_request = {
        "description": "请求参数不合法（取值越界、字段未知、JSON 格式错误等）。",
        "content": {"application/json": {"schema": _ref("Error"), "examples": error_examples}},
    }
    server_error = {
        "description": "服务端内部错误（如数据集文件缺失 / 损坏）。错误信息已脱敏。",
        "content": {"application/json": {
            "schema": _ref("Error"),
            "examples": {"serverError": error_examples["serverError"]},
        }},
    }

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Rainbow-FinGPT API v1",
            "version": "1.0.0",
            "description": (
                "Rainbow-FinGPT 看板的面向前端接口，共三类：\n\n"
                "- `GET /api/v1/homepage`：首页视图模型（BFF），一次请求返回 Hero、收益曲线、"
                "资产配置、风险事件与策略表现五个区块。\n"
                "- `GET /api/v1/dataset`：数据集过滤 → 排序 → 分页，返回扁平化的干净 JSON。\n"
                "- `POST /api/v1/process`：在服务端完成选股（screen）、组合权重分配（allocate）与聚合统计（stats）。\n\n"
                "错误响应统一为 `{\"error\": \"...\", \"detail\": \"...\"}`；成功响应统一带 `Cache-Control: no-store`。\n"
                "CORS 由 Flask-CORS 统一配置，白名单通过环境变量 `CORS_ORIGINS` 覆盖。\n\n"
                "本文件由 `src/openapi_spec.py` 单一来源生成，`GET /api/v1/openapi.json` 返回的内容"
                "与它逐字节一致，可直接落盘提交。"
            ),
            "contact": {"name": "Rainbow-FinGPT 后端团队", "email": "dev@example.com"},
            "license": {"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
        },
        "servers": [
            {"url": "http://127.0.0.1:5000", "description": "本地开发（python src/server.py）"},
            {"url": "http://127.0.0.1:5001", "description": "本地双进程模式（python start_local.py）"},
            {"url": "https://yuxuanwucn-stock-dashboard-api.onrender.com", "description": "在线演示环境"},
        ],
        "tags": [
            {"name": "Homepage", "description": "首页视图模型（BFF）"},
            {"name": "Dataset", "description": "数据集的分页查询"},
            {"name": "Process", "description": "前端提交的处理请求"},
            {"name": "Meta", "description": "接口元信息"},
        ],
        "paths": {
            "/api/v1/dataset": {
                "get": {
                    "tags": ["Dataset"],
                    "summary": "分页查询数据集",
                    "operationId": "listDataset",
                    "description": (
                        "主表为 `docs/data/analysis/ranking_v3.json`（缺失时回退 v2），"
                        "并与 `summary.json` 的行情快照按 `code` 关联。\n\n"
                        "分页语义：先过滤，再排序，最后分页；`meta.total` 始终是过滤后的命中总数，"
                        "响应头同时带 `X-Total-Count`。页码超出范围时自动收敛到最后一页。"
                    ),
                    "parameters": _query_params(),
                    "responses": {
                        "200": {
                            "description": "查询成功。",
                            "headers": {
                                "X-Total-Count": {
                                    "description": "过滤后的命中总条数，便于前端做分页器。",
                                    "schema": {"type": "integer", "example": 156},
                                },
                            },
                            "content": {
                                "application/json": {
                                    "schema": _ref("DatasetResponse"),
                                    "examples": {
                                        "defaultPage": {
                                            "summary": "默认查询（按排名升序，每页 20 条）",
                                            "value": {
                                                "meta": {
                                                    "source": "analysis/ranking_v3.json",
                                                    "trade_date": "2026-09-04",
                                                    "generated_at": "2026-09-06 00:17:35+08:00",
                                                    "engine": "v3.0-leading-first",
                                                    "sort": "rank:asc",
                                                    "total": 156,
                                                    "page": 1,
                                                    "page_size": 20,
                                                    "total_pages": 8,
                                                    "has_next": True,
                                                    "has_prev": False,
                                                    "returned": 20,
                                                },
                                                "items": [
                                                    {
                                                        "rank": 1,
                                                        "code": "159562",
                                                        "name": "黄金股ETF",
                                                        "type": "etf",
                                                        "category": "贵金属弹性",
                                                        "trade_date": "2026-09-04",
                                                        "stale": False,
                                                        "scores": {
                                                            "total": 45.7, "risk_adjusted": 45.7,
                                                            "fundamental": None, "technical": 100.0,
                                                            "industry": 57.0, "leading": 20.0,
                                                        },
                                                        "market": {
                                                            "last_close": 1.372, "change_pct": 1.25,
                                                            "change_amt": 0.017, "last_date": "2026-09-04",
                                                            "status": "ok",
                                                        },
                                                        "risk": {
                                                            "level": "low", "label": "低风险", "score": 19.0,
                                                            "annualized_volatility_20d_pct": 20.98,
                                                            "max_drawdown_60d_pct": -8.73, "atr14_pct": 1.97,
                                                        },
                                                        "technical": {
                                                            "trend": "uptrend", "rsi14": 74.2,
                                                            "volume_ratio_5d": 1.92,
                                                            "return_5d_pct": 2.51, "return_20d_pct": 1.59,
                                                        },
                                                        "signal": {
                                                            "bet_type": "range_bound",
                                                            "fundamental_gate_passed": True,
                                                            "holding_period": 20,
                                                            "trade_frequency": "medium",
                                                            "recommendation": "震荡股：均值回归或观望，避免追涨杀跌",
                                                        },
                                                    },
                                                ],
                                            },
                                        },
                                        "filteredWithFacets": {
                                            "summary": "按关键词与风险等级过滤，并返回筛选器取值分布",
                                            "value": {
                                                "meta": {
                                                    "sort": "total_score:desc",
                                                    "total": 9,
                                                    "page": 1,
                                                    "page_size": 20,
                                                    "total_pages": 1,
                                                    "has_next": False,
                                                    "has_prev": False,
                                                    "returned": 9,
                                                    "facets": {
                                                        "type": [{"value": "stock", "count": 9}],
                                                        "category": [{"value": "存储", "count": 9}],
                                                        "risk_level": [{"value": "medium", "count": 6},
                                                                       {"value": "high", "count": 3}],
                                                        "trend": [{"value": "uptrend", "count": 5},
                                                                  {"value": "sideways", "count": 4}],
                                                    },
                                                },
                                                "items": [],
                                            },
                                        },
                                    },
                                },
                            },
                        },
                        "400": bad_request,
                        "500": server_error,
                    },
                },
            },
            "/api/v1/process": {
                "post": {
                    "tags": ["Process"],
                    "summary": "处理前端请求（选股 / 组合权重 / 统计）",
                    "operationId": "processDataset",
                    "description": (
                        "接收前端提交的处理规格，在服务端调用与 `GET /api/v1/dataset` 完全相同的数据集逻辑，"
                        "返回筛选结果、聚合统计，以及（可选）组合权重。\n\n"
                        "- `screen`：只返回按规则选出的标的。\n"
                        "- `allocate`：在 screen 基础上给出权重（等权 / 按分数 / 按波动率倒数），并支持单标的上限约束。\n"
                        "- `stats`：只返回聚合统计，适合概览面板。\n\n"
                        "请求体中出现未知字段会直接返回 400，避免前端拼错字段后静默失效。"
                    ),
                    "requestBody": {
                        "required": True,
                        "description": "处理规格。至少要提供 `operation` 或一个过滤条件；空对象 `{}` 等价于对全量数据集做 screen。",
                        "content": {
                            "application/json": {
                                "schema": _ref("ProcessRequest"),
                                "examples": {
                                    "allocate": {
                                        "summary": "在低/中风险标的中选 10 只做风险平价组合",
                                        "value": {
                                            "operation": "allocate",
                                            "filters": {"risk_level": ["low", "medium"], "min_score": 30},
                                            "top_n": 10,
                                            "weighting": "risk_inverse",
                                            "max_weight": 0.25,
                                        },
                                    },
                                    "screen": {
                                        "summary": "只做选股，按总分降序取前 5",
                                        "value": {
                                            "operation": "screen",
                                            "filters": {"q": "存储", "type": ["stock"]},
                                            "sort": "-total_score",
                                            "top_n": 5,
                                        },
                                    },
                                    "stats": {
                                        "summary": "只看全量数据集的聚合统计",
                                        "value": {"operation": "stats", "filters": {}},
                                    },
                                },
                            },
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "处理成功。",
                            "content": {
                                "application/json": {
                                    "schema": _ref("ProcessResponse"),
                                    "examples": {
                                        "allocated": {
                                            "summary": "组合权重分配结果",
                                            "value": {
                                                "operation": "allocate",
                                                "generated_at": "2026-09-27T12:00:00+08:00",
                                                "matched": 42,
                                                "selected_count": 3,
                                                "meta": {"source": "analysis/ranking_v3.json",
                                                         "trade_date": "2026-09-04", "total": 42,
                                                         "page": 1, "page_size": 3, "total_pages": 14},
                                                "stats": {
                                                    "count": 3,
                                                    "score": {"avg": 38.5, "median": 37.2, "min": 33.1, "max": 45.7},
                                                    "risk_level_distribution": [{"value": "low", "count": 2},
                                                                                 {"value": "medium", "count": 1}],
                                                    "category_top": [
                                                        {"category": "贵金属弹性", "count": 1, "avg_score": 45.7},
                                                        {"category": "农产品大宗", "count": 1, "avg_score": 43.5},
                                                    ],
                                                    "stale_count": 0,
                                                },
                                                "allocation": {
                                                    "method": "risk_inverse",
                                                    "max_weight": 0.25,
                                                    "invested_weight": 1.0,
                                                    "cash_weight": 0.0,
                                                    "positions": [
                                                        {"code": "159562", "name": "黄金股ETF",
                                                         "category": "贵金属弹性", "weight": 0.35,
                                                         "amount_pct": 35.0, "score": 45.7,
                                                         "risk_level": "low",
                                                         "volatility_20d_pct": 20.98},
                                                        {"code": "159985", "name": "豆粕ETF",
                                                         "category": "农产品大宗", "weight": 0.33,
                                                         "amount_pct": 33.0, "score": 43.5,
                                                         "risk_level": "low",
                                                         "volatility_20d_pct": 21.4},
                                                    ],
                                                    "notes": [],
                                                },
                                                "items": [],
                                            },
                                        },
                                    },
                                },
                            },
                        },
                        "400": bad_request,
                        "500": server_error,
                    },
                },
            },
            "/api/v1/homepage": {
                "get": {
                    "tags": ["Homepage"],
                    "summary": "获取首页视图模型",
                    "operationId": "getHomepage",
                    "description": (
                        "把散落在 `docs/data/**` 的组合净值、基准、资产配置、风险事件与策略表现，"
                        "组装成整页视图模型（BFF），前端一次请求即可渲染首页 02–06 全部区块。\n\n"
                        "口径说明：累计收益沿用项目既有约定 —— 对日收益率做**累加**"
                        "（`benchmark.json` 的 `cumulative_return_pct` 即 Σ `daily_return_pct`，"
                        "实测 −6.18% ≈ 累加值 −6.20%）；策略净值序列以 1.0 为初始本金，"
                        "收益率 = (nav − 1) × 100，与 `metrics_version_*.total_return_pct` 一致。\n\n"
                        "注意：`performance.json` 里的 `history[].total_return` 是**基准**的累计曲线，"
                        "不是组合曲线；本接口取 `records[].portfolio_return_pct` 作为组合。"
                    ),
                    "parameters": [
                        {
                            "name": "points", "in": "query", "required": False,
                            "description": "收益曲线的采样点数，8–120，默认 21（与设计稿的 7 个 X 轴刻度对齐）。",
                            "schema": {"type": "integer", "minimum": 8, "maximum": 120,
                                       "default": 21, "example": 21},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "首页视图模型。",
                            "content": {
                                "application/json": {
                                    "schema": _ref("HomepageResponse"),
                                    "examples": {
                                        "default": {
                                            "summary": "真实数据（2026-09-04 收盘口径）",
                                            "value": {
                                                "generated_at": "2026-09-27T14:05:00+08:00",
                                                "hero": {
                                                    "title": "您好！让财富为您的晚年生活保驾护航",
                                                    "subtitle": "专业的养老金融解决方案，稳健增值，安心相伴",
                                                    "metrics": [
                                                        {"id": "safety", "icon": "shield",
                                                         "label": "资产安全评级", "value": "AAA",
                                                         "tone": "green", "caption": "极高防御"},
                                                        {"id": "drawdown-resist", "icon": "rise",
                                                         "label": "震荡市抗跌实绩", "value": "+18.83%",
                                                         "tone": "red", "caption": "组合相对同期基准的超额收益"},
                                                        {"id": "max-drawdown", "icon": "shield",
                                                         "label": "历史最大回撤控制", "value": "4.22%",
                                                         "tone": "blue", "caption": "净值自区间高点的最大跌幅"},
                                                    ],
                                                    "gauge": {
                                                        "title": "资产健康晴雨表",
                                                        "level": "市场温度 70.2",
                                                        "desc": "正常 ｜ 建议仓位 75.3%",
                                                        "percent": 0.753,
                                                    },
                                                },
                                                "equityCurve": {
                                                    "dates": ["06-01", "06-04", "06-10"],
                                                    "portfolio": {
                                                        "name": "稳健组合-防守型",
                                                        "returnLabel": "+12.63%",
                                                        "returnPct": 12.63,
                                                        "series": [0.0, 5.37, 7.42],
                                                    },
                                                    "benchmark": {
                                                        "name": "全池等权基准",
                                                        "note": "同期",
                                                        "returnLabel": "-6.20%",
                                                        "returnPct": -6.2,
                                                        "series": [0.0, 1.8, 3.4],
                                                    },
                                                    "stats": {
                                                        "maxDrawdownPct": -4.22,
                                                        "volatilityPct": 14.38,
                                                        "excessPct": 18.83,
                                                        "samples": 21,
                                                        "convention": "running_sum_of_daily_returns",
                                                    },
                                                },
                                                "allocation": [
                                                    {"key": "300750", "name": "宁德时代",
                                                     "weight": 18.1, "color": "#F08634"},
                                                    {"key": "cash", "name": "高流动性现金管理",
                                                     "weight": 36.1, "color": "#F08634"},
                                                ],
                                                "cashNote": {
                                                    "title": "为什么留 36% 现金？",
                                                    "body": "当前现金 360,000 元，占总资产 36.0%。",
                                                    "details": ["应急储备：突发医疗或家庭支出时无需被动赎回。"],
                                                },
                                                "riskEvents": [
                                                    {"id": "sentiment-watch", "tone": "green",
                                                     "icon": "shield", "title": "情绪面监测",
                                                     "timeAgo": "1个月前",
                                                     "content": "已跟踪 144 个事件样本：正向超预期 26 次、负向意外 10 次。"},
                                                ],
                                                "expert": {
                                                    "strategies": [
                                                        {"key": "aggressive_v2", "name": "动态止盈止损优化版",
                                                         "cumulativeReturnPct": 6.52, "sharpe": 0.55,
                                                         "maxDrawdownPct": 1.25, "winRatePct": 57.1,
                                                         "score": 10.61, "tradingDays": 7,
                                                         "isChampion": True, "rank": 1, "rankText": "1/15"},
                                                    ],
                                                    "strategyTotal": 15,
                                                    "nav": {
                                                        "dates": ["03-26", "05-06"],
                                                        "series": [
                                                            {"key": "nav_dynamic_alpha_tnale",
                                                             "label": "动态 Alpha", "color": "#E9A93B",
                                                             "returnPct": 169.16, "series": [-0.07, 5.7]},
                                                        ],
                                                    },
                                                    "correlation": {
                                                        "labels": ["静态 NALE", "时序 NALE", "动态 Alpha", "沪深300"],
                                                        "matrix": [[1.0, 0.9758, 0.9387, 0.9263],
                                                                   [0.9758, 1.0, 0.9423, 0.933],
                                                                   [0.9387, 0.9423, 1.0, 0.9291],
                                                                   [0.9263, 0.933, 0.9291, 1.0]],
                                                    },
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        },
                        "400": bad_request,
                        "500": server_error,
                    },
                },
            },
            "/api/v1/openapi.json": {
                "get": {
                    "tags": ["Meta"],
                    "summary": "获取本接口的 OpenAPI 规格",
                    "operationId": "getOpenApiSpec",
                    "description": "返回本文件（由 `src/openapi_spec.py` 在运行时生成，永远与路由保持一致）。",
                    "responses": {
                        "200": {
                            "description": "OpenAPI 3.0.3 规格。",
                            "content": {"application/json": {
                                "schema": {"type": "object", "additionalProperties": True},
                            }},
                        },
                    },
                },
            },
        },
        "components": {"schemas": schemas},
    }


if __name__ == "__main__":  # 便于离线导出：python src/openapi_spec.py
    print(render_openapi_json(), end="")
