# -*- coding: utf-8 -*-
"""从 CSMAR 行情表取得真实交易日标记（不重拉四张全量源表）。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "task_split"
    / "student_c"
    / "sources"
    / "csmar_raw"
    / "trd_fward_quotation_filling_calendar.csv"
)


def _coerce(response: object) -> pd.DataFrame:
    if isinstance(response, pd.DataFrame):
        return response.copy()
    if isinstance(response, dict):
        value = response
        for key in ("previewDatas", "rows", "data"):
            if isinstance(value, dict) and key in value:
                value = value[key]
                break
        return pd.DataFrame(value if isinstance(value, list) else [value])
    return pd.DataFrame(response)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="取得 CSMAR Filling=0 真实交易日历")
    parser.add_argument("--sdk-cwd", type=Path, required=True)
    parser.add_argument("--symbol", default="600030")
    parser.add_argument("--start-date", default="2024-01-02")
    parser.add_argument("--end-date", default="2026-08-28")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sdk_cwd = args.sdk_cwd.expanduser().resolve()
    output = args.output if args.output.is_absolute() else (PROJECT_ROOT / args.output).resolve()
    if not (sdk_cwd / "token.txt").is_file():
        raise RuntimeError(f"CSMAR SDK 工作目录缺少 token.txt: {sdk_cwd}")
    if output.exists() and not args.overwrite:
        raise RuntimeError(f"输出已存在，请使用 --overwrite: {output}")

    from csmarapi.CsmarService import CsmarService

    original_cwd = Path.cwd()
    os.chdir(sdk_cwd)
    try:
        response = CsmarService().query(
            ["Symbol", "TradingDate", "Filling"],
            f"Symbol in ('{str(args.symbol).zfill(6)}')",
            "TRD_FwardQuotation",
            args.start_date,
            args.end_date,
        )
    finally:
        os.chdir(original_cwd)

    frame = _coerce(response)
    required = {"TradingDate", "Filling"}
    if frame.empty or not required.issubset(frame.columns):
        raise RuntimeError("CSMAR Filling 日历返回为空或缺少 TradingDate/Filling")
    calendar = frame[["TradingDate", "Filling"]].copy()
    calendar["TradingDate"] = pd.to_datetime(calendar["TradingDate"], errors="coerce")
    calendar["Filling"] = calendar["Filling"].astype(str).str.strip()
    calendar = calendar.dropna(subset=["TradingDate"]).drop_duplicates().sort_values("TradingDate")
    real_days = calendar.loc[calendar["Filling"] == "0", "TradingDate"]
    if len(real_days) != 644:
        raise RuntimeError(f"CSMAR 真实交易日数量异常: {len(real_days)}，预期 644")
    calendar["TradingDate"] = calendar["TradingDate"].dt.strftime("%Y-%m-%d")
    output.parent.mkdir(parents=True, exist_ok=True)
    calendar.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"CSMAR Filling 日历已写出: {output} ({len(real_days)} real / {len(calendar)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
