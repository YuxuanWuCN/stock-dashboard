# -*- coding: utf-8 -*-
"""今日策略：把实时价格接入本课题模型，输出当日可执行策略与临界条件。

用法:
    python -m src.trading.today_strategy --sa 1017 --fg 1100
不传价格时自动尝试用 akshare 拉取分钟级最新价。
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.temporal_nale import TemporalNALE
from src.models.trend_gate import TrendGateMachine

FEATURES = ROOT / "data" / "processed" / "czce_sa_fg_aligned_features.csv"
MULT = 20.0
MARGIN = 0.12


def live_price(symbol: str):
    try:
        import akshare as ak
        d = ak.futures_zh_minute_sina(symbol=symbol, period="1")
        if d is not None and not d.empty:
            return float(d["close"].iloc[-1]), str(d["datetime"].iloc[-1])
    except Exception as exc:
        print("  [警告] %s 实时价拉取失败: %s" % (symbol, exc))
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sa", type=float, default=None, help="纯碱主力实时价")
    ap.add_argument("--fg", type=float, default=None, help="玻璃主力实时价")
    ap.add_argument("--equity", type=float, default=1_000_000.0)
    ap.add_argument("--risk-pct", type=float, default=0.02)
    ap.add_argument("--stop", type=float, default=25.0, help="止损距离 元/吨")
    args = ap.parse_args()

    sa_live, sa_ts = (args.sa, "命令行") if args.sa else live_price("SA0")
    fg_live, fg_ts = (args.fg, "命令行") if args.fg else live_price("FG0")

    df = pd.read_csv(FEATURES)
    df["date"] = pd.to_datetime(df["date"])
    hist_last = df["date"].iloc[-1].date()

    print("=" * 74)
    print("【今日策略】%s" % date.today())
    print("  历史日线截止 : %s" % hist_last)
    print("  纯碱实时价   : %s  (%s)" % (sa_live, sa_ts))
    print("  玻璃实时价   : %s  (%s)" % (fg_live, fg_ts))
    print("=" * 74)

    if sa_live is None:
        print("无实时价，终止")
        return

    # ---------- 构造"今日"行：价格用实时，其余特征沿用最新可得值 ----------
    today = df.iloc[-1].copy()
    today["date"] = pd.Timestamp(date.today())
    today["close_sa"] = sa_live
    if fg_live:
        today["close_fg"] = fg_live
    df2 = pd.concat([df, pd.DataFrame([today])], ignore_index=True)

    r = df2.iloc[-1]
    # 重新计算 EMA（因果递推，只用收盘价）
    close = df2["close_sa"].astype(float)
    ema_fast = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema_slow = close.ewm(span=60, adjust=False).mean().iloc[-1]

    tsmom = float(df2["tsmom_sa"].iloc[-1])
    nale_engine = TemporalNALE(window=60, sa_to_fg_lag=18.0, sa_half_life=25.0)
    crush = nale_engine.compute_crush_spread(df2)
    nale_v = float(crush["nale_leading_signal"].iloc[-1])

    # ---------- 门控打分（复刻 trend_gate 内部公式） ----------
    w_price = max(0.0, 1.0 - 0.20 - 0.35)
    w_nale, w_ts = 0.35, 0.20
    trend_score = 1.0 if (sa_live < ema_fast and ema_fast < ema_slow) else 0.0
    raw = w_price * trend_score + w_nale * max(nale_v, 0.0) + w_ts * max(tsmom, 0.0)
    defense = 1.0 + 0.5 * tsmom if tsmom < -0.2 else 1.0
    score = raw * defense

    print("一、今日状态")
    print("  实时价 %.1f | EMA20 %.1f | EMA60 %.1f" % (sa_live, ema_fast, ema_slow))
    print("  均线排列          : %s" % ("空头排列（价<EMA20<EMA60）" if trend_score else "非空头排列"))
    print("  NALE 产业链信号   : %+.4f" % nale_v)
    print("  TSMOM 期限结构    : %+.4f" % tsmom)
    print("  原始分 / 防御系数 : %.3f / %.3f" % (raw, defense))
    print("  综合破位得分 Z    : %.3f   阈值 0.50  →  %s"
          % (score, "破位主跌（做空）" if score >= 0.5 else "震荡/修复（观望）"))

    # ---------- 二、临界条件分析（关键） ----------
    # 严格复刻 trend_gate.evaluate_regime 的打分与防御逻辑：
    #   tsmom/nale 先 clip 到 [-1,1]；只在取正值时计入得分；
    #   仅当 tsmom < -0.2 时施加 (1 + 0.5*tsmom) 的抑制系数。
    W_PRICE, W_NALE, W_TS = 0.45, 0.35, 0.20

    def z_of(price, ema_f, ema_s, nale, tsmom):
        trend = 1.0 if (price < ema_f and ema_f < ema_s) else 0.0
        ts = max(-1.0, min(1.0, tsmom))
        na = max(-1.0, min(1.0, nale))
        raw = W_PRICE * trend + W_NALE * max(na, 0.0) + W_TS * max(ts, 0.0)
        defense = 1.0 + 0.5 * ts if ts < -0.2 else 1.0
        return raw * defense

    grid = np.linspace(-1.0, 1.0, 2001)
    # 保持 NALE、TSMOM 为当前值，让价格处于最理想空头排列时的 Z（即 price 项满分）
    max_hold = z_of(sa_live, ema_fast, ema_slow, nale_v, tsmom)
    max_any = max(z_of(sa_live, ema_fast, ema_slow, n, t) for n in grid for t in grid)

    print("-" * 74)
    print("二、临界条件分析：模型要满足什么才会翻成做空信号")
    print("  固定 NALE=%+.4f、TSMOM=%+.4f，价格处于最完美空头排列时 Z = %.3f"
          % (nale_v, tsmom, max_hold))
    if max_hold < 0.5:
        print("  ⚠ 也就是说：**NALE 与 TSMOM 不变时，价格跌到任何位置都不会触发做空**。")

    # 现状下：nale 提到多少才行？
    need_nale = None
    for n in np.linspace(0, 1, 20001):
        if z_of(sa_live, ema_fast, ema_slow, n, tsmom) >= 0.5:
            need_nale = n
            break
    # TSMOM 提到多少才行（NALE 保持现状）？
    need_ts = None
    for t in np.linspace(-1, 1, 20001):
        if z_of(sa_live, ema_fast, ema_slow, nale_v, t) >= 0.5:
            need_ts = t
            break

    print("  参考阈值（假设价格维持空头排列）:")
    print("    ① NALE 需升至 ≥ %s（当前 %+.4f）" %
          ("%+.4f" % need_nale if need_nale is not None else "无解（即使 NALE=+1）", nale_v))
    print("    ② 或 TSMOM 需升至 ≥ %s（当前 %+.4f）" %
          ("%+.4f" % need_ts if need_ts is not None else "无解", tsmom))
    print("  全局上限 Z = %.3f（NALE、TSMOM 均取 +1 时）" % max_any)
    if need_ts is not None:
        print("  → 现实中最可能先发生的是 TSMOM 转正：只要它越过 %+.2f，Z 即可破 0.50。" % need_ts)

    print("-" * 74)
    print("三、今日可执行策略")
    if score >= 0.5:
        action = "卖开（做空）纯碱主力"
    else:
        action = "空仓观望 —— 模型明确不给开仓信号（含不建议追空）"
    print("  动作            : %s" % action)

    risk_budget = args.equity * args.risk_pct
    risk_per_lot = args.stop * MULT
    lots = int(risk_budget // risk_per_lot)
    margin_per_lot = sa_live * MULT * MARGIN
    print("  若执行，建议仓位  : %d 手（%.0f 元权益 × %.0f%% 风险 ÷ (%.0f 元/吨 × %d 吨/手)）"
          % (lots, args.equity, args.risk_pct * 100, args.stop, int(MULT)))
    print("                     单手保证金约 %.0f 元，%d 手共约 %.0f 元（占权益 %.1f%%）"
          % (margin_per_lot, lots, margin_per_lot * lots,
             margin_per_lot * lots / args.equity * 100))
    print("  参考止损          : %.1f（+%.0f 元/吨）" % (sa_live + args.stop, args.stop))

    print("-" * 74)
    print("四、今天需要盯的翻空触发条件")
    print("  ① TSMOM 由 %.4f 升到 %s 以上" %
          (tsmom, ("%+.2f" % need_ts) if need_ts is not None else "无解"))
    print("  ② 或 NALE 由 %+.4f 升到 %s 以上" %
          (nale_v, ("%+.4f" % need_nale) if need_nale is not None else "无解"))
    print("  满足任一 + 价格维持空头排列 → Z 才可能越过 0.50；")
    print("  且门控带 3 日迟滞滤波，越线后仍需连续确认才切换状态。")
    print("=" * 74)


if __name__ == "__main__":
    main()
