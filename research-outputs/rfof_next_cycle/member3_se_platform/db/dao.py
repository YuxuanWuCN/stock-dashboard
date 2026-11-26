"""数据访问层（DAO）：A/B 实验与生命周期账本的唯一写入口。

分工
----
* ``connection.py`` 负责连接、PRAGMA、schema 与只追加表写保护；
* 本模块负责**业务校验**（枚举、区间、组间一致性、幂等）与事务边界；
* ``export.py`` 负责脱敏导出，``duck_reader.py`` 负责只读行情取数。

关键约束（与 #13 对齐）
----------------------
* A/B 分组由 ``session_id`` 确定性哈希分配：同一会话跨进程、跨导出分组不变；
* 事件写入以 ``event_uuid`` 幂等：离线平板补传重复批次不会重复计数；
* 客户端上报的 ``ab_group`` / ``age_group`` 与画像不一致时**拒绝**，而不是覆盖，
  从数据层杜绝“隐藏实验臂被篡改”的污染。
"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterable, Mapping

import connection
import export as export_module

AGE_GROUPS = ("youth", "elder", "unspecified")
COHORTS = ("campus", "community", "online", "lab")
CONSENT_SCOPES = ("analytics_only", "analytics_and_research")
DEVICE_CLASSES = ("phone", "tablet", "desktop", "unknown")
EVENT_TYPES = ("page_load", "scenario_view", "decision", "quiz_submit")
SCENARIO_DD = (0.0, -10.0, -20.0)
INSTRUMENTS = ("sus", "lsi", "rules_quiz")
SOURCES = ("web", "offline_import", "lab")
STRATEGIES = ("R-FOF-A4", "TDF-2040", "A-only")
LEDGER_SCENARIOS = ("base", "dd10", "dd20")
MAX_LATENCY_MS = 3_600_000
COMPREHENSION_MAX = 3.0

EVENT_REQUIRED = (
    "event_uuid", "session_id", "scenario_dd", "panic_redeem_clicked",
    "decision_latency_ms",
)
# 事件里允许出现的键（多余键直接拒绝，防止前端把敏感字段夹带进来）
EVENT_KEYS = frozenset({
    "event_uuid", "session_id", "ab_group", "age_group", "scenario_dd",
    "event_type", "panic_redeem_clicked", "decision_latency_ms",
    "comprehension_score", "client_ts", "source",
})


class ValidationError(ValueError):
    """输入不满足 schema/业务契约（HTTP 层映射为 400）。"""


class ConflictError(ValueError):
    """与既有画像/分组冲突（HTTP 层映射为 409）。"""


def assign_ab_group(session_id: str) -> str:
    """确定性 1:1 分组：sha256('rfof-ab-v1:' + session_id) 首字节奇偶。"""
    if not isinstance(session_id, str) or not 8 <= len(session_id) <= 64:
        raise ValidationError("session_id must be an 8-64 char string")
    return "A" if sha256(f"rfof-ab-v1:{session_id}".encode()).digest()[0] % 2 == 0 else "B"


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _enum(value: Any, allowed: Iterable[str], field: str) -> str:
    _check(isinstance(value, str) and value in tuple(allowed), f"{field} must be one of {tuple(allowed)}")
    return str(value)


def _int_in_range(value: Any, low: int, high: int, field: str) -> int:
    # bool 是 int 的子类，但实验日志里 True/False 不应被当作 1/0 的合法替身。
    _check(isinstance(value, int) and not isinstance(value, bool), f"{field} must be an integer")
    _check(low <= int(value) <= high, f"{field} must be within [{low}, {high}]")
    return int(value)


def _text(value: Any, field: str, *, max_length: int, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    _check(isinstance(value, str), f"{field} must be a string")
    _check(len(value.strip()) > 0, f"{field} must not be blank")
    _check(len(value) <= max_length, f"{field} is too long (max {max_length})")
    return str(value)


def _scenario(value: Any) -> float:
    _check(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        "scenario_dd must be a number",
    )
    _check(float(value) in SCENARIO_DD, f"scenario_dd must be one of {SCENARIO_DD}")
    return float(value)


class Repository:
    """单库 DAO。写入串行化（线程锁 + BEGIN IMMEDIATE），读取无锁。"""

    def __init__(self, db_path: str | Path, *, ensure_schema: bool = True):
        self.path = Path(db_path)
        if ensure_schema and not self.path.is_file():
            connection.init_db(self.path)
        self._connection = connection.connect(self.path)
        self._lock = threading.RLock()

    # ------------------------------------------------------------ 生命周期
    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    @contextmanager
    def transaction(self):
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")

    # ---------------------------------------------------------------- 画像
    def get_profile(self, session_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT * FROM user_profiles WHERE session_id = ?", (str(session_id),)
        ).fetchone()
        return dict(row) if row else None

    def ensure_profile(
        self,
        session_id: str,
        *,
        age_group: str,
        cohort: str = "online",
        consent_scope: str = "analytics_only",
        device_class: str = "unknown",
        client_zone: str | None = None,
    ) -> dict:
        """幂等创建画像；已存在时校验 age_group/cohort 一致并返回既有记录。"""
        _text(session_id, "session_id", max_length=64)
        age_group = _enum(age_group, AGE_GROUPS, "age_group")
        cohort = _enum(cohort, COHORTS, "cohort")
        consent_scope = _enum(consent_scope, CONSENT_SCOPES, "consent_scope")
        device_class = _enum(device_class, DEVICE_CLASSES, "device_class")
        if client_zone is not None:
            client_zone = _text(client_zone, "client_zone", max_length=64)

        existing = self.get_profile(session_id)
        if existing is not None:
            if existing["age_group"] != age_group:
                raise ConflictError(
                    f"age_group mismatch for session: stored={existing['age_group']} "
                    f"reported={age_group}"
                )
            if existing["cohort"] != cohort:
                raise ConflictError(
                    f"cohort mismatch for session: stored={existing['cohort']} reported={cohort}"
                )
            return {**existing, "created": False}

        ab_group = assign_ab_group(session_id)
        try:
            with self.transaction() as conn:
                conn.execute(
                    "INSERT INTO user_profiles "
                    "(session_id, age_group, cohort, ab_group, consent_scope, device_class, client_zone) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (session_id, age_group, cohort, ab_group, consent_scope, device_class, client_zone),
                )
        except sqlite3.IntegrityError:
            # 并发首次进入：另一进程已经插入同一 session_id，按幂等语义返回既有画像。
            existing = self.get_profile(session_id)
            if existing is None:
                raise
            return {**existing, "created": False}
        profile = self.get_profile(session_id)
        assert profile is not None
        return {**profile, "created": True}

    # ---------------------------------------------------------------- 事件
    def record_events(self, events: Iterable[Mapping[str, Any]]) -> dict:
        """批量写入交互事件；返回 inserted / duplicates / ids。

        每条事件必须能对应到已建立的匿名画像。``ab_group``/``age_group`` 若缺省则
        由画像补齐；若显式上报则必须与画像一致（否则 ConflictError）。
        """
        prepared = [self._prepare_event(event) for event in events]
        inserted = 0
        duplicates = 0
        ids: list[dict] = []
        with self.transaction() as conn:
            for event in prepared:
                profile = self.get_profile(event["session_id"])
                if profile is None:
                    raise ValidationError(
                        f"unknown session_id: {event['session_id']} (create a session first)"
                    )
                ab_group = event.pop("ab_group", None) or profile["ab_group"]
                age_group = event.pop("age_group", None) or profile["age_group"]
                if ab_group != profile["ab_group"]:
                    raise ConflictError("ab_group does not match the assigned arm of this session")
                if age_group != profile["age_group"]:
                    raise ConflictError("age_group does not match the profile of this session")
                cursor = conn.execute(
                    "INSERT INTO ui_ab_events (event_uuid, session_id, ab_group, age_group, "
                    "scenario_dd, event_type, panic_redeem_clicked, decision_latency_ms, "
                    "comprehension_score, client_ts, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(event_uuid) DO NOTHING",
                    (
                        event["event_uuid"], event["session_id"], ab_group, age_group,
                        event["scenario_dd"], event["event_type"],
                        event["panic_redeem_clicked"], event["decision_latency_ms"],
                        event["comprehension_score"], event.get("client_ts"),
                        event["source"],
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                else:
                    duplicates += 1
                row = conn.execute(
                    "SELECT event_id FROM ui_ab_events WHERE event_uuid = ?",
                    (event["event_uuid"],),
                ).fetchone()
                ids.append({"event_uuid": event["event_uuid"], "event_id": int(row[0])})
        return {"inserted": inserted, "duplicates": duplicates, "events": ids}

    def _prepare_event(self, event: Mapping[str, Any]) -> dict:
        _check(isinstance(event, Mapping), "each event must be an object")
        unknown = set(event) - EVENT_KEYS
        _check(not unknown, f"event contains unsupported fields: {sorted(unknown)}")
        for key in EVENT_REQUIRED:
            _check(key in event, f"event is missing required field: {key}")

        event_uuid = _text(event["event_uuid"], "event_uuid", max_length=64)
        session_id = _text(event["session_id"], "session_id", max_length=64)
        _check(len(event_uuid) >= 8, "event_uuid must be at least 8 chars")

        prepared = {
            "event_uuid": event_uuid,
            "session_id": session_id,
            "scenario_dd": _scenario(event["scenario_dd"]),
            "event_type": _enum(event.get("event_type", "decision"), EVENT_TYPES, "event_type"),
            "panic_redeem_clicked": _int_in_range(
                event["panic_redeem_clicked"], 0, 1, "panic_redeem_clicked"
            ),
            "decision_latency_ms": _int_in_range(
                event["decision_latency_ms"], 0, MAX_LATENCY_MS, "decision_latency_ms"
            ),
            "source": _enum(event.get("source", "web"), SOURCES, "source"),
        }
        score = event.get("comprehension_score", 0)
        _check(
            isinstance(score, (int, float)) and not isinstance(score, bool)
            and 0 <= float(score) <= COMPREHENSION_MAX,
            f"comprehension_score must be within [0, {COMPREHENSION_MAX}]",
        )
        prepared["comprehension_score"] = float(score)
        if event.get("ab_group") is not None:
            prepared["ab_group"] = _enum(event["ab_group"], ("A", "B"), "ab_group")
        if event.get("age_group") is not None:
            prepared["age_group"] = _enum(event["age_group"], AGE_GROUPS, "age_group")
        prepared["client_ts"] = _text(
            event.get("client_ts"), "client_ts", max_length=40, allow_none=True
        )
        return prepared

    # ---------------------------------------------------------------- 问卷
    def record_survey(
        self,
        session_id: str,
        instrument: str,
        items: Iterable[Mapping[str, Any]],
    ) -> int:
        """长表 upsert：同一会话同一量表同一题项保留最后一次作答。"""
        _text(session_id, "session_id", max_length=64)
        instrument = _enum(instrument, INSTRUMENTS, "instrument")
        if self.get_profile(session_id) is None:
            raise ValidationError(f"unknown session_id: {session_id}")
        rows = []
        for item in items:
            _check(isinstance(item, Mapping), "each survey item must be an object")
            _check(set(item) <= {"item_code", "item_value", "sequence"}, "unsupported survey fields")
            code = _text(item.get("item_code"), "item_code", max_length=32)
            value = item.get("item_value")
            _check(
                isinstance(value, (int, float)) and not isinstance(value, bool),
                "item_value must be numeric",
            )
            sequence = _int_in_range(item.get("sequence", 0), 0, 1000, "sequence")
            if instrument == "rules_quiz":
                _check(float(value) in (0.0, 1.0), "rules_quiz item_value must be 0 or 1")
            else:
                _check(1.0 <= float(value) <= 5.0, f"{instrument} item_value must be within [1, 5]")
            rows.append((session_id, instrument, code, float(value), sequence))
        with self.transaction() as conn:
            conn.executemany(
                "INSERT INTO survey_responses "
                "(session_id, instrument, item_code, item_value, sequence) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id, instrument, item_code) DO UPDATE SET "
                "item_value = excluded.item_value, sequence = excluded.sequence, "
                "answered_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                rows,
            )
        return len(rows)

    # ---------------------------------------------------------------- 账本
    def append_ledger(self, rows: Iterable[Mapping[str, Any]]) -> int:
        """写入/更新逐日账本（幂等 upsert，允许重跑同一净值序列）。"""
        prepared = []
        for row in rows:
            _check(isinstance(row, Mapping), "each ledger row must be an object")
            strategy = _text(row.get("strategy_id"), "strategy_id", max_length=48)
            _check(strategy in STRATEGIES, f"strategy_id must be one of {STRATEGIES}")
            scenario = _enum(row.get("scenario"), LEDGER_SCENARIOS, "scenario")
            trade_date = _text(row.get("trade_date"), "trade_date", max_length=10)
            _check(
                len(trade_date) == 10 and trade_date[4] == "-" and trade_date[7] == "-",
                "trade_date must be ISO YYYY-MM-DD",
            )
            nav = float(row.get("nav", 0) or 0)
            _check(nav > 0, "nav must be positive")
            drawdown = float(row.get("drawdown", 0) or 0)
            _check(drawdown <= 0, "drawdown must be <= 0")
            locked = float(row.get("locked_floor", 0) or 0)
            _check(locked >= 0, "locked_floor must be >= 0")
            daily = row.get("daily_return")
            if daily is not None:
                daily = float(daily)
                _check(daily > -1, "daily_return must be > -1")
            digest = row.get("source_sha256")
            if digest is not None:
                _text(digest, "source_sha256", max_length=64)
                _check(len(str(digest)) == 64, "source_sha256 must be 64 hex chars")
            prepared.append((strategy, scenario, trade_date, nav, daily, drawdown, locked, digest))
        with self.transaction() as conn:
            conn.executemany(
                "INSERT INTO lifecycle_ledger "
                "(strategy_id, scenario, trade_date, nav, daily_return, drawdown, locked_floor, source_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(strategy_id, scenario, trade_date) DO UPDATE SET "
                "nav = excluded.nav, daily_return = excluded.daily_return, "
                "drawdown = excluded.drawdown, locked_floor = excluded.locked_floor, "
                "source_sha256 = excluded.source_sha256",
                prepared,
            )
        return len(prepared)

    # ---------------------------------------------------------------- 查询
    def decision_stats(self) -> list[dict]:
        return [dict(row) for row in self._connection.execute(
            "SELECT * FROM v_ab_decision_stats ORDER BY ab_group, age_group, scenario_dd"
        )]

    def coverage(self) -> list[dict]:
        return [dict(row) for row in self._connection.execute(
            "SELECT * FROM v_ab_session_coverage ORDER BY ab_group, age_group, cohort"
        )]

    def session_events(self, session_id: str) -> list[dict]:
        return [dict(row) for row in self._connection.execute(
            "SELECT * FROM ui_ab_events WHERE session_id = ? ORDER BY event_id", (session_id,)
        )]

    # ---------------------------------------------------------------- 导出
    def export(self, out_dir: str | Path, *, salt: str | None = None) -> dict:
        return export_module.export_dataset(self._connection, out_dir, salt=salt)