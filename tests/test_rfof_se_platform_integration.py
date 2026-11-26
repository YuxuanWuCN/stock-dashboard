# -*- coding: utf-8 -*-
"""仓库级集成测试：R-FOF 下周期软工程平台（成员 3 / SE）。

与 ``member3_se_platform/tests`` 的单元测试互补：这里从仓库根出发，串起
「建库 → API 采集 → 统计视图 → 脱敏导出 → 用 pandas 复算」的完整链路，
并把 Issue #14 的两条交付纪律固化为断言：

1. 不提交超过 20MB 的二进制数据库缓存；
2. 导出数据不带原始 session_id，且统计口径可以被独立复算。
"""

from __future__ import annotations

import csv
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM = REPO_ROOT / "research-outputs" / "rfof_next_cycle" / "member3_se_platform"
DB_DIR = PLATFORM / "db"
APP_DIR = PLATFORM / "ab_webapp"
MAX_DB_BYTES = 20 * 1024 * 1024

for path in (DB_DIR, APP_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import server as server_module  # noqa: E402
from dao import assign_ab_group  # noqa: E402


@pytest.fixture
def app(tmp_path):
    assert (APP_DIR / "index.html").is_file(), "A/B 前端页面缺失"
    return server_module.create_app(tmp_path / "integration.sqlite3", static_dir=APP_DIR)


def _session_for(group: str) -> str:
    for index in range(200):
        candidate = f"{index:032x}"
        if assign_ab_group(candidate) == group:
            return candidate
    raise AssertionError(f"找不到 {group} 组会话")


def _event(session_id: str, uuid: str, *, scenario: float, panic: int, latency: int, score: float):
    return {
        "event_uuid": uuid,
        "session_id": session_id,
        "scenario_dd": scenario,
        "event_type": "decision",
        "panic_redeem_clicked": panic,
        "decision_latency_ms": latency,
        "comprehension_score": score,
    }


def test_end_to_end_collection_stats_and_export(app, tmp_path):
    client = app.test_client()
    a_session, b_session = _session_for("A"), _session_for("B")

    for session, age in ((a_session, "youth"), (b_session, "elder")):
        response = client.post("/api/session", json={
            "session_id": session, "age_group": age, "cohort": "community",
            "device_class": "tablet",
        })
        assert response.status_code == 201
        assert response.get_json()["ab_group"] == assign_ab_group(session)

    # A 组：2 次 -20% 情景，恐慌赎回 1 次；B 组：3 次 -20% 情景，0 次赎回。
    events = [
        _event(a_session, "evt-int-a-0001", scenario=-20, panic=0, latency=1000, score=2),
        _event(a_session, "evt-int-a-0002", scenario=-20, panic=1, latency=3000, score=2),
        _event(b_session, "evt-int-b-0001", scenario=-20, panic=0, latency=8000, score=3),
        _event(b_session, "evt-int-b-0002", scenario=-20, panic=0, latency=9000, score=3),
        _event(b_session, "evt-int-b-0003", scenario=-20, panic=0, latency=7000, score=3),
    ]
    response = client.post("/api/events", json={"events": events})
    assert response.status_code == 201
    assert response.get_json()["inserted"] == 5

    survey = client.post("/api/survey", json={
        "session_id": b_session, "instrument": "rules_quiz",
        "items": [{"item_code": "q1", "item_value": 1, "sequence": 1},
                  {"item_code": "q2", "item_value": 1, "sequence": 2},
                  {"item_code": "q3", "item_value": 1, "sequence": 3}],
    })
    assert survey.status_code == 201

    # 独立复算：直接从导出的 CSV 算出与视图一致的恐慌赎回率（不信任视图）。
    export_dir = tmp_path / "exports"
    manifest = app.extensions["rfof_repository"].export(export_dir, salt="integration-salt")
    events_csv = pd.read_csv(export_dir / "ui_ab_events.csv", encoding="utf-8-sig")
    assert len(events_csv) == manifest["tables"]["ui_ab_events"]["rows"] == 5
    assert events_csv["session_ref"].str.startswith("S-").all()
    assert a_session not in events_csv.to_csv(index=False)
    assert b_session not in events_csv.to_csv(index=False)

    recomputed = (events_csv.groupby("ab_group")["panic_redeem_clicked"].mean() * 100).round(2)
    assert recomputed["A"] == pytest.approx(50.0)
    assert recomputed["B"] == pytest.approx(0.0)

    stats = client.get("/api/stats").get_json()["decisions"]
    by_group = {row["ab_group"]: row for row in stats}
    assert by_group["A"]["panic_rate_pct"] == pytest.approx(recomputed["A"])
    assert by_group["B"]["panic_rate_pct"] == pytest.approx(recomputed["B"])
    assert by_group["B"]["avg_latency_ms"] == pytest.approx(8000.0)

    # 导出清单可复核：行数、列白名单、CSV 文件哈希
    import hashlib

    for table, item in manifest["tables"].items():
        target = export_dir / item["file"]
        assert hashlib.sha256(target.read_bytes()).hexdigest() == item["csv_sha256"]
    assert set(manifest["tables"]["ui_ab_events"]["columns"]).isdisjoint({"session_id"})


def test_sqlite_file_stays_small(app):
    repository = app.extensions["rfof_repository"]
    repository.connection.execute("PRAGMA wal_checkpoint(FULL)")
    size = repository.path.stat().st_size
    assert size < MAX_DB_BYTES, f"SQLite 文件 {size} 字节，超过 20MB 上限"


def test_no_large_binary_is_tracked_under_platform():
    """工作区与暂存区都不允许出现 >20MB 的二进制数据库/缓存文件。"""
    binary_suffixes = {".sqlite3", ".db", ".sqlite", ".parquet", ".wal", ".shm"}
    candidates = {path for path in PLATFORM.rglob("*")
                  if path.is_file() and path.suffix in binary_suffixes}
    if (REPO_ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", str(PLATFORM)],
            cwd=REPO_ROOT, capture_output=True, check=True,
        )
        candidates |= {
            REPO_ROOT / name for name in result.stdout.decode("utf-8").split("\0") if name
        }
    oversized = [
        f"{path.relative_to(REPO_ROOT)} ({path.stat().st_size} bytes)"
        for path in candidates
        if path.is_file() and path.stat().st_size > MAX_DB_BYTES
    ]
    assert not oversized, f"禁止提交超大二进制缓存：{oversized}"


def test_local_server_boots_and_serves_webapp(tmp_path):
    app = server_module.create_app(tmp_path / "boot.sqlite3", static_dir=APP_DIR)
    client = app.test_client()
    assert client.get("/").status_code == 200
    health = client.get("/api/health").get_json()
    assert health["duckdb_available"] is True
    assert health["stock_panel_available"] is True
    app.extensions["rfof_repository"].close()