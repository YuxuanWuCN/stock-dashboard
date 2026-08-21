import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis.bet_type_classifier import classify_bet_type, get_strategy_recommendation

analysis_dir = ROOT / "docs" / "data" / "analysis"
kline_dir = ROOT / "docs" / "data" / "kline"

bet_counts = {"trend": 0, "volatile": 0, "range_bound": 0}

for p in [analysis_dir / "ranking.json", analysis_dir / "ranking_v3.json"]:
    if not p.exists():
        continue
    payload = json.loads(p.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    for item in items:
        code = item["code"]
        kline_p = kline_dir / f"{code}.json"
        closes, highs, lows = [], [], []
        if kline_p.exists():
            try:
                kd = json.loads(kline_p.read_text(encoding="utf-8"))
                kline = kd.get("kline", [])
                for k in kline:
                    closes.append(float(k[1]))
                    lows.append(float(k[2]))
                    highs.append(float(k[3]))
            except Exception:
                pass
        
        btype, metrics = classify_bet_type(closes, highs, lows)
        item["bet_type"] = btype
        item["bet_type_metrics"] = metrics
        item["strategy_recommendation"] = get_strategy_recommendation(btype)
        bet_counts[btype] = bet_counts.get(btype, 0) + 1
            
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"双轨榜单赌注分类注入完成: {bet_counts}")
