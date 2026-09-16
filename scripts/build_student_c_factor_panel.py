# -*- coding: utf-8 -*-
"""scripts/build_student_c_factor_panel.py —— 构建同学 C（金融与消费医药组）100 只标的标准因子面板

任务池为大金融 + 白酒食品与医药生物共 100 只标的，窗口 2024-01-02 ~ 2026-08-28。
与 ``build_student_a_factor_panel.py`` 完全同构：共用 ``src/data/factor_panel.py`` 数据层，
保持同样的参数、退出码语义与输出契约，只替换默认任务池、输出目录与组别标识。

三条硬约束（与 AGENTS.md、data/school_factors/README.md、src/data/factor_panel.py 一致）：

1. **证券代码一律 6 位字符串**，保留前导 0（本组含 000591 太阳能、001258 立新能源等
   深市标的，前导 0 丢失即等同错配标的）。
2. **缺失值只在单只标的内部填充**，填充全部按 ``groupby("stock_code")`` 执行，
   绝不跨标的借值；``--max-fill-gap`` 可限制最长连续填充天数。
3. **绝不生成合成数据**：源文件缺失的字段保持 NaN，并如实写入 manifest 的
   ``field_gaps`` / ``gaps``。本脚本不读取 ``data/raw/`` 下任何回测产物
   （那些是上游随机生成的模拟价格，不得充作真实行情）。

需要从 CSMAR 导出的表（学校账号在机房 Python 环境导出 CSV/Parquet，本脚本零配置热加载）：

  日频行情   TRD_FwardQuotation  Symbol, TradingDate, ClosePrice, Volume, TurnoverRate1, MarketValue
  日频估值   FI_T10              Stkcd, Accper, F100103C, F100401A
  年度 ROE   FI_T5               Stkcd, Accper, F050504C
  公告日期   AIQ_AccInfoDisTimeY  Symbol, EndDate, DeclareDate

用法示例：

    python scripts/build_student_c_factor_panel.py \
        --raw-file data/school_factors/csmar_trade_dayadj.csv \
        --raw-file data/school_factors/csmar_pe_adj.csv \
        --raw-file data/school_factors/csmar_capitals.csv \
        --quarterly-file data/school_factors/csmar_fin_analysis.csv \
        --trade-calendar data/school_factors/cn_trading_calendar.csv \
        --overwrite

退出码：0 = 写出且必需字段满覆盖；1 = 已写出但存在覆盖缺口；2 = 数据不可用
或未提供源文件（此时不写任何输出）。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.factor_panel import (  # noqa: E402
    FACTOR_COLUMNS,
    STANDARD_COLUMNS,
    CoverageError,
    FactorPanelError,
    SourceReadError,
    SourceSchemaError,
    anchor_quarterly_to_daily,
    build_panel,
    ingest_long_source,
    ingest_quarterly_source,
    melt_wide_price_matrix,
    normalize_stock_codes,
    read_source,
    validate_panel,
    write_panel,
)

DEFAULT_TASK_FILE = PROJECT_ROOT / "data" / "task_split" / "student_C_finance_consumer_100.csv"
DEFAULT_START = "2024-01-02"
DEFAULT_END = "2026-08-28"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "task_split" / "student_c"
DEFAULT_STEM = "student_c_factor_panel"
REQUIRED_COLUMNS = list(FACTOR_COLUMNS)

#: 组别标识，写入 manifest 便于三方结果比对与追溯。
STUDENT_GROUP = "同学 C（大金融与消费医药组）"

CSMAR_TABLE_GUIDE = """
需要从 CSMAR 导出的表（确认后在机房 Python 环境导出 CSV/Parquet，
支持多个文件，字段名会自动按中英文别名对齐）：

  日频行情   TRD_FwardQuotation  Symbol, TradingDate, ClosePrice, Volume, TurnoverRate1, MarketValue
  日频估值   FI_T10              Stkcd, Accper, F100103C, F100401A
  年度 ROE   FI_T5               Stkcd, Accper, F050504C
  公告日期   AIQ_AccInfoDisTimeY  Symbol, EndDate, DeclareDate

