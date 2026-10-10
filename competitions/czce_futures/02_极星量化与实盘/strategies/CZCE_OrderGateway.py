# -*- coding: utf-8 -*-
"""
极星 9.5 订单执行网关（Stage-2 / 验收门槛 G3-G4）
==================================================
文件名 : CZCE_OrderGateway.py
运行环境: 极星 9.5 内嵌 Python 3.7 量化沙箱
权限等级: **可发单**（仅在 policy.json 中 allow_trading=true 时生效）

职责
----
把"外部 agent 生成的订单意向 + 人类确认凭证"翻译成极星官方 ``A_SendOrder``
调用，并把发单结果与委托状态回写到 ``reconciliation.json`` 供核对。

它**不做任何行情判断、不产生任何自主交易信号**。所有交易决策来自外部
agent 写入的 order_request.json，且必须附带人类签发的 order_approval.json。

安全设计（缺一不可）
--------------------
1. allow_trading 默认 false，且**运行时可翻转**：翻成 false 立即 StopTrade()；
2. ``kill_switch.flag`` 存在即 StopTrade() 并拒绝一切发单；
3. 意向与批准均受 max_request_age_sec 时效约束；
4. 批准凭证绑定 order_request.json 的**字节级 sha256**，改动即失效；
5. 限额（手数/当日笔数/在途笔数/合约白名单/保证金率）全部读自 policy.json；
6. 单价必须为正且相对最新价偏离不超过 10%（防脏 tick 报出离谱价）；
7. 发单成功后 request 与 approval 立即移入 ``consumed/``，单凭证不可重放；
8. 只允许限价单（policy.allowed_price_types），且默认挂被动价。
"""

import hashlib
import json
import os
import time
from datetime import datetime

# ---------------------------------------------------------------- 参数
g_params['Symbol'] = 'ZCE|Z|SA|MAIN'
g_params['GatewayIntervalMs'] = 1000

# ---------------------------------------------------------------- 路径
IPC_DIR = r"D:\第九届郑商所杯_2026\02_极星量化与实盘\ipc"
POLICY_PATH = os.path.join(IPC_DIR, "policy.json")
REQUEST_PATH = os.path.join(IPC_DIR, "order_request.json")
APPROVAL_PATH = os.path.join(IPC_DIR, "order_approval.json")
CANCEL_PATH = os.path.join(IPC_DIR, "cancel_request.json")
RECON_PATH = os.path.join(IPC_DIR, "reconciliation.json")
HEARTBEAT_PATH = os.path.join(IPC_DIR, "gateway_heartbeat.json")
KILL_SWITCH_PATH = os.path.join(IPC_DIR, "kill_switch.flag")
EXEC_LOG_PATH = os.path.join(IPC_DIR, "execution_log.jsonl")
CONSUMED_DIR = os.path.join(IPC_DIR, "consumed")

PROTOCOL_VERSION = "1.0"

#: 致命错误：意向本身不可能成功，直接归档，避免每秒重复校验
FATAL_MARKERS = (
    "协议版本", "request_id", "不在白名单", "direction", "offset",
    "lots", "price_type", "price_side", "reason", "已过期", "篡改",
    "令牌", "approved_by", "approval", "不存在",
)

ORDER_STATUS_CN = {
    'N': '无', '0': '已发送', '1': '已受理', '2': '待触发', '3': '已生效',
    '4': '已排队', '5': '部分成交', '6': '完全成交', '7': '待撤', '8': '待改',
    '9': '已撤单', 'A': '已撤余单', 'B': '指令失败', 'C': '待审核', 'D': '已挂起',
    'E': '已申请', 'F': '无效单', 'G': '部分触发', 'H': '完全触发', 'I': '余单失败',
}
CLOSED_STATUS = ('6', '9', 'A', 'B', 'F', 'I')

_state = {
    "init_epoch": None,
    "last_tick": 0.0,
    "tick_count": 0,
    "trade_started": False,
    "orders_today_date": "",
    "orders_today": 0,
    "tracked_orders": [],   # [{"local_order_id":..,"symbol":..,"request_id":..,"sent_at":..}]
    "attempts": {},         # request_id -> 连续发单失败次数（防止同一意向无限重试）
    "last_events": [],
}

#: 同一意向连续失败多少次后放弃并归档
MAX_SEND_ATTEMPTS = 10


