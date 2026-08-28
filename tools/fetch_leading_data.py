"""tools/fetch_leading_data.py —— 本地批量抓取领先指标数据（005 融合）。

在能联网的本地电脑运行，按 INDUSTRY_LEADING_MAP 四类领先映射抓取真实数据，
写入 docs/data/leading_signals/{category}.json。沙箱/离线环境自动降级合成。

用法：
    python tools/fetch_leading_data.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis.leading_indicators import INDUSTRY_LEADING_MAP, LeadingIndicatorEngine


def main() -> int:
    engine = LeadingIndicatorEngine()
    out_dir = ROOT / "docs" / "data" / "leading_signals"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for category in INDUSTRY_LEADING_MAP:
        sig = engine.fetch_real_leading_signal(category)
        results[category] = sig
        out_path = out_dir / f"{category}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(sig, f, ensure_ascii=False, indent=2)
        mm = sig.get("momentum_metrics", {})
        print(
            f"[{category}] source={sig.get('data_source')} "
            f"inflection={mm.get('inflection_flag')} slope={mm.get('slope_pct')}% "
            f"-> {out_path.name}"
        )

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "categories": {
            c: {
                "data_source": s.get("data_source"),
                "inflection_flag": s.get("momentum_metrics", {}).get("inflection_flag"),
            }
            for c, s in results.items()
        },
    }
    with open(out_dir / "_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\n汇总已写入 _summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
