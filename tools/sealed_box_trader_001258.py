# -*- coding: utf-8 -*-
"""立新能源(001258) 封箱交易者预测比对 —— 预测 vs 实际走势重合度评估

玩法：把封装好的信号系统当作一个"交易者"：
  1. 每天收盘后，只用当日及之前数据（无前视）预测未来 1/3/5 日方向
  2. 模拟交易：预测上涨→持有，预测下跌→空仓
  3. 与真实走势逐日比对，量化"重合度"（方向命中率）
  4. 对比随机基线(50%)与项目目标(80%)，并可视化预测 vs 实际
"""
import json
import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\股票分析项目\2.0版")
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

from tools.prediction_accuracy_harness import (
    load_kline, compute_features, SIGNAL_RULES, ENSEMBLE_VOTERS,
    rule_sign, rule_rsi_momentum, rule_rsi_meanrev, rule_reversal, rule_vol_breakout,
)

CODE = "001258"
KLINE = ROOT / "docs" / "data" / "kline" / f"{CODE}.json"
HORIZONS = (1, 3, 5)
WARMUP = 60

data = load_kline(KLINE)
closes = data["closes"]
dates = data["dates"]
n = len(closes)
feats = compute_features(data)
print(f"[加载] {data['name']}({data['code']}) {n} 根K线 {dates[0]} ~ {dates[-1]}")

# ---------------- 1. 构建预测序列 ----------------
# 集成投票（5 信号多数投票）+ 单信号对比
rules = {
    "mom5": (feats["mom5"], rule_sign),
    "ma10": (feats["ma_ratio10"], rule_sign),
    "cross_5_20": (feats["cross_5_20"], rule_sign),
    "rsi_mom": (feats["rsi14"], rule_rsi_momentum),
    "rsi_rev": (feats["rsi14"], rule_rsi_meanrev),
    "vol_breakout": (feats["vol_z20"], rule_vol_breakout),
}

def ensemble_vote(i: int):
    votes = []
    for name in ENSEMBLE_VOTERS:
        feat_name, rule = SIGNAL_RULES[name]
        votes.append(rule(feats[feat_name][i]))
    votes = [v for v in votes if v is not None]
    if len(votes) < 3:
        return None
    s = sum(votes)
    return 1 if s > 0 else (-1 if s < 0 else None)

# ---------------- 2. 逐日预测 vs 实际比对 ----------------
report = {"stock": {"code": CODE, "name": data["name"]}, "horizons": list(HORIZONS)}

for h in HORIZONS:
    print(f"\n===== 预测期 {h} 日 =====")
    labels = [None] * n
    for i in range(n - h):
        labels[i] = 0 if closes[i + h] == closes[i] else (1 if closes[i + h] > closes[i] else -1)

    # 集成投票
    correct = total = 0
    for i in range(WARMUP, n - h):
        p = ensemble_vote(i)
        if p is None or labels[i] in (None, 0):
            continue
        total += 1
        correct += (p == labels[i])
    acc = correct / total if total else None
    print(f"  集成投票(5信号): {correct}/{total} = {acc*100:.1f}%" if acc else "  集成投票: 样本不足")
    report[f"ensemble_h{h}"] = {"accuracy": acc, "n": total}

    # 各单信号
    for sig_name, (feat, rule) in rules.items():
        correct = total = 0
        for i in range(WARMUP, n - h):
            p = rule(feat[i])
            if p is None or labels[i] in (None, 0):
                continue
            total += 1
            correct += (p == labels[i])
        acc = correct / total if total else None
        if acc is not None:
            print(f"  {sig_name:12s}: {correct}/{total} = {acc*100:.1f}%")
        report[f"{sig_name}_h{h}"] = {"accuracy": acc, "n": total}

