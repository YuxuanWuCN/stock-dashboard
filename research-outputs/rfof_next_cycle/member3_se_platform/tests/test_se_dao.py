# -*- coding: utf-8 -*-
"""DAO 单元测试：确定性分组、幂等写入、校验边界、统计视图与脱敏导出。"""

from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path

import pytest

from dao import ConflictError, Repository, ValidationError, assign_ab_group
import export as export_module


# ------------------------------------------------------------------ 分组
def test_ab_group_is_deterministic_across_calls_and_has_no_third_arm():
    session = "0123456789abcdef0123456789abcdef"
    first = assign_ab_group(session)
    assert first in {"A", "B"}
    assert assign_ab_group(session) == first
    assert assign_ab_group("0" * 32) in {"A", "B"}
    with pytest.raises(ValidationError):
        assign_ab_group("short")
    with pytest.raises(ValidationError):
        assign_ab_group(None)  # type: ignore[arg-type]


def test_ab_group_is_balanced_over_random_sessions():
    groups = [assign_ab_group(sha256(str(index).encode()).hexdigest()[:32]) for index in range(2000)]
    share_a = groups.count("A") / len(groups)
    assert 0.45 <= share_a <= 0.55, f"A 组占比 {share_a:.3f} 偏离 50% 过多"


# ------------------------------------------------------------------ 画像
def test_ensure_profile_is_idempotent(repo):
    session = "feedfacefeedfacefeedfacefeedface"
    first = repo.ensure_profile(session, age_group="youth", cohort="campus")
    assert first["created"] is True
    assert first["ab_group"] == assign_ab_group(session)
    second = repo.ensure_profile(session, age_group="youth", cohort="campus")
    assert second["created"] is False
    assert second["profile_id"] == first["profile_id"]


def test_ensure_profile_rejects_changed_demographics(repo):
    session = "feedfacefeedfacefeedfacefeedface"
    repo.ensure_profile(session, age_group="youth", cohort="campus")
    with pytest.raises(ConflictError, match="age_group mismatch"):
        repo.ensure_profile(session, age_group="elder", cohort="campus")
    with pytest.raises(ConflictError, match="cohort mismatch"):
        repo.ensure_profile(session, age_group="youth", cohort="community")


@pytest.mark.parametrize("field, value", [
    ("age_group", "kid"),
    ("cohort", "kindergarten"),
    ("consent_scope", "all"),
    ("device_class", "toaster"),
])
def test_ensure_profile_validates_enums(repo, field, value):
    kwargs = dict(age_group="youth", cohort="campus")
    kwargs[field] = value
    with pytest.raises(ValidationError):
        repo.ensure_profile("deadbeefdeadbeefdeadbeefdeadbeef", **kwargs)


# ------------------------------------------------------------------ 事件
def test_record_events_inserts_and_fills_group_from_profile(repo, profile, event_factory):
    event = event_factory()
    result = repo.record_events([event])
    assert result["inserted"] == 1 and result["duplicates"] == 0
    row = repo.connection.execute(
        "SELECT ab_group, age_group, comprehension_score FROM ui_ab_events WHERE event_uuid = ?",
        (event["event_uuid"],),
    ).fetchone()
    assert row["ab_group"] == profile["ab_group"]
    assert row["age_group"] == profile["age_group"]
    assert row["comprehension_score"] == 1.0


def test_record_events_is_idempotent_on_event_uuid(repo, profile, event_factory):
    event = event_factory()
    first = repo.record_events([event])
    second = repo.record_events([dict(event, panic_redeem_clicked=1)])
    assert first["inserted"] == 1
    assert second["inserted"] == 0 and second["duplicates"] == 1
    assert second["events"][0]["event_id"] == first["events"][0]["event_id"]
    replay = repo.connection.execute(
        "SELECT panic_redeem_clicked FROM ui_ab_events WHERE event_uuid = ?",
        (event["event_uuid"],),
    ).fetchone()
    assert replay["panic_redeem_clicked"] == 0, "重复补传不得改写已落库事件"


