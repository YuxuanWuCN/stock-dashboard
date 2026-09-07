# -*- coding: utf-8 -*-
"""将 CSMAR 面板过滤到真实交易日（剔除非交易日填充行）。

CSMAR ``TRD_FwardQuotation`` 在非交易日返回填充行（``Filling=2``），
导致面板含 696 个日期（644 真实 + 52 填充）。本脚本以公开行情面板的
644 个真实交易日为日历基准，对 CSMAR 面板做交集过滤，产出与项目惯例
一致的最终因子数据集。

用法::

    python scripts/filter_csmar_panel_to_real_days.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CSMAR_PANEL = (
    PROJECT_ROOT / "data" / "task_split" / "student_b" / "csmar" / "student_b_csmar_factor_panel.parquet"
)
DEFAULT_PUBLIC_PANEL = (
    PROJECT_ROOT / "data" / "task_split" / "student_b" / "student_b_factor_panel.parquet"
)
DEFAULT_OUT = (
    PROJECT_ROOT / "data" / "task_split" / "student_b" / "csmar" / "student_b_csmar_factor_panel_filtered.parquet"
)
DEFAULT_OUT_CSV = (
    PROJECT_ROOT / "data" / "task_split" / "student_b" / "csmar" / "student_b_csmar_factor_panel_filtered.csv"
)
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "data" / "task_split" / "student_b" / "csmar" / "student_b_csmar_factor_panel_filtered_manifest.json"
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="过滤 CSMAR 面板到真实交易日")
    p.add_argument("--csmar-panel", type=Path, default=DEFAULT_CSMAR_PANEL)
    p.add_argument("--public-panel", type=Path, default=DEFAULT_PUBLIC_PANEL)
    p.add_argument("--out-parquet", type=Path, default=DEFAULT_OUT)
    p.add_argument("--out-csv", type=Path, default=DEFAULT_OUT_CSV)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args(argv)


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _display_path(path: Path) -> str:
    """在 manifest 中优先记录仓库相对路径，避免提交本机绝对路径。"""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def main(argv=None) -> int:
    args = parse_args(argv)
    csmar_path = _resolve(args.csmar_panel)
    public_path = _resolve(args.public_panel)
    out_parquet = _resolve(args.out_parquet)
    out_csv = _resolve(args.out_csv)
    manifest_path = _resolve(args.manifest)

    if not csmar_path.exists():
        print(f"CSMAR 面板不存在: {csmar_path}", file=sys.stderr)
        return 2
    if not public_path.exists():
        print(f"公开面板不存在: {public_path}", file=sys.stderr)
        return 2

    existing = [p for p in [out_parquet, out_csv, manifest_path] if p.exists()]
    if existing and not args.overwrite:
        print(
            "目标文件已存在，使用 --overwrite 覆盖: " + ", ".join(p.name for p in existing),
            file=sys.stderr,
        )
        return 2

    csmar = pd.read_parquet(csmar_path)
    public = pd.read_parquet(public_path)

    csmar["trade_date"] = pd.to_datetime(csmar["trade_date"])
    public["trade_date"] = pd.to_datetime(public["trade_date"])

    real_days = set(public["trade_date"].drop_duplicates())
    n_csmar_before = csmar["trade_date"].nunique()
    filtered = csmar[csmar["trade_date"].isin(real_days)].copy()
    n_after = filtered["trade_date"].nunique()
    n_removed = n_csmar_before - n_after

    if filtered.empty:
        print("过滤后无数据", file=sys.stderr)
        return 2

    # 排序：按股票、日期
    filtered = filtered.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)

    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_parquet(out_parquet, index=False)
    filtered.to_csv(out_csv, index=False, encoding="utf-8-sig")

    manifest = {
        "source": "filtered from CSMAR panel to real trading days",
        "csmar_panel": _display_path(csmar_path),
        "public_panel_calendar": _display_path(public_path),
        "public_panel_calendar_in_submission": False,
        "rows_before": len(csmar),
        "rows_after": len(filtered),
        "days_before": int(n_csmar_before),
        "days_after": int(n_after),
        "non_trading_fill_days_removed": int(n_removed),
        "window": {"start": str(filtered["trade_date"].min().date()), "end": str(filtered["trade_date"].max().date())},
        "factor_coverage": {c: float(filtered[c].notna().mean()) for c in filtered.columns if c not in ("stock_code", "trade_date")},
        "fabrication_check": {"synthetic_values_generated": False, "random_data_used": False},
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"CSMAR 面板过滤完成: {n_csmar_before} 天 -> {n_after} 天 (剔除 {n_removed} 个非交易日填充)")
    print(f"行数: {len(csmar)} -> {len(filtered)}")
    print(f"输出: {out_parquet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
