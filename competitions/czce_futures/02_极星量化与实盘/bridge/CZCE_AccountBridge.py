# -*- coding: utf-8 -*-
"""
极星 9.5 账户只读桥接策略（Stage-1 / 验收门槛 G1-G2）
======================================================
文件名 : CZCE_AccountBridge.py
运行环境: 极星 9.5 内嵌 Python 3.7 量化沙箱
权限等级: **只读**。本文件不包含任何下单函数（无 A_SendOrder / SellShort /
          BuyToShort / A_DeleteOrder 调用），用于在进入交易阶段前先证明
          "策略能被客户端加载" 与 "账户数据能被正确读出"。

与旧版的差异（旧版已废弃，存在以下问题）：
1. 旧版把参数写成 g_params['X'] = ... 的顶层赋值，但从未真正读取账户 ID，
   且依赖行情推送（SetTriggerType(1)）驱动；收盘后无行情则永不落盘。
   新版增加 SetTriggerType(3, ms) 定时触发，**收盘后依然可以验证链路**。
2. 旧版任何 A_ 函数抛异常就直接放弃整个采集；新版逐函数容错并输出诊断矩阵，
   失败原因可被外部 agent 直接读文本获取（Agent 无需读图）。
3. 旧版无心跳，外部无法判断策略是否存活。新版每次采集写 heartbeat.json。

验收用法
--------
1. 在极星中加载本策略，**勾选"实盘运行"**（否则 A_ 函数不可用），
   并在策略实例设置中关联比赛模拟账户；
2. 观察 `ipc/heartbeat.json` 与 `ipc/account_snapshot.json` 是否出现；
3. `python -m src.trading.agent_gateway g1` / `g2` 输出验收结论。
"""

import json
import os
import time
from datetime import datetime

# ---------------------------------------------------------------- 参数
g_params['Symbol'] = 'ZCE|Z|SA|MAIN'   # 基准合约（纯碱主连），仅用于建立行情/交易数据关联
g_params['ProbeIntervalMs'] = 1000     # 定时触发间隔（毫秒，必须为 100 的整数倍）
g_params['DumpCooldownSec'] = 2.0      # 两次落盘的最小间隔，避免高频写盘

# ---------------------------------------------------------------- 路径
IPC_DIR = r"D:\第九届郑商所杯_2026\02_极星量化与实盘\ipc"
POLICY_PATH = os.path.join(IPC_DIR, "policy.json")
SNAPSHOT_PATH = os.path.join(IPC_DIR, "account_snapshot.json")
HEARTBEAT_PATH = os.path.join(IPC_DIR, "heartbeat.json")
DIAG_PATH = os.path.join(IPC_DIR, "bridge_diagnostics.json")
CLIENT_LOG_DIR = r"D:\第九届郑商所杯_2026\02_极星量化与实盘\logs"

_state = {
    "init_epoch": None,
    "last_dump": 0.0,
    "probe_count": 0,
    "error_count": 0,
    "last_error": "",
    "account_ids": [],
}


# ---------------------------------------------------------------- 工具
def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_json(path, obj):
    """原子写入，避免外部 agent 读到半截 JSON。"""
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


def _safe(fn, *args):
    """执行一个极星 API 调用，返回 (ok, value_or_error)。"""
    try:
        return True, fn(*args)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e))


def _log(msg):
    try:
        LogInfo(msg)
    except Exception:
        pass


