# tools/random_control.py —— 随机对照组：检验组合是否显著跑赢随机抽样
#
# 协议 v1 第 4 条：对照组 = 全池等权（已有）+ 随机抽样 100 次（本工具）。
#
# 原理：
#   对每个组合的每个交易日，从当日有效股票池（summary 中 status=ok 且
#   change_pct 非空、last_date == 该交易日）随机抽取与组合持仓数相同的 N 只，
#   等权计算当日收益。重复 100 次得到"随机选股"的收益分布。
#   组合当日收益在随机分布中的分位 > 95%（单侧）视为当日显著跑赢运气；
#   全样本用 t 检验（组合日收益 - 随机均值）检验均值是否显著为正。
#
# 用法：
#   python tools/random_control.py                # 分析全部组合
#   python tools/random_control.py --only global  # 只分析 global
#   python tools/random_control.py --trials 200   # 抽样次数（默认 100）

import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATA_DIR
from src.utils import beijing_date_str

SUMMARY_PATH = os.path.join(DATA_DIR, "summary.json")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "paper", "daily_snapshots")
PAPER_DIR = os.path.join(DATA_DIR, "paper")
OUT_PATH = os.path.join(DATA_DIR, "paper", "random_control.json")

PORTFOLIO_MAP = {
    "aggressive": "performance_aggressive.json",
    "robust": "performance.json",
    "bluechip": "performance_bluechip.json",
    "defensive": "performance_defensive.json",
    "global": "performance_global.json",
    "tech": "performance_tech.json",
}


def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _daily_changes_by_date(summary):
    """按交易日组织有效股票涨跌幅：{trade_date: [(code, change_pct), ...]}。

    优先使用 K线重建快照（daily_snapshots/{date}.json，覆盖历史缺口），
    快照缺失的日期回退到 summary 当前状态。
    """
    by_date = {}
    # 1) 快照优先（B 修复：覆盖 8/11 等部分失败日）
    if os.path.isdir(SNAPSHOT_DIR):
        for fname in sorted(os.listdir(SNAPSHOT_DIR)):
            if not fname.endswith(".json"):
                continue
            d = fname[:-5]
            snap = _load_json(os.path.join(SNAPSHOT_DIR, fname))
            if not snap:
                continue
            by_date[d] = [(it["code"], float(it["change_pct"]))
                          for it in snap.get("items", [])
                          if it.get("change_pct") is not None]
    # 2) summary 兜底
    for item in summary.get("items", []):
        if item.get("status") != "ok":
            continue
        chg = item.get("change_pct")
        d = item.get("last_date")
        if chg is None or not d:
            continue
        if d not in by_date:
            by_date[d] = []
        by_date[d].append((item["code"], float(chg)))
    return by_date


def _random_sample_daily(changes, n, trials, seed):
    """对某日有效池做 trials 次随机抽样，返回随机等权日收益列表。"""
    if len(changes) < n:
        return None
    rng = random.Random(seed)
    out = []
    for _ in range(trials):
        picks = rng.sample(changes, n)
        out.append(sum(c for _, c in picks) / n)
    return out


def _percentile(value, dist):
    """value 在 dist 中的分位（0~100）：小于等于 value 的比例。"""
    if not dist:
        return None
    return sum(1 for v in dist if v <= value) / len(dist) * 100.0


def _t_test_pvalue(diffs):
    """单侧 t 检验：diffs 均值 > 0 的 p 值（无 scipy 依赖，用 t 分布近似）。"""
    n = len(diffs)
    if n < 2:
        return None
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    if var <= 0:
        return None
    t_stat = mean / math.sqrt(var / n)
    # 用标准正态近似 t 分布（n>=20 时足够；n 小时给出保守近似）
    return _normal_tail(t_stat)


