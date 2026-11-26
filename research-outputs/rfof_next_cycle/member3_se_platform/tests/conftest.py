# -*- coding: utf-8 -*-
"""R-FOF 下周期 · 软工程平台（成员 3 / SE）测试夹具。

测试目录与实现目录并存，因此这里把 ``db/``、``ab_webapp/`` 加入 sys.path，
并统一提供临时库、画像、事件工厂等夹具，避免每个用例重复造数。
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

SUITE_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = SUITE_ROOT / "db"
APP_DIR = SUITE_ROOT / "ab_webapp"
REPO_ROOT = SUITE_ROOT.parents[2]

for _path in (DB_DIR, APP_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

SESSION_ID = "0123456789abcdef0123456789abcdef"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "rfof_ab.sqlite3"


@pytest.fixture
def repo(db_file: Path):
    from dao import Repository

    repository = Repository(db_file)
    try:
        yield repository
    finally:
        repository.close()


@pytest.fixture
def session_id() -> str:
    return SESSION_ID


@pytest.fixture
def profile(repo, session_id):
    return repo.ensure_profile(
        session_id,
        age_group="elder",
        cohort="community",
        consent_scope="analytics_and_research",
        device_class="tablet",
    )


@pytest.fixture
def event_factory(session_id):
    from uuid import uuid4

    def factory(**overrides):
        event = {
            "event_uuid": f"evt-{uuid4().hex[:16]}",
            "session_id": session_id,
            "scenario_dd": -10,
            "event_type": "decision",
            "panic_redeem_clicked": 0,
            "decision_latency_ms": 1500,
            "comprehension_score": 1,
        }
        event.update(overrides)
        return event

    return factory