# ---------------------------------------------------------------- 工具
def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _read_json(path):
    try:
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path, obj):
    try:
        tmp = path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)
        return True, ""
    except Exception as e:
        return False, str(e)


def _sha256_file(path):
    try:
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def _audit(event, **fields):
    record = {"ts": _now_str(), "epoch": time.time(), "event": event}
    record.update(fields)
    try:
        with open(EXEC_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
    _state["last_events"].append(record)
    _state["last_events"] = _state["last_events"][-30:]
    return record


def _safe(fn, *args):
    try:
        return True, fn(*args)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e))


def _log(msg):
    try:
        LogInfo(msg)
    except Exception:
        pass


def _archive_consumed(tag, request, approval, extra=None):
    """把已处理的意向移入 consumed/，防止重放。"""
    try:
        if not os.path.exists(CONSUMED_DIR):
            os.makedirs(CONSUMED_DIR)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rid = (request or {}).get("request_id", "noid")
        for src, label in ((REQUEST_PATH, "request"), (APPROVAL_PATH, "approval")):
            if os.path.exists(src):
                dst = os.path.join(CONSUMED_DIR, "%s_%s_%s_%s.json" % (stamp, tag, rid, label))
                os.rename(src, dst)
        if extra is not None:
            path = os.path.join(CONSUMED_DIR, "%s_%s_%s_result.json" % (stamp, tag, rid))
            _write_json(path, extra)
    except Exception as e:
        _log("【Gateway】归档 consumeds 失败: %s\n" % str(e))


# ---------------------------------------------------------------- 校验
def _validate_request(request, policy, now):
    """返回错误列表。空列表表示通过。"""
    errs = []
    if str(request.get("protocol_version")) != PROTOCOL_VERSION:
        errs.append("协议版本不匹配")
    rid = request.get("request_id", "")
    if not isinstance(rid, str) or not rid.startswith("req-") or len(rid) < 12:
        errs.append("request_id 格式非法")
    if request.get("symbol") not in policy.get("allowed_symbols", []):
        errs.append("合约不在白名单")
    if request.get("direction") not in ("BUY", "SELL"):
        errs.append("direction 非法")
    if request.get("offset") not in policy.get("allowed_offsets", []):
        errs.append("offset 非法")
    lots = request.get("lots")
    if not isinstance(lots, int) or isinstance(lots, bool) or lots < 1:
        errs.append("lots 必须为正整数")
    elif lots > int(policy.get("max_lots_per_order", 1)):
        errs.append("lots 超过单笔上限")
    if request.get("price_type") not in policy.get("allowed_price_types", []):
        errs.append("price_type 非法")
    if request.get("price_side") not in ("PASSIVE", "AGGRESSIVE"):
        errs.append("price_side 非法")
    reason = request.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errs.append("reason 为空，缺少审计留痕")
    created = request.get("created_at_epoch")
    if not isinstance(created, (int, float)):
        errs.append("created_at_epoch 非数值")
    else:
        age = now - float(created)
        if age > float(policy.get("max_request_age_sec", 120)):
            errs.append("意向已过期")
    if _state["orders_today"] >= int(policy.get("max_orders_per_day", 1)):
        errs.append("当日委托笔数已达上限")
    if len(_state["tracked_orders"]) >= int(policy.get("max_open_orders", 1)):
        errs.append("在途委托数已达上限")
    return errs


def _validate_approval(approval, request, request_sha, policy, now):
    errs = []
    if approval is None:
        errs.append("order_approval.json 不存在")
        return errs
    if str(approval.get("protocol_version")) != PROTOCOL_VERSION:
        errs.append("批准凭证协议版本不匹配")
    if approval.get("request_id") != request.get("request_id"):
        errs.append("批准凭证与当前意向 ID 不一致")
    if not request_sha or approval.get("request_sha256") != request_sha:
        errs.append("批准凭证哈希不符（意向可能被篡改）")
    token = approval.get("token", "")
    if not isinstance(token, str) or len(token) < 32:
        errs.append("批准令牌强度不足")
    if not str(approval.get("approved_by", "")).strip():
        errs.append("approved_by 缺失")
    approved_at = approval.get("approved_at_epoch")
    if not isinstance(approved_at, (int, float)):
        errs.append("approved_at_epoch 非数值")
    elif now - float(approved_at) > float(policy.get("max_request_age_sec", 120)):
        errs.append("批准已过期")
    return errs


