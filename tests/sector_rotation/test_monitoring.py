# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_monitoring.py —— 监控告警（阶段6，任务 5.2）

全部为纯函数手算复核（AGENTS.md 第3条）：
- 数据新鲜度滞后分级（warning/critical）
- 输入合法性越界与样本不足
- 行为约束：月内轮动超限 / 冷却期违例 / 最短持仓违例
- LLM 健康：当日降级、历史不可用率与分歧率
- run_monitoring 集成：产物落盘与 has_critical 判定
不触网、不读真实 K 线目录（calendar 注入）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from src.sector_rotation.config import (
    MAX_ROTATION_PER_MONTH,
    MIN_HOLDING_DAYS,
    SECTORS,
)
from src.sector_rotation.monitoring import (
    FRESHNESS_CRITICAL_LAG_DAYS,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    check_behavior_constraints,
    check_freshness,
    check_input_validity,
    check_llm_health,
    run_monitoring,
    summarize,
)


def _cal(n: int, start: str = "2026-03-02") -> List[str]:
    from datetime import date, timedelta

    d = date.fromisoformat(start)
    out: List[str] = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _sevs(alerts, check: str) -> List[str]:
    return [a.severity for a in alerts if a.check == check]


def _has(alerts, check: str, severity: str) -> bool:
    return any(a.check == check and a.severity == severity for a in alerts)


# ============================================================================
# 1. 数据新鲜度
# ============================================================================

def test_fresh_rotation_stale_warning_and_kline_missing_critical():
    cal = _cal(30)
    stale_date = cal[-4]  # 滞后 3 个交易日
    alerts = check_freshness(cal, kline_last_date=cal[-1],
                             rotation_trade_date=stale_date, rotation_exists=True)
    assert _has(alerts, "freshness.rotation", SEVERITY_WARNING)
    assert not _has(alerts, "freshness.rotation", SEVERITY_CRITICAL)
    assert not _has(alerts, "freshness.kline", SEVERITY_CRITICAL)

    alerts2 = check_freshness(cal, kline_last_date=None,
                              rotation_trade_date=cal[-1], rotation_exists=True)
    assert _has(alerts2, "freshness.kline", SEVERITY_CRITICAL)


def test_fresh_rotation_deep_lag_is_critical():
    cal = _cal(30)
    deep = cal[-(FRESHNESS_CRITICAL_LAG_DAYS + 1)]
    alerts = check_freshness(cal, cal[-1], deep, rotation_exists=True)
    assert _has(alerts, "freshness.rotation", SEVERITY_CRITICAL)


def test_fresh_missing_rotation_and_empty_calendar():
    cal = _cal(10)
    alerts = check_freshness(cal, cal[-1], None, rotation_exists=False)
    assert _has(alerts, "freshness.rotation", SEVERITY_WARNING)
    empty = check_freshness([], None, None, rotation_exists=False)
    assert _has(empty, "freshness.kline_calendar", SEVERITY_CRITICAL)


def test_fresh_date_not_in_calendar_flags_warning():
    cal = _cal(10)
    alerts = check_freshness(cal, cal[-1], "2026-03-07", rotation_exists=True)  # 周六
    assert _has(alerts, "freshness.rotation", SEVERITY_WARNING)


# ============================================================================
# 2. 输入合法性
# ============================================================================

