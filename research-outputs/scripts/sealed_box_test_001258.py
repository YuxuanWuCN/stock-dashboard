# -*- coding: utf-8 -*-
"""立新能源(001258) 封箱历史回归检验 v2 —— 修复 LLM 接口后全流程复跑"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\股票分析项目\2.0版")
sys.path.insert(0, str(ROOT))

import pandas as pd
from src.analysis import fama_macbeth, alpha_gate, factor_db
from src.analysis.leading_indicators import LeadingIndicatorEngine
from src.llm.leading_indicator_tracker import LeadingIndicatorTracker

CODE = "001258"
NAME = "立新能源"
ANALYSIS_DATE = "2026-08-14"

report = {
    "title": "立新能源(001258) 封箱历史回归检验 v2",
    "stock": {"code": CODE, "name": NAME},
    "analysis_date": ANALYSIS_DATE,
    "pipeline": "kline -> factor_align -> fama_macbeth -> alpha_gate -> leading_indicators -> source_tracker",
    "config_note": "回归 min_obs_days=60 为本次封箱测试配置（生产默认 250）；其余均为生产默认参数",
}

# ---------- 1. K 线 ----------
kline_df = fama_macbeth._load_kline_json(CODE)
report["kline"] = {
    "rows": len(kline_df),
    "start": str(kline_df["date"].iloc[0]),
    "end": str(kline_df["date"].iloc[-1]),
    "last_close": float(kline_df["close"].iloc[-1]),
    "period_return_pct": round((kline_df["close"].iloc[-1] / kline_df["close"].iloc[0] - 1) * 100, 2),
}
print(f"[1/6] K线: {len(kline_df)} 根, 区间累计涨幅 {report['kline']['period_return_pct']}%")

# ---------- 2. 因子对齐 ----------
factors_df, quality = factor_db.validate_factors_csv(ROOT / "docs" / "data" / "factors" / "fixture_factors.csv")
aligned_f, aligned_k, dropped = factor_db.align_with_kline(factors_df, kline_df)
rets = pd.Series(aligned_k["close"].to_numpy(dtype=float)).pct_change(fill_method=None)
report["factor"] = {
    "factor_rows": len(factors_df),
    "factor_range": [quality.get("start"), quality.get("end")],
    "aligned_rows": len(aligned_f),
    "dropped_kline_dates": dropped["dropped_kline_dates"],
}
print(f"[2/6] 因子对齐: {len(aligned_f)} 交易日 (K线掉 {len(dropped['dropped_kline_dates'])} 天)")

# ---------- 3. Fama-MacBeth ----------
reg = fama_macbeth.regress_one(aligned_f, rets.to_numpy(dtype=float),
                               analysis_date=ANALYSIS_DATE, min_obs_days=60)
report["regression"] = {
    "status": reg.get("status"), "alpha": reg.get("alpha"),
    "alpha_p_value": reg.get("alpha_p_value"),
    "information_ratio": reg.get("information_ratio"),
    "betas": reg.get("betas"), "vif": reg.get("vif"),
    "n_obs": reg.get("n_obs"),
    "window": [reg.get("window_start"), reg.get("window_end")],
    "reason": reg.get("reason"),
}
if reg.get("status") == "ok":
    b = reg["betas"]
    print(f"[3/6] 回归 OK: alpha={reg['alpha']:.4f} (p={reg['alpha_p_value']:.4f}), IR={reg['information_ratio']:.3f}")
    print(f"      betas={ {k: round(v, 3) for k, v in b.items()} }, VIF={ {k: round(v, 2) for k, v in (reg.get('vif') or {}).items()} }")
else:
    print(f"[3/6] 回归: {reg.get('status')} - {reg.get('reason')}")

# ---------- 4. Alpha 门控 ----------
gate = alpha_gate.evaluate_gate(reg)
report["alpha_gate"] = gate
print(f"[4/6] Alpha 门控: {gate['verdict']} (reason={gate.get('reject_reason')})")

# ---------- 5. 领先指标 ----------
engine = LeadingIndicatorEngine()
category = engine.match_industry_category("新能源电力")
signal = engine.generate_synthetic_leading_signal(category, historical_trend=kline_df["close"].tolist())
m = signal["momentum_metrics"]
report["leading_indicator"] = {
    "category": category, "industry_name": signal["industry_name"],
    "momentum_metrics": m,
}
print(f"[5/6] 领先指标({signal['industry_name']}): 斜率={m['slope_pct']}%, 动量={m['momentum']}, 拐点={m['inflection_flag']}")

# ---------- 6. 源头追踪 ----------
tracker = LeadingIndicatorTracker()
track_result = tracker.analyze_source_signals(
    stock_code=CODE, stock_name=NAME, industry="新能源电力",
    news_list=[
        {"title": "公司披露7月发电量数据同比高增", "source": "公司公告", "date": "2026-08-10"},
        {"title": "光伏新增装机持续超预期", "source": "行业资讯", "date": "2026-08-12"},
    ],
    custom_series=kline_df["close"].tolist()[-120:],
)
report["source_tracker"] = track_result
print(f"[6/6] 源头追踪: fallback={track_result.get('fallback', False)}, "
      f"节点={track_result.get('process_node')}, 阶段={track_result.get('inference_conclusion', {}).get('stage')}")

# ---------- 汇总 ----------
print("\n" + "=" * 60)
print("封箱检验结论:")
print(f"  Alpha 门控: {'✅ PASS' if gate['verdict'] == 'pass' else '❌ REJECT (' + str(gate.get('reject_reason')) + ')'}")
print(f"  领先指标: {m['momentum']} / 拐点 {m['inflection_flag']} / 斜率 {m['slope_pct']}%")
print(f"  源头追踪: {'降级模式(LLM不可用)' if track_result.get('fallback') else 'LLM 模式'}")

out_path = ROOT / f"{CODE}_封箱回归检验_v2.json"
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
print(f"\n[输出] 检验报告: {out_path}")
