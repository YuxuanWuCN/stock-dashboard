# -*- coding: utf-8 -*-
"""从已配置的 CSMAR SDK 拉取同学 C 的四张源表并构建标准因子面板。

本脚本只负责认证状态检查、CSMAR 查询和原始源表落盘；字段规范化、股票内填充、
季度 ROE 公告日锚定和最终校验继续复用 ``build_student_c_factor_panel.py``。
凭据由官方 SDK 从其工作目录的 ``token.txt`` 读取，本脚本不读取、打印或复制该文件。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import build_student_c_factor_panel as builder  # noqa: E402
from src.data.factor_panel import (  # noqa: E402
    CSMAR_FIELD_ALIASES,
    FactorPanelError,
    normalize_stock_code,
    normalize_stock_codes,
)


DEFAULT_TASK_FILE = PROJECT_ROOT / "data" / "task_split" / "student_C_finance_consumer_100.csv"
DEFAULT_START = "2024-01-02"
DEFAULT_END = "2026-08-28"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "task_split" / "student_c" / "csmar"
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "task_split" / "student_c" / "sources" / "csmar_raw"
DEFAULT_LOOKBACK_DAYS = 730
OUTPUT_STEM = "student_c_csmar_factor_panel"


class CSMARFetchError(RuntimeError):
    """CSMAR 拉取层错误基类。"""


class CSMARAuthenticationError(CSMARFetchError):
    """SDK 未认证或 token 文件不可用。"""


class CSMARQueryError(CSMARFetchError):
    """SDK 查询失败。"""


class CSMARDataError(CSMARFetchError):
    """SDK 返回空数据或不可解析的数据。"""


class CSMAROutputExistsError(CSMARFetchError):
    """目标文件已存在且未显式允许覆盖。"""


@dataclass(frozen=True)
class TableSpec:
    key: str
    table: str
    code_column: str
    columns: tuple[str, ...]
    date_column: str
    filename: str
    quarterly: bool = False


TABLE_SPECS: dict[str, TableSpec] = {
    "trade": TableSpec(
        key="trade",
        table="TRD_FwardQuotation",
        code_column="Symbol",
        columns=("Symbol", "TradingDate", "Filling", "ClosePrice", "Volume", "TurnoverRate1", "MarketValue"),
        date_column="TradingDate",
        filename="trd_fward_quotation.csv",
    ),
    "valuation": TableSpec(
        key="valuation",
        table="FI_T10",
        code_column="Stkcd",
        columns=("Stkcd", "Accper", "F100103C", "F100401A"),
        date_column="Accper",
        filename="fi_t10.csv",
    ),
    "roe": TableSpec(
        key="roe",
        table="FI_T5",
        code_column="Stkcd",
        columns=("Stkcd", "Accper", "F050504C"),
        date_column="Accper",
        filename="fi_t5.csv",
    ),
    "announce": TableSpec(
        key="announce",
        table="AIQ_AccInfoDisTimeY",
        code_column="Symbol",
        columns=("Symbol", "EndDate", "DeclareDate"),
        date_column="EndDate",
        filename="aiq_acc_info_dis_time_y.csv",
    ),
}

DERIVED_FINANCIAL_FILENAME = "stk_fin_analysis.csv"


def _field_key(value: Any) -> str:
    return "".join(str(value).strip().replace("-", "").replace("_", "").split()).casefold()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="拉取同学 C 的 CSMAR 四张源表并构建因子面板")
    parser.add_argument("--task-file", type=Path, default=DEFAULT_TASK_FILE)
    parser.add_argument("--start-date", default=DEFAULT_START)
    parser.add_argument("--end-date", default=DEFAULT_END)
    parser.add_argument(
        "--fundamental-lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="季度基本面查询额外向前保留的天数",
    )
    parser.add_argument(
        "--sdk-cwd",
        type=Path,
        default=None,
        help="官方 CSMAR SDK 工作目录，必须包含 token.txt；不会读取其内容",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def build_code_condition(codes: Sequence[Any], code_column: str = "SecuCode") -> str:
    normalized = normalize_stock_codes(codes)
    if not normalized:
        raise CSMARDataError("任务池代码为空")
    return code_column + " in (" + ",".join(f"'{code}'" for code in normalized) + ")"


def _coerce_response(response: Any, table: str) -> pd.DataFrame:
    if response is None or response is False:
        raise CSMARDataError(f"{table} 返回空结果")
    if isinstance(response, pd.DataFrame):
        frame = response.copy()
    elif isinstance(response, (list, tuple)):
        frame = pd.DataFrame(response)
    elif isinstance(response, dict):
        value: Any = response
        for key in ("previewDatas", "rows", "data"):
            if isinstance(value, dict) and key in value:
                value = value[key]
                break
        frame = pd.DataFrame(value if isinstance(value, list) else [value])
    else:
        raise CSMARDataError(f"{table} 返回类型不可解析: {type(response).__name__}")
    if frame.empty:
        raise CSMARDataError(f"{table} 返回空结果")
    return frame


def _find_code_column(frame: pd.DataFrame, table: str) -> str:
    for column in frame.columns:
        if CSMAR_FIELD_ALIASES.get(_field_key(column)) == "stock_code":
            return str(column)
    raise CSMARDataError(f"{table} 返回结果缺少证券代码列")


def _normalize_query_frame(frame: pd.DataFrame, spec: TableSpec, codes: Sequence[str]) -> pd.DataFrame:
    code_column = _find_code_column(frame, spec.table)
    out = frame.copy()
    try:
        out[code_column] = out[code_column].map(normalize_stock_code)
    except FactorPanelError as exc:
        raise CSMARDataError(f"{spec.table} 返回非法证券代码") from exc
    out = out[out[code_column].isin(set(codes))].copy()
    if out.empty:
        raise CSMARDataError(f"{spec.table} 返回结果不包含任务池标的")
    return out


def query_csmar_table(
    service: Any,
    spec: TableSpec,
    codes: Sequence[Any],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """按官方 SDK 的 ``query(columns, condition, table, start, end)`` 契约查询。"""
    normalized = normalize_stock_codes(codes)
    condition = build_code_condition(normalized, spec.code_column)
    query_method = getattr(service, "query", None)
    if not callable(query_method):
        raise CSMARQueryError("CSMAR SDK 未提供 query 方法")
    try:
        response = query_method(
            list(spec.columns),
            condition,
            spec.table,
            start_date,
            end_date,
        )
    except Exception as exc:  # noqa: BLE001 - 不把 SDK 原始异常正文写入输出
        raise CSMARQueryError(f"{spec.table} 查询失败: {type(exc).__name__}") from exc
    return _normalize_query_frame(_coerce_response(response, spec.table), spec, normalized)


def combine_financial_sources(
    roe_frame: pd.DataFrame,
    announce_frame: pd.DataFrame,
    codes: Sequence[Any],
) -> pd.DataFrame:
    """把 FI_T5 年度 ROE 与 AIQ 公告日按代码/报告期连接。

    只保留年报（12 月 31 日）且存在公告日的记录；没有公告日的 ROE 不进入
    面板，避免把 Accper 错当成市场可知日。
    """
    normalized_codes = set(normalize_stock_codes(codes))
    roe = roe_frame.copy()
    announce = announce_frame.copy()
    roe["Stkcd"] = roe["Stkcd"].map(normalize_stock_code)
    announce["Symbol"] = announce["Symbol"].map(normalize_stock_code)
    roe["Accper"] = pd.to_datetime(roe["Accper"], errors="coerce")
    announce["EndDate"] = pd.to_datetime(announce["EndDate"], errors="coerce")
    announce["DeclareDate"] = pd.to_datetime(announce["DeclareDate"], errors="coerce")
    roe = roe[
        roe["Stkcd"].isin(normalized_codes)
        & roe["Accper"].notna()
        & (roe["Accper"].dt.month == 12)
        & (roe["Accper"].dt.day == 31)
    ].copy()
    announce = announce[
        announce["Symbol"].isin(normalized_codes)
        & announce["EndDate"].notna()
        & announce["DeclareDate"].notna()
    ].copy()
    merged = pd.merge(
        roe[["Stkcd", "Accper", "F050504C"]],
        announce[["Symbol", "EndDate", "DeclareDate"]],
        left_on=["Stkcd", "Accper"],
        right_on=["Symbol", "EndDate"],
        how="inner",
    )
    if merged.empty:
        raise CSMARDataError("FI_T5 年度 ROE 与 AIQ 公告日没有可连接记录")
    return merged[["Stkcd", "Accper", "DeclareDate", "F050504C"]].rename(
        columns={"Stkcd": "Stkcd", "Accper": "Accper", "DeclareDate": "DeclareDate", "F050504C": "F050504C"}
    )


def _resolve_path(path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate).resolve()


def _check_existing_outputs(out_dir: Path, raw_dir: Path, overwrite: bool) -> None:
    expected = [
        out_dir / f"{OUTPUT_STEM}.csv",
        out_dir / f"{OUTPUT_STEM}.parquet",
        out_dir / f"{OUTPUT_STEM}_manifest.json",
        *(raw_dir / spec.filename for spec in TABLE_SPECS.values()),
        raw_dir / DERIVED_FINANCIAL_FILENAME,
    ]
    existing = [path for path in expected if path.exists()]
    if existing and not overwrite:
        raise CSMAROutputExistsError(
            "目标文件已存在；为避免覆盖，请使用 --overwrite："
            + ", ".join(path.name for path in existing)
        )


def _ensure_authenticated(service: Any) -> None:
    check = getattr(service, "getListDbs", None)
    if not callable(check):
        raise CSMARAuthenticationError("CSMAR SDK 未提供认证状态检查方法")
    try:
        databases = check()
    except Exception as exc:  # noqa: BLE001
        raise CSMARAuthenticationError(f"CSMAR 认证检查失败: {type(exc).__name__}") from exc
    if not databases:
        raise CSMARAuthenticationError("CSMAR 账号未认证或已离线")


def _default_service_factory() -> Any:
    try:
        from csmarapi.CsmarService import CsmarService
    except ImportError as exc:
        raise CSMARAuthenticationError("当前 Python 环境未安装 csmarapi") from exc
    return CsmarService()


def _write_raw_frames(raw_dir: Path, frames: dict[str, pd.DataFrame]) -> dict[str, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for key, spec in TABLE_SPECS.items():
        path = raw_dir / spec.filename
        frames[key].to_csv(path, index=False, encoding="utf-8-sig")
        paths[key] = path
    financial_path = raw_dir / DERIVED_FINANCIAL_FILENAME
    frames["financial"].to_csv(financial_path, index=False, encoding="utf-8-sig")
    paths["financial"] = financial_path
    return paths


def _augment_manifest(
    out_dir: Path,
    raw_paths: dict[str, Path],
    args: argparse.Namespace,
    codes: Sequence[str],
    fundamental_start: str,
) -> None:
    path = out_dir / f"{OUTPUT_STEM}_manifest.json"
    if not path.exists():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["sdk_fetch"] = {
        "source": "CSMAR SDK",
        "task_code_count": len(codes),
        "daily_query_window": {"start": args.start_date, "end": args.end_date},
        "financial_query_window": {"start": fundamental_start, "end": args.end_date},
        "raw_files": {key: builder._display_path(value) for key, value in raw_paths.items()},
        "authentication_value_logged": False,
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_and_build(args: argparse.Namespace, service_factory: Callable[[], Any] | None = None) -> int:
    task_file = _resolve_path(args.task_file)
    out_dir = _resolve_path(args.out_dir)
    raw_dir = _resolve_path(args.raw_dir)
    sdk_cwd = _resolve_path(args.sdk_cwd or Path.cwd())
    try:
        codes, _ = builder.read_task_codes(task_file, "code")
        if len(codes) != 100:
            raise CSMARDataError(f"任务池必须恰好 100 支，实际 {len(codes)} 支")
        if not (sdk_cwd / "token.txt").is_file():
            raise CSMARAuthenticationError(f"SDK 工作目录缺少 token.txt: {sdk_cwd}")
        _check_existing_outputs(out_dir, raw_dir, bool(args.overwrite))

        fundamental_start = (
            pd.Timestamp(args.start_date) - pd.Timedelta(days=int(args.fundamental_lookback_days))
        ).strftime("%Y-%m-%d")
        if args.dry_run:
            if not args.quiet:
                print(f"任务池={len(codes)}; 日频={args.start_date}~{args.end_date}; 财务起点={fundamental_start}")
            return 0

        original_cwd = Path.cwd()
        os.chdir(sdk_cwd)
        try:
            service = service_factory() if service_factory is not None else _default_service_factory()
            _ensure_authenticated(service)
            frames: dict[str, pd.DataFrame] = {}
            for key, spec in TABLE_SPECS.items():
                query_start = fundamental_start if key in {"roe", "announce"} else args.start_date
                frames[key] = query_csmar_table(
                    service, spec, codes, query_start, args.end_date
                )
            frames["financial"] = combine_financial_sources(frames["roe"], frames["announce"], codes)
            raw_paths = _write_raw_frames(raw_dir, frames)
        finally:
            os.chdir(original_cwd)

        builder_args: list[str] = [
            "--task-file", str(task_file),
            "--raw-file", str(raw_paths["trade"]),
            "--raw-file", str(raw_paths["valuation"]),
            "--quarterly-file", str(raw_paths["financial"]),
            "--start-date", str(args.start_date),
            "--end-date", str(args.end_date),
            "--out-dir", str(out_dir),
            "--stem", OUTPUT_STEM,
            "--max-fill-gap", "10000",
        ]
        if args.overwrite:
            builder_args.append("--overwrite")
        if args.quiet:
            builder_args.append("--quiet")
        result = builder.main(builder_args)
        if result in (0, 1):
            _augment_manifest(out_dir, raw_paths, args, codes, fundamental_start)
        return result
    except (CSMARFetchError, FactorPanelError, OSError, ValueError) as exc:
        print(f"同学 C CSMAR 数据任务失败：{exc}", file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    return fetch_and_build(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