def _normal_tail(t):
    """标准正态右尾概率近似（用互补误差函数 erfc，尾部更稳）。"""
    # 正态 CDF: Phi(x) = 0.5 * erfc(-x/sqrt(2))
    # 右尾 P(Z > t) = 1 - Phi(t) = 0.5 * erfc(t/sqrt(2))
    return 0.5 * _erfc(t / math.sqrt(2.0))


def _erfc(x):
    """互补误差函数（数值配方 6.2.8，尾部精度 ~1e-7）。"""
    z = abs(x)
    t = 1.0 / (1.0 + 0.5 * z)
    ans = t * math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 +
          t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 +
          t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))))
    return ans if x >= 0 else 2.0 - ans


def analyze_portfolio(key, perf, by_date, trials, seed_base):
    """分析单个组合：每日分位 + 全样本 t 检验。"""
    records = perf.get("records", [])
    daily = []
    for rec in records:
        d = rec.get("trade_date")
        pool = by_date.get(d)
        if not pool:
            continue
        items = rec.get("items") or []
        n = len([i for i in items if i.get("change_pct") is not None])
        if n == 0:
            continue
        dist = _random_sample_daily(pool, n, trials, seed_base + len(daily))
        if dist is None:
            continue
        combo_ret = rec.get("portfolio_return_pct")
        if combo_ret is None:
            continue
        random_mean = sum(dist) / len(dist)
        daily.append({
            "trade_date": d,
            "portfolio_return_pct": combo_ret,
            "random_mean": round(random_mean, 4),
            "excess": round(combo_ret - random_mean, 4),
            "percentile": round(_percentile(combo_ret, dist), 1) if dist else None,
            "holdings": n,
            "pool_size": len(pool),
        })

    result = {"days": daily}
    if len(daily) >= 2:
        diffs = [x["excess"] for x in daily]
        mean_excess = sum(diffs) / len(diffs)
        result["mean_excess"] = round(mean_excess, 4)
        result["p_value"] = _t_test_pvalue(diffs)
        result["significant"] = bool(
            result["p_value"] is not None and result["p_value"] < 0.05 and mean_excess > 0)
        result["win_days"] = sum(1 for x in daily if x["excess"] > 0)
        result["n_days"] = len(daily)
    else:
        result["mean_excess"] = None
        result["p_value"] = None
        result["significant"] = None
        result["win_days"] = None
        result["n_days"] = len(daily)
    return result


def main():
    parser = argparse.ArgumentParser(description="随机对照组：组合 vs 随机选股 100 次")
    parser.add_argument("--only", type=str, help="只分析指定组合")
    parser.add_argument("--trials", type=int, default=100, help="随机抽样次数（默认 100）")
    args = parser.parse_args()

    summary = _load_json(SUMMARY_PATH)
    if not summary:
        print("❌ 缺少 summary.json")
        return 1
    by_date = _daily_changes_by_date(summary)
    print(f"有效池按交易日: { {d: len(v) for d, v in sorted(by_date.items())} }")

    keys = [args.only] if args.only else list(PORTFOLIO_MAP.keys())
    results = {}
    for key in keys:
        path = os.path.join(PAPER_DIR, PORTFOLIO_MAP[key])
        perf = _load_json(path)
        if not perf:
            print(f"⚠️  跳过 {key}：无绩效文件")
            continue
        seed = 20260813 + len(results) * 7919
        results[key] = analyze_portfolio(key, perf, by_date, args.trials, seed)
        r = results[key]
        if r["n_days"]:
            sig = "✅ 显著" if r.get("significant") else ("⚠️ 不显著" if r.get("p_value") is not None else "样本不足")
            print(f"{key:10s} n={r['n_days']:>2} 日均超额 {r['mean_excess'] or 0:+.3f}% "
                  f"p={r['p_value'] if r['p_value'] is not None else '--'} {sig}")

    out = {
        "schema_version": "1.0",
        "generated_at": beijing_date_str(),
        "trials": args.trials,
        "method": "per-day 100x random sampling equal-weight; one-sided t-test on daily excess",
        "portfolios": results,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n💾 结果已保存: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
