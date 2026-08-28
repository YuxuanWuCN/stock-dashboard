"""一次性 bypass token（彩虹找虫 v2）。

Manifest 门禁误报/特殊情况的人工放行通道，带审计。
借鉴 peaks-cli 的 gate bypass：
- 一次性 token，消费即焚
- 每 sop 每 project 每 session 未消费 token 数上限（默认 3）
- 签发必须记原因；消费必须记上下文
- 存储 .quality-state/bypass-tokens.json（自动受门禁保护）

设计约束：纯标准库；全部 UTF-8；不读 stdin；自身异常 fail-open。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parents[1] / ".quality-state"
MAX_PER_SESSION = 3


def token_store_path() -> Path:
    return STATE_DIR / "bypass-tokens.json"


def read_tokens() -> dict:
    try:
        return json.loads(token_store_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "tokens": []}


def write_tokens(store: dict) -> None:
    token_store_path().parent.mkdir(parents=True, exist_ok=True)
    temporary = token_store_path().with_suffix(".json.tmp")
    temporary.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(token_store_path())


def issue_token(reason: str, *, sop: str = "default", session: str = "current") -> dict:
    """签发一次性 token。超出上限 → RuntimeError。"""
    store = read_tokens()
    tokens = store.setdefault("tokens", [])
    session = str(session)
    sop = str(sop)
    active = [
        t for t in tokens
        if t.get("sop") == sop and t.get("session") == session and t.get("consumed_at") is None
    ]
    if len(active) >= MAX_PER_SESSION:
        raise RuntimeError(f"超出 bypass 上限：每会话每 SOP 最多 {MAX_PER_SESSION} 个未消费 token")

    token = {
        "id": uuid.uuid4().hex,
        "reason": str(reason),
        "sop": sop,
        "session": session,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "consumed_at": None,
        "consumed_by": None,
    }
    tokens.append(token)
    write_tokens(store)
    return token


def consume_token(token_id: str, context: str) -> tuple[bool, str]:
    """消费 token。成功返回 (True, sop)；失败返回 (False, 原因)。"""
    store = read_tokens()
    for token in store.get("tokens", []):
        if token.get("id") == token_id:
            if token.get("consumed_at") is not None:
                return False, "token 已消费"
            token["consumed_at"] = datetime.now(timezone.utc).isoformat()
            token["consumed_by"] = str(context)
            write_tokens(store)
            return True, str(token.get("sop", "default"))
    return False, "token 无效或不存在"


def command_bypass(args: argparse.Namespace) -> int:
    """bypass 子命令：签发 token。输出一行 BYPASS-TOKEN=<id>。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        token = issue_token(args.reason, sop=getattr(args, "sop", "default"))
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(f"BYPASS-TOKEN={token['id']}")
    print(f"原因：{token['reason']} ｜ SOP：{token['sop']}")
    return 0


def command_bypass_consume(args: argparse.Namespace) -> int:
    """bypass-consume 子命令：消费 token。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ok, info = consume_token(args.token, getattr(args, "context", "cli"))
    if not ok:
        print(f"错误：{info}", file=sys.stderr)
        return 2
    print(f"token 已消费（SOP: {info}）")
    return 0


def run(argv: list[str] | None = None) -> int:
    """CLI 入口：python tools/bypass.py issue --reason ... / consume <token>"""
    parser = argparse.ArgumentParser(prog="bypass")
    sub = parser.add_subparsers(dest="cmd", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--reason", required=True)
    issue.add_argument("--sop", default="default")
    issue.set_defaults(handler=command_bypass)
    consume = sub.add_parser("consume")
    consume.add_argument("token")
    consume.add_argument("--context", default="cli")
    consume.set_defaults(handler=command_bypass_consume)
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(run())
