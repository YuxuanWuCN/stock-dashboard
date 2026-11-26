"""本地初始化脚本：建库、应用 schema、打印表清单并生成 ER 图。

用法
----
    python db/init_db.py                          # 默认建在 data/rfof_ab.sqlite3
    python db/init_db.py --db /tmp/rfof.sqlite3   # 指定路径
    python db/init_db.py --check                  # 只校验既有库，不新建
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import sys

import connection
import er_diagram

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "rfof_ab.sqlite3"


def _tables(db_path: Path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="初始化 R-FOF SQLite 业务库")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="数据库路径")
    parser.add_argument("--check", action="store_true", help="只校验既有库")
    parser.add_argument("--no-er", action="store_true", help="跳过 ER 图生成")
    parser.add_argument("--print-er", action="store_true", help="只打印 Mermaid ER 图")
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if args.check:
        if not db_path.is_file():
            print(f"库不存在：{db_path}", file=sys.stderr)
            return 1
        conn = connection.connect(db_path)
        try:
            version = connection.schema_version(conn)
        finally:
            conn.close()
    else:
        if args.print_er:
            conn = connection.connect(":memory:", append_only=False)
            connection.apply_schema(conn)
        else:
            connection.init_db(db_path)
            conn = connection.connect(db_path)
        try:
            version = connection.schema_version(conn)
            if args.print_er:
                print(er_diagram.mermaid(conn))
                return 0
        finally:
            conn.close()

    print(f"数据库：{db_path}")
    print(f"schema_version：{version}")
    print("表：" + ", ".join(_tables(db_path)))

    conn = connection.connect(db_path, append_only=False)
    try:
        print("视图：" + ", ".join(
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name"
            )
        ))
    finally:
        conn.close()

    if not args.no_er:
        er_path = Path(er_diagram.__file__).with_name("er_diagram.md")
        er_conn = connection.connect(db_path, append_only=False)
        try:
            er_path.write_text(er_diagram.markdown(er_conn), encoding="utf-8")
        finally:
            er_conn.close()
        print(f"ER 图：{er_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())