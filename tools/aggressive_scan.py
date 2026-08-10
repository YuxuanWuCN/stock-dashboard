# tools/aggressive_scan.py —— 全库激进潜力扫描（遍历所有自选股）
#
# 用法：python tools/aggressive_scan.py [--top 20]
# 输出：控制台 Top N + docs/data/paper/aggressive_scan.json（全量评分）
#
# 激进分 = 5日上涨概率×0.4 + 3日上涨概率×0.3 + 20日动量(0~40截断)×0.75

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATA_DIR


def scan(top: int = 20) -> list:
    ranking_path = os.path.join(DATA_DIR, "analysis", "ranking.json")
    with open(ranking_path, "r", encoding="utf-8") as f:
        ranking = json.load(f)

    rows = []
    for it in ranking.get("items", []):
        if it.get("stale"):
            continue
        code = it["code"]
        tech = {}
        ap = os.path.join(DATA_DIR, "analysis", f"{code}.json")
        if os.path.exists(ap):
            try:
                with open(ap, "r", encoding="utf-8") as f:
                    tech = (json.load(f).get("technical") or {})
            except Exception:
                tech = {}
        fc = it.get("forecast") or {}
        up3 = fc.get("up_probability_3d_pct") or 0
        up5 = fc.get("up_probability_5d_pct") or 0
        ret20 = tech.get("return_20d_pct") or 0
        momentum = max(-20, min(40, ret20))
        score = up5 * 0.4 + up3 * 0.3 + max(0, momentum) * 0.75
        rows.append({
            "code": code,
            "name": it.get("name"),
            "rank": it.get("rank"),
            "type": it.get("type"),
            "aggressive_score": round(score, 2),
            "up3": up3,
            "up5": up5,
            "return_20d_pct": round(ret20, 1),
            "trend": tech.get("trend") or "",
            "rsi14": tech.get("rsi14"),
        })

    rows.sort(key=lambda r: r["aggressive_score"], reverse=True)
    out_path = os.path.join(DATA_DIR, "paper", "aggressive_scan.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generated": len(rows), "top": rows[:top], "all": rows}, f, ensure_ascii=False, indent=2)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="全库激进潜力扫描")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    rows = scan(args.top)
    print(f"全库有效标的: {len(rows)}")
    print(f"{'代码':<8}{'名称':<12}{'排名':>5}{'激进分':>7}{'3日%':>6}{'5日%':>6}{'20日%':>8}{'趋势':<10}{'类型'}")
    for r in rows[:args.top]:
        print(f"{r['code']:<8}{r['name']:<12}{r['rank']:>5}{r['aggressive_score']:>7.1f}{r['up3']:>6}{r['up5']:>6}{r['return_20d_pct']:>8.1f}{r['trend']:<10}{r['type']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())