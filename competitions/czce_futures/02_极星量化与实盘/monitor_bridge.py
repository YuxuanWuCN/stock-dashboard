# -*- coding: utf-8 -*-
"""
第九届“郑商所杯”极星量化与实盘监控看板 (monitor_bridge.py)
-------------------------------------------------------
功能：
1. 监听 02_极星量化与实盘/logs/ 下的 account_snapshot.json 与 strategy_signals.json；
2. 实时格式化展示郑商所比赛账户权益、可用资金、保证金占用率与持仓结构；
3. 同步展示 Temporal Trend Gate 因果门控状态与 Zero-Cost Collar 期权推荐行权价。
"""

import json
import os
import sys
import time

# Windows 终端 UTF-8 输出支持
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(CURRENT_DIR, "logs")
SNAPSHOT_FILE = os.path.join(LOG_DIR, "account_snapshot.json")
SIGNAL_FILE = os.path.join(LOG_DIR, "strategy_signals.json")


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def read_json_safe(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def format_status():
    snapshot = read_json_safe(SNAPSHOT_FILE)
    signal = read_json_safe(SIGNAL_FILE)

    print("=" * 68)
    print(" 🏆 第九届“郑商所杯” 极星 19.5 实盘/模拟量化账户与信号实时监控看板")
    print("=" * 68)

    if not snapshot and not signal:
        print("\n [等待数据接入...]")
        print(" 极星 19.5 客户端已就绪，但尚未检测到策略输出日志。")
        print("\n 接入指引：")
        print(" 1. 请在极星 19.5 主界面右键点击 【插入模块】 -> 【量化策略】；")
        print(" 2. 点击 【添加策略】 -> 展开 【用户策略】；")
        print(" 3. 即可看到已同步部署的量化插件与桥接：")
        print("    - CZCE_AccountBridge               (账户资产与风控桥接)")
        print("    - CZCE_19_5_DualProduct_Plugin     (纯碱/玻璃双轨盈余与动态套保插件)")
        print(" 4. 关联比赛账户，勾选【实盘运行】，点击 【开始策略】；")
        print(" 5. 策略启动后，本看板将在此处每秒实时刷新账户与信号状态。")
        print("\n" + "-" * 68)
        print(" 日志监听目录: %s" % LOG_DIR)
        return

    # 1. 账户资产风控区
    if snapshot:
        acc_id = snapshot.get("account_id", "--")
        assets = snapshot.get("assets", 0.0)
        avail = snapshot.get("available", 0.0)
        margin = snapshot.get("margin", 0.0)
        pnl = snapshot.get("floating_pnl", 0.0)
        m_rate = snapshot.get("margin_rate_pct", 0.0)
        risk = snapshot.get("risk_level", "SAFE")
        update_t = snapshot.get("update_time", "--")

        risk_icon = "🟢" if risk == "SAFE" else ("🟡" if risk == "WARNING" else "🔴")
        print(f"\n【1. 比赛账户实时状态】({update_t})")
        print(f"  账号: {acc_id:<16} 风控等级: {risk_icon} {risk}")
        print(f"  动态权益: {assets:>12,.2f} 元  |  可用资金: {avail:>12,.2f} 元")
        print(f"  占用保证金: {margin:>10,.2f} 元  |  浮动盈亏: {pnl:>12,.2f} 元")
        print(f"  保证金占用率: {m_rate:>7.2f}% (预警线: 70% | 熔断线: 85%)")

        positions = snapshot.get("positions", [])
        if positions:
            print("\n  持仓明细:")
            for p in positions:
                sym = p.get("symbol", "--")
                buy_pos = p.get("buy_position", 0)
                sell_pos = p.get("sell_position", 0)
                net_pos = p.get("net_position", 0)
                avg_p = p.get("avg_price", 0.0)
                print(f"    - 合约: {sym:<16} 多仓: {buy_pos} | 空仓: {sell_pos} | 净持仓: {net_pos} | 均价: {avg_p:.2f}")

    # 2. 策略门控信号区
    if signal:
        s_sym = signal.get("symbol", "--")
        s_price = signal.get("current_price", 0.0)
        regime = signal.get("trend_regime", 0)
        regime_desc = signal.get("regime_name", "--")
        h_ratio = signal.get("target_hedge_ratio", 0.0) * 100.0
        target_lots = signal.get("target_short_lots", 0)
        curr_lots = signal.get("current_short_lots", 0)
        diff_lots = signal.get("lots_adjustment_needed", 0)
        exec_status = signal.get("execution_status", "--")
        collar = signal.get("collar_options_recommendation", {})
        c_put = collar.get("recommended_put_strike", "--")
        c_call = collar.get("recommended_call_strike", "--")
        update_s = signal.get("update_time", "--")

        reg_icon = "🔴" if regime == 1 else "🟢"
        print(f"\n【2. 纯碱动态套保 Trend Gate 门控】({update_s})")
        print(f"  标的合约: {s_sym} | 现价: {s_price:.1f} 元/吨")
        print(f"  因果门控状态: {reg_icon} Regime {regime} -> {regime_desc}")
        print(f"  目标对冲比例: {h_ratio:.0f}%  (目标空头: {target_lots} 手 | 当前持有: {curr_lots} 手 | 调仓缺口: {diff_lots:+d} 手)")
        print(f"  执行状态: {exec_status}")
        print(f"  场内零成本 Collar 期权推荐: Put行权价={c_put} 元/吨 | Call行权价={c_call} 元/吨")

    print("\n" + "=" * 68)
    print(" [提示] 按 Ctrl+C 退出监控看板")


def main():
    while True:
        try:
            clear_screen()
            format_status()
            time.sleep(2)
        except KeyboardInterrupt:
            print("\n已退出监控。")
            break


if __name__ == "__main__":
    main()