本脚本只读取学校账号导出的原始文件，不做任何网络请求，也不生成合成数据。
"""

#: 明确禁止读取的合成数据目录（上游随机生成的回测产物，非真实行情）。
FORBIDDEN_SYNTHETIC_PATHS = (
    PROJECT_ROOT / "data" / "raw" / "backtest_paper_2024_2026_300stocks",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="构建同学 C（大金融与消费医药组）100 只标的标准因子面板",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=CSMAR_TABLE_GUIDE,
    )
    parser.add_argument("--task-file", type=Path, default=DEFAULT_TASK_FILE,
                        help="任务池标的清单 CSV（含 code 列）")
    parser.add_argument("--raw-file", type=Path, action="append", default=[],
                        help="CSMAR 长表导出（一行=一只标的×一个日期），可重复指定多个")
    parser.add_argument("--wide-price", type=Path, default=None,
                        help="宽表收盘价矩阵（行=日期、列=证券代码），仅产出 close 列")
    parser.add_argument("--quarterly-file", type=Path, default=None,
                        help="季度基本面导出（含公告日列），用于把 ROE 等季度指标锚定到日频")
    parser.add_argument("--start-date", default=DEFAULT_START, help="窗口起始日（含）")
    parser.add_argument("--end-date", default=DEFAULT_END, help="窗口结束日（含）")
    parser.add_argument("--trade-calendar", type=Path, default=None,
                        help="交易日历文件（一行一个日期）；提供后可判定窗口内交易日是否完整")
    parser.add_argument("--fill", default="close,volume,turnover_rate,market_value,pe_ttm,pb",
                        help="需要股票内填充的因子列，逗号分隔")
    parser.add_argument("--fill-method", default="ffill", choices=("ffill", "bfill", "both"),
                        help="填充方向：前向/后向/先前向后向")
    parser.add_argument("--max-fill-gap", type=int, default=10,
                        help="单只标的内最多连续填充的交易日数，超出保留空值")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="输出目录")
    parser.add_argument("--stem", default=DEFAULT_STEM, help="输出文件名前缀")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有输出文件")
    parser.add_argument("--require-complete", action="store_true",
                        help="任一必需字段非满覆盖即以退出码 1 结束（默认也写文件）")
    parser.add_argument("--quiet", action="store_true", help="只输出错误与最终结论")
    return parser.parse_args(argv)


def _display_path(path: Path) -> str:
    """仓库内显示相对路径，仓库外显示绝对路径。

    早前直接用 ``relative_to(PROJECT_ROOT)``，当 ``--out-dir`` 指向仓库外时
    会在成功写盘后抛 ValueError，被兜底 except 捕获并误报退出码 2。
    """
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(msg, flush=True)


def _iter_raw_paths(paths: Sequence[Path]) -> list[Path]:
    """把目录参数展开为其中的数据文件列表（按名称排序，保证可复现）。"""
    resolved: list[Path] = []
    for path in paths:
        if path.is_dir():
            resolved.extend(sorted(
                p for p in path.iterdir()
                if p.suffix.lower() in {".csv", ".parquet", ".xlsx", ".xls"}
            ))
        else:
            resolved.append(path)
    return resolved


def _column_key(name: object) -> str:
    """归一化列名：剥离 BOM/空白并转小写。"""
    return str(name).replace("\ufeff", "").strip().casefold()


def read_task_codes(task_file: Path, task_column: str) -> tuple[list[str], pd.DataFrame]:
    """读取任务池并返回规范化后的 6 位代码列表与原始清单。"""
    frame = read_source(task_file, source_label="task_universe")
    matches = [
        c for c in frame.columns
        if _column_key(c) in {task_column, "code", "stock_code", "secucode", "证券代码"}
    ]
    if not matches:
        raise SourceSchemaError(
            f"任务池文件缺少 {task_column!r} 列，实际列：{list(frame.columns)}"
        )
    codes = normalize_stock_codes(frame[matches[0]])
    if len(codes) != len(frame):
        raise SourceSchemaError(
            f"任务池存在重复代码：{len(frame)} 行 -> {len(codes)} 个唯一代码"
        )
    return codes, frame


def _guard_against_synthetic(path: Path, label: str) -> None:
    """拒绝把上游合成数据当真实行情喂入，避免污染因子面板的数据血统。"""
    target = path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    for forbidden in FORBIDDEN_SYNTHETIC_PATHS:
        try:
            target.relative_to(forbidden.resolve())
            raise SourceSchemaError(
                f"{label} 指向上游回测产物 {path}，该文件由随机数生成、非真实行情；"
                "请改用 CSMAR 导出（--raw-file）或真实行情宽表（--wide-price）"
            )
        except ValueError:
            continue


def read_wide_price(path: Path) -> pd.DataFrame:
    """读取宽表收盘价矩阵：第一列为日期索引，其余列为证券代码。

    直接 ``pd.read_csv`` 会把索引读成名为 ``Unnamed: 0`` 的普通列，那样
    ``melt_wide_price_matrix`` 会把 ``Unnamed: 0`` 当证券代码处理并报错。
    """
    _guard_against_synthetic(path, "--wide-price")
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        frame = pd.read_excel(path, index_col=0, dtype=str)
    else:
        frame = pd.read_csv(path, index_col=0, dtype=str, keep_default_na=False)
    # 丢掉任何不是证券代码的列（索引残留、Unnamed、说明列）
    keep = [c for c in frame.columns if not str(c).startswith("Unnamed")]
    frame = frame[keep]
    if frame.columns.empty:
        raise SourceSchemaError(f"宽表 {path.name} 没有证券代码列")
    return frame


def load_sources(args: argparse.Namespace) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """加载全部源文件，返回 {标签: 标准长表} 与已提供字段清单。"""
    sources: dict[str, pd.DataFrame] = {}
    if args.wide_price is not None:
        wide = melt_wide_price_matrix(
            read_wide_price(args.wide_price), source_label=str(args.wide_price)
        )
        sources[f"wide_price:{args.wide_price.name}"] = wide

    for raw_path in _iter_raw_paths(args.raw_file):
        _guard_against_synthetic(raw_path, "--raw-file")
        source = ingest_long_source(read_source(raw_path), source_label=raw_path.name)
        sources[raw_path.name] = source
    provided = [c for frame in sources.values() for c in FACTOR_COLUMNS if c in frame.columns]
    return sources, provided


def load_trade_calendar(path: Path | None) -> pd.Index | None:
    if path is None:
        return None
    frame = read_source(path, source_label="trade_calendar")
    candidate = frame.columns[0]
    dates = pd.to_datetime(frame[candidate], errors="coerce")
    if dates.isna().any():
        raise SourceReadError("交易日历含无法解析的日期")
    return pd.DatetimeIndex(sorted(dates.dropna().unique()))


def _has_announce_column(path: Path) -> bool:
    from src.data.factor_panel import REPORT_ANCHOR_ALIASES, _field_key

    frame = read_source(path, source_label=path.name)
    return any(
        REPORT_ANCHOR_ALIASES.get(_field_key(c)) == "announce_date" for c in frame.columns
    )


def _summarize_gaps(report: dict) -> list[str]:
    """把校验报告压成人类可读的缺口清单。"""
    gaps: list[str] = []
    for column, info in report["factor_completeness"].items():
        if info is None:
            gaps.append(f"{column}: 字段不存在")
        elif info["coverage"] < 1.0:
            gaps.append(f"{column}: 覆盖 {info['coverage']:.2%}")
        elif info["null"] > 0:
            gaps.append(f"{column}: 仍有 {info['null']} 个空值")
    if report["missing_stocks"]:
        gaps.append(f"缺失标的 {len(report['missing_stocks'])} 只")
    if report.get("duplicate_stock_date_rows"):
        gaps.append(f"重复 证券代码×日期 行 {report['duplicate_stock_date_rows']} 行")
    if not report.get("code_all_6_digit_strings"):
        gaps.append("存在非 6 位字符串证券代码")
    return gaps


def _build_manifest(
    args: argparse.Namespace,
    codes: list[str],
    sources: dict[str, pd.DataFrame],
    fill_stats: dict[str, dict[str, int]],
    report: dict,
    gaps: list[str],
) -> dict:
    """构造数据血统清单：来源、窗口、填充政策、覆盖缺口与反伪造声明。"""
    filled_total = {
        column: sum(v.get(column, 0) for v in fill_stats.values())
        for column in FACTOR_COLUMNS
    }
    return {
        "schema_version": 1,
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "student_group": STUDENT_GROUP,
        "task_file": str(args.task_file.relative_to(PROJECT_ROOT) if args.task_file.is_relative_to(PROJECT_ROOT) else args.task_file).replace("\\", "/"),
        "codes": codes,
        "n_stocks": len(codes),
        "window": {"start": args.start_date, "end": args.end_date},
        "sources": sorted(sources.keys()),
        "source_provenance": {
            "source": "CSMAR SDK raw exports",
            "raw_source_contract": "TRD_FwardQuotation/FI_T10/FI_T5/AIQ_AccInfoDisTimeY",
            "synthetic_source_used": False,
        },
        "columns": list(STANDARD_COLUMNS),
        "code_contract": "6 位字符串，保留前导 0",
        "fill_policy": {
            "scope": "仅单只标的内部（groupby stock_code）",
            "cross_stock_fill": False,
            "method": args.fill_method,
            "max_consecutive_gap": args.max_fill_gap,
            "filled_per_column": {k: int(v) for k, v in filled_total.items()},
            "filled_per_stock": {k: v for k, v in fill_stats.items()},
        },
        "factor_completeness": report["factor_completeness"],
        "factor_ranges": report["factor_ranges"],
        "duplicate_stock_date_rows": report["duplicate_stock_date_rows"],
        "missing_stocks": report["missing_stocks"],
        "calendar_check": report["date_gaps_inside_window"],
        "field_gaps": {
            column: {
                "rows": report["n_rows"],
                "non_null": (report["factor_completeness"].get(column) or {}).get("non_null", 0),
                "null": (report["factor_completeness"].get(column) or {}).get("null", 0),
                "coverage": round(
                    (report["factor_completeness"].get(column) or {}).get("coverage", 0.0), 6
                ),
            }
            for column in FACTOR_COLUMNS
            if report["factor_completeness"].get(column)
        },
        "coverage_status": "complete" if not gaps else "incomplete",
        "gaps": gaps,
        "fabrication_check": {
            "synthetic_values_generated": False,
            "random_data_used": False,
            "constant_fallback_used": False,
            "synthetic_backtest_artifacts_ingested": False,
            "note": "源文件缺失的字段一律保持空值，见 gaps 字段；"
                    "data/raw/backtest_* 下的回测产物被显式拒绝作为输入",
        },
        "csmar_tables_to_export": [
            "TRD_FwardQuotation (Symbol, TradingDate, ClosePrice, Volume, TurnoverRate1, MarketValue)",
            "FI_T10 (Stkcd, Accper, F100103C, F100401A)",
            "FI_T5 (Stkcd, Accper, F050504C)",
            "AIQ_AccInfoDisTimeY (Symbol, EndDate, DeclareDate)",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    manifest: dict | None = None
    try:
        codes, _task_universe = read_task_codes(args.task_file, task_column="code")
        log(f"[1/5] 任务池：{len(codes)} 只标的（6 位字符串，前导 0 已保留）", args.quiet)

        sources, provided = load_sources(args)
        if not sources:
            print(
                "未提供 CSMAR 源文件，无法构建面板。\n"
                + CSMAR_TABLE_GUIDE
                + "\n本脚本不会用随机数或常数伪造数据。请先由学校账号导出原始文件，"
                "再用 --raw-file（可多次）或 --wide-price 传入；"
                "公开行情过渡源可用项目已有真实行情采集器拉取。\n"
            )
            return 2
        provided = sorted(dict.fromkeys(provided))
        log(f"[2/5] 源文件：{len(sources)} 个，已提供字段 {provided}", args.quiet)

        calendar = load_trade_calendar(args.trade_calendar)
        fill_columns = [c.strip() for c in args.fill.split(",") if c.strip() and c.strip() in FACTOR_COLUMNS]
        unknown_fill = [c.strip() for c in args.fill.split(",") if c.strip() and c.strip() not in FACTOR_COLUMNS]
        if unknown_fill:
            raise SourceSchemaError(f"--fill 含未知因子列：{unknown_fill}")

        panel, fill_stats = build_panel(
            task_codes=codes,
            long_sources=sources,
            start_date=args.start_date,
            end_date=args.end_date,
            trade_calendar=calendar,
            fill_columns=fill_columns,
            fill_method=args.fill_method,
            max_gap=args.max_fill_gap,
            require_columns=REQUIRED_COLUMNS if args.require_complete else [],
        )
        log(f"[3/5] 面板构建完成：{len(panel)} 行 × {panel['stock_code'].nunique()} 只标的", args.quiet)

        # 季度基本面锚定：只有用户显式传入季度文件时才执行
        if args.quarterly_file is not None:
            quarterly = ingest_quarterly_source(
                read_source(args.quarterly_file), source_label=args.quarterly_file.name
            )
            if _has_announce_column(args.quarterly_file):
                panel = anchor_quarterly_to_daily(
                    panel, quarterly, "roe", "announce_date", args.quarterly_file.name
                )
            else:
                raise SourceSchemaError(
                    f"{args.quarterly_file.name} 未包含公告日列，无法执行无未来信息锚定；"
                    "请从 CSMAR 导出 AnnounceModifyDate 字段"
                )
            sources[args.quarterly_file.name] = quarterly

        report = validate_panel(panel, codes, args.start_date, args.end_date, expected_dates=calendar)
        log(
            f"[4/5] 校验：日期 {report['start_date']} ~ {report['end_date']}，"
            f"交易日 {report['n_trading_dates']} 个，"
            f"代码全为 6 位字符串={report['code_all_6_digit_strings']}",
            args.quiet,
        )

        gaps = _summarize_gaps(report)
        manifest = _build_manifest(args, codes, sources, fill_stats, report, gaps)
        if manifest["coverage_status"] != "complete":
            print("\n以下字段未达满覆盖（保持空值，未做任何跨股票填充或估算）：")
            for column, info in manifest["field_gaps"].items():
                print(
                    f"  - {column}: 非空 {info['non_null']}/{info['rows']} "
                    f"({info['coverage']:.1%})，缺失 {info['null']}"
                )
            print("\n补齐方式：见 python scripts/build_student_c_factor_panel.py --help 中的 CSMAR 表清单；"
                  "或把学校导出的原始文件加入 --raw-file 后重跑本脚本。")

        out_dir = args.out_dir if args.out_dir.is_absolute() else PROJECT_ROOT / args.out_dir
        existing = [p for p in out_dir.glob(f"{args.stem}*") if p.exists()]
        if existing and not args.overwrite:
            print(
                f"\n输出目录已有同名文件，拒绝覆盖（加 --overwrite 允许）："
                f"{[p.name for p in existing]}"
            )
            return 2
        csv_path, parquet_path, manifest_path = write_panel(panel, out_dir, args.stem, manifest)
        log(
            f"[5/5] 已写出：\n    {_display_path(csv_path)}\n"
            f"    {_display_path(parquet_path)}\n"
            f"    {_display_path(manifest_path)}",
            args.quiet,
        )
    except (FactorPanelError, SourceReadError, SourceSchemaError, CoverageError) as exc:
        print(f"数据层错误：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"未预期错误：{exc}", file=sys.stderr)
        return 2

    return 0 if manifest["coverage_status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
