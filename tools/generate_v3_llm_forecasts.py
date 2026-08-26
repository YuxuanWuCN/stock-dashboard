# -*- coding: utf-8 -*-
"""tools/generate_v3_llm_forecasts.py —— 并发批量生成全池股票的 v3 版本直接 LLM 预测"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.llm.llm_forecaster import LLMForecaster

def process_single_stock(fpath_str: str, forecaster: LLMForecaster) -> tuple[str, dict]:
    fpath = Path(fpath_str)
    try:
        with open(fpath, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        code = data.get("code")
        name = data.get("name", code)
        category = data.get("category", "通用")

        latest = data.get("technical", {})
        kline_p = Path(f"docs/data/kline/{code}.json")
        if kline_p.exists():
            try:
                with open(kline_p, "r", encoding="utf-8") as kfp:
                    kdata = json.load(kfp)
                kline = kdata.get("kline", [])
                if len(kline) >= 2:
                    close = kline[-1][1]
                    prev_close = kline[-2][1]
                    chg = (close - prev_close) / prev_close * 100 if prev_close else 0.0
                    latest["close"] = close
                    latest["change_pct"] = chg
            except Exception:
                pass

        scores = data.get("scores", {})
        leading = data.get("leading", {})
        similarity = data.get("similarity", {})

        item = {"code": code, "name": name, "category": category}
        # 生成直接 LLM 预测
        forecast = forecaster.forecast_single(
            item=item,
            latest=latest,
            scores=scores,
            leading=leading,
            fallback_knn=similarity,
        )

        data["forecast"] = forecast
        with open(fpath, "w", encoding="utf-8") as out_fp:
            json.dump(data, out_fp, ensure_ascii=False, indent=2)

        return code, forecast
    except Exception as exc:
        print(f"Error forecasting {fpath.name}: {exc}")
        return "", {}

def main():
    analysis_files = sorted(list(Path("docs/data/analysis").glob("*.json")))
    analysis_files = [str(f) for f in analysis_files if f.name not in ("ranking.json", "ranking_v3.json")]
    
    print(f"============================================================")
    print(f"🌟 启动 v3 版本直接 LLM 量化预测批量生成 (共 {len(analysis_files)} 支标的)")
    print(f"大模型后端: Google Gemini 3.7 Flash")
    print(f"============================================================")

    forecaster = LLMForecaster()
    forecasts_map = {}

    # 使用线程池并发调用 Gemini 3.7 Flash
    workers = 8
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_single_stock, f, forecaster): f for f in analysis_files}
        completed = 0
        for fut in as_completed(futures):
            code, fc = fut.result()
            if code and fc:
                forecasts_map[code] = fc
            completed += 1
            if completed % 20 == 0 or completed == len(analysis_files):
                print(f"[{completed}/{len(analysis_files)}] 已生成预测 ({completed*100/len(analysis_files):.1f}%)")

    print(f"✅ 全量 {len(forecasts_map)} 支股票直接 LLM 预测生成完毕！")

    # 同步更新 ranking.json 与 ranking_v3.json
    for rpath in ["docs/data/analysis/ranking.json", "docs/data/analysis/ranking_v3.json"]:
        rp = Path(rpath)
        if rp.exists():
            try:
                with open(rp, "r", encoding="utf-8") as rfp:
                    rdata = json.load(rfp)
                items = rdata.get("items", [])
                for it in items:
                    c = it.get("code")
                    if c in forecasts_map:
                        it["forecast"] = forecasts_map[c]
                with open(rp, "w", encoding="utf-8") as rfp:
                    json.dump(rdata, rfp, ensure_ascii=False, indent=2)
                print(f"✅ 同步更新至: {rpath}")
            except Exception as e:
                print(f"Error syncing {rpath}: {e}")

if __name__ == "__main__":
    main()
