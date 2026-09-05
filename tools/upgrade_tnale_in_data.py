# -*- coding: utf-8 -*-
"""tools/upgrade_tnale_in_data.py —— 全量升级本地分析数据与榜单的 T-NALE 时空动态拓扑属性。

此脚本基于本地完整的 K 线与分析缓存，在完全离线、不依赖外部网络的情况下，
全量计算并注入 T-NALE 物理时滞 (tau)、波峰视界 (peak_horizon) 及持有时窗等动态指标。
"""

import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.graph.sector_graph_engine import SectorGraphEngine

ANALYSIS_DIR = ROOT / "docs" / "data" / "analysis"
KLINE_DIR = ROOT / "docs" / "data" / "kline"
WATCHLIST_PATH = ROOT / "watchlist.csv"
RANKING_PATH = ANALYSIS_DIR / "ranking.json"


def main():
    print("=" * 60)
    print("开始执行 T-NALE 本地全量数据与榜单时空动态拓扑升级...")
    print("=" * 60)

    # 1. 加载 watchlist
    watchlist = []
    with open(WATCHLIST_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not r:
                continue
            code = r.get("code", "").strip()
            if code and not code.startswith("#"):
                watchlist.append({
                    "code": code,
                    "name": r.get("name", "").strip(),
                    "type": r.get("type", "stock").strip().lower(),
                    "category": r.get("category", "").strip(),
                })
    print(f"成功加载 {len(watchlist)} 只自选标的。")

    # 2. 加载 K 线
    kline_map = {}
    for w in watchlist:
        c = w["code"]
        kp = KLINE_DIR / f"{c}.json"
        if kp.exists():
            try:
                kline_map[c] = json.loads(kp.read_text(encoding="utf-8"))
            except Exception:
                pass
    print(f"成功加载 {len(kline_map)} 个本地 K 线序列。")

    # 3. 初始化并构建板块时空图谱引擎
    sector_engine = SectorGraphEngine(corr_threshold=0.40)
    sector_engine.build_graph(watchlist, kline_map, lookback_days=60)
    print(f"T-NALE 引擎图谱构建完毕，覆盖 {len(sector_engine.sector_states)} 个板块。")

    # 4. 遍历升级各标的详情 JSON
    updated_analyses = {}
    upgraded_count = 0
    for w in watchlist:
        code = w["code"]
        category = w.get("category", "")
        ap = ANALYSIS_DIR / f"{code}.json"
        if not ap.exists():
            continue

        try:
            data = json.loads(ap.read_text(encoding="utf-8"))
        except Exception:
            continue

        fc = data.get("forecast") or {}
        nale_payload = sector_engine.get_nale_network_payload(code, category, fc)
        data["nale_network"] = nale_payload

        t_dyn = (nale_payload.get("temporal_dynamics") or {}) if nale_payload else {}
        if t_dyn:
            fc["physical_lag_tau_days"] = t_dyn.get("physical_lag_tau_days")
            fc["peak_horizon_days"] = t_dyn.get("peak_horizon_days")
            fc["peak_spillover_return_pct"] = t_dyn.get("peak_spillover_return_pct")
            fc["optimal_holding_days"] = t_dyn.get("optimal_holding_days")

        if nale_payload.get("has_limit_up_resonance") and nale_payload.get("spillover_return_5d_pct", 0) > 0:
            spill_ret = nale_payload["spillover_return_5d_pct"]
            spill_prob = nale_payload.get("spillover_prob_5d_pct", 0)
            leader_info = nale_payload.get("leader_stock") or {}
            leader_name = leader_info.get("name", "龙头")
            tau = t_dyn.get("physical_lag_tau_days", 14)
            peak_ret = t_dyn.get("peak_spillover_return_pct", spill_ret)

            spill_reason = {
                "title": f"T-NALE·{nale_payload['sector_name']}时空时滞共振",
                "detail": f"同板块龙头【{leader_name}】封板催化，经产业链物理传导（时滞τ≈{int(tau)}天），注入 +{spill_ret}% 溢出预期及 +{spill_prob}% 看涨胜率（波峰前瞻+{peak_ret}%）",
                "impact": "positive",
                "score_delta": 4.5
            }
            reasons = data.get("reasons", [])
            reasons = [r for r in reasons if not (isinstance(r, dict) and ("NALE·" in r.get("title", "")))]
            reasons.insert(0, spill_reason)
            data["reasons"] = reasons

        data["forecast"] = fc
        ap.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        updated_analyses[code] = data
        upgraded_count += 1

    print(f"已全量升级 {upgraded_count} 个标的详情 JSON 文件。")

    # 5. 升级 ranking.json
    if RANKING_PATH.exists():
        ranking = json.loads(RANKING_PATH.read_text(encoding="utf-8"))
        items = ranking.get("items", [])
        for it in items:
            code = it.get("code")
            if code in updated_analyses:
                ud = updated_analyses[code]
                it["nale_network"] = ud.get("nale_network")
                it["forecast"] = ud.get("forecast")
                it["reasons"] = ud.get("reasons", it.get("reasons"))
        RANKING_PATH.write_text(json.dumps(ranking, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已同步更新 {RANKING_PATH.name} 中的 {len(items)} 项榜单标的。")

    print("T-NALE 数据升级完成！接下来运行 compare_v2_v3 生成最新双轨对比及 ranking_v3.json...")


if __name__ == "__main__":
    main()
