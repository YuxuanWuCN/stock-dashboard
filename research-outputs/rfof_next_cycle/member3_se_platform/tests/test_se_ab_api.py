# -*- coding: utf-8 -*-
"""A/B 实验后端 API 测试：会话幂等、事件校验、批量上限、离线导入与导出权限。"""

from __future__ import annotations

import csv
import io
import json

import pytest

import server as server_module
from dao import assign_ab_group

SESSION = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def app(db_file, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>stub</body></html>", encoding="utf-8")
    return server_module.create_app(db_file, static_dir=static)


@pytest.fixture
def client(app):
    return app.test_client()


def _event(**overrides):
    event = {
        "event_uuid": "evt-api-00000001",
        "session_id": SESSION,
        "scenario_dd": -20,
        "panic_redeem_clicked": 1,
        "decision_latency_ms": 4200,
        "comprehension_score": 2,
        "event_type": "decision",
    }
    event.update(overrides)
    return event


def _ensure_session(client, **overrides):
    payload = {"session_id": SESSION, "age_group": "elder", "cohort": "community"}
    payload.update(overrides)
    return client.post("/api/session", json=payload)


def test_health_reports_schema_and_real_panel(client):
    response = client.get("/api/health")
    body = response.get_json()
    assert response.status_code == 200 and body["ok"] is True
    assert body["schema_version"] == "1"
    assert body["duckdb_available"] is True
    assert body["stock_panel_available"] is True
    assert body["stock_panel_manifest_match"] is True


def test_session_creation_is_idempotent_and_matches_dao_assignment(client):
    first = _ensure_session(client)
    assert first.status_code == 201
    body = first.get_json()
    assert body["created"] is True
    assert body["ab_group"] == assign_ab_group(SESSION)
    assert body["session_id"] == SESSION

    second = _ensure_session(client)
    assert second.status_code == 200
    assert second.get_json()["created"] is False
    assert second.get_json()["ab_group"] == body["ab_group"]


def test_session_rejects_demographic_change(client):
    _ensure_session(client)
    conflict = _ensure_session(client, age_group="youth")
    assert conflict.status_code == 409
    assert "age_group mismatch" in conflict.get_json()["error"]


def test_session_validates_payload(client):
    assert _ensure_session(client, session_id="short").status_code == 400
    assert _ensure_session(client, age_group="kid").status_code == 400
    assert client.post("/api/session", json=[1, 2]).status_code == 400


def test_get_session(client):
    _ensure_session(client)
    assert client.get(f"/api/session/{SESSION}").status_code == 200
    assert client.get("/api/session/" + "f" * 32).status_code == 404


def test_events_accept_single_object_and_batch(client):
    _ensure_session(client)
    single = client.post("/api/events", json=_event())
    assert single.status_code == 201
    assert single.get_json()["inserted"] == 1
    batch = client.post("/api/events", json={"events": [
        _event(event_uuid="evt-api-00000002", scenario_dd=-10),
        _event(event_uuid="evt-api-00000003", scenario_dd=0),
    ]})
    assert batch.status_code == 201
    assert batch.get_json()["inserted"] == 2


def test_events_are_idempotent(client):
    _ensure_session(client)
    client.post("/api/events", json={"events": [_event()]})
    replay = client.post("/api/events", json={"events": [_event(panic_redeem_clicked=0)]})
    assert replay.status_code == 201
    assert replay.get_json() == {
        "ok": True, "inserted": 0, "duplicates": 1,
        "events": [{"event_uuid": "evt-api-00000001", "event_id": 1}],
    }


def test_events_reject_bad_payloads(client):
    _ensure_session(client)
    assert client.post("/api/events", json={"events": []}).status_code == 400
    assert client.post("/api/events", json={"events": "nope"}).status_code == 400
    assert client.post("/api/events", json={"events": [_event(scenario_dd=-5)]}).status_code == 400
    assert client.post("/api/events", json={"events": [_event(decision_latency_ms=-1)]}).status_code == 400
    assert client.post("/api/events", json={"events": [_event(comprehension_score=4)]}).status_code == 400
    assert client.post("/api/events", json={"events": [_event(real_name="张三")]}).status_code == 400


def test_events_require_existing_session(client):
    response = client.post("/api/events", json={"events": [_event(session_id="f" * 32)]})
    assert response.status_code == 400
    assert "unknown session_id" in response.get_json()["error"]


def test_events_reject_arm_tampering(client):
    created = _ensure_session(client).get_json()
    forged = "A" if created["ab_group"] == "B" else "B"
    response = client.post("/api/events", json={"events": [_event(ab_group=forged)]})
    assert response.status_code == 409


def test_events_batch_limit(client):
    _ensure_session(client)
    events = [_event(event_uuid=f"evt-batch-{index:08d}") for index in range(server_module.MAX_BATCH + 1)]
    response = client.post("/api/events", json={"events": events})
    assert response.status_code == 413


def test_events_reject_oversized_body(client):
    _ensure_session(client)
    huge = _event(client_ts="x" * (2 * 1024 * 1024))
    response = client.post("/api/events", json={"events": [huge]})
    assert response.status_code == 413


def test_survey_roundtrip_and_validation(client):
    _ensure_session(client)
    ok = client.post("/api/survey", json={
        "session_id": SESSION, "instrument": "rules_quiz",
        "items": [{"item_code": f"q{i}", "item_value": 1, "sequence": i} for i in (1, 2, 3)],
    })
    assert ok.status_code == 201 and ok.get_json()["saved"] == 3
    assert client.post("/api/survey", json={"session_id": SESSION, "instrument": "rules_quiz",
                                            "items": [{"item_code": "q1", "item_value": 2}]}).status_code == 400
    assert client.post("/api/survey", json={"session_id": SESSION, "instrument": "sqlite_master",
                                            "items": []}).status_code == 400


def test_stats_returns_decision_and_coverage_views(client):
    _ensure_session(client)
    client.post("/api/events", json={"events": [_event(), _event(event_uuid="evt-api-00000005",
                                                                  panic_redeem_clicked=0)]})
    body = client.get("/api/stats").get_json()
    assert body["decisions"][0]["decisions"] == 2
    assert body["decisions"][0]["panic_rate_pct"] == 50.0
    assert body["coverage"][0]["sessions"] == 1


def test_offline_import_is_idempotent(client):
    bundle = {
        "profiles": [{
            "session_id": "offline0offline0offline0offline0",
            "age_group": "elder", "cohort": "community", "device_class": "tablet",
        }],
        "events": [_event(session_id="offline0offline0offline0offline0",
                          event_uuid="evt-offline-0001")],
    }
    first = client.post("/api/import", json=bundle)
    assert first.status_code == 201
    assert first.get_json()["imported"] == {"profiles": 1, "events": 1, "surveys": 0}
    second = client.post("/api/import", json=bundle)
    assert second.get_json()["imported"] == {"profiles": 0, "events": 0, "surveys": 0}


def test_export_allows_loopback_without_token(client, app):
    _ensure_session(client)
    client.post("/api/events", json={"events": [_event()]})
    response = client.get("/api/export?table=ui_ab_events")
    assert response.status_code == 200
    text = response.data.decode("utf-8")
    assert "session_ref" in text.splitlines()[0]
    assert SESSION not in text
    assert "attachment" in response.headers["Content-Disposition"]


def test_export_requires_token_when_configured(db_file, tmp_path):
    static = tmp_path / "static2"
    static.mkdir()
    (static / "index.html").write_text("stub", encoding="utf-8")
    app = server_module.create_app(db_file, static_dir=static, export_token="s3cret")
    client = app.test_client()
    _ensure_session(client)
    assert client.get("/api/export?table=ui_ab_events").status_code == 403
    allowed = client.get("/api/export?table=ui_ab_events", headers={"X-Export-Token": "s3cret"})
    assert allowed.status_code == 200


def test_export_denies_non_loopback_without_token(client):
    response = client.get("/api/export?table=ui_ab_events",
                          environ_overrides={"REMOTE_ADDR": "10.1.2.3"})
    assert response.status_code == 403


def test_export_rejects_unknown_table(client):
    response = client.get("/api/export?table=user_profiles'%20OR%201=1")
    assert response.status_code == 400


def test_csv_export_values_roundtrip(client):
    _ensure_session(client)
    client.post("/api/events", json={"events": [_event()]})
    text = client.get("/api/export?table=v_ab_decision_stats").data.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows[0]["ab_group"] in {"A", "B"}
    assert rows[0]["panic_rate_pct"] == "100.0"


def test_static_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"stub" in response.data


def test_error_payload_shape(client):
    response = client.post("/api/events", json={"events": [_event(scenario_dd=-5)]})
    body = response.get_json()
    assert body["ok"] is False and isinstance(body["error"], str)
    assert "scenario_dd" in body["error"]


def test_cors_header_present(client):
    response = client.get("/api/health")
    assert response.headers["Access-Control-Allow-Origin"] == "*"

def test_export_salt_is_stable_within_one_database(client, tmp_path, monkeypatch):
    """同一实验库的多次导出必须能用 session_ref 关联（#13 要 join 三张表）。"""
    monkeypatch.delenv("RFOF_EXPORT_SALT", raising=False)
    _ensure_session(client)
    client.post("/api/events", json={"events": [_event()]})
    first = client.get("/api/export?table=ui_ab_events")
    second = client.get("/api/export?table=ui_ab_events")
    ref = lambda response: response.data.decode("utf-8").splitlines()[1].split(",")[2]
    assert ref(first) == ref(second)
    assert first.headers["X-Export-Salt-SHA256"] == second.headers["X-Export-Salt-SHA256"]

    # 换一个库（另一个研究批次）后，同一 session_id 的假名必须不同。
    other = server_module.create_app(tmp_path / "other.sqlite3", static_dir=tmp_path)
    other_client = other.test_client()
    assert other_client.post("/api/session", json={
        "session_id": SESSION, "age_group": "elder", "cohort": "community",
    }).status_code == 201
    assert other_client.post("/api/events", json={"events": [_event()]}).status_code == 201
    third = other_client.get("/api/export?table=ui_ab_events")
    assert ref(third) != ref(first)
    other.extensions["rfof_repository"].close()


def test_export_salt_can_be_pinned_for_reproducible_analysis(client, monkeypatch):
    monkeypatch.setenv("RFOF_EXPORT_SALT", "pinned-salt")
    _ensure_session(client)
    client.post("/api/events", json={"events": [_event()]})
    first = client.get("/api/export?table=ui_ab_events")
    second = client.get("/api/export?table=ui_ab_events")
    ref = lambda response: response.data.decode("utf-8").splitlines()[1].split(",")[2]
    assert ref(first) == ref(second)
    assert first.headers["X-Export-Salt-SHA256"] == second.headers["X-Export-Salt-SHA256"]


def test_static_route_does_not_leak_backend_source(client):
    assert client.get("/server.py").status_code == 404
    assert client.get("/db/schema.sql").status_code == 404
