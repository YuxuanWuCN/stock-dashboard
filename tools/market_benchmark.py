# tools/market_benchmark.py —— 市场级对照组：选股池 vs 宽基指数
#
# 协议 v1 第 4 条第三项对照：检验 202 只自选股池本身是否跑赢大盘
# （前两个对照组只检验"选股排序"是否有效，本对照检验"选股池"是否有效）。
#
# 原理：
#   对每个绩效记录日 D：
#   - 池当日收益 = 快照（daily_snapshots/{D}.json）全部股票等权平均
#   - 基准当日收益 = 宽基 ETF K线 (D 收盘 - 前收) / 前收 * 100
#   全样本单侧 t 检验：池收益 - 基准收益 的均值是否显著为正。
#
# 基准：510300 沪深300ETF 为主；159919（沪深300另一只）验证一致性；
#       510050 上证50、510500 中证500 为辅助。
#
# 用法：python tools/market_benchmark.py
# 输出：docs/data/paper/market_benchmark.json

import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATA_DIR
from src.utils import beijing_date_str

KLINE_DIR = os.path.join(DATA_DIR, "kline")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "paper", "daily_snapshots")
PAPER_DIR = os.path.join(DATA_DIR, "paper")
OUT_PATH = os.path.join(DATA_DIR, "paper", "market_benchmark.json")

# 宽基基准（主/验证/辅助）
BENCHMARKS = [
    ("510300", "沪深300ETF", "primary"),
    ("159919", "沪深300ETF易方达", "crosscheck"),
    ("510050", "上证50ETF", "secondary"),
    ("510500", "中证500ETF", "secondary"),
]


def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _kline_daily_return(code, trade_date):
    """从 K线取单日收益（%）；缺前收/当日数据返回 None。"""
    d = _load_json(os.path.join(KLINE_DIR, f"{code}.json"))
    if not d:
        return None
    dates = d.get("dates", [])
    kline = d.get("kline", [])
    if trade_date not in dates:
        return None
    i = dates.index(trade_date)
    if i < 1:
        return None
    prev = kline[i - 1][1]
    cur = kline[i][1]
    if not prev or not cur or prev <= 0:
        return None
    return round((cur - prev) / prev * 100.0, 4)


def _pool_daily_return(trade_date):
    """快照全部股票等权日收益（%）；无快照返回 None。"""
    snap = _load_json(os.path.join(SNAPSHOT_DIR, f"{trade_date}.json"))
    if not snap:
        return None
    changes = [it["change_pct"] for it in snap.get("items", []) if it.get("change_pct") is not None]
    if not changes:
        return None
    return round(sum(changes) / len(changes), 4)


def _t_test_pvalue(diffs):
    """单侧 t 检验（均值 > 0），与 random_control 一致。"""
    n = len(diffs)
    if n < 2:
        return None
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    if var <= 0:
        return None
    t_stat = mean / math.sqrt(var / n)
    return 0.5 * _erfc(t_stat / math.sqrt(2.0))


def _erfc(x):
    z = abs(x)
    t = 1.0 / (1.0 + 0.5 * z)
    ans = t * math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 +
          t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 +
          t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))))
    return ans if x >= 0 else 2.0 - ans


def collect_dates():
    """绩效记录中出现的全部交易日。"""
    dates = set()
    for fname in os.listdir(PAPER_DIR):
        if not fname.startswith("performance") or not fname.endswith(".json"):
            continue
        perf = _load_json(os.path.join(PAPER_DIR, fname))
        if not perf:
            continue
        for rec in perf.get("records", []):
            if rec.get("trade_date"):
                dates.add(rec["trade_date"])
    return sorted(dates)


def main():
    dates = collect_dates()
    print(f"绩效记录日: {dates}")

    # 每日：池收益 + 各基准收益
    rows = defaultdict(dict)
    for d in dates:
        pool_ret = _pool_daily_return(d)
        rows[d]["pool_return"] = pool_ret
        for code, name, role in BENCHMARKS:
            rows[d][code] = _kline_daily_return(code, d)

    results = {}
    for code, name, role in BENCHMARKS:
        pairs = []
        for d in dates:
            pool_ret = rows[d]["pool_return"]
            bench_ret = rows[d][code]
            if pool_ret is None or bench_ret is None:
                continue
            pairs.append({
                "trade_date": d,
                "pool_return": pool_ret,
                "benchmark_return": bench_ret,
                "excess": round(pool_ret - bench_ret, 4),
            })
        diffs = [p["excess"] for p in pairs]
        mean_excess = sum(diffs) / len(diffs) if diffs else None
        p = _t_test_pvalue(diffs) if len(diffs) >= 2 else None
        results[code] = {
            "name": name,
            "role": role,
            "n_days": len(pairs),
            "mean_excess": round(mean_excess, 4) if mean_excess is not None else None,
            "p_value": p,
            "significant": bool(p is not None and p < 0.05 and mean_excess > 0),
            "daily": pairs,
        }
        if pairs:
            sig = "✅ 显著跑赢" if results[code]["significant"] else (
                "❌ 显著跑输" if p is not None and mean_excess < 0 and (1 - p) < 0.05 else "⚠️ 不显著")
            print(f"{code} {name:12s} ({role:10s}) n={len(pairs):>2} 日均超额 {mean_excess:+.3f}% p={p if p is not None else '--'} {sig}")

    out = {
        "schema_version": "1.0",
        "generated_at": beijing_date_str(),
        "method": "equal-weight pool daily return vs benchmark ETF kline daily return; one-sided t-test",
        "benchmarks": results,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n💾 结果已保存: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