# ---------------------------------------------------------------- 生命周期
def initialize(context):
    """策略加载时执行一次。"""
    _state["init_epoch"] = time.time()

    # 1. 订阅基准合约 K 线（供 BarCount / Close 等使用，同时建立合约关联关系）
    #    sampleConfig 传 'N' = 不执行历史K线回测，确保策略始终处于实时阶段，
    #    避免 A_ 系列账户函数在历史阶段返回 0 污染账户快照。
    ok_bar, bar_msg = _safe(SetBarInterval, g_params['Symbol'], 'M', 1, 'N')

    # 2. 触发方式：即时行情 + 交易数据 + K线 + **定时**（定时是关键，收盘后仍可验活）
    trig_results = []
    for trig in (1, 2, 5):
        ok, msg = _safe(SetTriggerType, trig)
        trig_results.append({"type": trig, "ok": ok, "msg": "" if ok else msg})
    ok_timer, timer_msg = _safe(SetTriggerType, 3, int(g_params['ProbeIntervalMs']))
    trig_results.append({"type": "3(timer)", "ok": ok_timer, "msg": "" if ok_timer else timer_msg})

    # 3. 关联实盘/模拟账户并订阅行情
    ok_actual, actual_msg = _safe(SetActual)
    ok_sub, sub_msg = _safe(SubQuote, g_params['Symbol'])
    ok_orderway, orderway_msg = _safe(SetOrderWay, 2)

    # 4. 确保输出目录存在
    for d in (IPC_DIR, CLIENT_LOG_DIR):
        try:
            if not os.path.exists(d):
                os.makedirs(d)
        except Exception as e:
            _log("【Bridge】创建目录失败 %s: %s\n" % (d, str(e)))

    # 5. 记录账户 ID（不做 SetUserNo 硬编码，账户在策略实例设置中关联）
    ok_ids, ids = _safe(A_AllAccountID)
    account_ids = []
    if ok_ids and isinstance(ids, (list, tuple)):
        account_ids = [str(x) for x in ids]
    _state["account_ids"] = account_ids
    ok_single, single_id = _safe(A_AccountID)

    diag = {
        "phase": "initialize",
        "stage": "Stage-1 只读桥接（无下单能力）",
        "loaded_at": _now_str(),
        "loaded_at_epoch": _state["init_epoch"],
        "symbol": g_params['Symbol'],
        "set_bar_interval": {"ok": ok_bar, "msg": "" if ok_bar else bar_msg},
        "triggers": trig_results,
        "set_actual": {"ok": ok_actual, "msg": "" if ok_actual else actual_msg},
        "sub_quote": {"ok": ok_sub, "msg": "" if ok_sub else sub_msg},
        "set_order_way": {"ok": ok_orderway, "msg": "" if ok_orderway else orderway_msg},
        "account_ids": account_ids,
        "account_id_single": {"ok": ok_single, "value": str(single_id) if ok_single else ""},
        "python_version": None,
    }
    try:
        import sys
        diag["python_version"] = sys.version
    except Exception:
        pass
    # policy.json 是否可读（只读桥接不依赖它，但用于确认路径与权限正确）
    try:
        with open(POLICY_PATH, 'r', encoding='utf-8') as f:
            policy = json.load(f)
        diag["policy_readable"] = True
        diag["policy_allow_trading"] = bool(policy.get("allow_trading", False))
        diag["policy_protocol_version"] = policy.get("protocol_version")
    except Exception as e:
        diag["policy_readable"] = False
        diag["policy_error"] = str(e)

    _write_json(DIAG_PATH, diag)

    _log("====================================================\n")
    _log("【Bridge】Stage-1 只读账户桥接已加载（无下单能力）\n")
    _log("【Bridge】定时触发: %s | 关联账户: %s\n" % (
        "OK" if ok_timer else ("FAIL(%s)" % timer_msg),
        ",".join(account_ids) if account_ids else "未关联(请在策略设置中选择比赛模拟账户)",
    ))
    _log("【Bridge】输出目录: %s\n" % IPC_DIR)
    _log("====================================================\n")


