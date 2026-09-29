# -*- coding: utf-8 -*-
"""
首页视图模型接口（BFF）—— ``GET /api/v1/homepage``

把散落在 ``docs/data/**`` 里的组合净值、基准、资产配置、风险事件与策略表现，
按《前端复现规范》第 6 节的数据契约组装成「一次请求渲染整页」的视图模型，
避免前端为 6 个区块发 8 次请求、并在浏览器里各写一套聚合逻辑。

数据来源（全部为既有流水线产物，本模块只读不写）
------------------------------------------------
- ``paper/performance.json``                                组合净值曲线 + 资金
- ``paper/benchmark.json``                                  同期基准曲线
- ``paper/portfolio.json``                                  资产配置与现金比例
- ``strategy/market_temperature.json``                      市场温度 → 健康晴雨表
- ``llm/market_feedback.json``                              事件样本 → 风险事件卡
- ``quantitative/latest_evolution.json``                    策略表现（替代原「因子面板」）
- ``quantitative/backtest_2024_2026_dual_simulation.json``  策略净值序列 + 相关性
- ``quantitative/manifest.json``                            策略中文名

错误响应沿用 ``{"error", "detail"}``，与 dataset_api 保持一致。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import HTTPException

try:  # 包内导入（gunicorn --chdir src server:app）
    from .data_store import get, integer, load_relative, num, text
    from .dataset_api import ApiError
except ImportError:  # 直接以脚本方式运行 src/ 下的模块
    from data_store import get, integer, load_relative, num, text
    from dataset_api import ApiError

bp = Blueprint("homepage_api_v1", __name__, url_prefix="/api/v1")

logger = logging.getLogger("homepage_api")

# ---------------------------------------------------------------- 常量

#: 曲线默认采样点数。设计稿 X 轴标注 7 个刻度（对应 21 个采样点），
#: 与 EquityCurveChart 的 X_LABEL_INDEX = [0,3,6,9,12,16,20] 对齐。
DEFAULT_POINTS = 21
MIN_POINTS = 8
MAX_POINTS = 120

#: 06 区块策略净值曲线的采样点数，与 StrategyNavChart 的刻度下标对齐。
NAV_POINTS = 23

HERO_TITLE = "您好！让财富为您的晚年生活保驾护航"
HERO_SUBTITLE = "专业的养老金融解决方案，稳健增值，安心相伴"

#: 配置环图配色（沿用设计稿的五色语义系统）
ALLOCATION_PALETTE = ("#26A17F", "#3D87E8", "#F08634", "#E9A93B", "#F0515A", "#6DA6F2")
CASH_COLOR = "#F08634"

#: 策略净值曲线的四个序列 → (字段名, 显示名, 颜色)
NAV_SERIES = (
    ("nav_static_nale", "静态 NALE", "#3D87E8"),
    ("nav_temporal_nale_fixed", "时序 NALE", "#26A17F"),
    ("nav_dynamic_alpha_tnale", "动态 Alpha", "#E9A93B"),
    ("nav_csi300_benchmark", "沪深300", "#A9B4C2"),
)


def _no_store(payload: Any, status: int = 200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------- 数值工具


def _numbers(values: Sequence[Any]) -> List[float]:
    """过滤出真正的数值（排除 None / bool / 非数值）。"""
    return [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _max_drawdown_pct(cumulative_pct: Sequence[float]) -> Optional[float]:
    """由累计收益率序列（%）算最大回撤（%，非正数）。"""
    values = _numbers(cumulative_pct)
    if not values:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        equity = 1.0 + value / 100.0
        peak_equity = 1.0 + peak / 100.0
        if peak_equity > 0:
            worst = min(worst, equity / peak_equity - 1.0)
    return round(worst * 100, 2)


def _annualized_volatility_pct(daily_returns_pct: Sequence[Any]) -> Optional[float]:
    """由日收益率序列（%）算年化波动率（%），按 252 个交易日。"""
    values = _numbers(daily_returns_pct)
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return round(math.sqrt(variance) * math.sqrt(252), 2)


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """皮尔逊相关系数；样本不足或方差为 0 时返回 None。"""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    covariance = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0.0 or dy == 0.0:
        return None
    return round(covariance / (dx * dy), 4)


def _downsample(rows: Sequence[Any], points: int) -> List[Any]:
    """等距抽样到指定点数，保留首尾端点。"""
    total = len(rows)
    if total <= points or points < 2:
        return list(rows)
    step = (total - 1) / (points - 1)
    indexes = sorted({int(round(i * step)) for i in range(points)})
    return [rows[i] for i in indexes if 0 <= i < total]


def _short_date(raw: Any) -> str:
    """``2026-09-04`` → ``09-04``（与设计稿 X 轴刻度格式一致）。"""
    value = text(raw) or ""
    return value[5:10] if len(value) >= 10 else value


def _relative_time(raw: Any) -> str:
    """把日期字符串转成「今天 / N天前 / N个月前」。"""
    value = text(raw)
    if not value:
        return ""
    candidate = value.replace("/", "-").replace("T", " ")[:19]
    parsed: Optional[datetime] = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d_%H%M%S"):
        try:
            parsed = datetime.strptime(candidate, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return value
    days = (datetime.now().date() - parsed.date()).days
    if days <= 0:
        return "今天"
    if days < 30:
        return f"{days}天前"
    if days < 365:
        return f"{max(1, days // 30)}个月前"
    return f"{days // 365}年前"


def _format_pct(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}%"


# ---------------------------------------------------------------- 各区块组装


def _curve_payload(points: int) -> Dict[str, Any]:
    """03 绝对收益曲线：组合累计收益率 + 同期基准。

    口径说明：本项目既有产物统一用「日收益率累加」表示累计收益
    （``benchmark.json`` 的 ``cumulative_return_pct`` = Σ ``daily_return_pct``，
    实测 -6.18% ≈ 累加值 -6.20%）。这里沿用同一口径，保证首页数字与看板、
    论文材料一致；注意 ``performance.json`` 里的 ``history[].total_return``
    其实是**基准**的累计曲线（与 ``benchmark.json`` 完全同源），不能当组合曲线用。
    """
    performance = load_relative("paper/performance.json")
    benchmark = load_relative("paper/benchmark.json")
    portfolio_meta = load_relative("paper/portfolio.json")

    records = [row for row in (get(performance, "records") or []) if isinstance(row, Mapping)]
    if not records:
        raise ApiError(503, "组合净值数据不可用", "缺少 docs/data/paper/performance.json 的 records 字段")

    # ---- 组合：逐日累加 portfolio_return_pct ----
    running = 0.0
    portfolio_series: List[Tuple[str, float]] = []
    for row in records:
        day = text(row.get("trade_date")) or text(row.get("date")) or ""
        daily = num(row.get("portfolio_return_pct"))
        if not day or daily is None:
            continue
        running += daily
        portfolio_series.append((day, round(running, 4)))

    # ---- 基准：优先用 benchmark.json，缺失时回退到组合文件里的等权列 ----
    benchmark_records = [row for row in (get(benchmark, "records") or []) if isinstance(row, Mapping)]
    if not benchmark_records:
        benchmark_records = [
            {"trade_date": row.get("trade_date"), "daily_return_pct": row.get("equal_weight_return_pct")}
            for row in records
        ]

    running = 0.0
    benchmark_by_day: Dict[str, float] = {}
    for row in benchmark_records:
        day = text(row.get("trade_date")) or text(row.get("date")) or ""
        daily = num(row.get("daily_return_pct"))
        if daily is None:
            daily = num(row.get("equal_weight_return_pct"))
        if not day or daily is None:
            continue
        running += daily
        benchmark_by_day[day] = round(running, 4)

    sampled = _downsample(portfolio_series, points)
    dates = [_short_date(day) for day, _ in sampled]
    portfolio_values = [round(value, 2) for _, value in sampled]
    benchmark_values = [round(benchmark_by_day.get(day, 0.0), 2) for day, _ in sampled]

    portfolio_return = portfolio_values[-1] if portfolio_values else None
    benchmark_return = benchmark_values[-1] if benchmark_values else None

    return {
        "dates": dates,
        "portfolio": {
            # 显示名取 portfolio.json（与右侧配置面板同源），而非 performance.json
            # 里那个陈旧的 portfolio_name 字段
            "name": text(portfolio_meta.get("name")) if isinstance(portfolio_meta, Mapping)
            else text(performance.get("portfolio_name")) or "我们的防御组合",
            "returnLabel": _format_pct(portfolio_return),
            "returnPct": portfolio_return,
            "series": portfolio_values,
        },
        "benchmark": {
            "name": text(benchmark.get("benchmark_name")) or "同期基准",
            "note": "同期",
            "returnLabel": _format_pct(benchmark_return),
            "returnPct": benchmark_return,
            "series": benchmark_values,
        },
        "stats": {
            # 风险指标必须用全量序列：抽样后的点会低估最大回撤
            "maxDrawdownPct": _max_drawdown_pct([value for _, value in portfolio_series]),
            "volatilityPct": _annualized_volatility_pct([row.get("portfolio_return_pct") for row in records]),
            "excessPct": round(portfolio_return - benchmark_return, 2)
            if portfolio_return is not None and benchmark_return is not None else None,
            "samples": len(sampled),
            "convention": "running_sum_of_daily_returns",
        },
    }


def _gauge_payload() -> Dict[str, Any]:
    """02 资产健康晴雨表：市场温度 → 建议仓位（防御充分度）。"""
    temperature = load_relative("strategy/market_temperature.json")
    ratio = num(get(temperature, "position_ratio_adjusted"), 4)
    if ratio is None:
        ratio = num(get(temperature, "position_ratio"), 4)
    temp_value = num(get(temperature, "temperature"))
    status = text(get(temperature, "status")) or "未知"

    if ratio is None:
        percent = 0.6
        level = "市场温度不可用"
        desc = "未取到市场温度数据，按保守仓位展示"
    else:
        percent = round(max(0.0, min(1.0, ratio)), 4)
        level = f"市场温度 {temp_value:.1f}" if temp_value is not None else f"市场{status}"
        desc = f"{status} ｜ 建议仓位 {percent * 100:.1f}%"

    return {
        "title": "资产健康晴雨表",
        "level": level,
        "desc": desc,
        "percent": percent,
        "tip": "由市场温度模型给出的建议仓位比例，越高代表防御系统越有加仓空间",
    }


def _rating(volatility_pct: Optional[float], drawdown_pct: Optional[float]) -> Tuple[str, str]:
    """由年化波动率与最大回撤映射资产安全评级（规则随接口一并返回）。"""
    if volatility_pct is None or drawdown_pct is None:
        return "—", "风险指标不足，暂无法评级"
    dd = abs(drawdown_pct)
    if dd <= 5 and volatility_pct <= 15:
        return "AAA", "极高防御"
    if dd <= 8 and volatility_pct <= 20:
        return "AA", "高防御"
    if dd <= 12 and volatility_pct <= 25:
        return "A", "中等防御"
    return "BBB", "防御一般"


def _hero_payload(curve_stats: Mapping[str, Any]) -> Dict[str, Any]:
    """02 Hero：三项核心指标 + 晴雨表。"""
    volatility = curve_stats.get("volatilityPct")
    drawdown = curve_stats.get("maxDrawdownPct")
    excess = curve_stats.get("excessPct")
    rating, rating_caption = _rating(volatility, drawdown)

    metrics = [
        {
            "id": "safety",
            "icon": "shield",
            "label": "资产安全评级",
            "value": rating,
            "tone": "green",
            "caption": rating_caption,
            "tip": "按组合年化波动率与历史最大回撤映射：回撤 ≤5% 且波动 ≤15% 为 AAA",
        },
        {
            "id": "drawdown-resist",
            "icon": "rise",
            "label": "震荡市抗跌实绩",
            "value": _format_pct(excess),
            "tone": "red",
            "caption": "组合相对同期基准的超额收益",
            "tip": "统计区间内组合累计收益与同期基准收益之差",
        },
        {
            "id": "max-drawdown",
            "icon": "shield",
            "label": "历史最大回撤控制",
            "value": f"{abs(drawdown):.2f}%" if drawdown is not None else "—",
            "tone": "blue",
            "caption": "净值自区间高点的最大跌幅",
            "tip": "由组合累计净值序列逐日滚动计算",
        },
    ]

    return {
        "title": HERO_TITLE,
        "subtitle": HERO_SUBTITLE,
        "metrics": metrics,
        "gauge": _gauge_payload(),
    }


def _allocation_payload() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """04 资产配置：真实持仓 + 现金比例。"""
    portfolio = load_relative("paper/portfolio.json")
    is_mapping = isinstance(portfolio, Mapping)
    cash_pct = num(portfolio.get("cash_pct")) if is_mapping else None

    segments: List[Dict[str, Any]] = []
    for index, item in enumerate(portfolio.get("items") or [] if is_mapping else []):
        if not isinstance(item, Mapping):
            continue
        weight = num(item.get("pct"))
        if weight is None or weight <= 0:
            continue
        code = text(item.get("code")) or f"pos-{index}"
        segments.append({
            "key": code,
            "name": text(item.get("name")) or code,
            "weight": round(weight, 1),
            "color": ALLOCATION_PALETTE[len(segments) % len(ALLOCATION_PALETTE)],
            "reason": text(item.get("reason")),
        })

    if cash_pct and cash_pct > 0:
        segments.append({
            "key": "cash",
            "name": "高流动性现金管理",
            "weight": round(cash_pct, 1),
            "color": CASH_COLOR,
            "reason": None,
        })

    if not segments:
        # 兜底：没有持仓数据时给出与设计稿一致的三段结构，保证页面不空
        segments = [
            {"key": "green-power", "name": "稳健绿电龙头", "weight": 35, "color": "#26A17F", "reason": None},
            {"key": "hardware", "name": "硬科技低波防御", "weight": 25, "color": "#3D87E8", "reason": None},
            {"key": "cash", "name": "高流动性现金管理", "weight": 40, "color": CASH_COLOR, "reason": None},
        ]

    # 环图按 weight/100 画弧，权重合计要精确等于 100，否则环上会留缺口。
    # 只在合计接近 100 时归一（处理进位误差）；若数据本身不完整则如实展示，不放大。
    total_weight = sum(segment["weight"] for segment in segments)
    if total_weight > 0 and 95.0 <= total_weight <= 105.0:
        if abs(total_weight - 100.0) > 0.05:
            scale = 100.0 / total_weight
            for segment in segments:
                segment["weight"] = round(segment["weight"] * scale, 1)
        residual = round(100.0 - sum(segment["weight"] for segment in segments), 1)
        if residual:
            largest = max(segments, key=lambda segment: segment["weight"])
            largest["weight"] = round(largest["weight"] + residual, 1)

    cash_amount = num(portfolio.get("cash")) if is_mapping else None
    if cash_amount is not None and cash_pct is not None:
        lead = f"当前现金 {cash_amount:,.0f} 元，占总资产 {cash_pct:.1f}%。"
    else:
        lead = "当前保留了一定比例的现金仓位。"

    cash_note = {
        "title": f"为什么留 {cash_pct:.0f}% 现金？" if cash_pct else "为什么要留现金？",
        "body": f"{lead}因为要确保您随时有应急资金，且在市场风险期不上杠杆。",
        "details": [
            "应急储备：突发医疗或家庭支出时无需被动赎回。",
            "波动缓冲：市场急跌时现金仓位可平滑净值曲线。",
            "再平衡弹药：极端低估时才有加仓的能力。",
        ],
    }
    return segments, cash_note


def _risk_events_payload() -> List[Dict[str, Any]]:
    """05 产业链避险：由事件样本与市场温度组装三张卡。"""
    feedback = load_relative("llm/market_feedback.json")
    summary = feedback.get("summary") if isinstance(feedback, Mapping) else None
    is_summary = isinstance(summary, Mapping)
    time_ago = _relative_time(feedback.get("updated_at") if isinstance(feedback, Mapping) else None)

    total = integer(summary.get("total")) if is_summary else None
    positive = integer(summary.get("positive_surprise")) if is_summary else None
    negative = integer(summary.get("negative_surprise")) if is_summary else None
    excess_5d = num(summary.get("avg_excess_5d_pct")) if is_summary else None
    alignment = num(summary.get("alignment_rate")) if is_summary else None
    reward = num(summary.get("avg_rlsp_reward_5d")) if is_summary else None

    temperature = load_relative("strategy/market_temperature.json")
    temperature_value = num(get(temperature, "temperature"))
    position = num(get(temperature, "position_ratio_adjusted"), 4)
    if position is None:
        position = num(get(temperature, "position_ratio"), 4)

    events: List[Dict[str, Any]] = []

    if total is not None:
        events.append({
            "id": "sentiment-watch",
            "tone": "green",
            "icon": "shield",
            "title": "情绪面监测",
            "timeAgo": time_ago,
            "content": (
                f"已跟踪 {total} 个事件样本：正向超预期 {positive or 0} 次、"
                f"负向意外 {negative or 0} 次，整体情绪偏中性，未出现系统性恶化信号。"
            ),
        })

    if excess_5d is not None:
        events.append({
            "id": "event-alpha",
            "tone": "blue",
            "icon": "arrowUp",
            "title": "事件驱动超额",
            "timeAgo": time_ago,
            "content": (
                f"事件发布后 5 日平均超额收益 {_format_pct(excess_5d)}"
                + (f"，模型对齐率 {alignment * 100:.1f}%。" if alignment is not None else "。")
            ),
        })
    elif reward is not None:
        events.append({
            "id": "event-alpha",
            "tone": "blue",
            "icon": "arrowUp",
            "title": "事件驱动超额",
            "timeAgo": time_ago,
            "content": f"事件驱动信号 5 日平均回报 {reward:.3f}，仍在有效区间。",
        })

    if temperature_value is not None:
        position_text = f"，建议仓位 {position * 100:.1f}%" if position is not None else ""
        events.append({
            "id": "position-adjust",
            "tone": "orange",
            "icon": "shield",
            "title": "智能仓位调节",
            "timeAgo": _relative_time(get(temperature, "generated_at")),
            "content": (
                f"当前市场温度 {temperature_value:.1f}{position_text}，"
                "风险期自动降低敞口、落袋为安。"
            ),
        })

    if not events:
        raise ApiError(503, "风险事件数据不可用", "缺少 docs/data/llm/market_feedback.json")
    return events[:3]


def _strategy_names() -> Dict[str, str]:
    """策略 key → 中文显示名（来自 quantitative/manifest.json 与 variants.display_name）。"""
    manifest = load_relative("quantitative/manifest.json")
    names: Dict[str, str] = {}
    for entry in (get(manifest, "portfolios") or []):
        if isinstance(entry, Mapping):
            key = text(entry.get("key"))
            name = text(entry.get("name"))
            if key and name:
                names[key] = name
    evolution = load_relative("quantitative/latest_evolution.json")
    for entry in (get(evolution, "variants") or []):
        if isinstance(entry, Mapping):
            key = text(entry.get("name"))
            name = text(entry.get("display_name"))
            if key and name:
                names.setdefault(key, name)
    return names


def _strategy_payload() -> Dict[str, Any]:
    """06 策略表现：策略对比表 + 净值曲线 + 相关性矩阵。"""
    evolution = load_relative("quantitative/latest_evolution.json")
    all_strategies = get(evolution, "all_strategies") or {}
    champion = text(get(evolution, "champion", "name"))
    names = _strategy_names()

    rows: List[Dict[str, Any]] = []
    for key, stats in all_strategies.items():
        if not isinstance(stats, Mapping):
            continue
        rows.append({
            "key": key,
            "name": names.get(key, key),
            "cumulativeReturnPct": num(stats.get("cumulative_return")),
            "sharpe": num(stats.get("sharpe")),
            "maxDrawdownPct": num(stats.get("max_drawdown")),
            "winRatePct": num(stats.get("win_rate")),
            "score": num(stats.get("score")),
            "tradingDays": integer(stats.get("trading_days")),
            "isChampion": key == champion,
        })
    rows.sort(key=lambda row: (-(row["score"] if row["score"] is not None else -1e9), row["key"]))
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        row["rankText"] = f"{index}/{total}"

    # ---- 策略净值曲线 + 相关性矩阵 ----
    simulation = load_relative("quantitative/backtest_2024_2026_dual_simulation.json")
    nav_rows = [row for row in (get(simulation, "daily_nav_series") or []) if isinstance(row, Mapping)]

    nav_dates: List[str] = []
    nav_series: List[Dict[str, Any]] = []
    correlation: Optional[Dict[str, Any]] = None

    if nav_rows:
        sampled = _downsample(nav_rows, NAV_POINTS)
        nav_dates = [_short_date(row.get("date")) for row in sampled]

        daily_returns: Dict[str, List[float]] = {}
        for field, label, color in NAV_SERIES:
            values: List[float] = []
            for row in sampled:
                current = num(row.get(field), 6)
                # 净值序列以 1.0 为初始本金，因此收益率 = (nav - 1) × 100，
                # 与 metrics_version_* 里的 total_return_pct 口径完全一致
                values.append(round((current - 1.0) * 100, 2) if current is not None else 0.0)
            nav_series.append({
                "key": field,
                "label": label,
                "color": color,
                "series": values,
                "returnPct": values[-1] if values else None,
            })

            # 相关系数用全量日收益（而非抽样点），否则样本量不足
            previous: Optional[float] = None
            series_returns: List[float] = []
            for row in nav_rows:
                current = num(row.get(field), 6)
                if previous and current is not None:
                    series_returns.append(current / previous - 1.0)
                if current is not None:
                    previous = current
            daily_returns[field] = series_returns

        fields = [entry[0] for entry in NAV_SERIES]
        matrix: List[List[float]] = []
        for field_a in fields:
            matrix.append([
                _pearson(daily_returns[field_a], daily_returns[field_b]) or 0.0
                for field_b in fields
            ])
        correlation = {"labels": [entry[1] for entry in NAV_SERIES], "matrix": matrix}

    return {
        # 只取前 4 个：设计稿该列固定 216px 高，行数多了会被裁掉
        "strategies": rows[:4],
        "strategyTotal": total,
        "nav": {"dates": nav_dates, "series": nav_series},
        "correlation": correlation,
    }


# ---------------------------------------------------------------- 路由


@bp.route("/homepage", methods=["GET"])
def api_homepage():
    """一次请求返回整页视图模型（02/03/04/05/06 五个区块的动态数据）。"""
    raw_points = request.args.get("points")
    points = DEFAULT_POINTS
    if raw_points not in (None, ""):
        try:
            points = int(str(raw_points).strip())
        except (TypeError, ValueError):
            raise ApiError(400, "参数 points 需要整数", f"收到 {raw_points!r}")
        if points < MIN_POINTS or points > MAX_POINTS:
            raise ApiError(400, "参数 points 超出取值范围",
                           f"应在 [{MIN_POINTS}, {MAX_POINTS}] 之间，收到 {points}")

    curve = _curve_payload(points)
    allocation, cash_note = _allocation_payload()

    payload = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "hero": _hero_payload(curve.get("stats") or {}),
        "equityCurve": curve,
        "allocation": allocation,
        "cashNote": cash_note,
        "riskEvents": _risk_events_payload(),
        "expert": _strategy_payload(),
        "meta": {
            # 回显**实际**点数：源数据只有 70 天时，请求 120 也只能给 70 个点
            "points": len(curve.get("dates") or []),
            "requested_points": points,
            "sources": {
                "equityCurve": "paper/performance.json + paper/benchmark.json",
                "allocation": "paper/portfolio.json",
                "gauge": "strategy/market_temperature.json",
                "riskEvents": "llm/market_feedback.json",
                "strategies": "quantitative/latest_evolution.json",
                "nav": "quantitative/backtest_2024_2026_dual_simulation.json",
            },
        },
    }
    return _no_store(payload)


# ---------------------------------------------------------------- 统一错误处理


@bp.errorhandler(ApiError)
def _handle_api_error(error: ApiError):
    body: Dict[str, Any] = {"error": error.message}
    if error.detail:
        body["detail"] = error.detail
    return _no_store(body, error.status)


@bp.errorhandler(Exception)
def _handle_unexpected(error: Exception):
    if isinstance(error, HTTPException):
        return _no_store({"error": error.description}, error.code or 500)
    logger.exception("homepage api 未处理异常", exc_info=error)
    return _no_store({"error": "服务器内部错误，请稍后重试"}, 500)
