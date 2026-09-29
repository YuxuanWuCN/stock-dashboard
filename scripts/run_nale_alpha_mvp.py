#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/run_nale_alpha_mvp.py

NALE 十维 PCA 动态门控 —— 工程 MVP 端到端运行器（fixture 模式）。

目的
----
把 fork（SoliloquyRyan/codex/nale-alpha-week1-engineering-20260912）同步来的
NALE 动态门控脚手架，在生产几何（126 训练 / 42 验证 / 42 测试 + 6 日 purge）
下端到端跑通，产出该框架规定的全套工件与图。

证据声明（重要）
----------------
本脚本使用 **engineering_fixture** 数据，框架会将其标注为
"ENGINEERING FIXTURE - NOT MARKET EVIDENCE"，仅验证工程链路可复现，
**不构成任何市场实证结论**。真实 observed 运行需要逐日 embedding 面板与
带生效期的网络证据（当前均缺失，见 reports/.../m4-full-run-状态报告.md）。

用法
----
    python scripts/run_nale_alpha_mvp.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.analysis.nale_alpha_experiment import run_prepared_nale_experiment
from src.analysis.nale_alpha_figures import render_rank_ic_figure
from src.analysis.nale_alpha_pipeline import DataEvidence
from src.analysis.nale_alpha_walkforward import WalkForwardConfig, plan_dates
from src.graph.nale_alpha_network import make_network_snapshot

N_STOCKS = 24
N_DAYS = 240
SEED = 42
PC_COLUMNS = tuple(f"PC{i:02d}" for i in range(1, 11))
GRAPH_ID = "eng-fixture-ledger-v1"

CONFIG = WalkForwardConfig(
    train_days=126, validation_days=42, test_days=42, purge_days=6,
    ridge_v1=0.01, ridge_v2=0.01, ridge_v3=0.01, half_life_days=20.0,
)


def build_fixture():
    """构造 24 支标的 × 240 交易日、带环形供应链的工程夹具（非市场数据）。"""
    rng = np.random.default_rng(SEED)
    calendar = tuple(pd.bdate_range("2024-01-02", periods=N_DAYS).strftime("%Y-%m-%d"))
    codes = tuple(f"{600000 + i:06d}" for i in range(N_STOCKS))

    # 供应链：环形 + 少量跨环边（夹具结构，不代表真实关系）
    ledger = []
    for i in range(N_STOCKS):
        for offset in (1, 7):
            ledger.append({
                "source_code": codes[i], "target_code": codes[(i + offset) % N_STOCKS],
                "weight": 1.0,
                "source_published_at": calendar[0] + "T10:00:00+08:00",
                "available_at": calendar[0] + "T14:00:00+08:00",
                "valid_from": calendar[0], "valid_to": None,
                "evidence_id": f"eng-edge-{codes[i]}-{codes[(i + offset) % N_STOCKS]}",
                "relationship_version": "v1", "is_observed": False,
            })
    edges = pd.DataFrame(ledger)
    networks = {
        day: make_network_snapshot(
            edges, codes, day + "T15:10:00+08:00",
            graph_history_id=GRAPH_ID, allow_fixture=True,
        )
        for day in calendar
    }

    # 十维 PCA 输入：股票层面有稳定差异（保证截面可分）+ 缓慢时变
    stock_load = rng.normal(0.0, 1.0, size=(N_STOCKS, 10))
    time_trend = rng.normal(0.0, 0.02, size=(10,))
    pc_values = np.zeros((N_DAYS, N_STOCKS, 10))
    for t in range(N_DAYS):
        shock = rng.normal(0.0, 0.35, size=(N_STOCKS, 10)) * 0.15
        pc_values[t] = stock_load + time_trend * t + shock

    # 门控真值随 PC 非线性变化（给 V1–V3 留出可学习空间）
    gate_logit = (0.9 * pc_values[:, :, 0] - 0.7 * pc_values[:, :, 1]
                  + 0.4 * pc_values[:, :, 2])
    alpha_true = 0.05 + 0.70 / (1.0 + np.exp(-gate_logit))

    # S0 与邻居差 D（与 walkforward 内部的 propagate_nale 口径一致：邻居均值 - 自身）
    base = 1.2 * pc_values[:, :, 3] - 0.8 * pc_values[:, :, 4] + 0.5 * pc_values[:, :, 5]
    slope = np.zeros((N_DAYS, N_STOCKS))
    ring = [(i + 1) % N_STOCKS for i in range(N_STOCKS)]
    for i in range(N_STOCKS):
        slope[:, i] = (base[:, ring[i]] + base[:, (i + 7) % N_STOCKS]) / 2.0
    s0 = base
    difference = slope - base

    rows = []
    for t, day in enumerate(calendar):
        label_day = calendar[min(t + 6, N_DAYS - 1)]
        for i, code in enumerate(codes):
            noise = rng.normal(0.0, 0.004)
            y_excess = 0.01 + 0.4 * (s0[t, i] + alpha_true[t, i] * difference[t, i]) + noise
            row = {
                "date": day, "code": code,
                "signal_at": day + "T15:10:00+08:00",
                "label_available_at": label_day + "T18:00:00+08:00",
                "s0": float(s0[t, i]), "y_excess": float(y_excess),
                "pca_version": "eng-fixture-pca10",
                "feature_source_id": "eng-fixture-embedding",
                "network_evidence_id": GRAPH_ID,
                "price_source_id": "eng-fixture-prices",
                "evidence_class": "engineering_fixture",
                "label_horizon_days": 5,
                "alpha_true": float(alpha_true[t, i]),
            }
            for k, column in enumerate(PC_COLUMNS):
                row[column] = float(pc_values[t, i, k])
            rows.append(row)
    return pd.DataFrame(rows), networks, calendar


