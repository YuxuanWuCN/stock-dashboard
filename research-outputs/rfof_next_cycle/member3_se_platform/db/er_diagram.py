"""从 SQLite 实际 schema 反向生成 ER 关系图（防止文档与库结构漂移）。

输出
----
* ``db/er_diagram.md``：Mermaid ER 源码 + 字段口径表，可直接在 GitHub / VSCode 渲染；
* 控制台：Mermaid 文本，便于粘贴到 Issue / PR / 答辩材料。

用法
----
    python db/er_diagram.py            # 生成 er_diagram.md
    python db/er_diagram.py --print    # 只打印

图关系来自 ``PRAGMA foreign_key_list``，字段来自 ``PRAGMA table_info``，
因此 schema.sql 改动后重跑即可，不需要手抄。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from connection import apply_schema, connect, init_db  # noqa: F401  (init_db 供 CLI 重建使用)

CORE_TABLES = ("user_profiles", "survey_responses", "lifecycle_ledger", "ui_ab_events")
VIEWS = ("v_ab_decision_stats", "v_ab_session_coverage", "v_survey_wide")


def _columns(conn: sqlite3.Connection, table: str) -> list[dict]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    result = []
    for row in rows:
        result.append({
            "name": row[1],
            "type": row[2],
            "not_null": bool(row[3]),
            "default": row[4],
            "pk": bool(row[5]),
        })
    return result


def _references(conn: sqlite3.Connection, table: str) -> list[tuple[str, str, str]]:
    """返回 (子表列, 父表, 父表列) 三元组，按 (子表, 父表) 排序保证输出稳定。"""
    rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    links = [(row[3], row[2], row[4]) for row in rows]
    return sorted(links)


def mermaid(conn: sqlite3.Connection, tables: tuple[str, ...] = CORE_TABLES) -> str:
    lines = ["erDiagram"]
    for table in tables:
        lines.append(f"    {table} {{")
        for column in _columns(conn, table):
            markers = []
            if column["pk"]:
                markers.append("PK")
            if column["not_null"]:
                markers.append("NOT NULL")
            if column["default"] is not None:
                markers.append("DEFAULT")
            suffix = (" " + " ".join(markers)) if markers else ""
            lines.append(f"        {column['type'].replace(' ', '_')} {column['name']}{suffix}")
        lines.append("    }")
    for table in tables:
        for child_column, parent, parent_column in _references(conn, table):
            lines.append(f"    {parent} ||--o{{ {table} : \"{parent_column} -> {child_column}\"")
    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def markdown(conn: sqlite3.Connection) -> str:
    parts = [
        "# R-FOF 下周期 · SQLite 业务与行为日志库 ER 图",
        "",
        "> 本文件由 `db/er_diagram.py` 依据**实际库结构**自动生成，请勿手改；",
        "> 修改 `db/schema.sql` 后运行 `python db/er_diagram.py` 重新生成。",
        "",
        "## 1. 实体关系（Mermaid）",
        "",
        "```mermaid",
        mermaid(conn).rstrip(),
        "```",
        "",
        "## 2. 关系口径",
        "",
        "| 父表 | 子表 | 关系 | 说明 |",
        "| --- | --- | --- | --- |",
        "| `user_profiles.session_id` | `survey_responses.session_id` | 1 : N，级联删除 | 同一匿名会话可提交多份量表 |",
        "| `user_profiles.session_id` | `ui_ab_events.session_id` | 1 : N，级联删除 | 交互事件按会话归档 |",
        "| `lifecycle_ledger` | — | 独立事实表 | 策略×情景×交易日的逐日净值/回撤/棘轮账本 |",
        "",
        "## 3. 字段字典",
        "",
    ]
    for table in CORE_TABLES:
        parts.append(f"### {table}")
        parts.append("")
        parts.append("| 字段 | 类型 | 约束 | 默认值 |")
        parts.append("| --- | --- | --- | --- |")
        for column in _columns(conn, table):
            constraints = []
            if column["pk"]:
                constraints.append("PK")
            if column["not_null"]:
                constraints.append("NOT NULL")
            parts.append(
                "| `{}` | {} | {} | {} |".format(
                    _escape(column["name"]),
                    _escape(column["type"]),
                    _escape(", ".join(constraints)) or "—",
                    _escape(column["default"]) if column["default"] is not None else "—",
                )
            )
        parts.append("")
    parts.append("## 4. 分析视图")
    parts.append("")
    for view in VIEWS:
        parts.append(f"* `{view}`")
    parts.append("")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 R-FOF SQLite ER 图")
    parser.add_argument("--db", default=":memory:", help="数据库路径，默认在内存中建库")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "er_diagram.md"))
    parser.add_argument("--print", action="store_true", help="只打印 Mermaid 文本")
    args = parser.parse_args(argv)

    if args.db == ":memory:":
        conn = connect(":memory:", append_only=False)
        apply_schema(conn)
    else:
        init_db(args.db)
        conn = connect(args.db, append_only=False)

    try:
        if args.print:
            print(mermaid(conn))
        else:
            Path(args.out).write_text(markdown(conn), encoding="utf-8")
            print(f"ER 图已生成：{args.out}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())