def _is_fatal(errs):
    for e in errs:
        for marker in FATAL_MARKERS:
            if marker in e:
                return True
    return False


# ---------------------------------------------------------------- 执行
def _resolve_price(request):
    """按 price_side 取价，并做脏数据防护。返回 (price, error)。"""
    side = request.get("price_side")
    direction = request.get("direction")
    if side == "PASSIVE":
        fn = Q_BidPrice if direction == "BUY" else Q_AskPrice
    else:
        fn = Q_AskPrice if direction == "BUY" else Q_BidPrice

    ok, price = _safe(fn)
    if not ok:
        return None, "取价失败: %s" % price
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None, "取价非数值: %r" % (price,)
    if price <= 0:
        return None, "取价为 %s（可能无行情/已收盘）" % price

    ok_last, last = _safe(Q_Last)
    try:
        last = float(last)
    except (TypeError, ValueError):
        last = 0.0
    if last > 0 and abs(price - last) / last > 0.10:
        return None, "价格偏离最新价超过 10%%（price=%.2f, last=%.2f）" % (price, last)
    return price, ""


def _try_send(request, policy):
    """执行发单。返回 (ok, detail_dict)。"""
    errs = _validate_request(request, policy, time.time())
    if errs and _is_fatal(errs):
        return False, {"stage": "request_rejected_fatal", "errors": errs}
    if errs:
        return False, {"stage": "request_waiting", "errors": errs}
    request_sha = _sha256_file(REQUEST_PATH)
    approval = _read_json(APPROVAL_PATH)
    appr_errs = _validate_approval(approval, request, request_sha, policy, time.time())
    if appr_errs and any("已过期" in e or "篡改" in e or "不一致" in e or "强度" in e for e in appr_errs):
        return False, {"stage": "approval_rejected_fatal", "errors": appr_errs}
    if appr_errs:
        return False, {"stage": "awaiting_human_approval", "errors": appr_errs}

    price, price_err = _resolve_price(request)
    if price_err:
        return False, {"stage": "price_unavailable", "errors": [price_err]}

    # 资金与保证金风控（仅开仓）
    ok_av, avail = _safe(A_Available)
    ok_as, assets = _safe(A_Assets)
    ok_mg, margin = _safe(A_Margin)
    try:
        avail = float(avail) if ok_av else 0.0
        assets = float(assets) if ok_as else 0.0
        margin = float(margin) if ok_mg else 0.0
    except (TypeError, ValueError):
        avail, assets, margin = 0.0, 0.0, 0.0
    margin_rate = (margin / assets * 100.0) if assets > 0 else 0.0

    if request.get("offset") == "ENTRY":
        if avail < float(policy.get("min_available_for_entry", 0.0)):
            return False, {"stage": "risk_block_available",
                           "errors": ["可用资金 %.2f 低于下限 %.2f" % (avail, float(policy.get("min_available_for_entry", 0.0)))]}
        if margin_rate > float(policy.get("require_margin_rate_below_pct", 100.0)):
            return False, {"stage": "risk_block_margin",
                           "errors": ["保证金率 %.2f%% 高于阈值 %.2f%%" % (margin_rate, float(policy.get("require_margin_rate_below_pct", 100.0)))]}

    # 账户绑定
    ok_id, account_id = _safe(A_AccountID)
    user_no = str(account_id) if ok_id and account_id else ""
    if not user_no:
        return False, {"stage": "no_account", "errors": ["策略未关联交易账户（A_AccountID 为空）"]}

    direction = request["direction"]
    offset = request["offset"]
    dir_enum = Enum_Buy() if direction == "BUY" else Enum_Sell()
    if offset == "ENTRY":
        off_enum = Enum_Entry()
    elif offset == "EXIT_TODAY":
        off_enum = Enum_ExitToday()
    else:
        off_enum = Enum_Exit()

    remark = "agent:%s" % request.get("request_id", "")

    ok_send, sent = _safe(
        A_SendOrder,
        user_no, request["symbol"], dir_enum, off_enum, int(request["lots"]), float(price),
        Enum_Order_Limit(), Enum_GFD(), Enum_Speculate(),
        'N', 'N', 'N', 0.0, remark,
    )
    if not ok_send:
        return False, {"stage": "send_exception", "errors": [str(sent)], "price": price}

    try:
        ret_code, ret_msg = sent
    except Exception:
        return False, {"stage": "send_bad_return", "errors": ["A_SendOrder 返回不可解析: %r" % (sent,)], "price": price}

    detail = {
        "stage": "sent" if int(ret_code) == 0 else "send_failed",
        "ret_code": int(ret_code),
        "ret_msg": str(ret_msg),
        "price": price,
        "user_no": user_no,
        "available_before": round(avail, 2),
        "margin_rate_before": round(margin_rate, 2),
    }
    if int(ret_code) == 0:
        _state["tracked_orders"].append({
            "local_order_id": str(ret_msg),
            "symbol": request["symbol"],
            "request_id": request.get("request_id"),
            "direction": direction,
            "offset": offset,
            "lots": int(request["lots"]),
            "price": price,
            "sent_at": _now_str(),
        })
        _state["orders_today"] += 1
    else:
        # 常见失败码释义（来自官方文档）
        hints = {
            -1: "未勾选'实盘运行'，请在策略设置中启用",
            -2: "当前处于历史回测阶段，不可发单（本策略已用 sampleConfig='N' 规避）",
            -3: "未指定下单账户或账户未在极星客户端登录",
            -5: "未调用 StartTrade 开启实盘下单",
        }
        detail["hint"] = hints.get(int(ret_code), "见官方文档 retCode 说明")
    return int(ret_code) == 0, detail