def _inputs(**overrides: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    base = {
        sid: {"stock_count": 6, "sentiment_score": 0.1, "sentiment_trend": "stable",
              "confidence": 0.8}
        for sid in SECTORS
    }
    for sid, patch in overrides.items():
        base[sid].update(patch)
    return base


def test_validity_flags_out_of_bounds_and_small_sample():
    inputs = _inputs(storage={"sentiment_score": 1.7},
                     gold={"confidence": -0.2},
                     green={"stock_count": 3})
    alerts = check_input_validity(inputs)
    assert _has(alerts, "validity.sentiment_bounds", SEVERITY_CRITICAL)
    assert _has(alerts, "validity.confidence_bounds", SEVERITY_CRITICAL)
    assert _has(alerts, "validity.sample_size", SEVERITY_WARNING)
    assert not _has(alerts, "validity.missing_sectors", SEVERITY_CRITICAL)


def test_validity_missing_sector_is_critical():
    inputs = _inputs()
    inputs.pop("gold")
    alerts = check_input_validity(inputs)
    assert _has(alerts, "validity.missing_sectors", SEVERITY_CRITICAL)
    assert alerts[0].detail["missing"] == ["gold"]


def test_validity_clean_inputs_produce_no_alerts():
    assert check_input_validity(_inputs()) == []


# ============================================================================
# 3. 行为约束（history.jsonl 复核）
# ============================================================================

def _row(day: str, holding: str, rotate: bool = False, target: str = "") -> Dict[str, Any]:
    return {"trade_date": day, "holding_sector": holding, "current_sector": holding,
            "should_rotate": rotate, "target_sector": target or None}


def test_behavior_flags_cooldown_and_min_holding_and_monthly_cap():
    cal = _cal(40)
    rows = [_row(d, "gold") for d in cal]
    # idx2 轮动到 storage（此前 gold 仅 2 行 -> 最短持仓违例）
    rows[2] = _row(cal[2], "gold", rotate=True, target="storage")
    for i in range(3, len(cal)):
        rows[i] = _row(cal[i], "storage")
    # idx5 立刻轮动回 gold（间隔 3 < COOLDOWN=7）
    rows[5] = _row(cal[5], "storage", rotate=True, target="gold")
    for i in range(6, len(cal)):
        rows[i] = _row(cal[i], "gold")

    alerts = check_behavior_constraints(rows)
    assert _has(alerts, "behavior.min_holding_violation", SEVERITY_CRITICAL)
    assert _has(alerts, "behavior.cooldown_violation", SEVERITY_CRITICAL)
    assert not _has(alerts, "behavior.monthly_rotation_cap", SEVERITY_CRITICAL)

    # 手算复核冷却违例参数：间隔 = 5 - 2 = 3 行
    cd = [a for a in alerts if a.check == "behavior.cooldown_violation"][0]
    assert cd.detail["gap"] == 3
    mh = [a for a in alerts if a.check == "behavior.min_holding_violation"][0]
    assert mh.detail["held"] == 2 and mh.detail["limit"] == MIN_HOLDING_DAYS


def test_behavior_monthly_cap_flags_four_rotations_in_same_month():
    cal = _cal(15, start="2026-06-01")  # 15 个工作日全落在同一自然月
    rows = [_row(d, "gold") for d in cal]
    # idx 1..4 连续 4 次轮动（> MAX_ROTATION_PER_MONTH=3）
    for i in (1, 2, 3, 4):
        rows[i] = _row(cal[i], "gold", rotate=True, target="storage")
    alerts = check_behavior_constraints(rows)
    cap = [a for a in alerts if a.check == "behavior.monthly_rotation_cap"]
    assert len(cap) == 1
    assert cap[0].detail["rotations"] == MAX_ROTATION_PER_MONTH + 1
    assert cap[0].detail["limit"] == MAX_ROTATION_PER_MONTH
    # 间隔 1 行同时触冷却违例（两类检查互不干扰）
    assert _has(alerts, "behavior.cooldown_violation", SEVERITY_CRITICAL)


def test_behavior_compliant_history_is_silent():
    cal = _cal(30)
    rows = [_row(d, "gold") for d in cal]
    # 持仓 6 行后轮动（满足 MIN_HOLDING=5），此后再无轮动
    rows[6] = _row(cal[6], "gold", rotate=True, target="storage")
    for i in range(7, len(cal)):
        rows[i] = _row(cal[i], "storage")
    assert check_behavior_constraints(rows) == []


def test_behavior_first_row_rotation_exempt():
    cal = _cal(12)
    rows = [_row(d, "gold") for d in cal]
    rows[0] = _row(cal[0], "gold", rotate=True, target="storage")
    for i in range(1, len(cal)):
        rows[i] = _row(cal[i], "storage")
    assert check_behavior_constraints(rows) == []


# ============================================================================
# 4. LLM 健康
# ============================================================================

def test_llm_current_unavailable_and_advisor_fallback():
    rows = [{"trade_date": "2026-04-01", "llm_validation_status": "unavailable"}]
    alerts = check_llm_health({"status": "unavailable"}, {"success": False,
                                                          "fallback_reason": "timeout"}, rows)
    assert _has(alerts, "llm.current_unavailable", SEVERITY_WARNING)
    assert _has(alerts, "llm.advisor_fallback", SEVERITY_WARNING)


def test_llm_diverged_current_flagged():
    alerts = check_llm_health({"status": "diverged"}, None, [])
    assert _has(alerts, "llm.current_diverged", SEVERITY_WARNING)


def test_llm_historical_unavailable_rate():
    rows = [{"trade_date": f"2026-04-0{i}", "llm_validation_status":
             "unavailable" if i <= 2 else "agreed"} for i in range(1, 5)]
    # 2/4 = 50% -> 触阈值
    alerts = check_llm_health(None, None, rows)
    assert _has(alerts, "llm.unavailable_rate", SEVERITY_WARNING)
    rates = [a for a in alerts if a.check == "llm.unavailable_rate"][0]
    assert "50%" in rates.message


def test_llm_healthy_history_no_alerts():
    rows = [{"trade_date": f"2026-04-0{i}", "llm_validation_status": "agreed"}
            for i in range(1, 5)]
    assert check_llm_health({"status": "agreed"}, {"success": True}, rows) == []


# ============================================================================
# 5. run_monitoring 集成
# ============================================================================

def _payload(trade_date: str, llm_status: str = "agreed") -> Dict[str, Any]:
    return {
        "trade_date": trade_date,
        "llm_validation": {"status": llm_status},
        "audit": {"sector_inputs": _inputs(), "advisor_audit": None},
    }


def test_run_monitoring_writes_report_and_detects_warnings(tmp_path: Path):
    cal = _cal(20)
    out_dir = tmp_path / "rot"
    out_dir.mkdir()
    (out_dir / "latest_rotation.json").write_text(
        json.dumps(_payload(cal[-1], llm_status="unavailable"), ensure_ascii=False),
        encoding="utf-8")
    (out_dir / "history.jsonl").write_text(
        json.dumps({"trade_date": cal[-1], "holding_sector": "gold",
                    "should_rotate": False, "llm_validation_status": "unavailable"}) + "\n",
        encoding="utf-8")
    reports = tmp_path / "reports"
    report = run_monitoring(out_dir=out_dir, calendar=cal, reports_dir=reports)

    stamp = datetime.now().strftime("%Y%m%d")
    path = reports / f"alerts_{stamp}.json"
    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == report
    assert report["has_critical"] is False
    assert report["summary"][SEVERITY_WARNING] >= 1
    assert any(a["check"] == "llm.current_unavailable" for a in report["alerts"])


def test_run_monitoring_corrupt_latest_is_critical(tmp_path: Path):
    cal = _cal(10)
    out_dir = tmp_path / "rot"
    out_dir.mkdir()
    (out_dir / "latest_rotation.json").write_text("{ broken", encoding="utf-8")
    report = run_monitoring(out_dir=out_dir, calendar=cal,
                            reports_dir=tmp_path / "reports")
    assert report["has_critical"] is True
    assert any(a["check"] == "validity.latest_corrupted" for a in report["alerts"])


def test_run_monitoring_missing_latest_warns_not_critical(tmp_path: Path):
    cal = _cal(10)
    out_dir = tmp_path / "rot"
    out_dir.mkdir()
    report = run_monitoring(out_dir=out_dir, calendar=cal,
                            reports_dir=tmp_path / "reports")
    assert report["has_critical"] is False
    assert any(a["check"] == "freshness.rotation" for a in report["alerts"])


def test_summarize_counts_by_severity():
    alerts = check_input_validity(_inputs(storage={"sentiment_score": 5.0},
                                          gold={"stock_count": 1}))
    counts = summarize(alerts)
    assert counts[SEVERITY_CRITICAL] == 1
    assert counts[SEVERITY_WARNING] == 1