def test_record_events_requires_known_session(repo, event_factory):
    with pytest.raises(ValidationError, match="unknown session_id"):
        repo.record_events([event_factory(session_id="b" * 32)])


def test_record_events_rejects_arm_tampering(repo, profile, event_factory):
    forged = "A" if profile["ab_group"] == "B" else "B"
    with pytest.raises(ConflictError, match="ab_group"):
        repo.record_events([event_factory(ab_group=forged)])
    # 分组与画像一致时允许显式上报
    repo.record_events([event_factory(ab_group=profile["ab_group"])])


def test_record_events_rejects_age_group_tampering(repo, profile, event_factory):
    forged = "youth" if profile["age_group"] != "youth" else "elder"
    with pytest.raises(ConflictError, match="age_group"):
        repo.record_events([event_factory(age_group=forged)])


def test_record_events_rejects_unknown_fields(repo, profile, event_factory):
    with pytest.raises(ValidationError, match="unsupported fields"):
        repo.record_events([event_factory(real_name="张三")])


@pytest.mark.parametrize("field, value, message", [
    ("scenario_dd", -5, "scenario_dd"),
    ("scenario_dd", 0.5, "scenario_dd"),
    ("panic_redeem_clicked", 2, "panic_redeem_clicked"),
    ("panic_redeem_clicked", True, "panic_redeem_clicked"),
    ("decision_latency_ms", -1, "decision_latency_ms"),
    ("decision_latency_ms", 3_600_001, "decision_latency_ms"),
    ("decision_latency_ms", 1.5, "decision_latency_ms"),
    ("comprehension_score", 3.1, "comprehension_score"),
    ("comprehension_score", -1, "comprehension_score"),
    ("event_type", "hover", "event_type"),
    ("source", "usb", "source"),
])
def test_record_events_validates_ranges(repo, profile, event_factory, field, value, message):
    with pytest.raises(ValidationError, match=message):
        repo.record_events([event_factory(**{field: value})])


def test_record_events_accepts_only_contract_scenarios(repo, profile, event_factory):
    for scenario in (0.0, -10.0, -20.0):
        repo.record_events([event_factory(scenario_dd=scenario)])
    assert repo.connection.execute("SELECT COUNT(*) FROM ui_ab_events").fetchone()[0] == 3


def test_record_events_batch_is_atomic(repo, profile, event_factory):
    good = event_factory()
    bad = event_factory(scenario_dd=-7)
    with pytest.raises(ValidationError):
        repo.record_events([good, bad])
    assert repo.connection.execute("SELECT COUNT(*) FROM ui_ab_events").fetchone()[0] == 0


# ------------------------------------------------------------------ 问卷
def test_record_survey_upserts_last_answer(repo, profile):
    saved = repo.record_survey(profile["session_id"], "sus", [
        {"item_code": "sus_01", "item_value": 3, "sequence": 1},
        {"item_code": "sus_02", "item_value": 5, "sequence": 2},
    ])
    assert saved == 2
    repo.record_survey(profile["session_id"], "sus", [
        {"item_code": "sus_01", "item_value": 4, "sequence": 1}
    ])
    rows = repo.connection.execute(
        "SELECT item_code, item_value FROM survey_responses ORDER BY item_code"
    ).fetchall()
    assert [tuple(row) for row in rows] == [("sus_01", 4.0), ("sus_02", 5.0)]


def test_record_survey_requires_profile(repo):
    with pytest.raises(ValidationError, match="unknown session_id"):
        repo.record_survey("c" * 32, "sus", [{"item_code": "sus_01", "item_value": 3}])


