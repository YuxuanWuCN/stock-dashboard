# -*- coding: utf-8 -*-
"""Agent ↔ 极星 9.5 文件握手协议（外部侧实现）。

协议目标
--------
让外部 agent 能够"生成订单意向"，但**只有在人类明确确认后**，才由极星内嵌策略
调用官方 ``A_SendOrder`` 真正发单。所有校验规则来自唯一的 ``policy.json``，
两侧代码都不硬编码限额。

文件清单（``ipc/`` 目录）
------------------------
===================== ========== ==========================================
文件                   方向       含义
===================== ========== ==========================================
policy.json           人工维护   唯一限额来源
account_snapshot.json 策略→agent 账户快照（G2 验收对象）
heartbeat.json        策略→agent 策略存活心跳（含诊断探针结果）
order_request.json    agent→策略 待确认的订单意向
order_approval.json   agent→策略 人类批准凭证（绑定 request 字节哈希）
cancel_request.json   agent→策略 撤单指令
reconciliation.json   策略→agent 发单结果与委托状态回查（G3/G4）
execution_log.jsonl   策略→agent 追加式审计流水
consumed/             策略维护   已执行意向归档（防重放）
===================== ========== ==========================================

设计要点
--------
1. **单次使用**：批准凭证被消费后连同 request 一起移入 ``consumed/``，同一凭证
   无法第二次发单（防重放）。
2. **字节级绑定**：``order_approval.json`` 中的 ``request_sha256`` 必须是
   ``order_request.json`` **原始字节**的 sha256。任何对意向的篡改都会使批准失效。
3. **时效约束**：意向与批准都受 ``max_request_age_sec`` 限制，陈旧批准不会被执行。
4. **熔断优先**：``kill_switch.flag`` 存在时，一切发单校验直接失败。

本模块仅依赖标准库。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROTOCOL_VERSION = "1.0"

#: 项目内默认 IPC 目录
DEFAULT_IPC_DIR = Path(r"D:\第九届郑商所杯_2026\02_极星量化与实盘\ipc")

POLICY_FILENAME = "policy.json"
REQUEST_FILENAME = "order_request.json"
APPROVAL_FILENAME = "order_approval.json"
CANCEL_FILENAME = "cancel_request.json"
SNAPSHOT_FILENAME = "account_snapshot.json"
HEARTBEAT_FILENAME = "heartbeat.json"
RECONCILIATION_FILENAME = "reconciliation.json"
EXECUTION_LOG_FILENAME = "execution_log.jsonl"
KILL_SWITCH_FILENAME = "kill_switch.flag"
CONSUMED_DIRNAME = "consumed"

DEFAULT_POLICY: Dict[str, Any] = {
    "protocol_version": PROTOCOL_VERSION,
    "allow_trading": False,
    "allowed_symbols": ["ZCE|Z|SA|MAIN"],
    "allowed_price_types": ["LIMIT"],
    "allowed_offsets": ["ENTRY", "EXIT", "EXIT_TODAY"],
    "max_lots_per_order": 1,
    "max_orders_per_day": 3,
    "max_open_orders": 1,
    "max_request_age_sec": 120,
    "min_available_for_entry": 100000.0,
    "require_margin_rate_below_pct": 60.0,
    "probe_interval_ms": 1000,
}

_RID_RE = re.compile(r"^req-\d{8}T\d{6}Z-[0-9a-f]{6}$")
_TOKEN_RE = re.compile(r"^[0-9a-f]{32,}$")


class ProtocolError(Exception):
    """协议校验失败。``reasons`` 保存全部失败原因，便于一次性修正。"""

    def __init__(self, reasons):
        if isinstance(reasons, str):
            reasons = [reasons]
        self.reasons: List[str] = list(reasons)
        super().__init__("; ".join(self.reasons))


# --------------------------------------------------------------------------
# 路径与基础读写
# --------------------------------------------------------------------------
def resolve_ipc_dir(ipc_dir: Optional[Any] = None) -> Path:
    return Path(ipc_dir) if ipc_dir is not None else DEFAULT_IPC_DIR


def _path(ipc_dir, name: str) -> Path:
    return resolve_ipc_dir(ipc_dir) / name


def read_json(path: Path) -> Optional[dict]:
    """读取 JSON；文件不存在返回 None，内容损坏抛出 ProtocolError。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = p.read_bytes()
    except OSError as exc:  # pragma: no cover - 文件系统异常
        raise ProtocolError("无法读取 %s: %s" % (p, exc)) from exc
    if not raw.strip():
        raise ProtocolError("%s 为空文件" % p)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("%s 不是合法 UTF-8 JSON: %s" % (p, exc)) from exc


