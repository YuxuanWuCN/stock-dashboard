# -*- coding: utf-8 -*-
"""美光科技(MU) 封箱交易者预测比对 —— 细致版

对比立新能源版，本次增加:
  1. 全 14 信号 × 5 预测期(1/3/5/10/20日) 命中率矩阵
  2. 集成投票"比分"分层（预测强度 vs 命中率 校准表）
  3. 分段统计：上升段/下降段/震荡段的命中率差异
  4. 完整模拟交易：收益率/年化/最大回撤/胜率/盈亏比/月度收益
  5. 逐日明细 JSON（date/close/actual/pred/score/hit）
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
import matplotlib.dates as mdates
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

from tools.prediction_accuracy_harness import (
    load_kline, compute_features, SIGNAL_RULES, ENSEMBLE_VOTERS,
    rule_sign, rule_rsi_momentum, rule_rsi_meanrev, rule_reversal, rule_vol_breakout,
)

CODE = "MU"
KLINE = ROOT / "docs" / "data" / "kline" / f"{CODE}.json"
HORIZONS = (1, 3, 5, 10, 20)
WARMUP = 60

data = load_kline(KLINE)
closes = data["closes"]
dates = data["dates"]
n = len(closes)
feats = compute_features(data)
print(f"[加载] {data['name']}({data['code']}) {n} 根K线 {dates[0]} ~ {dates[-1]}")

def label_series(h):
    lab = [None] * n
    for i in range(n - h):
        lab[i] = 0 if closes[i + h] == closes[i] else (1 if closes[i + h] > closes[i] else -1)
    return lab

def ensemble_vote(i):
    votes = []
    for name in ENSEMBLE_VOTERS:
        feat_name, rule = SIGNAL_RULES[name]
        v = rule(feats[feat_name][i])
        if v is not None:
            votes.append(v)
    if len(votes) < 3:
        return None, 0, 0
    s = sum(votes)
    return (1 if s > 0 else (-1 if s < 0 else None)), s, len(votes)

report = {"stock": {"code": CODE, "name": data["name"]}, "n_days": n,
          "range": [dates[0], dates[-1]], "horizons": list(HORIZONS)}

# ================= 1. 全信号 × 全预测期 命中率矩阵 =================
print("\n" + "=" * 78)
print("【1】全信号 × 预测期 命中率矩阵 (无前视, 预热60日)")
print("=" * 78)
header = f"{'信号':<14}" + "".join(f"{'h='+str(h):>9}" for h in HORIZONS)
print(header)
matrix = {}
for sig, (feat_name, rule) in SIGNAL_RULES.items():
    feat = feats[feat_name]
    row = {}
    for h in HORIZONS:
        labels = label_series(h)
        correct = total = 0
        for i in range(WARMUP, n - h):
            p = rule(feat[i])
            if p is None or labels[i] in (None, 0):
                continue
            total += 1
            correct += (p == labels[i])
        acc = correct / total if total else None
        row[h] = {"acc": acc, "n": total}
    matrix[sig] = row
    cells = []
    for h in HORIZONS:
        a = row[h]["acc"]
        cells.append(f"{a*100:7.1f}%/" if a is not None else f"{'--':>9}")
    print(f"{sig:<14}" + "".join(f"{c:>9}" for c in cells))
report["signal_matrix"] = {s: {str(h): v for h, v in row.items()} for s, row in matrix.items()}

# ================= 2. 集成投票比分分层（预测强度校准） =================
print("\n" + "=" * 78)
print("【2】集成投票比分分层 —— 预测强度 vs 实际命中率 (1日)")
print("=" * 78)
buckets = {"|score|>=3": [], "|score|=2": [], "|score|=1": []}
for i in range(WARMUP, n - 1):
    p, score, nv = ensemble_vote(i)
    actual = 1 if closes[i + 1] > closes[i] else (-1 if closes[i + 1] < closes[i] else 0)
    if p is None or actual == 0:
        continue
    ab = abs(score)
    key = "|score|>=3" if ab >= 3 else (f"|score|={ab}" if ab in (2, 1) else None)
    if key:
        buckets[key].append((p == actual, nv))
for key, rows in buckets.items():
    hits = sum(1 for ok, _ in rows for _ in [0] if ok)
    hits = sum(1 for ok, _ in rows if ok)
    n_b = len(rows)
    print(f"  {key:10s}: 命中 {hits}/{n_b} = {hits/n_b*100:.1f}%  (样本 {n_b})" if n_b else f"  {key}: 无样本")
    report[f"bucket_{key.replace('|','').replace('=','_')}"] = {"hits": hits, "n": n_b,
                                                               "acc": hits / n_b if n_b else None}

# ================= 3. 分段统计（上升/下降/震荡段） =================
print("\n" + "=" * 78)
print("【3】按市场环境分段 —— 各段的集成预测命中率 (1日)")
print("=" * 78)
seg_labels = []
for i in range(n):
    if i < 20:
        seg_labels.append("warmup")
        continue
    r20 = closes[i] / closes[i - 20] - 1 if closes[i - 20] else 0
    if r20 > 0.05:
        seg_labels.append("up")
    elif r20 < -0.05:
        seg_labels.append("down")
    else:
        seg_labels.append("flat")
for seg in ("up", "down", "flat"):
    hits = total = 0
    for i in range(WARMUP, n - 1):
        if seg_labels[i] != seg:
            continue
        p, _, _ = ensemble_vote(i)
        actual = 1 if closes[i + 1] > closes[i] else (-1 if closes[i + 1] < closes[i] else 0)
        if p is None or actual == 0:
            continue
        total += 1
        hits += (p == actual)
    acc = hits / total if total else None
    print(f"  {seg:6s}段: 命中 {hits}/{total} = {acc*100:.1f}%" if acc else f"  {seg}: 无样本")
    report[f"segment_{seg}"] = {"hits": hits, "n": total, "acc": acc}

# ================= 4. 模拟交易 v2（比分阈值过滤） =================
print("\n" + "=" * 78)
print("【4】模拟交易 —— 比分>=2 才开仓（预测1日方向，次日持有）")
print("=" * 78)

def simulate(threshold=2):
    equity = [100.0] * n
    trades = []
    in_pos = 0
    entry_price = None
    for i in range(1, n):
        ret = closes[i] / closes[i - 1] - 1 if closes[i - 1] else 0
        p, score, nv = ensemble_vote(i - 1)
        if p is not None and abs(score) >= threshold and in_pos == 0:
            in_pos = p
            entry_price = closes[i - 1]
        daily = ret * in_pos
        equity[i] = equity[i - 1] * (1 + daily)
        if in_pos != 0:
            trades.append((dates[i], closes[i], in_pos, daily))
        # 每日检查离场：预测翻空即平
        p2, _, _ = ensemble_vote(i)
        if in_pos != 0 and (p2 is not None and p2 != in_pos):
            in_pos = 0
    return equity, trades

eq_sig, trades = simulate(2)
eq_hold = [100.0] * n
for i in range(1, n):
    eq_hold[i] = eq_hold[i - 1] * (closes[i] / closes[i - 1]) if closes[i - 1] else eq_hold[i - 1]

hold_ret = (eq_hold[-1] / eq_hold[WARMUP] - 1) * 100
sig_ret = (eq_sig[-1] / eq_sig[WARMUP] - 1) * 100

# 信号策略统计
daily_ret_sig = [eq_sig[i] / eq_sig[i - 1] - 1 for i in range(1, n) if eq_sig[i - 1]]
wins = [r for r in daily_ret_sig if r > 0]
losses = [r for r in daily_ret_sig if r < 0]
win_rate = len(wins) / len(daily_ret_sig) if daily_ret_sig else None
avg_win = sum(wins) / len(wins) if wins else 0
avg_loss = sum(losses) / len(losses) if losses else 0
profit_factor = (sum(wins) / abs(sum(losses))) if losses else float("inf")
peak = eq_sig[WARMUP]
max_dd = 0.0
for v in eq_sig[WARMUP:]:
    peak = max(peak, v)
    max_dd = max(max_dd, (peak - v) / peak)
days = max(n - WARMUP, 1)
annual = ((eq_sig[-1] / eq_sig[WARMUP]) ** (252 / days) - 1) * 100 if eq_sig[WARMUP] else 0

print(f"  买入持有: {hold_ret:+.2f}%  (年化约 {(((eq_hold[-1]/eq_hold[WARMUP])**(252/days))-1)*100:+.1f}%)")
print(f"  信号策略: {sig_ret:+.2f}%  (年化约 {annual:+.1f}%)")
print(f"  策略最大回撤: {max_dd*100:.1f}% | 交易天数胜率: {win_rate*100:.1f}% | 盈亏比(avg): {avg_win/abs(avg_loss):.2f}" if losses else "  无亏损日")
print(f"  利润因子: {profit_factor:.2f}")

report["simulation"] = {
    "hold_return_pct": round(hold_ret, 2), "signal_return_pct": round(sig_ret, 2),
    "signal_annual_pct": round(annual, 1), "max_drawdown_pct": round(max_dd * 100, 1),
    "win_rate": round(win_rate, 3) if win_rate else None,
    "profit_factor": round(profit_factor, 2) if math.isfinite(profit_factor) else None,
    "n_trades": len(trades),
}

# ================= 5. 逐日明细 =================
print("\n[5] 生成逐日明细...")
daily_detail = []
for i in range(WARMUP, n - 1):
    p, score, nv = ensemble_vote(i)
    actual = 1 if closes[i + 1] > closes[i] else (-1 if closes[i + 1] < closes[i] else 0)
    daily_detail.append({
        "date": dates[i], "close": round(closes[i], 2),
        "actual_dir": actual, "pred_dir": p, "score": score, "n_votes": nv,
        "hit": (p == actual) if (p is not None and actual != 0) else None,
    })
report["daily"] = daily_detail
report["overall_1d"] = {
    "overlap": sum(1 for d in daily_detail if d["hit"] is not None),
    "matched": sum(1 for d in daily_detail if d["hit"] is True),
}

# ================= 6. 可视化（4面板） =================
print("[6] 绘图...")
fig, axes = plt.subplots(4, 1, figsize=(15, 14), sharex=True)

ax = axes[0]
ax.plot(range(n), closes, color="#1a365d", lw=1.5)
ax.set_ylabel("收盘价")
ax.set_title(f"{data['name']}({CODE}) 封箱交易者细致比对（{dates[0]} ~ {dates[-1]}）", fontsize=13, fontweight="bold")
ax.grid(alpha=0.3)

ax = axes[1]
actual1 = [1 if closes[i+1] > closes[i] else (-1 if closes[i+1] < closes[i] else 0) for i in range(n-1)]
pred1 = [ensemble_vote(i)[0] or 0 for i in range(n-1)]
ax.plot(range(1, n), actual1, color="#38a169", lw=1.1, label="实际1日方向")
ax.plot(range(1, n), pred1, color="#c53030", lw=1.1, alpha=0.85, label="集成预测1日方向")
ax.axhline(0, color="gray", lw=0.8)
ax.set_ylabel("方向")
ax.legend(loc="upper left", fontsize=9); ax.grid(alpha=0.3)

ax = axes[2]
scores = [ensemble_vote(i)[1] for i in range(n-1)]
colors_bar = ["#c53030" if s > 0 else ("#2f855a" if s < 0 else "#a0aec0") for s in scores]
ax.bar(range(1, n), scores, color=colors_bar, width=1.0)
ax.axhline(0, color="gray", lw=0.8)
ax.set_ylabel("投票比分")
ax.set_title("集成投票比分（强度/方向）", fontsize=10)
ax.grid(alpha=0.3)

ax = axes[3]
ax.plot(range(n), eq_hold, color="#2b6cb0", lw=1.4, label=f"买入持有 {hold_ret:+.1f}%")
ax.plot(range(n), eq_sig, color="#d69e2e", lw=1.4, label=f"信号策略 {sig_ret:+.1f}%")
ax.fill_between(range(n), eq_sig, eq_hold, where=[s >= h for s, h in zip(eq_sig, eq_hold)],
                color="#d69e2e", alpha=0.15, label="策略超额区间")
ax.set_ylabel("净值(基准100)")
ax.legend(loc="upper left", fontsize=9); ax.grid(alpha=0.3)

fig.tight_layout()
out_png = ROOT / f"{CODE}_封箱交易者细致比对.png"
fig.savefig(out_png, dpi=160)
out_json = ROOT / f"{CODE}_封箱交易者细致比对.json"
with open(out_json, "w", encoding="utf-8") as fh:
    json.dump({k: v for k, v in report.items() if k != "daily"}, fh, ensure_ascii=False, indent=2, default=str)
print(f"\n[输出] 图: {out_png}")
print(f"[输出] 数据: {out_json}")