def test_rules_quiz_total_matches_three_items(repo, profile):
    repo.record_survey(profile["session_id"], "rules_quiz", [
        {"item_code": "q1", "item_value": 1, "sequence": 1},
        {"item_code": "q2", "item_value": 0, "sequence": 2},
        {"item_code": "q3", "item_value": 1, "sequence": 3},
    ])
    total = repo.connection.execute(
        "SELECT quiz_total FROM v_survey_wide WHERE session_id = ?", (profile["session_id"],)
    ).fetchone()[0]
    assert total == 2.0


# ------------------------------------------------------------------ 账本
def test_append_ledger_is_idempotent_and_upserts(repo):
    row = {
        "strategy_id": "R-FOF-A4", "scenario": "dd20", "trade_date": "2026-03-16",
        "nav": 0.88, "daily_return": -0.02, "drawdown": -12.0, "locked_floor": 280500,
        "source_sha256": "a" * 64,
    }
    assert repo.append_ledger([row]) == 1
    updated = dict(row, nav=0.879, drawdown=-12.1)
    assert repo.append_ledger([updated]) == 1
    stored = repo.connection.execute(
        "SELECT nav, drawdown FROM lifecycle_ledger "
        "WHERE strategy_id = 'R-FOF-A4' AND scenario = 'dd20' AND trade_date = '2026-03-16'"
    ).fetchone()
    assert stored["nav"] == pytest.approx(0.879)
    assert stored["drawdown"] == pytest.approx(-12.1)


def test_append_ledger_validates_strategy_and_hash(repo):
    base = {
        "strategy_id": "R-FOF-A4", "scenario": "base", "trade_date": "2026-01-05",
        "nav": 1.0, "drawdown": 0.0, "locked_floor": 0,
    }
    with pytest.raises(ValidationError, match="strategy_id"):
        repo.append_ledger([dict(base, strategy_id="YOLO")])
    with pytest.raises(ValidationError, match="source_sha256"):
        repo.append_ledger([dict(base, source_sha256="abc")])


# ------------------------------------------------------------------ 统计
def test_decision_stats_are_hand_checkable(repo, event_factory):
    candidates = [f"{index:032x}" for index in range(64)]
    a_session = next(sid for sid in candidates if assign_ab_group(sid) == "A")
    b_session = next(sid for sid in candidates if assign_ab_group(sid) == "B")
    assert a_session != b_session
    repo.ensure_profile(a_session, age_group="youth", cohort="campus")
    repo.ensure_profile(b_session, age_group="elder", cohort="community")
    repo.record_events([
        event_factory(session_id=a_session, scenario_dd=-20, panic_redeem_clicked=0,
                      decision_latency_ms=1000, comprehension_score=3),
        event_factory(session_id=a_session, scenario_dd=-20, panic_redeem_clicked=1,
                      decision_latency_ms=3000, comprehension_score=3),
        event_factory(session_id=b_session, scenario_dd=-20, panic_redeem_clicked=1,
                      decision_latency_ms=2000, comprehension_score=1),
        event_factory(session_id=b_session, scenario_dd=0, panic_redeem_clicked=0,
                      decision_latency_ms=500, comprehension_score=0),
        event_factory(session_id=b_session, scenario_dd=0, panic_redeem_clicked=0,
                      decision_latency_ms=500, comprehension_score=0, event_type="scenario_view"),
    ])
    stats = repo.decision_stats()
    by_key = {(row["ab_group"], row["scenario_dd"]): row for row in stats}
    assert set(by_key) == {("A", -20.0), ("B", -20.0), ("B", 0.0)}
    assert by_key[("A", -20.0)]["decisions"] == 2
    assert by_key[("A", -20.0)]["panic_redeems"] == 1
    assert by_key[("A", -20.0)]["panic_rate_pct"] == pytest.approx(50.0)
    assert by_key[("A", -20.0)]["avg_latency_ms"] == pytest.approx(2000.0)
    assert by_key[("B", -20.0)]["panic_rate_pct"] == pytest.approx(100.0)
    assert by_key[("B", 0.0)]["decisions"] == 1, "scenario_view 不应计入决策数"


