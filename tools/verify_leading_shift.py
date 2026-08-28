"""tools/verify_leading_shift.py —— A/B 验证：领先信号是否真的改变排名（005 SC-003）。

用同一批原始输入（risk/tech/industry/similarity）重算两组综合分：
  baseline: leading=None（中性 50）  vs  actual: 领先信号真实值
比较两组排名的换位情况，输出统计与具体换位标的。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis.scoring import compute_composite_score

ANALYSIS_DIR = ROOT / "docs" / "data" / "analysis"


def main() -> int:
    data = {}
    for p in ANALYSIS_DIR.glob("*.json"):
        if p.name == "ranking.json":
            continue
        try:
            data[p.name[:-5]] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

    all_fc = [d["similarity"]["horizon_5d"]["average_return_pct"] for d in data.values()
              if d.get("similarity", {}).get("horizon_5d", {}).get("average_return_pct") is not None]
    all_up = [d["similarity"]["horizon_5d"]["up_probability_pct"] for d in data.values()
              if d.get("similarity", {}).get("horizon_5d", {}).get("up_probability_pct") is not None]

    base_scores, actual_scores = {}, {}
    for code, d in data.items():
        scores = d.get("scores", {})
        risk_result = {"score": scores.get("risk", 50.0),
                       "level": (d.get("risk") or {}).get("level", "medium"),
                       "label": (d.get("risk") or {}).get("label", "中等风险")}
        tech = {"score": scores.get("technical", 50.0)}
        ind = {"score": scores.get("industry", 50.0)}
        sim = d.get("similarity", {})
        base = compute_composite_score(risk_result, tech, ind, sim, all_fc, all_up)
        actual = compute_composite_score(risk_result, tech, ind, sim, all_fc, all_up,
                                         leading_signal=d.get("leading"))
        base_scores[code] = base["risk_adjusted"]
        actual_scores[code] = actual["risk_adjusted"]

    base_rank = {c: i + 1 for i, c in enumerate(sorted(base_scores, key=lambda c: base_scores[c], reverse=True))}
    actual_rank = {c: i + 1 for i, c in enumerate(sorted(actual_scores, key=lambda c: actual_scores[c], reverse=True))}

    moved = {c: (base_rank[c], actual_rank[c], actual_rank[c] - base_rank[c]) for c in data
             if base_rank[c] != actual_rank[c]}
    print(f"总标的: {len(data)}  换位标的: {len(moved)}")

    # 领先信号驱动换位的标的（leading 非中性 50）
    lead_movers = []
    for code in data:
        ld = data[code].get("leading", {})
        ds = ld.get("data_source", "none")
        if ds == "akshare" and code in moved:
            lead_movers.append((code, data[code].get("name", ""), base_rank[code], actual_rank[code],
                                actual_rank[code] - base_rank[code], data[code]["scores"].get("leading")))
    lead_movers.sort(key=lambda x: x[4])
    print(f"\n=== 真实领先数据(aakshare)驱动的换位 ===")
    for m in lead_movers:
        print(f"{m[0]} {m[1]}: 排名 {m[2]} -> {m[3]} (Δ{m[4]}) 领先分={m[5]}")

    print(f"\n=== 最大换位 Top10 ===")
    top = sorted(moved.items(), key=lambda kv: abs(kv[1][2]))[-10:][::-1]
    for code, (br, ar, delta) in top:
        print(f"{code} {data[code].get('name','')}: {br} -> {ar} (Δ{delta})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
