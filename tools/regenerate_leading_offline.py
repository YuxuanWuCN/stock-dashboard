"""tools/regenerate_leading_offline.py —— 离线重生成：为现有分析 JSON 附加领先信号并重算综合分。

不重新抓取行情：K线/基本面/行业分全部复用现有 docs/data/analysis/*.json 的已算结果，
仅做三件事：
  1) 计算每只标的的领先指标信号（akshare 真实抓取，失败降级合成）；
  2) 用真实的 compute_composite_score 重算含 leading 分量的综合分；
  3) 更新 analysis JSON（scores.leading / leading / reasons）并重建 ranking.json。

用法（本地能联网时先跑 tools/fetch_leading_data.py 预热 akshare 缓存）：
    python tools/regenerate_leading_offline.py
"""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis.fundamental_config import FUNDAMENTAL_WEIGHT, TECHNICAL_WEIGHT
from src.analysis.leading_indicators import LeadingIndicatorEngine
from src.analysis.scoring import compute_composite_score

ANALYSIS_DIR = ROOT / "docs" / "data" / "analysis"
RANKING_PATH = ANALYSIS_DIR / "ranking.json"


def _load_all() -> dict:
    out = {}
    for p in ANALYSIS_DIR.glob("*.json"):
        if p.name == "ranking.json":
            continue
        try:
            out[p.name[:-5]] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    return out


def _beijing_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "+08:00"


def main() -> int:
    engine = LeadingIndicatorEngine()
    data = _load_all()
    print(f"加载 {len(data)} 个分析 JSON")

    # 全局预测百分位输入（与 build_ranking.main 口径一致）
    all_fc = [
        d["similarity"]["horizon_5d"]["average_return_pct"]
        for d in data.values()
        if d.get("similarity", {}).get("horizon_5d", {}).get("average_return_pct") is not None
    ]
    all_up = [
        d["similarity"]["horizon_5d"]["up_probability_pct"]
        for d in data.values()
        if d.get("similarity", {}).get("horizon_5d", {}).get("up_probability_pct") is not None
    ]
    print(f"全局预测样本: 收益 {len(all_fc)} 条 / 上涨概率 {len(all_up)} 条")

    results = {}
    for code, d in data.items():
        category = d.get("category", "")
        leading_signal = engine.fetch_real_leading_signal(
            engine.match_industry_category(category)
        )

        scores = d.get("scores", {})
        risk_result = {
            "score": scores.get("risk", 50.0),
            "level": (d.get("risk") or {}).get("level", "medium"),
            "label": (d.get("risk") or {}).get("label", "中等风险"),
        }
        technical_result = {"score": scores.get("technical", 50.0)}
        industry_result = {"score": scores.get("industry", 50.0)}
        sim = d.get("similarity", {})

        composite = compute_composite_score(
            risk_result, technical_result, industry_result, sim,
            all_fc, all_up,
            leading_signal=leading_signal,
        )

        # 更新 analysis JSON 字段
        d["leading"] = leading_signal
        d["scores"] = {
            "risk_adjusted": composite["risk_adjusted"],
            "risk": composite["risk"],
            "technical": composite["technical"],
            "industry": composite["industry"],
            "leading": composite["leading"],
        }
        if composite.get("leading_reason"):
            lc = composite["leading"]
            d.setdefault("reasons", []).append({
                "type": "positive" if lc >= 65 else ("negative" if lc <= 35 else "neutral"),
                "title": "领先指标",
                "detail": composite["leading_reason"],
                "contribution": round((lc - 50.0) * 2, 1),
            })
        # 排序截断与主流程一致（按贡献绝对值，取前 5）
        d["reasons"] = sorted(
            d.get("reasons", []),
            key=lambda r_: abs(r_.get("contribution", 0) or 0),
            reverse=True,
        )[:5]

        results[code] = d

    # 写回 analysis JSON（只更新带 leading 的字段）
    for code, d in results.items():
        (ANALYSIS_DIR / f"{code}.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"已更新 {len(results)} 个分析 JSON")

    # 重建 ranking.json（沿用 build_ranking.main 的 item_entry 格式）
    items = []
    sorted_codes = sorted(
        results,
        key=lambda c: (
            not results[c].get("stale", False),
            results[c]["scores"].get("risk_adjusted") if results[c]["scores"].get("risk_adjusted") is not None else -999,
        ),
        reverse=True,
    )
    for rank, code in enumerate(sorted_codes, start=1):
        d = results[code]
        comp = d["scores"]
        risk_adjusted = comp.get("risk_adjusted")
        fundamental = d.get("fundamental")
        fundamental_score = fundamental.get("score") if fundamental else None

        total_score = risk_adjusted
        if fundamental_score is not None and risk_adjusted is not None:
            total_score = round(
                max(0.0, min(100.0, TECHNICAL_WEIGHT * risk_adjusted + FUNDAMENTAL_WEIGHT * fundamental_score)),
                1,
            )

        tech = d.get("technical", {})
        ind = d.get("industry", {})
        ld = d.get("leading", {})
        mm = ld.get("momentum_metrics", {})
        items.append({
            "rank": rank,
            "code": d["code"],
            "name": d["name"],
            "type": d.get("type", ""),
            "category": d.get("category", ""),
            "trade_date": d.get("trade_date", ""),
            "stale": d.get("stale", False),
            "risk_adjusted_score": risk_adjusted,
            "fundamental_score": fundamental_score,
            "total_score": total_score,
            "risk": {
                "score": comp.get("risk"),
                "level": (d.get("risk") or {}).get("level", "medium"),
                "label": (d.get("risk") or {}).get("label", "中等风险"),
                "factors": (d.get("risk") or {}).get("factors", []),
            },
            "forecast": d.get("forecast", {}),
            "technical": {
                "score": comp.get("technical"),
                "trend": tech.get("trend"),
                "rsi14": tech.get("rsi14"),
                "volume_ratio_5d": tech.get("volume_ratio_5d"),
            },
            "industry": {
                "name": ind.get("name"),
                "reference_type": ind.get("reference_type"),
                "score": comp.get("industry"),
                "return_5d_pct": ind.get("return_5d_pct"),
                "return_20d_pct": ind.get("return_20d_pct"),
                "relative_strength_20d_pct": ind.get("relative_strength_20d_pct"),
            },
            "leading": {
                "score": comp.get("leading"),
                "inflection": mm.get("inflection_flag", "none"),
                "momentum": mm.get("momentum", "flat"),
                "data_source": ld.get("data_source", "none"),
                "source_name": ld.get("source_name", ""),
            },
            "fundamental": fundamental,
            "reasons": d.get("reasons", []),
            "alpha_gate": d.get("alpha_gate"),
        })

    trade_dates = [i["trade_date"] for i in items if i["trade_date"]]
    trade_date_str = Counter(trade_dates).most_common(1)[0][0] if trade_dates else ""
    ranking = {
        "schema_version": "2.0",
        "generated_at": _beijing_now(),
        "trade_date": trade_date_str,
        "horizons": [3, 5],
        "ranking_method": "risk_adjusted_v1",
        "status": "success",
        "total": len(results),
        "succeeded": len(items),
        "failed": 0,
        "items": items,
    }
    RANKING_PATH.write_text(json.dumps(ranking, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ranking.json 已重建（{len(items)} 项）")

    # 统计领先信号来源
    src_cnt = Counter(ld.get("data_source", "none") for ld in (d.get("leading", {}) for d in results.values()))
    print(f"领先信号来源统计: {dict(src_cnt)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