# ---------------- 3. 模拟交易者（h=1 滚动持有） ----------------
print("\n===== 模拟交易（预测1日方向，上涨持有/下跌空仓）=====")
equity_signal = [100.0] * n
equity_hold = [100.0] * n
positions = []
for i in range(1, n):
    equity_hold[i] = equity_hold[i - 1] * (1 + closes[i] / closes[i - 1] - 1) if closes[i - 1] else equity_hold[i - 1]
    p = ensemble_vote(i - 1)  # 用昨日信号
    if p is None:
        p = 0
    pos = 1 if p > 0 else 0
    positions.append(pos)
    daily_ret = closes[i] / closes[i - 1] - 1 if closes[i - 1] else 0
    equity_signal[i] = equity_signal[i - 1] * (1 + pos * daily_ret)

hold_ret = (closes[-1] / closes[WARMUP] - 1) * 100
sig_ret = (equity_signal[-1] / equity_signal[WARMUP] - 1) * 100
in_market = sum(positions) / max(len(positions), 1)
print(f"  买入持有: {hold_ret:+.2f}%")
print(f"  信号策略: {sig_ret:+.2f}%  (仓位暴露率 {in_market*100:.1f}%)")
report["simulation"] = {
    "hold_return_pct": round(hold_ret, 2),
    "signal_return_pct": round(sig_ret, 2),
    "market_exposure": round(in_market, 3),
}

# ---------------- 4. 重合度：预测方向序列 vs 实际方向序列 ----------------
pred_seq = [ensemble_vote(i) for i in range(n - 1)]
actual_seq = [1 if closes[i + 1] > closes[i] else (-1 if closes[i + 1] < closes[i] else 0) for i in range(n - 1)]
overlap = matched = 0
for p, a in zip(pred_seq, actual_seq):
    if p is not None and a != 0:
        overlap += 1
        matched += (p == a)
coincidence = matched / overlap if overlap else None
print(f"\n===== 重合度（1日方向，逐日比对）=====")
print(f"  有效比对天数: {overlap}, 预测与实际重合: {matched} 天, 重合率: {coincidence*100:.1f}%")
print(f"  随机基线: 50% | 项目目标: 80%")
report["coincidence"] = {"overlap_days": overlap, "matched_days": matched, "rate": coincidence}

# ---------------- 5. 可视化 ----------------
fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)

ax = axes[0]
ax.plot(range(n), closes, color="#1a365d", lw=1.6, label="实际收盘价")
ax.set_ylabel("价格")
ax.set_title(f"{data['name']}({CODE}) 封箱交易者预测 vs 实际走势比对", fontsize=13, fontweight="bold")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)

ax = axes[1]
pred_vals = [p if p is not None else 0 for p in pred_seq]
ax.plot(range(1, n), [a for a in actual_seq], color="#38a169", lw=1.2, label="实际1日方向")
ax.plot(range(1, n), pred_vals, color="#c53030", lw=1.2, alpha=0.85, label="集成预测1日方向")
ax.axhline(0, color="gray", lw=0.8)
ax.set_ylabel("方向 (+1涨/-1跌)")
ax.set_title(f"逐日方向预测 vs 实际（重合率 {coincidence*100:.1f}% vs 随机 50%）", fontsize=11)
ax.legend(loc="upper left"); ax.grid(alpha=0.3)

ax = axes[2]
ax.plot(range(n), equity_hold, color="#2b6cb0", lw=1.4, label="买入持有")
ax.plot(range(n), equity_signal, color="#d69e2e", lw=1.4, label="信号策略(预测上涨才持有)")
ax.set_ylabel("净值 (基准100)")
ax.set_title(f"策略模拟：买入持有 {hold_ret:+.1f}% vs 信号策略 {sig_ret:+.1f}%")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)

fig.tight_layout()
out_png = ROOT / f"{CODE}_封箱交易者预测比对.png"
fig.savefig(out_png, dpi=160)
print(f"\n[图] {out_png}")

out_json = ROOT / f"{CODE}_封箱交易者预测比对.json"
with open(out_json, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2)
print(f"[数据] {out_json}")