def main() -> int:
    run_id = datetime.now().strftime("eng-fixture-mvp-%Y%m%d-%H%M%S")
    tables_dir = REPO_ROOT / "reports" / "tables" / "nale_alpha_week1" / run_id
    figures_dir = REPO_ROOT / "reports" / "figures" / "nale_alpha_week1" / run_id
    processed_dir = REPO_ROOT / "data" / "processed" / "nale_alpha_week1" / run_id
    for path in (tables_dir, figures_dir, processed_dir):
        path.mkdir(parents=True, exist_ok=True)

    print(f"[fixture] 构造 {N_STOCKS} 支 × {N_DAYS} 交易日…")
    panel, networks, calendar = build_fixture()
    plan = plan_dates(calendar, CONFIG)
    print(f"[split] 训练 {len(plan.train_dates)} / purge {len(plan.purged_after_train)} / "
          f"验证 {len(plan.validation_dates)} / purge {len(plan.purged_after_validation)} / "
          f"测试 {len(plan.test_dates)}")

    evidence = DataEvidence(kind="fixture", audit_id="eng-fixture-mvp-20260915")
    print("[run] 走步验证选择 → 冻结 → 单次测试 …")
    result = run_prepared_nale_experiment(
        panel, networks, calendar, CONFIG,
        evidence=evidence, allow_fixture=True,
        min_valid_ic_dates=20, min_stocks=20, horizon_days=5,
        bootstrap_iterations=2000,
    )

    # ---- 工件落盘 ----
    (tables_dir / "version_comparison.csv").write_text(
        result.test_metrics.version_comparison.to_csv(index=False), encoding="utf-8-sig")
    (tables_dir / "paired_differences.csv").write_text(
        result.test_metrics.paired_differences.to_csv(index=False), encoding="utf-8-sig")
    (tables_dir / "daily_ics.csv").write_text(
        result.test_metrics.daily_ics.to_csv(index=False), encoding="utf-8-sig")
    (tables_dir / "monthly_weights.csv").write_text(
        result.pipeline.test_output.monthly_weights.to_csv(index=False), encoding="utf-8-sig")
    (tables_dir / "validation_version_comparison.csv").write_text(
        result.validation_metrics.version_comparison.to_csv(index=False), encoding="utf-8-sig")
    result.pipeline.test_output.predictions.to_parquet(
        processed_dir / "predictions_test.parquet", index=False)
    result.pipeline.validation_output.predictions.to_parquet(
        processed_dir / "predictions_validation.parquet", index=False)
    (processed_dir / "split_manifest.json").write_text(
        json.dumps(result.pipeline.test_output.date_plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8")
    (processed_dir / "run_manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "evidence_class": "engineering_fixture",
        "market_claim": False,
        "note": "工程夹具运行，仅验证链路可复现，不构成市场实证结论。",
        "empirical_status": result.pipeline.empirical_status,
        "config": {
            "train_days": CONFIG.train_days, "validation_days": CONFIG.validation_days,
            "test_days": CONFIG.test_days, "purge_days": CONFIG.purge_days,
            "bootstrap_iterations": 2000, "seed": 42, "horizon_days": 5,
        },
        "n_stocks": N_STOCKS, "n_days": N_DAYS,
        "version_status": dict(result.pipeline.version_status),
        "selection": {
            "v1_ridge": result.pipeline.selection.hyperparameters.v1_ridge,
            "v2_ridge": result.pipeline.selection.hyperparameters.v2_ridge,
            "v3_ridge": result.pipeline.selection.hyperparameters.v3_ridge,
            "v3_history_days": result.pipeline.selection.hyperparameters.v3_history_days,
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 图 ----
    # 注：metrics 模块的状态词为 evaluated/missing_version，figures 模块期望
    # available/not_evaluable，两者词表不一致（脚手架缺陷，见状态报告 §4）。
    STATUS_MAP = {"evaluated": "available", "missing_version": "not_evaluable",
                  "insufficient_valid_dates": "not_evaluable"}
    for phase, metrics in (("test", result.test_metrics),
                           ("validation", result.validation_metrics)):
        comparison = metrics.version_comparison.copy()
        comparison["phase"] = phase
        comparison["status"] = comparison["status"].map(STATUS_MAP)
        png = render_rank_ic_figure(comparison, fixture=True)
        (figures_dir / f"rank_ic_{phase}.png").write_bytes(png)

    # ---- 控制台摘要 ----
    print("\n=== 测试期版本对比（Rank IC，工程夹具）===")
    columns = [c for c in ("version", "status", "rank_ic_mean", "rank_ic_ir",
                           "n_valid_ic_dates", "direction_hit_rate")
               if c in result.test_metrics.version_comparison.columns]
    print(result.test_metrics.version_comparison[columns].to_string(index=False))
    print("\n=== 关键配对差值（V1-B0 / V2-V1 / V3-V2，Bootstrap 2000 次）===")
    paired = result.test_metrics.paired_differences
    keep = [c for c in ("comparison", "status", "n_paired_dates", "rank_ic_delta_mean",
                        "rank_ic_ci_lower", "rank_ic_ci_upper", "p_value", "holm_p")
            if c in paired.columns]
    print(paired[keep].to_string(index=False))
    print(f"\n✅ 工件目录:\n   {tables_dir}\n   {figures_dir}\n   {processed_dir}")
    print(f"   empirical_status = {result.pipeline.empirical_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
