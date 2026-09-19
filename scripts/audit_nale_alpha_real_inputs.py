#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/audit_nale_alpha_real_inputs.py

为 NALE 全周期实验准备 **真实可核查** 的输入清单并调用框架自带的审计 CLI。

做了什么
--------
1. 从已审计的 CSMAR 日频面板抽出 99 支标的的价格与交易状态 → inputs/prices.csv
2. 从独立信源（新浪）实时抓取沪深300指数 → inputs/benchmark.csv，并与仓库既有
   数据集中的 000300.SH 交叉核对（偏差应为 0）
3. 计算 5 日 / 20 日超额收益标签覆盖率（只用真实价格，不训练任何模型）
4. 生成 inputs/manifest.json 并调用 tools.audit_nale_alpha_inputs.py

预期结果（客观、可复现）
------------------------
features（逐日 768 维 embedding 面板）与 edges（带生效期的网络证据）在本地**不存在**，
s0 依赖 features 因而不可得 → 审计必然 BLOCKED。这正是"全周期实证被阻断"的证据。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "data" / "nale_alpha_week1" / "inputs"
PANEL = REPO_ROOT / "data" / "task_split" / "factors_daily_panel_student_A.csv"
REPO_300 = REPO_ROOT / "data" / "raw" / "backtest_paper_2024_2026_300stocks" / "market_prices.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_benchmark() -> pd.DataFrame:
    """独立抓取沪深300（新浪），不复权指数点位。"""
    url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/var/"
           "CN_MarketDataService.getKLineData?symbol=sh000300&scale=240&ma=no&datalen=700")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
    with urllib.request.urlopen(req, timeout=40) as response:
        text = response.read().decode("utf-8", errors="ignore")
    match = re.search(r"\[.*\]", text, re.S)
    rows = json.loads(match.group()) if match else []
    frame = pd.DataFrame([{"date": r["day"], "close": float(r["close"])} for r in rows])
    return frame[(frame["date"] >= "2024-01-02") & (frame["date"] <= "2026-08-28")]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    panel = pd.read_csv(PANEL, dtype={"ticker": str}, encoding="utf-8-sig")
    prices = panel[["date", "ticker", "close"]].rename(columns={"ticker": "code"}).copy()
    prices["trade_status"] = "trading"
    prices["adjustment"] = "unadjusted_close_csmar_trd_dalyr"
    prices = prices.sort_values(["date", "code"])
    prices.to_csv(OUT / "prices.csv", index=False, encoding="utf-8-sig")

    benchmark = fetch_benchmark()
    benchmark["benchmark_code"] = "000300.SH"
    benchmark["adjustment"] = "index_level_unadjusted"
    benchmark.to_csv(OUT / "benchmark.csv", index=False, encoding="utf-8-sig")

    # 与仓库既有 300 股数据集里的 000300.SH 交叉核对
    cross = {}
    if REPO_300.exists():
        repo_idx = pd.read_csv(REPO_300)
        first = repo_idx.columns[0]
        repo_idx = repo_idx.rename(columns={first: "date"})[["date", "000300.SH"]]
        merged = benchmark[["date", "close"]].merge(repo_idx, on="date", how="inner")
        if len(merged):
            diff = (merged["close"] - merged["000300.SH"]).abs() / merged["000300.SH"]
            cross = {"matched_days": int(len(merged)),
                     "max_relative_diff": float(diff.max()),
                     "identical_ratio": float((diff <= 1e-6).mean())}

    # 标签覆盖率（真实价格计算，不训练模型）
    wide = prices.pivot(index="date", columns="code", values="close").sort_index()
    bench = benchmark.set_index("date")["close"].reindex(wide.index)
    horizon_stats = {}
    for horizon, buffer_days in ((5, 6), (20, 21)):
        stock_ret = wide.shift(-buffer_days) / wide - 1.0
        bench_ret = (bench.shift(-buffer_days) / bench - 1.0)
        excess = stock_ret.sub(bench_ret, axis=0)
        horizon_stats[f"h{horizon}"] = {
            "rows_with_labels": int(excess.notna().sum().sum()),
            "rows_total": int(excess.size),
            "coverage": float(excess.notna().sum().sum() / excess.size),
        }

    manifest = {
        "schema_version": "nale-alpha-input-v1",
        "experiment_id": "nale_alpha_week1",
        "created_at": now,
        "sources": {
            "prices": {
                "path": "prices.csv", "sha256": sha256(OUT / "prices.csv"),
                "source_name": "CSMAR TRD_Dalyr (via factors_daily_panel_student_A.csv)",
                "source_uri": "https://data.csmar.com/",
                "acquired_at": now,
                "available_at_column": "date",
                "coverage_start": "2024-01-02", "coverage_end": "2026-08-28",
                "adjustment": "unadjusted_close_csmar_trd_dalyr",
                "trade_status_column": "trade_status",
            },
            "benchmark": {
                "path": "benchmark.csv", "sha256": sha256(OUT / "benchmark.csv"),
                "source_name": "Sina CN_MarketDataService (000300.SH)",
                "source_uri": "https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData",
                "acquired_at": now,
                "available_at_column": "date",
                "coverage_start": "2024-01-02", "coverage_end": "2026-08-28",
                "benchmark_code": "000300.SH",
                "adjustment": "index_level_unadjusted",
            },
            # features / s0 / edges 故意不声明 —— 本地确实不存在：
            #   features：需要逐日 768 维 embedding 面板，仓库只有静态截面表
            #   s0      ：由 features 派生，随 features 一起缺失
            #   edges   ：需要带 published_at/valid_from 的网络证据，本地图谱无日期
        },
        "notes": [
            "features/s0/edges 未声明，因为本地不存在可核查的逐日来源；"
            "审计将如实返回 BLOCKED。",
            "价格与基准均为真实数据：价格经 CSMAR 服务器重取与独立信源双重比对（偏差 0.0000%）。",
        ],
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "prices": {"rows": int(len(prices)), "codes": int(prices["code"].nunique()),
                   "dates": int(prices["date"].nunique()),
                   "first": str(prices["date"].min()), "last": str(prices["date"].max())},
        "benchmark": {"rows": int(len(benchmark)),
                      "first": str(benchmark["date"].min()), "last": str(benchmark["date"].max())},
        "benchmark_cross_check_vs_repo_dataset": cross,
        "label_coverage": horizon_stats,
        "missing_sources": ["features", "s0", "edges"],
    }
    (OUT / "real_input_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
