# -*- coding: utf-8 -*-
"""src/sector_rotation/monitoring.py —— 板块轮动监控与告警（阶段6，任务 5.2）

四类检查（全部为纯函数，可离线手算复核，AGENTS.md 第3条）：
1. 数据新鲜度：K 线与 latest_rotation.json 是否落在交易日历最近交易日；
2. 输入合法性：情绪分/置信度越界、板块样本数不足、板块缺失；
3. 行为约束：月内轮动超限、最短持仓违例、冷却期内触发（由 history.jsonl 复核）；
4. LLM 健康：当日复核降级、历史不可用率与分歧率。

产物：reports/sector_rotation/alerts_YYYYMMDD.json。
severity=critical 表示决策链路数据不可信或风控约束被破坏，CLI 据此非 0 退出。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .backtest.sentiment_providers import KlineStore
from .config import (
    COOLDOWN_DAYS,
    EXPECTED_STOCKS_PER_SECTOR,
    MAX_ROTATION_PER_MONTH,
    MIN_HOLDING_DAYS,
    SENTIMENT_BOUND_MAX,
    SENTIMENT_BOUND_MIN,
    SECTORS,
    get_all_tickers,
)
from .daily_job import HISTORY_NAME, KLINE_DIR, LATEST_NAME, load_history

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports" / "sector_rotation"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

# 数据滞后告警阈值（交易日数）：滞后即 warning，超过 critical 阈值升级
FRESHNESS_CRITICAL_LAG_DAYS = 10

# LLM 健康比率阈值
LLM_UNAVAILABLE_RATE_WARNING = 0.5   # 有复核记录的行中 unavailable 占比
LLM_DIVERGED_RATE_WARNING = 0.5      # 有复核结论的行中 diverged 占比


@dataclass
class Alert:
    """单条告警（落盘契约，字段名与 API/报表消费一致）"""
    check: str
    severity: str  # info | warning | critical
    message: str
    detail: Dict[str, Any]


def _alert(check: str, severity: str, message: str, **detail: Any) -> Alert:
    return Alert(check=check, severity=severity, message=message, detail=detail)


def _trading_lag(calendar: List[str], asof_date: Optional[str]) -> Optional[int]:
    """asof_date 落后于日历最后交易日的交易日数；asof 不在日历内或晚于末日返回 None/0。"""
    if not asof_date:
        return None
    if asof_date not in calendar:
        return None
    return len(calendar) - 1 - calendar.index(asof_date)


# ============================================================================
# 1. 数据新鲜度
# ============================================================================

def check_freshness(
    calendar: List[str],
    kline_last_date: Optional[str],
    rotation_trade_date: Optional[str],
    rotation_exists: bool,
) -> List[Alert]:
    alerts: List[Alert] = []
    if not calendar:
        alerts.append(_alert("freshness.kline_calendar", SEVERITY_CRITICAL,
                             "交易日历为空（K 线目录缺失或无公共日期）"))
        return alerts
    cal_last = calendar[-1]

    if not kline_last_date:
        alerts.append(_alert("freshness.kline", SEVERITY_CRITICAL,
                             "K 线数据缺失，无法评估行情新鲜度", calendar_last=cal_last))
    else:
        lag = _trading_lag(calendar, kline_last_date)
        if lag is None:
            alerts.append(_alert("freshness.kline", SEVERITY_WARNING,
                                 f"K 线末日 {kline_last_date} 不在公共交易日历内",
                                 calendar_last=cal_last))
        elif lag >= FRESHNESS_CRITICAL_LAG_DAYS:
            alerts.append(_alert("freshness.kline", SEVERITY_CRITICAL,
                                 f"K 线滞后 {lag} 个交易日（日历末日 {cal_last}）",
                                 kline_last_date=kline_last_date, lag=lag))
        elif lag > 0:
            alerts.append(_alert("freshness.kline", SEVERITY_WARNING,
                                 f"K 线滞后 {lag} 个交易日（日历末日 {cal_last}）",
                                 kline_last_date=kline_last_date, lag=lag))

    if not rotation_exists:
        alerts.append(_alert("freshness.rotation", SEVERITY_WARNING,
                             "latest_rotation.json 不存在（每日轮动任务未运行过）",
                             calendar_last=cal_last))
    else:
        lag = _trading_lag(calendar, rotation_trade_date)
        if lag is None:
            alerts.append(_alert("freshness.rotation", SEVERITY_WARNING,
                                 f"轮动决策日 {rotation_trade_date} 不在公共交易日历内",
                                 calendar_last=cal_last))
        elif lag >= FRESHNESS_CRITICAL_LAG_DAYS:
            alerts.append(_alert("freshness.rotation", SEVERITY_CRITICAL,
                                 f"轮动决策滞后 {lag} 个交易日，前端展示内容不可信",
                                 rotation_trade_date=rotation_trade_date, lag=lag))
        elif lag > 0:
            alerts.append(_alert("freshness.rotation", SEVERITY_WARNING,
                                 f"轮动决策滞后 {lag} 个交易日（当日任务未运行或失败）",
                                 rotation_trade_date=rotation_trade_date, lag=lag))
    return alerts


# ============================================================================
# 2. 输入合法性（消费 latest_rotation.json 的 audit.sector_inputs）
# ============================================================================

def check_input_validity(sector_inputs: Dict[str, Dict[str, Any]]) -> List[Alert]:
    alerts: List[Alert] = []
    missing = sorted(set(SECTORS) - set(sector_inputs))
    if missing:
        alerts.append(_alert("validity.missing_sectors", SEVERITY_CRITICAL,
                             f"板块输入缺失: {missing}", missing=missing))
    for sid, st in sector_inputs.items():
        score = st.get("sentiment_score")
        conf = st.get("confidence")
        count = st.get("stock_count")
        if score is not None and not (SENTIMENT_BOUND_MIN <= float(score) <= SENTIMENT_BOUND_MAX):
            alerts.append(_alert("validity.sentiment_bounds", SEVERITY_CRITICAL,
                                 f"板块 {sid} 情绪分 {score} 越界 [{SENTIMENT_BOUND_MIN}, {SENTIMENT_BOUND_MAX}]",
                                 sector=sid, sentiment_score=float(score)))
        if conf is not None and not (0.0 <= float(conf) <= 1.0):
            alerts.append(_alert("validity.confidence_bounds", SEVERITY_CRITICAL,
                                 f"板块 {sid} 置信度 {conf} 越界 [0, 1]",
                                 sector=sid, confidence=float(conf)))
        if count is not None and int(count) < EXPECTED_STOCKS_PER_SECTOR:
            alerts.append(_alert("validity.sample_size", SEVERITY_WARNING,
                                 f"板块 {sid} 样本数 {count} 低于预期 {EXPECTED_STOCKS_PER_SECTOR}",
                                 sector=sid, stock_count=int(count),
                                 expected=EXPECTED_STOCKS_PER_SECTOR))
    return alerts


# ============================================================================
# 3. 行为约束（由 history.jsonl 复核，纯函数）
# ============================================================================

def _row_holding(row: Dict[str, Any]) -> str:
    if bool(row.get("should_rotate")) and row.get("target_sector"):
        return str(row["target_sector"]).strip().lower()
    return str(row.get("holding_sector") or row.get("current_sector") or "").strip().lower()


def check_behavior_constraints(history_rows: List[Dict[str, Any]]) -> List[Alert]:
    """复核历史决策是否违反引擎硬约束（引擎本应拦截，违例即回归 Bug）。"""
    alerts: List[Alert] = []
    rows = [r for r in history_rows if r.get("trade_date")]
    rotation_idx = [i for i, r in enumerate(rows) if bool(r.get("should_rotate"))]

    # 3.1 月内轮动次数
    by_month: Dict[str, int] = {}
    for i in rotation_idx:
        month = str(rows[i]["trade_date"])[:7]
        by_month[month] = by_month.get(month, 0) + 1
    for month, n in sorted(by_month.items()):
        if n > MAX_ROTATION_PER_MONTH:
            alerts.append(_alert("behavior.monthly_rotation_cap", SEVERITY_CRITICAL,
                                 f"{month} 轮动 {n} 次，超过上限 {MAX_ROTATION_PER_MONTH}",
                                 month=month, rotations=n, limit=MAX_ROTATION_PER_MONTH))

    # 3.2 冷却期：相邻两次轮动的间隔必须 >= COOLDOWN_DAYS
    for a, b in zip(rotation_idx, rotation_idx[1:]):
        gap = b - a
        if gap < COOLDOWN_DAYS:
            alerts.append(_alert("behavior.cooldown_violation", SEVERITY_CRITICAL,
                                 f"{rows[a]['trade_date']} → {rows[b]['trade_date']} "
                                 f"间隔 {gap} 行，低于冷却期 {COOLDOWN_DAYS}",
                                 first=rows[a]["trade_date"], second=rows[b]["trade_date"], gap=gap))

    # 3.3 最短持仓：轮动发生时，上一持仓板块的连续行数必须 >= MIN_HOLDING_DAYS
    for i in rotation_idx:
        if i == 0:
            continue  # 首行即轮动 = 建仓日，不适用最短持仓
        prev_holding = _row_holding(rows[i - 1])
        new_holding = _row_holding(rows[i])
        if not prev_holding or prev_holding == new_holding:
            continue  # 目标与当前一致（防御降级等），未发生真实换仓
        held = 0
        for j in range(i - 1, -1, -1):
            if _row_holding(rows[j]) != prev_holding:
                break
            held += 1
        if held < MIN_HOLDING_DAYS:
            alerts.append(_alert("behavior.min_holding_violation", SEVERITY_CRITICAL,
                                 f"{rows[i]['trade_date']} 轮动时板块 {prev_holding} "
                                 f"仅持仓 {held} 行，低于最短持仓 {MIN_HOLDING_DAYS}",
                                 trade_date=rows[i]["trade_date"], sector=prev_holding,
                                 held=held, limit=MIN_HOLDING_DAYS))
    return alerts


# ============================================================================
# 4. LLM 健康
# ============================================================================

def check_llm_health(
    llm_validation: Optional[Dict[str, Any]],
    advisor_audit: Optional[Dict[str, Any]],
    history_rows: List[Dict[str, Any]],
) -> List[Alert]:
    alerts: List[Alert] = []

    status = (llm_validation or {}).get("status")
    if status == "unavailable":
        alerts.append(_alert("llm.current_unavailable", SEVERITY_WARNING,
                             "当日 LLM 复核不可用（已降级为纯量化路径，结论仍有效）"))
    elif status == "diverged":
        alerts.append(_alert("llm.current_diverged", SEVERITY_WARNING,
                             "当日 LLM 复核与量化结论分歧（量化结论保留，需人工关注）"))

    if advisor_audit is not None and not advisor_audit.get("success", True):
        alerts.append(_alert("llm.advisor_fallback", SEVERITY_WARNING,
                             f"advisor 审计记录降级: {advisor_audit.get('fallback_reason')}",
                             fallback_reason=advisor_audit.get("fallback_reason")))

    reviewed = [r for r in history_rows if r.get("llm_validation_status")]
    if reviewed:
        unavail = sum(1 for r in reviewed if r["llm_validation_status"] == "unavailable")
        rate = unavail / len(reviewed)
        if rate >= LLM_UNAVAILABLE_RATE_WARNING:
            alerts.append(_alert("llm.unavailable_rate", SEVERITY_WARNING,
                                 f"历史复核不可用率 {rate:.0%}（{unavail}/{len(reviewed)}），"
                                 f"LLM 链路长期不健康"))
        diverged = sum(1 for r in reviewed if r["llm_validation_status"] == "diverged")
        drate = diverged / len(reviewed)
        if drate >= LLM_DIVERGED_RATE_WARNING:
            alerts.append(_alert("llm.diverged_rate", SEVERITY_WARNING,
                                 f"历史复核分歧率 {drate:.0%}（{diverged}/{len(reviewed)}），"
                                 f"提示量化参数与新闻语义长期不一致"))
    return alerts


# ============================================================================
# 5. 编排与落盘
# ============================================================================

def summarize(alerts: List[Alert]) -> Dict[str, int]:
    counts = {SEVERITY_INFO: 0, SEVERITY_WARNING: 0, SEVERITY_CRITICAL: 0}
    for a in alerts:
        counts[a.severity] = counts.get(a.severity, 0) + 1
    return counts


def run_monitoring(
    out_dir: Optional[Path] = None,
    kline_dir: Optional[Path] = None,
    reports_dir: Optional[Path] = None,
    calendar: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """读取每日产物执行四类检查，落盘 alerts_YYYYMMDD.json 并返回汇总。

    依赖注入（calendar/out_dir 等）仅供测试；CLI 不传即用默认仓库路径。
    """
    out_root = Path(out_dir) if out_dir else ROOT_DIR / "docs" / "data" / "sector_rotation"
    kline_root = Path(kline_dir) if kline_dir else KLINE_DIR
    reports_root = Path(reports_dir) if reports_dir else REPORTS_DIR

    latest_path = out_root / LATEST_NAME
    history_path = out_root / HISTORY_NAME

    payload: Optional[Dict[str, Any]] = None
    if latest_path.exists():
        try:
            payload = json.loads(latest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None

    history_rows = load_history(history_path)

    if calendar is None:
        store = KlineStore.from_dir(kline_root, get_all_tickers())
        calendar = store.common_dates("2000-01-01", "2099-12-31")
    kline_last = calendar[-1] if calendar else None

    alerts: List[Alert] = []
    if payload is None:
        if not latest_path.exists():
            alerts.extend(check_freshness(calendar, kline_last, None, rotation_exists=False))
        else:
            alerts.append(_alert("validity.latest_corrupted", SEVERITY_CRITICAL,
                                 "latest_rotation.json 存在但无法解析"))
    else:
        sector_inputs = (payload.get("audit") or {}).get("sector_inputs") or {}
        alerts.extend(check_freshness(
            calendar, kline_last, payload.get("trade_date"), rotation_exists=True))
        alerts.extend(check_input_validity(sector_inputs))
        alerts.extend(check_behavior_constraints(history_rows))
        alerts.extend(check_llm_health(
            payload.get("llm_validation"),
            (payload.get("audit") or {}).get("advisor_audit"),
            history_rows))

    counts = summarize(alerts)
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rotation_trade_date": (payload or {}).get("trade_date"),
        "calendar_last_date": calendar[-1] if calendar else None,
        "history_days_recorded": len(history_rows),
        "has_critical": counts.get(SEVERITY_CRITICAL, 0) > 0,
        "summary": counts,
        "alerts": [asdict(a) for a in alerts],
    }

    reports_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    (reports_root / f"alerts_{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
