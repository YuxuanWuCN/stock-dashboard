# -*- coding: utf-8 -*-
"""用本课题自己的模型生成当前交易信号（Trend Gate + Temporal NALE + 期限结构）。

用法: python -m src.trading.generate_signal [--equity 1000000] [--inventory 10000]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models.temporal_nale import TemporalNALE
from src.models.trend_gate import TrendGateMachine

FEATURES = ROOT_DIR / "data" / "processed" / "czce_sa_fg_aligned_features.csv"
MULTIPLIER = 20.0      # 郑商所纯碱 20 吨/手
MARGIN_RATIO = 0.12    # 保证金比例（交易所+期货公司，按 12% 估）


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--equity", type=float, default=1_000_000.0, help="账户权益（元）")
    ap.add_argument("--inventory", type=float, default=10_000.0, help="现货敞口（吨）")
    ap.add_argument("--risk-pct", type=float, default=0.02, help="单笔风险占权益比例")
    ap.add_argument("--stop-ticks", type=float, default=30.0, help="止损距离（元/吨）")
    args = ap.parse_args()

    df = pd.read_csv(FEATURES)
    df["date"] = pd.to_datetime(df["date"])
    last_date = df["date"].iloc[-1]
    print("=" * 68)
    print("【本课题模型信号】数据截止交易日: %s" % last_date.date())

    # ---------- 1. Temporal NALE 产业链传导 ----------
    nale = TemporalNALE(window=60, sa_to_fg_lag=18.0, sa_half_life=25.0)
    crush = nale.compute_crush_spread(df)
    nale_sig = crush["nale_leading_signal"]

    # ---------- 2. Trend Gate 因果门控 ----------
    gate = TrendGateMachine(fast_span=20, slow_span=60, hysteresis_window=3,
                            nale_weight=0.35, tsmom_weight=0.20, active_defense=True)
    res = gate.evaluate_regime(
        df["close_sa"],
        nale_signals=nale_sig,
        tsmom_signals=df["tsmom_sa"] if "tsmom_sa" in df.columns else None,
    )

    df = df.join(res[["ema_fast", "ema_slow", "composite_score", "trend_gate",
                      "dynamic_hedge_ratio"]])
    df["nale_signal"] = nale_sig.values

    row = df.iloc[-1]
    price = float(row["close_sa"])
    regime = int(row["trend_gate"])
    score = float(row["composite_score"])
    h = float(row["dynamic_hedge_ratio"])

    print("-" * 68)
    print("一、市场状态判定")
    print("  收盘价           : %.1f 元/吨" % price)
    print("  EMA20 / EMA60    : %.1f / %.1f" % (row["ema_fast"], row["ema_slow"]))
    print("  均线排列         : %s" % ("空头排列（价<EMA20<EMA60）" if price < row["ema_fast"] < row["ema_slow"]
                                        else "非空头排列"))
    print("  综合破位得分 Z   : %.3f  (阈值 0.50)" % score)
    print("  NALE 产业链信号  : %.4f" % float(row["nale_signal"]))
    print("  TSMOM 期限结构   : %.4f" % float(row["tsmom_sa"]))
    print("  状态             : %s" % ("1 = 破位主跌浪" if regime == 1 else "0 = 震荡/修复"))
    print("  建议对冲比例 h*  : %.0f%%" % (h * 100))

    print("-" * 68)
    print("二、最近 8 个交易日的状态演化")
    tail = df.tail(8)[["date", "close_sa", "ema_fast", "ema_slow", "composite_score",
                       "trend_gate", "dynamic_hedge_ratio"]]
    for _, r in tail.iterrows():
        print("  %s  收 %7.1f  EMA20 %7.1f  EMA60 %7.1f  Z=%.3f  状态=%d  对冲=%.0f%%" % (
            r["date"].date(), r["close_sa"], r["ema_fast"], r["ema_slow"],
            r["composite_score"], r["trend_gate"], r["dynamic_hedge_ratio"] * 100))

    # ---------- 3. 交易指令建议 ----------
    full_lots = int(round(args.inventory / MULTIPLIER))
    target_lots = int(round(h * full_lots))
    margin_per_lot = price * MULTIPLIER * MARGIN_RATIO
    risk_per_lot = args.stop_ticks * MULTIPLIER
    risk_budget = args.equity * args.risk_pct
    lots_by_risk = int(risk_budget // risk_per_lot) if risk_per_lot > 0 else 0

    print("-" * 68)
    print("三、可执行建议")
    if regime == 1:
        direction = "卖开（做空）"
        reason = "均线空头排列 + NALE 先行挤压 + 门控确认，判定为破位主跌浪"
    else:
        direction = "持有/观望（不建议追空）"
        reason = "处于震荡/修复状态，主动防御机制抑制假突破追空"
    print("  方向             : %s" % direction)
    print("  依据             : %s" % reason)
    print("  现货套保视角     : 目标空头 %d 手（按现货 %.0f 吨、对冲比例 %.0f%%）"
          % (target_lots, args.inventory, h * 100))
    print("  比赛账户视角     : 单笔保证金 %.0f 元/手；按 %.0f 元权益，"
          "%.1f%% 风险预算、%.0f 元/吨止损 → 最多 %d 手"
          % (margin_per_lot, args.equity, args.risk_pct * 100, args.stop_ticks, lots_by_risk))
    print("  参考入场价       : %.1f 附近（最新收盘）" % price)
    print("  参考止损         : %.1f（+%.0f 元/吨）" % (price + args.stop_ticks, args.stop_ticks))
    print("=" * 68)


if __name__ == "__main__":
    main()
