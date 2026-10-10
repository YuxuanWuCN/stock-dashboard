# -*- coding: utf-8 -*-
"""多板块扫描：把同一套模型（Temporal NALE + Trend Gate）套到不同产业链配对上。

核心洞察：本系统的内核不是"纯碱/玻璃"，而是
    上游价格 + 下游价格 + 加工利润公式（crush spread）
只要这三样成立，任何"原料→成品"的产业链都能复用同一套模型。

用法: python -m src.trading.scan_sectors
"""

import sys
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.temporal_nale import TemporalNALE
from src.models.trend_gate import TrendGateMachine

# ---------------------------------------------------------------------------
# 产业链配对表：(板块名, 上游代码, 下游代码, 加工利润系数)
#   crush = 下游价格 - k * 上游价格 - 其他成本
#   系数 k 为该品种的单位耗用比（近似行业经验值，仅用于构造加工利润方向）
# ---------------------------------------------------------------------------
PAIRS = [
    ("纯碱→玻璃（现有课题）", "SA0", "FG0", 0.20, 350.0),
    ("PTA→短纤（聚酯链）", "TA0", "PF0", 0.86, 800.0),
    ("菜油→菜粕（油菜籽压榨）", "OI0", "RM0", -1.00, 0.0),   # 压榨：油与粕为联产品，取价差
    ("甲醇→PP（烯烃链）", "MA0", "PP0", 2.90, 500.0),
    ("动力煤→纯碱（能源成本）", "ZC0", "SA0", 0.55, 0.0),
    ("铁矿→螺纹（黑色链）", "I0", "RB0", 1.60, 900.0),
]

COL_MAP = {"日期": "date", "开盘价": "open", "最高价": "high", "最低价": "low",
           "收盘价": "close", "成交量": "volume", "持仓量": "open_interest",
           "动态结算价": "settle"}


def fetch(symbol: str):
    try:
        df = ak.futures_main_sina(symbol=symbol)
        if df is None or df.empty:
            return None
        df = df.rename(columns=COL_MAP)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    except Exception as exc:
        print("   [跳过] %s 拉取失败: %s" % (symbol, exc))
        return None


def analyse(name, up_sym, down_sym, k, fuel):
    up = fetch(up_sym)
    down = fetch(down_sym)
    if up is None or down is None:
        return None

    m = pd.merge(up[["date", "close"]].rename(columns={"close": "close_sa"}),
                 down[["date", "close"]].rename(columns={"close": "close_fg"}),
                 on="date", how="inner").reset_index(drop=True)
    if len(m) < 200:
        print("   [跳过] %s 对齐后仅 %d 行，样本不足" % (name, len(m)))
        return None
    m["crush_spread"] = m["close_fg"] - k * m["close_sa"] - fuel

    # --- 同一套模型 ---
    nale = TemporalNALE(window=60, sa_to_fg_lag=18.0, sa_half_life=25.0)
    crush = nale.compute_crush_spread(m)
    gate = TrendGateMachine(fast_span=20, slow_span=60, hysteresis_window=3,
                            nale_weight=0.35, tsmom_weight=0.20, active_defense=True)
    # tsmom 传 None：本扫描没有各板块的真实期限结构数据，为公平起见统一禁用
    res = gate.evaluate_regime(m["close_sa"], nale_signals=crush["nale_leading_signal"],
                               tsmom_signals=None)
    m = m.join(res)

    r = m.iloc[-1]
    last5 = m.tail(5)["trend_gate"].astype(int).tolist()
    return {
        "板块": name,
        "上游": up_sym,
        "下游": down_sym,
        "样本起": m["date"].iloc[0].date(),
        "样本止": m["date"].iloc[-1].date(),
        "交易日": len(m),
        "上游收盘": round(float(r["close_sa"]), 1),
        "下游收盘": round(float(r["close_fg"]), 1),
        "EMA20": round(float(r["ema_fast"]), 1),
        "EMA60": round(float(r["ema_slow"]), 1),
        "NALE": round(float(crush["nale_leading_signal"].iloc[-1]), 4),
        "Z": round(float(r["composite_score"]), 3),
        "状态": int(r["trend_gate"]),
        "建议对冲": "%.0f%%" % (float(r["dynamic_hedge_ratio"]) * 100),
        "近5日状态": "".join(str(x) for x in last5),
    }


def main() -> None:
    print("=" * 100)
    print("多板块扫描：同一套模型（Temporal NALE + Trend Gate）跨产业链复用")
    print("说明：本扫描统一不接入 TSMOM（各板块真实期限结构数据未纳入），")
    print("      门控权重退化为 0.65×价格项 + 0.35×NALE，仅用于横向比较能否产生信号。")
    print("=" * 100)

    rows = []
    for name, up, down, k, fuel in PAIRS:
        print("\n[扫描] %s  (%s → %s)" % (name, up, down))
        r = analyse(name, up, down, k, fuel)
        if r:
            rows.append(r)
            print("   %s → %s | 样本 %s~%s (%d 日)"
                  % (r["上游收盘"], r["下游收盘"], r["样本起"], r["样本止"], r["交易日"]))
            print("   EMA20 %.1f / EMA60 %.1f | NALE %+.4f | Z %.3f | 状态 %d | 对冲 %s | 近5日 %s"
                  % (r["EMA20"], r["EMA60"], r["NALE"], r["Z"], r["状态"],
                     r["建议对冲"], r["近5日状态"]))

    if not rows:
        print("\n未取得任何可用板块")
        return

    df = pd.DataFrame(rows)
    out = ROOT / "reports" / "tables" / "sector_scan.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 100)
    print("汇总（按 Z 降序，Z 越高越接近做空信号）")
    print("=" * 100)
    show = df.sort_values("Z", ascending=False)[
        ["板块", "上游", "下游", "NALE", "Z", "状态", "建议对冲", "近5日状态"]]
    print(show.to_string(index=False))

    sig = df[df["状态"] == 1]
    print("\n当前处于【破位主跌（状态1）】的板块: %s"
          % ("、".join(sig["板块"].tolist()) if len(sig) else "无"))
    print("说明：状态 1 = 满额对冲（可做空）；状态 0 = 震荡修复（观望）。")
    print("明细已写入: %s" % out)


if __name__ == "__main__":
    main()
