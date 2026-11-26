"""SQLite 连接工厂：统一的 PRAGMA、schema 应用与“只追加表”写保护。

设计要点
--------
* ``sqlite3.connect`` 默认不启用外键，这里显式打开，避免约束在长连接里静默失效；
* ``ui_ab_events`` 是实验原始日志：用 SQLite authorizer 在连接层拒绝 UPDATE / DELETE，
  防止行为记录被就地篡改（``lifecycle_ledger`` 为可重建的派生账本，允许 upsert）；
* schema 重复 apply 必须幂等（全部 IF NOT EXISTS），初始化脚本与测试共用本模块。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = "1"

# 只追加（append-only）表：实验原始事件一旦落库，不允许被 UPDATE/DELETE。
# ``lifecycle_ledger`` 是可从 #12 净值序列重建的派生账本，允许幂等 upsert，故不在此列。
APPEND_ONLY_TABLES = frozenset({"ui_ab_events"})

# 诚实写词的 PRAGMA（每次连接都设置，不依赖数据库文件里的默认状态）。
_PRAGMAS = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
)


def apply_schema(connection: sqlite3.Connection) -> None:
    """在给定连接上幂等地执行 schema.sql。"""
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    connection.commit()


def _authorizer(append_only: frozenset[str]):
    denied = {(sqlite3.SQLITE_UPDATE, name) for name in append_only}
    denied |= {(sqlite3.SQLITE_DELETE, name) for name in append_only}

    def callback(action: int, arg1, arg2, _dbname, _trigger) -> int:
        # arg1 是表名（对于 UPDATE/DELETE），arg2 是列名。
        key = (action, arg1)
        if key in denied:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return callback


def connect(
    db_path: str | Path,
    *,
    append_only: bool = True,
    timeout: float = 5.0,
) -> sqlite3.Connection:
    """打开（必要时创建）SQLite 库，并启用约束与写保护。

    ``append_only=True`` 时给连接挂上 authorizer：对 ``APPEND_ONLY_TABLES``
    的 UPDATE / DELETE 直接抛 ``sqlite3.DatabaseError``，INSERT / SELECT 不受影响。
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        path, timeout=timeout, isolation_level=None, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        connection.execute(pragma)
    if append_only:
        connection.set_authorizer(_authorizer(APPEND_ONLY_TABLES))
    return connection


def init_db(db_path: str | Path, *, overwrite: bool = False) -> Path:
    """初始化数据库文件；``overwrite=True`` 时删除旧文件重建（仅测试/本地重置）。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and path.exists():
        path.unlink()
    # 初始化阶段不带 authorizer，否则 DDL 之后的视图/索引维护可能被误拦截。
    connection = connect(path, append_only=False)
    try:
        apply_schema(connection)
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        if version != SCHEMA_VERSION:
            raise RuntimeError(f"schema version mismatch: {version} != {SCHEMA_VERSION}")
    finally:
        connection.close()
    return path


def schema_version(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        raise RuntimeError("schema_meta is empty: run init_db first")
    return str(row[0])