def _poll_tracked_orders(user_no):
    """回查在途委托状态，产出 G4 核对数据。"""
    ok_id, account_id = _safe(A_AccountID)
    user_no = user_no or (str(account_id) if ok_id and account_id else "")
    results = []
    for item in list(_state["tracked_orders"]):
        oid = item["local_order_id"]
        row = dict(item)
        for label, fn in (
            ("status", lambda o=oid: A_OrderStatus(o)),
            ("filled_lot", lambda o=oid: A_OrderFilledLot(o)),
            ("filled_price", lambda o=oid: A_OrderFilledPrice(o)),
            ("is_close", lambda o=oid: A_OrderIsClose(o)),
        ):
            ok, val = _safe(fn)
            row[label] = val if ok else ("ERR: %s" % val)
        status = str(row.get("status", ""))
        row["status_cn"] = ORDER_STATUS_CN.get(status, "未知(%s)" % status)
        results.append(row)
        if status in CLOSED_STATUS:
            _state["tracked_orders"].remove(item)
            _audit("order_closed", local_order_id=oid, status=status, status_cn=row["status_cn"],
                   filled_lot=row.get("filled_lot"), filled_price=row.get("filled_price"))
    return results


def _handle_cancel(user_no):
    """处理撤单指令（G4 收尾用）。"""
    req = _read_json(CANCEL_PATH)
    if not req:
        return None
    oid = str(req.get("local_order_id", ""))
    if not oid:
        _archive_consumed("cancel_bad", None, None, {"error": "cancel_request.json 缺少 local_order_id"})
        return None
    ok, res = _safe(A_DeleteOrder, user_no, oid)
    record = {
        "update_time": _now_str(),
        "local_order_id": oid,
        "delete_ok": ok,
        "delete_result": res if ok else str(res),
    }
    _audit("cancel_requested", local_order_id=oid, ok=ok, result=str(res))
    try:
        os.remove(CANCEL_PATH)
    except Exception:
        pass
    return record


# ---------------------------------------------------------------- 生命周期
def initialize(context):
    _state["init_epoch"] = time.time()
    # sampleConfig='N' = 不执行历史K线回测，确保始终处于实时阶段。
    # 否则历史阶段调用 A_SendOrder 会返回 retCode=-2（历史回测阶段不可发单），
    # 造成"合法意向被误判为发单失败而归档"的严重后果。
    SetBarInterval(g_params['Symbol'], 'M', 1, 'N')
    for trig in (1, 2, 5):
        _safe(SetTriggerType, trig)
    _safe(SetTriggerType, 3, int(g_params['GatewayIntervalMs']))
    _safe(SetActual)
    _safe(SubQuote, g_params['Symbol'])
    _safe(SetOrderWay, 2)
    try:
        if not os.path.exists(IPC_DIR):
            os.makedirs(IPC_DIR)
    except Exception:
        pass
    _state["orders_today_date"] = _today()
    policy = _read_json(POLICY_PATH) or {}
    _audit("gateway_initialized", allow_trading=bool(policy.get("allow_trading", False)),
           symbol=g_params['Symbol'])
    _log("====================================================\n")
    _log("【Gateway】Stage-2 订单网关已加载 | allow_trading=%s\n" % bool(policy.get("allow_trading", False)))
    _log("【Gateway】仅在收到人类批准凭证后才会调用 A_SendOrder\n")
    _log("====================================================\n")


