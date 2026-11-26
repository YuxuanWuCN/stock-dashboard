"""脱敏导出：把 SQLite 实验数据导出供 #13（信管 B）做卡方 / Fisher / Logistic 分析。

三层脱敏
--------
1. **列白名单**：只导出分析必需的列，任何后续新增的可识别列默认不会外流；
2. **会话假名化**：``session_id`` 一律替换为 ``session_ref``（``S-`` + sha256(salt +
   session_id)[:12]），同一次导出内可关联、跨导出不可关联；
3. **清单可复核**：每次导出写 ``export_manifest.json``，记录行数、列名、CSV 的
   sha256 与盐的 sha256（不写盐本身），方便 #13 复现统计口径。

本地用法
--------
    python db/export.py --db data/rfof_ab.sqlite3 --out exports/ --salt demo-salt
"""

from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import secrets
import sqlite3

# 导出表 → (选列, 行排序键, 会话列名或 None)
EXPORT_TABLES: dict[str, dict[str, object]] = {
    "ui_ab_events": {
        "columns": (
            "event_id", "event_uuid", "session_id", "ab_group", "age_group",
            "scenario_dd", "event_type", "panic_redeem_clicked",
            "decision_latency_ms", "comprehension_score", "client_ts",
            "server_ts", "source",
        ),
        "order_by": "event_id",
        "session_column": "session_id",
    },
    "user_profiles": {
        "columns": (
            "session_id", "age_group", "cohort", "ab_group", "consent_scope",
            "device_class", "client_zone", "created_at",
        ),
        "order_by": "profile_id",
        "session_column": "session_id",
    },
    "survey_responses": {
        "columns": (
            "response_id", "session_id", "instrument", "item_code", "item_value",
            "sequence", "answered_at",
        ),
        "order_by": "response_id",
        "session_column": "session_id",
    },
    "lifecycle_ledger": {
        "columns": (
            "strategy_id", "scenario", "trade_date", "nav", "daily_return",
            "drawdown", "locked_floor", "source_sha256",
        ),
        "order_by": "strategy_id, scenario, trade_date",
        "session_column": None,
    },
    "v_ab_decision_stats": {
        "columns": (
            "ab_group", "age_group", "scenario_dd", "decisions", "panic_redeems",
            "panic_rate_pct", "avg_latency_ms", "avg_comprehension",
        ),
        "order_by": "ab_group, age_group, scenario_dd",
        "session_column": None,
    },
}

# 白名单之外的任何列名都不应出现（防御性自检，见 assert_no_identifier_columns）
IDENTIFIER_TOKENS = frozenset({
    "name", "phone", "mobile", "idcard", "email", "address", "ip", "wechat",
    "passport", "realname", "birth", "birthday", "idcardno",
})


SALT_META_KEY = "export_salt"


def resolve_salt(conn: sqlite3.Connection, explicit: str | None = None) -> str:
    """确定导出盐：显式参数 > RFOF_EXPORT_SALT 环境变量 > 本库持久化盐。

    盐存在 ``schema_meta`` 里，因此同一实验库的多次导出**互相关联**（#13 可把
    events / survey / profiles 三张表按 ``session_ref`` join 起来）；换一个库
    （或显式指定不同盐）则不可关联，符合“同一研究内可追踪、跨研究不可反查”。
    """
    if explicit:
        return explicit
    configured = os.environ.get("RFOF_EXPORT_SALT")
    if configured:
        return configured
    row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (SALT_META_KEY,)).fetchone()
    if row is not None:
        return str(row[0])
    fresh = secrets.token_hex(16)
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
        (SALT_META_KEY, fresh),
    )
    row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (SALT_META_KEY,)).fetchone()
    return str(row[0])


def session_ref(session_id: str, salt: str) -> str:
    """稳定假名：同一盐下同会话映射一致，不同盐下不可反查、不可跨导出关联。"""
    if not session_id:
        raise ValueError("session_id is required")
    return "S-" + sha256(f"{salt}:{session_id}".encode("utf-8")).hexdigest()[:12]


def _resolve_source(conn: sqlite3.Connection, table: str) -> tuple[list[str], str, str | None]:
    if table not in EXPORT_TABLES:
        raise ValueError(f"table is not exportable: {table}")
    spec = EXPORT_TABLES[table]
    return list(spec["columns"]), str(spec["order_by"]), spec["session_column"]  # type: ignore[index]


def collect_rows(
    conn: sqlite3.Connection,
    table: str,
    salt: str,
) -> tuple[list[str], list[tuple]]:
    """读取白名单列并完成会话假名化；不含任何原始 session_id。"""
    columns, order_by, session_column = _resolve_source(conn, table)
    sql = f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order_by}"
    rows = conn.execute(sql).fetchall()
    out_columns = [("session_ref" if col == session_column else col) for col in columns]
    index = columns.index(session_column) if session_column else None
    prepared = []
    for row in rows:
        values = list(row)
        if index is not None:
            values[index] = session_ref(str(values[index]), salt)
        prepared.append(tuple(values))
    assert_no_identifier_columns(out_columns)
    return out_columns, prepared


def assert_no_identifier_columns(columns: list[str]) -> None:
    for column in columns:
        lowered = column.lower()
        parts = {part for part in re.split(r"[^a-z0-9]+", lowered) if part}
        normalized = re.sub(r"[^a-z0-9]+", "", lowered)
        for token in IDENTIFIER_TOKENS:
            # 两字符 token（如 ip）只做分词匹配，避免 description 之类误报。
            if token in parts or (len(token) >= 3 and token in normalized):
                raise AssertionError(f"导出列疑似包含可识别信息：{column}")


def _write_csv(path: Path, columns: list[str], rows: list[tuple]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    return sha256(path.read_bytes()).hexdigest()


def export_dataset(
    conn: sqlite3.Connection,
    out_dir: str | Path,
    *,
    salt: str | None = None,
    tables: tuple[str, ...] = tuple(EXPORT_TABLES),
) -> dict:
    """导出所有白名单表 + 清单。返回清单字典（同时写入 export_manifest.json）。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    selected_salt = resolve_salt(conn, salt)
    schema_version = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    manifest = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": str(schema_version),
        "salt_sha256": sha256(selected_salt.encode("utf-8")).hexdigest(),
        "pseudonymisation": "session_ref = 'S-' + sha256(salt + ':' + session_id)[:12]",
        "tables": {},
    }
    for table in tables:
        columns, rows = collect_rows(conn, table, selected_salt)
        name = f"{table}.csv"
        digest = _write_csv(out / name, columns, rows)
        manifest["tables"][table] = {
            "file": name,
            "rows": len(rows),
            "columns": columns,
            "csv_sha256": digest,
        }
    (out / "export_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R-FOF A/B 实验数据脱敏导出")
    parser.add_argument("--db", required=True, help="SQLite 数据库路径")
    parser.add_argument("--out", required=True, help="导出目录")
    parser.add_argument("--salt", default=None, help="假名盐；缺省则每次随机（记录盐哈希）")
    args = parser.parse_args(argv)

    from connection import connect

    conn = connect(args.db, append_only=False)
    try:
        manifest = export_dataset(conn, args.out, salt=args.salt)
    finally:
        conn.close()
    total = sum(item["rows"] for item in manifest["tables"].values())
    for table, item in manifest["tables"].items():
        print(f"{table:22s} rows={item['rows']:6d} sha256={item['csv_sha256'][:12]}")
    print(f"总行数 {total}，清单：{Path(args.out) / 'export_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())