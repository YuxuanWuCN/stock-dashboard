# -*- coding: utf-8 -*-
"""立新能源(001258) 趋势门前后对比 —— 验证趋势过滤在妖股上的效果"""
import json
import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\股票分析项目\2.0版")
sys.path.insert(0, str(ROOT))

from tools.prediction_accuracy_harness import (
    load_kline, compute_features, SIGNAL_RULES, ENSEMBLE_VOTERS,
)
from src.strategies.trend_gate import detect_trend, apply_trend_filter

CODE = "001258"
KLINE = ROOT / "docs" / "data" / "kline" / f"{CODE}.json"
WARMUP = 60

data = load_kline(KLINE)
closes = data["closes"]
dates = data["dates"]
n = len(closes)
feats = compute_features(data)
print(f"[加载] {data['name']}({data['code']}) {n} 根K线\n")

def ensemble_vote(i):
    votes = []
    for name in ENSEMBLE_VOTERS:
        feat_name, rule = SIGNAL_RULES[name]
        v = rule(feats[feat_name][i])
        if v is not None:
            votes.append(v)
    if len(votes) < 3:
        return None
    s = sum(votes)
    return 1 if s > 0 else (-1 if s < 0 else None)

# 标签
labels = [None] * n
for i in range(n - 1):
    labels[i] = 0 if closes[i + 1] == closes[i] else (1 if closes[i + 1] > closes[i] else -1)

# 市场环境分段（20日动量）
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

# ==================== v1：无趋势门 ====================
print("=" * 70)
print("【v1 基线】集成投票（无趋势门）")
print("=" * 70)
v1_results = {"total": {"hits": 0, "n": 0}, "up": {"hits": 0, "n": 0}, "down": {"hits": 0, "n": 0}, "flat": {"hits": 0, "n": 0}}
for i in range(WARMUP, n - 1):
    p = ensemble_vote(i)
    actual = labels[i]
    seg = seg_labels[i]
    if p is None or actual == 0:
        continue
    v1_results["total"]["n"] += 1
    v1_results[seg]["n"] += 1
    if p == actual:
        v1_results["total"]["hits"] += 1
        v1_results[seg]["hits"] += 1

for k in ("total", "up", "down", "flat"):
    h = v1_results[k]["hits"]
    t = v1_results[k]["n"]
    acc = h / t if t else None
    label = {"total": "整体", "up": "上升段", "down": "下降段", "flat": "震荡段"}[k]
    if acc is not None:
        print(f"  {label:6s}: 命中 {h}/{t} = {acc*100:.1f}%")

# ==================== v2：有趋势门 ====================
print("\n" + "=" * 70)
print("【v2 改进】集成投票 + 趋势门（下跌趋势禁止看多）")
print("=" * 70)
v2_results = {"total": {"hits": 0, "n": 0}, "up": {"hits": 0, "n": 0}, "down": {"hits": 0, "n": 0}, "flat": {"hits": 0, "n": 0}}
suppressed_count = 0
suppressed_hits = 0  # 被抑制的信号中有多少本来会错
for i in range(WARMUP, n - 1):
    p_raw = ensemble_vote(i)
    trend_state, _ = detect_trend(closes[:i+1])
    p = apply_trend_filter(p_raw, trend_state, mode="suppress_down")
    
    actual = labels[i]
    seg = seg_labels[i]
    
    if p_raw is not None and p is None:
        suppressed_count += 1
        if p_raw != actual:
            suppressed_hits += 1
    
    if p is None or actual == 0:
        continue
    v2_results["total"]["n"] += 1
    v2_results[seg]["n"] += 1
    if p == actual:
        v2_results["total"]["hits"] += 1
        v2_results[seg]["hits"] += 1

for k in ("total", "up", "down", "flat"):
    h = v2_results[k]["hits"]
    t = v2_results[k]["n"]
    acc = h / t if t else None
    label = {"total": "整体", "up": "上升段", "down": "下降段", "flat": "震荡段"}[k]
    if acc is not None:
        print(f"  {label:6s}: 命中 {h}/{t} = {acc*100:.1f}%")
print(f"\n  趋势门抑制次数: {suppressed_count} 次")
print(f"  其中避免错误: {suppressed_hits} 次（抑制掉的看多信号若执行会错）")

# ==================== 改善统计 ====================
print("\n" + "=" * 70)
print("【改善效果】")
print("=" * 70)
for k in ("total", "up", "down", "flat"):
    v1_acc = v1_results[k]["hits"] / v1_results[k]["n"] if v1_results[k]["n"] else None
    v2_acc = v2_results[k]["hits"] / v2_results[k]["n"] if v2_results[k]["n"] else None
    label = {"total": "整体", "up": "上升段", "down": "下降段", "flat": "震荡段"}[k]
    if v1_acc is not None and v2_acc is not None:
        delta = (v2_acc - v1_acc) * 100
        marker = "OK" if delta > 0 else ("X" if delta < 0 else "-")
        print(f"  [{marker}] {label:6s}: {v1_acc*100:.1f}% -> {v2_acc*100:.1f}%  (变化 {delta:+.1f}%)")

out = ROOT / f"{CODE}_趋势门前后对比.json"
with open(out, "w", encoding="utf-8") as fh:
    json.dump({"v1_baseline": v1_results, "v2_with_gate": v2_results, 
               "suppressed": suppressed_count, "suppressed_hits": suppressed_hits}, fh, indent=2)
print(f"\n[输出] {out}")
