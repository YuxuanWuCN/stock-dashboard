# -*- coding: utf-8 -*-
"""tools/backfill_bet_types.py —— 离线补全赌注类型数据

不依赖网络/流水线，直接用本地 docs/data/kline/*.json 计算每只标的的
赌注类型（妖股/趋势/震荡）+ 策略建议，输出 docs/data/analysis/bet_types.json 供前端展示。
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis.bet_type_classifier import classify_bet_type, get_strategy_recommendation

KLINE_DIR = ROOT / "docs" / "data" / "kline"
OUT = ROOT / "docs" / "data" / "analysis" / "bet_types.json"

LABEL_MAP = {
    "trend": {"label": "趋势股", "short": "趋势", "color": "trend"},
    "volatile": {"label": "妖股", "short": "妖股", "color": "volatile"},
    "range_bound": {"label": "震荡股", "short": "震荡", "color": "range"},
}

result = {}
count = {"trend": 0, "volatile": 0, "range_bound": 0, "skipped": 0}

for f in sorted(KLINE_DIR.glob("*.json")):
    try:
        with open(f, encoding="utf-8") as fh:
            k = json.load(fh)
    except (OSError, json.JSONDecodeError):
        continue

    code = k.get("code", f.stem)
    name = k.get("name", "")
    rows = k.get("kline", [])
    if len(rows) < 60:
        count["skipped"] += 1
        continue

    closes = [r[1] for r in rows]
    highs = [r[3] for r in rows]
    lows = [r[2] for r in rows]

    bet_type, metrics = classify_bet_type(closes, highs, lows)
    rec = get_strategy_recommendation(bet_type)
    meta = LABEL_MAP.get(bet_type, LABEL_MAP["range_bound"])

    result[code] = {
        "code": code,
        "name": name,
        "bet_type": bet_type,
        "label": meta["label"],
        "short": meta["short"],
        "color": meta["color"],
        "volatility_annual": metrics.get("volatility_annual"),
        "momentum_half_life": metrics.get("momentum_half_life"),
        "atr_ratio": metrics.get("atr_ratio"),
        "holding_period_days": rec["holding_period"],
        "trade_frequency": rec["trade_frequency"],
        "advice": rec["description"],
    }
    count[bet_type] = count.get(bet_type, 0) + 1

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump({
        "schema_version": "1.0",
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(result),
        "counts": count,
        "bet_types": result,
    }, fh, ensure_ascii=False, indent=2)

print(f"[OK] 生成 {len(result)} 只标的的赌注类型")
print(f"     趋势股: {count['trend']} | 妖股: {count['volatile']} | 震荡股: {count['range_bound']} | 跳过: {count['skipped']}")
print(f"     输出: {OUT}")
