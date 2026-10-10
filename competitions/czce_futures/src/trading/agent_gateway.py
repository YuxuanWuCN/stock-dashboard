# -*- coding: utf-8 -*-
"""Agent 侧订单网关 CLI。

用法（项目根目录 D:\\第九届郑商所杯_2026 下执行）::

    python -m src.trading.agent_gateway g1                 # 验收门槛 G1：策略是否被加载
    python -m src.trading.agent_gateway g2                 # 验收门槛 G2：账户快照是否可信
    python -m src.trading.agent_gateway snapshot            # 打印最新账户快照
    python -m src.trading.agent_gateway propose --direction SELL --offset ENTRY \
        --reason "G3 通路验证"                              # 生成订单意向（未发单）
    python -m src.trading.agent_gateway approve --by 张三   # 人类确认后签发批准凭证
    python -m src.trading.agent_gateway status              # 查看发单结果与委托状态
    python -m src.trading.agent_gateway cancel --order-id 1-1
    python -m src.trading.agent_gateway kill                # 熔断（拒绝一切发单）
    python -m src.trading.agent_gateway unkill

设计原则：``propose`` 与 ``approve`` 是两个独立命令，**中间必须由人类决定**。
本 CLI 永远不会自动调用 ``approve``。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.trading import order_protocol as proto

EXIT_PASS = 0
EXIT_FAIL = 1


def _print_kv(title: str, rows) -> None:
    print(title)
    print("-" * max(20, len(title)))
    for k, v in rows:
        print("  %-24s %s" % (k, v))
    print()


def _load_snapshot(ipc: Path):
    return proto.read_json(ipc / proto.SNAPSHOT_FILENAME)


# --------------------------------------------------------------------------
# 验收门槛 G1：策略已被客户端加载
# --------------------------------------------------------------------------
def cmd_g1(args) -> int:
    ipc = proto.resolve_ipc_dir(args.ipc)
    diag = proto.read_json(ipc / "bridge_diagnostics.json")
    heartbeat = proto.read_json(ipc / proto.HEARTBEAT_FILENAME)
    failures = []

    if diag is None:
        print("[G1] FAIL: 未找到 bridge_diagnostics.json —— 策略从未被极星加载。")
        print("     请确认：① 极星已启动并登录；② 策略已加载；③ 勾选了“实盘运行”。")
        return EXIT_FAIL

    rows = [
        ("加载时间", diag.get("loaded_at")),
        ("运行环境", str(diag.get("python_version", "")).split(" (")[0]),
        ("SetBarInterval", "OK" if diag.get("set_bar_interval", {}).get("ok") else diag.get("set_bar_interval")),
        ("SetActual", "OK" if diag.get("set_actual", {}).get("ok") else diag.get("set_actual")),
        ("SubQuote", "OK" if diag.get("sub_quote", {}).get("ok") else diag.get("sub_quote")),
        ("policy.json 可读", diag.get("policy_readable")),
        ("关联账户", diag.get("account_ids") or "未关联"),
        ("时间触发(3)", next((t for t in diag.get("triggers", []) if t.get("type") == "3(timer)"), {})),
    ]
    _print_kv("[G1] 策略加载诊断", rows)

    if not diag.get("set_actual", {}).get("ok"):
        failures.append("SetActual 调用失败，A_ 系列账户函数将不可用")
    timer = next((t for t in diag.get("triggers", []) if t.get("type") == "3(timer)"), None)
    if not timer or not timer.get("ok"):
        failures.append("定时触发(SetTriggerType(3)) 未设置成功，收盘后无法验证")
    if not diag.get("account_ids"):
        failures.append("策略未关联交易账户（A_AllAccountID 为空）")

    if heartbeat is None:
        failures.append("heartbeat.json 不存在：initialize 已执行但 handle_data 从未被触发")
    else:
        age = time.time() - float(heartbeat.get("timestamp", 0))
        rows = [
            ("最近心跳", heartbeat.get("update_time")),
            ("心跳延迟", "%.1f 秒前" % age),
            ("探测次数", heartbeat.get("probe_count")),
            ("API 错误累计", heartbeat.get("error_count")),
            ("最近错误", heartbeat.get("last_error") or "无"),
        ]
        _print_kv("[G1] 心跳", rows)
        if age > 30:
            failures.append("心跳已停止 %.0f 秒" % age)
        if heartbeat.get("error_count", 0) > 0 and not heartbeat.get("last_error"):
            failures.append("存在 API 错误但未记录原因")

    if failures:
        print("[G1] FAIL:")
        for f in failures:
            print("  - %s" % f)
        return EXIT_FAIL

    print("[G1] PASS —— 策略已被客户端加载，定时触发与账户关联均正常。")
    return EXIT_PASS


# --------------------------------------------------------------------------
# 验收门槛 G2：账户快照可信
# --------------------------------------------------------------------------
def cmd_g2(args) -> int:
    ipc = proto.resolve_ipc_dir(args.ipc)
    snap = _load_snapshot(ipc)
    if snap is None:
        print("[G2] FAIL: account_snapshot.json 不存在。")
        return EXIT_FAIL

    failures = []
    age = time.time() - float(snap.get("timestamp", 0))
    ok_cnt = snap.get("probe_ok", 0)
    total = snap.get("probe_total", 0) or 1
    market = snap.get("market", {})

    rows = [
        ("快照时间", snap.get("update_time")),
        ("数据延迟", "%.1f 秒前" % age),
        ("账户 ID", snap.get("account_id")),
        ("动态权益", snap.get("assets")),
        ("可用资金", snap.get("available")),
        ("占用保证金", snap.get("margin")),
        ("保证金率(%)", snap.get("margin_rate_pct")),
        ("浮动盈亏", snap.get("floating_pnl")),
        ("持仓条数", snap.get("position_count")),
        ("API 探针成功", "%d / %d" % (ok_cnt, total)),
        ("最新价 / 买一 / 卖一", "%s / %s / %s" % (market.get("last"), market.get("bid1"), market.get("ask1"))),
    ]
    _print_kv("[G2] 账户快照", rows)

    if age > 30:
        failures.append("快照已过期 %.0f 秒，策略可能已停止" % age)
    if ok_cnt / total < 0.8:
        failures.append("API 探针成功率 %.0f%% 低于 80%%，账户数据不可信" % (ok_cnt / total * 100))
    for key in ("assets", "available", "margin"):
        if snap.get(key) is None:
            failures.append("%s 读取失败（None）" % key)
    if snap.get("assets") in (None, 0):
        failures.append("动态权益为 0：多为未勾选“实盘运行”或账户未登录")

    hb = proto.read_json(ipc / proto.HEARTBEAT_FILENAME) or {}
    probes = hb.get("probes", {})
    failed = [(k, v.get("error")) for k, v in probes.items() if not v.get("ok")]
    if failed:
        print("[G2] 失败探针明细:")
        for k, err in failed:
            print("  - %-24s %s" % (k, err))
        print()

    if failures:
        print("[G2] FAIL:")
        for f in failures:
            print("  - %s" % f)
        return EXIT_FAIL

    print("[G2] 自动检查 PASS。")
    print()
    print("⚠️  仍需人工完成的一步（不可省略）：打开极星客户端【资金】页面，")
    print("    逐项核对下列数字是否与上方完全一致：")
    print("      动态权益 = %s" % snap.get("assets"))
    print("      可用资金 = %s" % snap.get("available"))
    print("      占用保证金 = %s" % snap.get("margin"))
    print("    截图或口头确认一致后，才能进入 G3 发单测试。")
    return EXIT_PASS


def cmd_snapshot(args) -> int:
    ipc = proto.resolve_ipc_dir(args.ipc)
    snap = _load_snapshot(ipc)
    if snap is None:
        print("account_snapshot.json 不存在")
        return EXIT_FAIL
    print(json.dumps(snap, ensure_ascii=False, indent=2))
    return EXIT_PASS


# --------------------------------------------------------------------------
# 订单意向与人工批准
# --------------------------------------------------------------------------
def cmd_propose(args) -> int:
    ipc = proto.resolve_ipc_dir(args.ipc)
    policy = proto.load_policy(ipc)
    request = proto.build_request(
        policy,
        symbol=args.symbol,
        direction=args.direction,
        offset=args.offset,
        lots=args.lots,
        reason=args.reason,
        price_type=args.price_type,
        price_side=args.price_side,
        operator=args.operator,
    )
    proto.validate_request(request, policy, orders_today=0, open_orders=0)
    path = proto.write_json_atomic(ipc / proto.REQUEST_FILENAME, request)
    sha = proto.sha256_file(path)

    print("已生成订单意向（尚未发单，等待人工确认）")
    print("-" * 60)
    print("  %s" % proto.describe_request(request))
    print("  request_id     : %s" % request["request_id"])
    print("  意向文件       : %s" % path)
    print("  request_sha256 : %s" % sha)
    print("  有效期         : %s 秒" % policy["max_request_age_sec"])
    print("  allow_trading  : %s" % policy["allow_trading"])
    print("-" * 60)
    if not policy["allow_trading"]:
        print("提示：policy.json 中 allow_trading=false，网关不会执行该意向。")
    print("确认后执行: python -m src.trading.agent_gateway approve --by <你的名字>")
    return EXIT_PASS


def cmd_approve(args) -> int:
    ipc = proto.resolve_ipc_dir(args.ipc)
    policy = proto.load_policy(ipc)
    request = proto.read_json(ipc / proto.REQUEST_FILENAME)
    if request is None:
        print("错误：没有待确认的 order_request.json")
        return EXIT_FAIL
    if proto.kill_switch_active(ipc) and not args.force:
        print("错误：kill_switch.flag 存在，熔断状态下拒绝签发批准。")
        print("     如确需继续，先执行 unkill。")
        return EXIT_FAIL

    sha = proto.sha256_file(ipc / proto.REQUEST_FILENAME)
    proto.validate_request(request, policy, orders_today=0, open_orders=0)
    approval = proto.make_approval(request, sha, args.by)
    proto.validate_approval(approval, request, sha, policy)
    path = proto.write_json_atomic(ipc / proto.APPROVAL_FILENAME, approval)

    print("已签发人工批准凭证")
    print("-" * 60)
    print("  %s" % proto.describe_request(request))
    print("  批准人   : %s" % approval["approved_by"])
    print("  批准时间 : %s" % approval["approved_at"])
    print("  凭证文件 : %s" % path)
    print("  有效期   : %s 秒（超时需重新 propose）" % policy["max_request_age_sec"])
    print("-" * 60)
    print("极星网关将在下一个触发周期（≤1 秒）读取并执行，随后可执行 status 核对。")
    return EXIT_PASS


def cmd_status(args) -> int:
    ipc = proto.resolve_ipc_dir(args.ipc)
    recon = proto.read_json(ipc / proto.RECONCILIATION_FILENAME)
    hb = proto.read_json(ipc / "gateway_heartbeat.json")
    if hb is None:
        print("gateway_heartbeat.json 不存在 —— Stage-2 网关策略尚未加载。")
        return EXIT_FAIL
    rows = [
        ("最近心跳", hb.get("update_time")),
        ("allow_trading", hb.get("allow_trading")),
        ("kill_switch", hb.get("kill_switch_active")),
        ("StartTrade 已开启", hb.get("trade_started")),
        ("账户 ID", hb.get("account_id")),
        ("当日已发单", hb.get("orders_today")),
        ("在途委托", hb.get("tracked_order_count")),
        ("最后阶段", hb.get("last_stage")),
    ]
    _print_kv("[G3/G4] 网关状态", rows)

    if recon is None:
        return EXIT_FAIL

    action = recon.get("last_action", {})
    print("最后动作: %s" % action.get("stage"))
    print(json.dumps(action.get("detail"), ensure_ascii=False, indent=2))
    print()

    tracked = recon.get("tracked_orders", [])
    if tracked:
        print("在途委托:")
        for t in tracked:
            print("  %s | 状态 %s(%s) | 成交 %s 手 @ %s | 是否完结 %s" % (
                t.get("local_order_id"), t.get("status"), t.get("status_cn"),
                t.get("filled_lot"), t.get("filled_price"), t.get("is_close"),
            ))
    else:
        print("在途委托: 无（可能已完全成交/撤单并归档）")
    print()

    events = recon.get("recent_events", [])
    if events:
        print("最近审计事件:")
        for e in events[-6:]:
            print("  %s %s" % (e.get("ts"), e.get("event")))
    return EXIT_PASS


def cmd_cancel(args) -> int:
    ipc = proto.resolve_ipc_dir(args.ipc)
    payload = {"local_order_id": args.order_id, "created_at_epoch": time.time()}
    proto.write_json_atomic(ipc / proto.CANCEL_FILENAME, payload)
    print("已提交撤单请求: local_order_id=%s（网关将在 ≤1 秒内执行 A_DeleteOrder）" % args.order_id)
    return EXIT_PASS


def cmd_kill(args) -> int:
    ipc = proto.resolve_ipc_dir(args.ipc)
    ipc.mkdir(parents=True, exist_ok=True)
    path = ipc / proto.KILL_SWITCH_FILENAME
    path.write_text("killed at %s by %s\n" % (proto.iso_now(), args.by), encoding="utf-8")
    print("已熔断: %s" % path)
    print("网关将在 ≤1 秒内 StopTrade() 并拒绝一切发单。")
    return EXIT_PASS


def cmd_unkill(args) -> int:
    ipc = proto.resolve_ipc_dir(args.ipc)
    path = ipc / proto.KILL_SWITCH_FILENAME
    if path.exists():
        path.unlink()
        print("已解除熔断: %s" % path)
    else:
        print("熔断未生效，无需解除。")
    return EXIT_PASS


def cmd_policy(args) -> int:
    ipc = proto.resolve_ipc_dir(args.ipc)
    policy = proto.load_policy(ipc)
    new_value = getattr(args, "allow_trading", None)
    if new_value is not None:
        raw = proto.read_json(ipc / proto.POLICY_FILENAME) or {}
        raw["allow_trading"] = bool(new_value)
        proto.write_json_atomic(ipc / proto.POLICY_FILENAME, raw)
        print("已更新 allow_trading = %s（网关 ≤1 秒内生效）" % bool(new_value))
        return EXIT_PASS
    print(json.dumps(policy, ensure_ascii=False, indent=2))
    print("熔断状态: %s" % ("已熔断" if proto.kill_switch_active(ipc) else "正常"))
    return EXIT_PASS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent_gateway", description="Agent ↔ 极星 9.5 订单网关 CLI")
    p.add_argument("--ipc", default=None, help="IPC 目录，默认 %s" % proto.DEFAULT_IPC_DIR)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("g1", help="验收门槛 G1：策略是否已被极星加载").set_defaults(func=cmd_g1)
    sub.add_parser("g2", help="验收门槛 G2：账户快照是否可信").set_defaults(func=cmd_g2)
    sub.add_parser("snapshot", help="打印账户快照").set_defaults(func=cmd_snapshot)
    sub.add_parser("status", help="查看网关状态与委托核对结果").set_defaults(func=cmd_status)
    sub.add_parser("policy", help="查看策略限额 policy.json").set_defaults(func=cmd_policy)

    pp = sub.add_parser("propose", help="生成订单意向（不发单）")
    pp.add_argument("--symbol", default="ZCE|Z|SA|MAIN")
    pp.add_argument("--direction", required=True, choices=["BUY", "SELL"])
    pp.add_argument("--offset", required=True, choices=["ENTRY", "EXIT", "EXIT_TODAY"])
    pp.add_argument("--lots", type=int, default=1)
    pp.add_argument("--price-type", default="LIMIT")
    pp.add_argument("--price-side", default="PASSIVE", choices=["PASSIVE", "AGGRESSIVE"])
    pp.add_argument("--reason", required=True)
    pp.add_argument("--operator", default="agent")
    pp.set_defaults(func=cmd_propose)

    pa = sub.add_parser("approve", help="人工确认后签发批准凭证")
    pa.add_argument("--by", required=True, help="确认人姓名（审计留痕）")
    pa.add_argument("--force", action="store_true", help="熔断状态下强制签发（不推荐）")
    pa.set_defaults(func=cmd_approve)

    pc = sub.add_parser("cancel", help="撤单")
    pc.add_argument("--order-id", required=True)
    pc.set_defaults(func=cmd_cancel)

    pk = sub.add_parser("kill", help="熔断：拒绝一切发单")
    pk.add_argument("--by", default="human")
    pk.set_defaults(func=cmd_kill)

    sub.add_parser("unkill", help="解除熔断").set_defaults(func=cmd_unkill)

    pol = sub.add_parser("policy-set", help="修改 allow_trading 开关")
    pol.add_argument("allow_trading", type=lambda s: s.lower() in ("1", "true", "yes", "on"),
                     choices=[True, False])
    pol.set_defaults(func=cmd_policy)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except proto.ProtocolError as exc:
        print("协议校验失败：")
        for r in exc.reasons:
            print("  - %s" % r)
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
