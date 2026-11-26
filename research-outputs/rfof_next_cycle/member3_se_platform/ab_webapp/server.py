"""A/B 实验本地后端 API（Flask，零外部服务依赖）。

启动
----
    python ab_webapp/server.py --port 8000
    # 或指定库：python ab_webapp/server.py --db data/rfof_ab.sqlite3 --port 8000

接口
----
POST /api/session      建立/取回匿名会话与分组（确定性分组，幂等）
POST /api/events       批量写交互事件（event_uuid 幂等）
POST /api/survey       写量表/测验作答（长表 upsert）
POST /api/import       导入离线平板导出的 JSON 包（幂等）
GET  /api/stats        决策统计与覆盖率视图
GET  /api/export       CSV 脱敏导出（本机访问或 X-Export-Token）
GET  /api/health       健康检查（含 DuckDB 与真实面板可用性）

权限口径
--------
* 写入接口只接受本机/局域网内的实验设备，不启用任何用户登录（匿名实验）；
* 导出接口含全部实验原始行，必须限制为「本机回环地址」或携带 ``RFOF_EXPORT_TOKEN``。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import hashlib
import json
import os
from pathlib import Path
import sys

from flask import Flask, Response, jsonify, request, send_from_directory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "db"))

import connection  # noqa: E402
import duck_reader  # noqa: E402
import export as export_module  # noqa: E402
from dao import ConflictError, Repository, ValidationError  # noqa: E402

DEFAULT_DB = HERE.parent / "data" / "rfof_ab.sqlite3"
MAX_BATCH = 500
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _json_error(status: int, message: str, *, field: str | None = None):
    payload = {"ok": False, "error": message}
    if field:
        payload["field"] = field
    return jsonify(payload), status


def create_app(
    db_path: str | Path | None = None,
    *,
    static_dir: str | Path | None = None,
    export_token: str | None = None,
) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 单批次 JSON 上限 2MB
    app.json.ensure_ascii = False

    database = Path(db_path) if db_path is not None else DEFAULT_DB
    repo = Repository(database)
    app.extensions["rfof_repository"] = repo
    token = export_token if export_token is not None else os.environ.get("RFOF_EXPORT_TOKEN") or None
    assets = Path(static_dir) if static_dir is not None else HERE

    @app.errorhandler(ValidationError)
    def _bad_input(error):
        return _json_error(400, str(error))

    @app.errorhandler(ConflictError)
    def _conflict(error):
        return _json_error(409, str(error))

    @app.errorhandler(404)
    def _not_found(_error):
        return _json_error(404, "resource not found")

    @app.after_request
    def _cors(response):
        # 社区平板可能用 file:// 打开页面再向笔记本上的本机服务补传事件；
        # 该接口是匿名只写（无 Cookie/无凭据），因此放开跨域但不允许携带凭据。
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, X-Export-Token")
        response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        return response

    @app.route("/api/<path:_path>", methods=["OPTIONS"])
    def _cors_preflight(_path: str):
        return ("", 204)

    # ------------------------------------------------------------- 静态页面
    @app.get("/")
    def index():
        return send_from_directory(assets, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        # 只放行前端资产；拒绝把 server.py 等后端源码当静态文件读走。
        if Path(filename).suffix.lower() not in {".html", ".css", ".js", ".svg", ".png",
                                                 ".jpg", ".webp", ".ico", ".json"}:
            return _json_error(404, "resource not found")
        return send_from_directory(assets, filename)

    # --------------------------------------------------------------- 健康
    @app.get("/api/health")
    def health():
        reader = duck_reader.DuckDBMarketReader(HERE.parents[3])
        try:
            panel = reader.panel_provenance()
            panel_ok = True
            panel_rows = panel["rows"]
            manifest_ok = panel["rows_match_manifest"]
        except FileNotFoundError:
            panel_ok, panel_rows, manifest_ok = False, 0, False
        try:
            import duckdb  # noqa: F401

            duck_ok = True
        except ImportError:
            duck_ok = False
        return jsonify({
            "ok": True,
            "schema_version": connection.schema_version(repo.connection),
            "db": str(database),
            "duckdb_available": duck_ok,
            "stock_panel_available": panel_ok,
            "stock_panel_rows": panel_rows,
            "stock_panel_manifest_match": manifest_ok,
        })

    # --------------------------------------------------------------- 会话
    @app.post("/api/session")
    def create_session():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error(400, "body must be a JSON object")
        session_id = payload.get("session_id")
        profile = repo.ensure_profile(
            session_id,
            age_group=payload.get("age_group", "unspecified"),
            cohort=payload.get("cohort", "online"),
            consent_scope=payload.get("consent_scope", "analytics_only"),
            device_class=payload.get("device_class", "unknown"),
            client_zone=payload.get("client_zone"),
        )
        body = {key: profile[key] for key in (
            "session_id", "ab_group", "age_group", "cohort", "consent_scope", "device_class"
        )}
        body["created"] = bool(profile["created"])
        return jsonify({"ok": True, **body}), (201 if profile["created"] else 200)

    @app.get("/api/session/<session_id>")
    def get_session(session_id: str):
        profile = repo.get_profile(session_id)
        if profile is None:
            return _json_error(404, "unknown session_id")
        return jsonify({"ok": True, **profile})

    # --------------------------------------------------------------- 事件
    @app.post("/api/events")
    def post_events():
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            events = payload.get("events", [payload] if "event_uuid" in payload else None)
        else:
            events = payload
        if not isinstance(events, list) or not events:
            return _json_error(400, "events must be a non-empty array")
        if len(events) > MAX_BATCH:
            return _json_error(413, f"at most {MAX_BATCH} events per request")
        result = repo.record_events(events)
        return jsonify({"ok": True, **result}), 201

    # --------------------------------------------------------------- 问卷
    @app.post("/api/survey")
    def post_survey():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error(400, "body must be a JSON object")
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return _json_error(400, "items must be a non-empty array")
        saved = repo.record_survey(
            payload.get("session_id", ""), payload.get("instrument", ""), items
        )
        return jsonify({"ok": True, "saved": saved}), 201

    # --------------------------------------------------------- 离线包导入
    @app.post("/api/import")
    def import_offline():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "body must be a JSON object")
        summaries = {"profiles": 0, "events": 0, "surveys": 0}
        for profile in payload.get("profiles", []):
            created = repo.ensure_profile(
                profile.get("session_id"),
                age_group=profile.get("age_group", "unspecified"),
                cohort=profile.get("cohort", "community"),
                consent_scope=profile.get("consent_scope", "analytics_only"),
                device_class=profile.get("device_class", "tablet"),
                client_zone=profile.get("client_zone"),
            )
            summaries["profiles"] += int(created["created"])
        events = payload.get("events", [])
        if events:
            for event in events:
                event.setdefault("source", "offline_import")
            summaries["events"] = repo.record_events(events)["inserted"]
        for survey in payload.get("surveys", []):
            summaries["surveys"] += repo.record_survey(
                survey.get("session_id"), survey.get("instrument"), survey.get("items", [])
            )
        return jsonify({"ok": True, "imported": summaries}), 201

    # --------------------------------------------------------------- 统计
    @app.get("/api/stats")
    def stats():
        return jsonify({
            "ok": True,
            "decisions": repo.decision_stats(),
            "coverage": repo.coverage(),
        })

    # --------------------------------------------------------------- 导出
    @app.get("/api/export")
    def export_csv():
        if not _export_allowed(token):
            return _json_error(403, "export is restricted to loopback or X-Export-Token")
        table = request.args.get("table", "ui_ab_events")
        # 盐的优先级：RFOF_EXPORT_SALT 环境变量 > 本库持久化研究盐。
        # 同一实验库的多次导出因此可以按 session_ref 互相 join（#13 需要）。
        salt = export_module.resolve_salt(repo.connection)
        try:
            columns, rows = export_module.collect_rows(repo.connection, table, salt)
        except ValueError as error:
            return _json_error(400, str(error))
        buffer = io.StringIO()
        import csv as csv_module

        writer = csv_module.writer(buffer)
        writer.writerow(columns)
        writer.writerows(rows)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return Response(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{table}_{stamp}.csv"',
                # 只暴露盐的哈希：组织者可核对两次导出是否同一盐，但拿不到盐本身。
                "X-Export-Salt-SHA256": hashlib.sha256(salt.encode("utf-8")).hexdigest(),
            },
        )

    return app


def _export_allowed(token: str | None) -> bool:
    if token:
        return request.headers.get("X-Export-Token", "") == token
    return _is_loopback(request.remote_addr)


def _is_loopback(address: str | None) -> bool:
    return address in _LOOPBACK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R-FOF A/B 实验本地服务")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 路径（不存在会自动初始化）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    app = create_app(args.db)
    print(f"R-FOF A/B 实验服务： http://{args.host}:{args.port}/  (db={args.db})")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())