def write_json_atomic(path: Path, obj: dict) -> Path:
    """原子写入：先写 ``.tmp`` 再 replace，避免策略读到半截文件。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    payload = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False)
    tmp.write_bytes(payload.encode("utf-8"))
    os.replace(str(tmp), str(p))
    return p


def sha256_file(path: Path) -> Optional[str]:
    p = Path(path)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_policy(ipc_dir: Optional[Any] = None) -> Dict[str, Any]:
    """加载 policy.json，缺项以 DEFAULT_POLICY 补齐，校验协议版本。"""
    path = _path(ipc_dir, POLICY_FILENAME)
    loaded = read_json(path)
    policy = dict(DEFAULT_POLICY)
    if loaded:
        policy.update({k: v for k, v in loaded.items() if not k.startswith("_")})
    if str(policy.get("protocol_version")) != PROTOCOL_VERSION:
        raise ProtocolError(
            "policy.json 协议版本 %r 与代码版本 %r 不一致"
            % (policy.get("protocol_version"), PROTOCOL_VERSION)
        )
    return policy


def kill_switch_active(ipc_dir: Optional[Any] = None) -> bool:
    return _path(ipc_dir, KILL_SWITCH_FILENAME).exists()


# --------------------------------------------------------------------------
# 时间与标识
# --------------------------------------------------------------------------
def now_epoch() -> float:
    return time.time()


def iso_now(epoch: Optional[float] = None) -> str:
    ts = now_epoch() if epoch is None else epoch
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def new_request_id(direction: str, epoch: Optional[float] = None) -> str:
    ts = now_epoch() if epoch is None else epoch
    stamp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "req-%s-%s" % (stamp, secrets.token_hex(3))


def new_token() -> str:
    return secrets.token_hex(16)


# --------------------------------------------------------------------------
# 意向构造与校验
# --------------------------------------------------------------------------
def build_request(
    policy: Dict[str, Any],
    symbol: str,
    direction: str,
    offset: str,
    lots: int,
    reason: str,
    price_type: str = "LIMIT",
    price_side: str = "PASSIVE",
    operator: str = "agent",
    epoch: Optional[float] = None,
) -> Dict[str, Any]:
    """构造订单意向对象（不做限额校验，校验交给 :func:`validate_request`）。"""
    ts = now_epoch() if epoch is None else epoch
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": new_request_id(direction, ts),
        "created_at": iso_now(ts),
        "created_at_epoch": ts,
        "operator": operator,
        "symbol": symbol,
        "direction": direction.upper(),
        "offset": offset.upper(),
        "lots": int(lots),
        "price_type": price_type.upper(),
        "price_side": price_side.upper(),
        "reason": reason,
    }


def validate_request(
    request: Optional[dict],
    policy: Dict[str, Any],
    epoch: Optional[float] = None,
    orders_today: int = 0,
    open_orders: int = 0,
) -> None:
    """校验订单意向。任何不合规都会以 :class:`ProtocolError` 抛出全部原因。"""
    if request is None:
        raise ProtocolError("order_request.json 不存在")

    now = now_epoch() if epoch is None else epoch
    errs: List[str] = []

    if str(request.get("protocol_version")) != PROTOCOL_VERSION:
        errs.append("协议版本不匹配: %r" % request.get("protocol_version"))

    rid = request.get("request_id")
    if not isinstance(rid, str) or not _RID_RE.match(rid):
        errs.append("request_id 缺失或格式非法: %r" % rid)

    if request.get("symbol") not in policy["allowed_symbols"]:
        errs.append("合约 %r 不在白名单 %s" % (request.get("symbol"), policy["allowed_symbols"]))

    if request.get("direction") not in ("BUY", "SELL"):
        errs.append("direction 必须为 BUY 或 SELL，得到 %r" % request.get("direction"))

    if request.get("offset") not in policy["allowed_offsets"]:
        errs.append("offset %r 不在允许集合 %s" % (request.get("offset"), policy["allowed_offsets"]))

    lots = request.get("lots")
    if not isinstance(lots, int) or isinstance(lots, bool) or lots < 1:
        errs.append("lots 必须为正整数，得到 %r" % (lots,))
    elif lots > int(policy["max_lots_per_order"]):
        errs.append("lots=%d 超过单笔上限 %d" % (lots, int(policy["max_lots_per_order"])))

    if request.get("price_type") not in policy["allowed_price_types"]:
        errs.append("price_type %r 不在允许集合 %s" % (request.get("price_type"), policy["allowed_price_types"]))

    if request.get("price_side") not in ("PASSIVE", "AGGRESSIVE"):
        errs.append("price_side 必须为 PASSIVE 或 AGGRESSIVE，得到 %r" % request.get("price_side"))

    reason = request.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errs.append("reason 不可为空（审计留痕要求）")

    created = request.get("created_at_epoch")
    if not isinstance(created, (int, float)):
        errs.append("created_at_epoch 缺失或非数值")
    else:
        age = now - float(created)
        if age < -5.0:
            errs.append("意向时间戳位于未来 %.1fs（时钟异常）" % (-age))
        elif age > float(policy["max_request_age_sec"]):
            errs.append(
                "意向已过期 %.1fs > %ss（防止陈旧指令被误执行）"
                % (age, policy["max_request_age_sec"])
            )

    if orders_today >= int(policy["max_orders_per_day"]):
        errs.append("当日委托数 %d 已达上限 %d" % (orders_today, int(policy["max_orders_per_day"])))

    if open_orders >= int(policy["max_open_orders"]):
        errs.append("在途委托数 %d 已达上限 %d" % (open_orders, int(policy["max_open_orders"])))

    if errs:
        raise ProtocolError(errs)


def validate_approval(
    approval: Optional[dict],
    request: dict,
    request_sha256: str,
    policy: Dict[str, Any],
    epoch: Optional[float] = None,
) -> None:
    """校验人工批准凭证是否与当前意向严格对应。"""
    if approval is None:
        raise ProtocolError("order_approval.json 不存在（尚未人工确认）")

    now = now_epoch() if epoch is None else epoch
    errs: List[str] = []

    if str(approval.get("protocol_version")) != PROTOCOL_VERSION:
        errs.append("批准凭证协议版本不匹配: %r" % approval.get("protocol_version"))

    if approval.get("request_id") != request.get("request_id"):
        errs.append(
            "批准凭证指向的意向 %r 与当前意向 %r 不一致"
            % (approval.get("request_id"), request.get("request_id"))
        )

    if approval.get("request_sha256") != request_sha256:
        errs.append("批准凭证哈希与意向文件字节不符（意向可能已被篡改）")

    token = approval.get("token")
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        errs.append("批准令牌缺失或强度不足（需 >=32 位十六进制）")

    if not str(approval.get("approved_by", "")).strip():
        errs.append("approved_by 缺失（必须记录确认人）")

    approved_at = approval.get("approved_at_epoch")
    if not isinstance(approved_at, (int, float)):
        errs.append("approved_at_epoch 缺失或非数值")
    else:
        age = now - float(approved_at)
        if age < -5.0:
            errs.append("批准时间位于未来 %.1fs（时钟异常）" % (-age))
        elif age > float(policy["max_request_age_sec"]):
            errs.append("批准已过期 %.1fs > %ss" % (age, policy["max_request_age_sec"]))

    if errs:
        raise ProtocolError(errs)


def make_approval(
    request: dict,
    request_sha256: str,
    approved_by: str,
    epoch: Optional[float] = None,
) -> Dict[str, Any]:
    ts = now_epoch() if epoch is None else epoch
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request["request_id"],
        "request_sha256": request_sha256,
        "approved_at": iso_now(ts),
        "approved_at_epoch": ts,
        "approved_by": approved_by,
        "token": new_token(),
    }


def describe_request(request: dict) -> str:
    """人类可读的意向摘要（用于在对话里请用户确认）。"""
    if not request:
        return "<无订单意向>"
    dir_cn = {"BUY": "买入", "SELL": "卖出"}.get(request.get("direction"), request.get("direction"))
    off_cn = {
        "ENTRY": "开仓",
        "EXIT": "平仓",
        "EXIT_TODAY": "平今",
    }.get(request.get("offset"), request.get("offset"))
    return (
        "{rid} | {sym} {dir}{off} {lots} 手 | {ptype}/{pside} | 理由: {reason}"
    ).format(
        rid=request.get("request_id"),
        sym=request.get("symbol"),
        dir=dir_cn,
        off=off_cn,
        lots=request.get("lots"),
        ptype=request.get("price_type"),
        pside=request.get("price_side"),
        reason=request.get("reason"),
    )