def handle_data(context):
    now = time.time()
    if now - _state["last_tick"] < 0.5:
        return
    _state["last_tick"] = now
    _state["tick_count"] += 1
    if _state["orders_today_date"] != _today():
        _state["orders_today_date"] = _today()
        _state["orders_today"] = 0

    policy = _read_json(POLICY_PATH) or {}
    allow = bool(policy.get("allow_trading", False))
    killed = os.path.exists(KILL_SWITCH_PATH)

    # ---- 1. 熔断与开关：运行时可翻转
    if (not allow or killed) and _state["trade_started"]:
        _safe(StopTrade)
        _state["trade_started"] = False
        _audit("trade_stopped", allow_trading=allow, kill_switch=killed)
    if allow and not killed and not _state["trade_started"]:
        ok, msg = _safe(StartTrade)
        _state["trade_started"] = bool(ok)
        _audit("trade_started", ok=ok, msg="" if ok else str(msg))

    ok_id, account_id = _safe(A_AccountID)
    user_no = str(account_id) if ok_id and account_id else ""

    action = {"stage": "idle", "detail": None}

    # ---- 2. 撤单
    if allow and not killed:
        cancel_record = _handle_cancel(user_no)
        if cancel_record:
            action = {"stage": "cancel_processed", "detail": cancel_record}

    # ---- 3. 发单
    if allow and not killed:
        request = _read_json(REQUEST_PATH)
        if request:
            ok_send, detail = _try_send(request, policy)
            rid = str(request.get("request_id", ""))
            stage = detail.get("stage")
            if ok_send:
                _state["attempts"].pop(rid, None)
            elif stage in ("request_rejected_fatal",):
                _state["attempts"].pop(rid, None)
            elif stage not in ("awaiting_human_approval", "request_waiting"):
                # 真正的"已尝试但未成功"：计数，达到上限后放弃，避免无限重试
                _state["attempts"][rid] = _state["attempts"].get(rid, 0) + 1
                if _state["attempts"][rid] >= MAX_SEND_ATTEMPTS:
                    stage = "send_failed_giveup"
                    detail["stage"] = stage
                    detail["giveup_after_attempts"] = _state["attempts"][rid]
                    _state["attempts"].pop(rid, None)
            _audit("order_attempt", request_id=rid, ok=ok_send, stage=stage, detail=detail)
            action = {"stage": stage, "detail": detail}
            if stage in ("sent", "request_rejected_fatal", "send_failed_giveup"):
                _archive_consumed(stage, request, _read_json(APPROVAL_PATH), detail)
    elif killed and _read_json(REQUEST_PATH):
        action = {"stage": "kill_switch_blocked", "detail": {"errors": ["kill_switch.flag 存在"]}}

    # ---- 4. 委托状态回查（G4）
    tracked = _poll_tracked_orders(user_no)

    # ---- 5. 落盘核对文件与心跳
    recon = {
        "update_time": _now_str(),
        "timestamp": now,
        "allow_trading": allow,
        "kill_switch_active": killed,
        "trade_started": _state["trade_started"],
        "account_id": user_no,
        "orders_today": _state["orders_today"],
        "last_action": action,
        "tracked_orders": tracked,
        "recent_events": _state["last_events"][-10:],
    }
    _write_json(RECON_PATH, recon)

    heartbeat = {
        "update_time": _now_str(),
        "timestamp": now,
        "alive": True,
        "stage": "Stage-2 订单网关",
        "tick_count": _state["tick_count"],
        "allow_trading": allow,
        "kill_switch_active": killed,
        "trade_started": _state["trade_started"],
        "orders_today": _state["orders_today"],
        "tracked_order_count": len(_state["tracked_orders"]),
        "account_id": user_no,
        "policy_protocol_version": policy.get("protocol_version"),
        "last_stage": action.get("stage"),
    }
    _write_json(HEARTBEAT_PATH, heartbeat)

    if _state["tick_count"] % 30 == 1:
        _log("【Gateway】#%d allow=%s kill=%s 已发单:%d 在途:%d 阶段:%s\n" % (
            _state["tick_count"], allow, killed, _state["orders_today"],
            len(_state["tracked_orders"]), action.get("stage"),
        ))