def handle_data(context):
    """触发回调。由行情/交易数据/K线/定时器共同驱动。"""
    now = time.time()
    if now - _state["last_dump"] < float(g_params['DumpCooldownSec']):
        return
    _state["last_dump"] = now
    _state["probe_count"] += 1

    # ---------------------------------------------- 1. 账户级数据探针
    probes = {}
    api_calls = [
        ("A_AccountID", lambda: A_AccountID()),
        ("A_AllAccountID", lambda: A_AllAccountID()),
        ("A_Assets", lambda: A_Assets()),
        ("A_Available", lambda: A_Available()),
        ("A_Margin", lambda: A_Margin()),
        ("A_Cost", lambda: A_Cost()),
        ("A_ProfitLoss", lambda: A_ProfitLoss()),
        ("A_CoverProfit", lambda: A_CoverProfit()),
        ("A_TotalPosition", lambda: A_TotalPosition()),
        ("A_BuyPosition", lambda: A_BuyPosition()),
        ("A_SellPosition", lambda: A_SellPosition()),
        ("A_TotalAvgPrice", lambda: A_TotalAvgPrice()),
        ("A_TotalProfitLoss", lambda: A_TotalProfitLoss()),
        ("A_CalcParam", lambda: A_CalcParam()),
        ("A_GetAllPositionSymbol", lambda: A_GetAllPositionSymbol()),
        ("Q_Last", lambda: Q_Last()),
        ("Q_BidPrice", lambda: Q_BidPrice()),
        ("Q_AskPrice", lambda: Q_AskPrice()),
        ("Close", lambda: Close()),
        ("BarCount", lambda: BarCount()),
        ("CurrentBar", lambda: CurrentBar()),
        ("PriceTick", lambda: PriceTick()),
        ("IsTradeAllowed", lambda: IsTradeAllowed()),
    ]
    for name, fn in api_calls:
        ok, val = _safe(fn)
        if ok:
            try:
                if isinstance(val, (list, tuple)):
                    val = [str(x) for x in val]
                elif isinstance(val, float):
                    val = round(val, 4)
                elif not isinstance(val, (int, str, bool, type(None), dict)):
                    val = str(val)
            except Exception:
                val = str(val)
            probes[name] = {"ok": True, "value": val}
        else:
            probes[name] = {"ok": False, "error": val}
            _state["error_count"] += 1
            _state["last_error"] = "%s -> %s" % (name, val)

    # ---------------------------------------------- 2. 归一化账户快照
    def _num(key):
        item = probes.get(key, {})
        if not item.get("ok"):
            return None
        try:
            return round(float(item["value"]), 2)
        except (TypeError, ValueError):
            return None

    assets = _num("A_Assets")
    available = _num("A_Available")
    margin = _num("A_Margin")
    margin_rate = None
    if assets not in (None, 0) and margin is not None:
        margin_rate = round(margin / assets * 100.0, 2)

    positions = []
    pos_probe = probes.get("A_GetAllPositionSymbol", {})
    if pos_probe.get("ok") and isinstance(pos_probe.get("value"), list):
        for sym in pos_probe["value"]:
            entry = {"symbol": sym}
            for label, fn in (
                ("buy_position", lambda s=sym: A_BuyPosition(s)),
                ("sell_position", lambda s=sym: A_SellPosition(s)),
                ("avg_price", lambda s=sym: A_TotalAvgPrice(s)),
                ("position_pnl", lambda s=sym: A_TotalProfitLoss(s)),
            ):
                ok, val = _safe(fn)
                entry[label] = val if ok else ("ERR: %s" % val)
            positions.append(entry)

    snapshot = {
        "update_time": _now_str(),
        "timestamp": now,
        "source": "CZCE_AccountBridge.py (Stage-1 只读)",
        "account_ids": _state["account_ids"],
        "account_id": probes.get("A_AccountID", {}).get("value"),
        "assets": assets,
        "available": available,
        "margin": margin,
        "margin_rate_pct": margin_rate,
        "floating_pnl": _num("A_ProfitLoss"),
        "cover_pnl": _num("A_CoverProfit"),
        "commission": _num("A_Cost"),
        "position_count": len(positions),
        "positions": positions,
        "market": {
            "last": _num("Q_Last"),
            "bid1": _num("Q_BidPrice"),
            "ask1": _num("Q_AskPrice"),
            "bar_count": _num("BarCount"),
            "current_bar": _num("CurrentBar"),
            "price_tick": _num("PriceTick"),
            "trade_allowed": probes.get("IsTradeAllowed", {}).get("value"),
        },
        "probe_ok": sum(1 for v in probes.values() if v.get("ok")),
        "probe_total": len(probes),
    }
    ok_snap, snap_err = _write_json(SNAPSHOT_PATH, snapshot)

    # ---------------------------------------------- 3. 心跳 + 诊断矩阵
    heartbeat = {
        "update_time": _now_str(),
        "timestamp": now,
        "alive": True,
        "stage": "Stage-1 只读桥接",
        "init_epoch": _state["init_epoch"],
        "uptime_sec": round(now - (_state["init_epoch"] or now), 1),
        "probe_count": _state["probe_count"],
        "error_count": _state["error_count"],
        "last_error": _state["last_error"],
        "snapshot_written": ok_snap,
        "snapshot_error": snap_err,
        "account_ids": _state["account_ids"],
        "probes": probes,
    }
    _write_json(HEARTBEAT_PATH, heartbeat)

    if _state["probe_count"] % 20 == 1:
        _log("【Bridge】探测#%d | 权益:%s 可用:%s 保证金:%s 保证金率:%s%% | API正常 %d/%d\n" % (
            _state["probe_count"], assets, available, margin, margin_rate,
            snapshot["probe_ok"], snapshot["probe_total"],
        ))
