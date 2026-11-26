# -*- coding: utf-8 -*-
"""SQLite schema 单元测试：结构、约束、触发器、只追加写保护与幂等初始化。"""

from __future__ import annotations

import sqlite3

import pytest

import connection

CORE_TABLES = {"user_profiles", "survey_responses", "lifecycle_ledger", "ui_ab_events"}
VIEWS = {"v_ab_decision_stats", "v_ab_session_coverage", "v_survey_wide"}


def _names(conn: sqlite3.Connection, kind: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))
    }


def test_core_tables_and_views_exist(db_file):
    connection.init_db(db_file)
    with connection.connect(db_file) as conn:
        assert CORE_TABLES <= _names(conn, "table")
        assert VIEWS <= _names(conn, "view")
        assert connection.schema_version(conn) == connection.SCHEMA_VERSION


def test_schema_application_is_idempotent_and_preserves_rows(repo, profile):
    connection.apply_schema(repo.connection)
    connection.apply_schema(repo.connection)
    count = repo.connection.execute("SELECT COUNT(*) FROM user_profiles").fetchone()[0]
    assert count == 1


def test_foreign_keys_are_enabled_and_cascade(repo, profile, event_factory):
    assert repo.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    repo.record_events([event_factory()])
    repo.record_survey(profile["session_id"], "sus", [
        {"item_code": "sus_01", "item_value": 4, "sequence": 1}
    ])
    # 直接删除画像（DAO 不做删除，这里验证数据库级联约束）
    conn = connection.connect(repo.path, append_only=False)
    try:
        conn.execute("DELETE FROM user_profiles WHERE session_id = ?", (profile["session_id"],))
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM ui_ab_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("sql", [
    "UPDATE ui_ab_events SET panic_redeem_clicked = 0",
    "DELETE FROM ui_ab_events",
])
def test_append_only_tables_reject_mutation(repo, profile, event_factory, sql):
    repo.record_events([event_factory()])
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        repo.connection.execute(sql)


def test_append_only_guard_allows_insert_and_select(repo, profile, event_factory):
    repo.record_events([event_factory()])
    assert repo.connection.execute("SELECT COUNT(*) FROM ui_ab_events").fetchone()[0] == 1


def test_ab_group_assignment_is_immutable(repo, profile):
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        repo.connection.execute(
            "UPDATE user_profiles SET ab_group = ? WHERE session_id = ?",
            ("B" if profile["ab_group"] == "A" else "A", profile["session_id"]),
        )


def test_updated_at_touch_trigger(repo, profile):
    before = repo.connection.execute(
        "SELECT created_at, updated_at FROM user_profiles WHERE session_id = ?",
        (profile["session_id"],),
    ).fetchone()
    repo.connection.execute(
        "UPDATE user_profiles SET device_class = 'phone' WHERE session_id = ?",
        (profile["session_id"],),
    )
    after = repo.connection.execute(
        "SELECT created_at, updated_at FROM user_profiles WHERE session_id = ?",
        (profile["session_id"],),
    ).fetchone()
    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] >= before["updated_at"]


@pytest.mark.parametrize("column, value", [
    ("age_group", "toddler"),
    ("cohort", "kindergarten"),
    ("ab_group", "C"),
    ("consent_scope", "everything"),
    ("device_class", "toaster"),
])
def test_profile_enums_are_enforced(repo, column, value):
    values = {
        "session_id": "feedfacefeedfacefeedfacefeedface",
        "age_group": "youth",
        "cohort": "campus",
        "ab_group": "A",
        "consent_scope": "analytics_only",
        "device_class": "phone",
    }
    values[column] = value
    with pytest.raises(sqlite3.IntegrityError):
        repo.connection.execute(
            "INSERT INTO user_profiles (session_id, age_group, cohort, ab_group, consent_scope, device_class) "
            "VALUES (:session_id, :age_group, :cohort, :ab_group, :consent_scope, :device_class)",
            values,
        )


@pytest.mark.parametrize("field, value", [
    ("scenario_dd", -5),
    ("scenario_dd", 10),
    ("comprehension_score", 3.5),
    ("decision_latency_ms", -1),
    ("decision_latency_ms", 3_600_001),
    ("panic_redeem_clicked", 2),
    ("event_type", "mouse_move"),
])
def test_event_checks_are_enforced(repo, profile, event_factory, field, value):
    repo.record_events([event_factory()])
    event = event_factory()
    event[field] = value
    event["event_uuid"] = "evt-check-000001"
    with pytest.raises(sqlite3.IntegrityError):
        repo.connection.execute(
            "INSERT INTO ui_ab_events (event_uuid, session_id, ab_group, age_group, scenario_dd, "
            "event_type, panic_redeem_clicked, decision_latency_ms, comprehension_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event["event_uuid"], event["session_id"], profile["ab_group"], profile["age_group"],
             event["scenario_dd"], event["event_type"], event["panic_redeem_clicked"],
             event["decision_latency_ms"], event["comprehension_score"]),
        )


def test_ledger_checks_are_enforced(repo):
    good = {
        "strategy_id": "R-FOF-A4", "scenario": "base", "trade_date": "2026-01-05",
        "nav": 1.05, "daily_return": 0.001, "drawdown": -2.0, "locked_floor": 255000,
    }
    for field, value in (
        ("nav", 0), ("drawdown", 1.0), ("locked_floor", -1),
        ("scenario", "crash"), ("trade_date", "2026/01/05"),
    ):
        row = dict(good, **{field: value})
        with pytest.raises((sqlite3.IntegrityError, ValueError)):
            repo.append_ledger([row])


def test_survey_value_range_trigger(repo, profile):
    # 第一层：DAO 先于数据库拦截越界值（错误信息更可读）
    with pytest.raises(ValueError, match="item_value"):
        repo.record_survey(profile["session_id"], "sus", [
            {"item_code": "sus_01", "item_value": 6}
        ])
    with pytest.raises(ValueError, match="rules_quiz"):
        repo.record_survey(profile["session_id"], "rules_quiz", [
            {"item_code": "q1", "item_value": 2}
        ])
    # 第二层：绕过 DAO 直写时，数据库触发器仍然是最后一道闸门
    with pytest.raises(sqlite3.DatabaseError, match="out of range"):
        repo.connection.execute(
            "INSERT INTO survey_responses (session_id, instrument, item_code, item_value) "
            "VALUES (?, 'sus', 'sus_09', 9)",
            (profile["session_id"],),
        )


def test_profile_table_has_no_direct_identifier_columns(repo):
    columns = [row[1] for row in repo.connection.execute("PRAGMA table_info(user_profiles)")]
    forbidden = ("name", "phone", "mobile", "id_card", "idcard", "email", "address", "ip")
    for column in columns:
        lowered = column.lower()
        for token in forbidden:
            assert token not in lowered.split("_"), f"{column} 疑似包含可识别字段"


def test_indexes_cover_ab_queries(repo):
    indexes = _names(repo.connection, "index")
    for expected in (
        "idx_events_session", "idx_events_group_age", "idx_events_type",
        "idx_survey_session", "idx_ledger_strategy_date", "idx_profiles_group_age",
    ):
        assert expected in indexes

def test_survey_update_trigger_blocks_out_of_range_upsert(repo, profile):
    repo.record_survey(profile["session_id"], "sus", [
        {"item_code": "sus_01", "item_value": 3, "sequence": 1}
    ])
    with pytest.raises(sqlite3.DatabaseError, match="out of range"):
        repo.connection.execute(
            "UPDATE survey_responses SET item_value = 9 WHERE session_id = ? AND item_code = 'sus_01'",
            (profile["session_id"],),
        )