def test_coverage_counts_sessions_and_quizzes(repo, profile, event_factory):
    repo.record_events([event_factory(event_type="quiz_submit", comprehension_score=3)])
    coverage = repo.coverage()
    assert len(coverage) == 1
    row = coverage[0]
    assert row["sessions"] == 1 and row["sessions_with_events"] == 1
    assert row["quiz_submissions"] == 1


# ------------------------------------------------------------------ 导出
def test_export_pseudonymises_sessions_and_writes_manifest(repo, profile, event_factory, tmp_path):
    repo.record_events([event_factory(), event_factory(scenario_dd=-20, panic_redeem_clicked=1)])
    repo.record_survey(profile["session_id"], "sus", [{"item_code": "sus_01", "item_value": 4}])
    out = tmp_path / "exports"
    manifest = repo.export(out, salt="unit-test-salt")

    events_csv = out / "ui_ab_events.csv"
    text = events_csv.read_text(encoding="utf-8-sig")
    assert profile["session_id"] not in text, "导出不得包含原始 session_id"
    assert export_module.session_ref(profile["session_id"], "unit-test-salt") in text
    with events_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert set(rows[0]) == set(manifest["tables"]["ui_ab_events"]["columns"])
    assert manifest["tables"]["ui_ab_events"]["rows"] == 2
    assert manifest["tables"]["ui_ab_events"]["csv_sha256"] == sha256(events_csv.read_bytes()).hexdigest()
    assert manifest["salt_sha256"] == sha256(b"unit-test-salt").hexdigest()
    assert "unit-test-salt" not in json.dumps(manifest), "清单不得泄露盐本身"
    assert set(manifest["tables"]) == set(export_module.EXPORT_TABLES)


def test_export_is_stable_for_same_salt_and_differs_across_salts(repo, profile, event_factory, tmp_path):
    repo.record_events([event_factory()])
    first = tmp_path / "first"
    second = tmp_path / "second"
    third = tmp_path / "third"
    repo.export(first, salt="salt-one")
    repo.export(second, salt="salt-one")
    repo.export(third, salt="salt-two")
    digest = lambda path: sha256((path / "ui_ab_events.csv").read_bytes()).hexdigest()
    assert digest(first) == digest(second)
    assert digest(first) != digest(third)
    ref_one = export_module.session_ref(profile["session_id"], "salt-one")
    ref_two = export_module.session_ref(profile["session_id"], "salt-two")
    assert ref_one != ref_two


def test_export_skips_identifier_columns(repo, profile, tmp_path):
    with pytest.raises(AssertionError, match="可识别信息"):
        export_module.assert_no_identifier_columns(["session_ref", "respondent_name"])
    manifest = repo.export(tmp_path / "clean", salt="s")
    for table in manifest["tables"].values():
        export_module.assert_no_identifier_columns(table["columns"])


def test_export_empty_database_is_valid(repo, tmp_path):
    manifest = repo.export(tmp_path / "empty", salt="s")
    assert all(item["rows"] == 0 for item in manifest["tables"].values())
    assert (tmp_path / "empty" / "export_manifest.json").is_file()


def test_unknown_export_table_is_rejected(repo):
    with pytest.raises(ValueError, match="not exportable"):
        export_module.collect_rows(repo.connection, "sqlite_master", "salt")


def test_repository_rejects_mutation_of_append_only_tables(repo, profile, event_factory):
    import sqlite3

    repo.record_events([event_factory()])
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        repo.connection.execute("DELETE FROM ui_ab_events")


def test_repository_auto_initialises_missing_database(tmp_path):
    path = tmp_path / "auto" / "nested.sqlite3"
    with Repository(path) as repository:
        assert repository.connection.execute("SELECT COUNT(*) FROM ui_ab_events").fetchone()[0] == 0
    assert path.is_file()