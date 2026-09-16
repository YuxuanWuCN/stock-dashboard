"""从学校安装的 CSMAR SDK 下载并校验日频 Carhart 因子。

任务包给出的 ``STK_MKT_Thrfac``、字段名和查询调用只是一份待学校账号确认的
模板。本脚本不会把 SDK 缺失、认证失败或不完整响应伪装成数据文件。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.factor_providers import (  # noqa: E402
    CSMARDataError,
    CSMARFactorProvider,
    CSMARProviderError,
)


DEFAULT_FIELDS = [
    "TradingDate",
    "RiskPremium1",
    "SMB1",
    "HML1",
    "UMD1",
    "RiskFreeRate",
]
DEFAULT_TABLE = "STK_MKT_Thrfac"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "school_factors" / "csmar_carhart_4factors.csv"
_CALENDAR_COLUMN_KEYS = {
    "date",
    "tradingdate",
    "trade_date",
    "tradedate",
    "日期",
    "交易日期",
    "交易日",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载并校验 CSMAR 日频 Carhart 因子")
    parser.add_argument("--table-name", default=DEFAULT_TABLE)
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default="2026-09-01")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--min-rows",
        type=int,
        default=1500,
        help="写入前要求的最少有效日频记录数，默认对应任务包的 2020-2026 验收口径。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="允许替换已有导出文件；默认拒绝覆盖。",
    )
    parser.add_argument(
        "--trading-calendar",
        type=Path,
        default=None,
        help=(
            "已确认的交易日历文件（CSV/Parquet/Excel）。提供后会要求返回日期集合"
            "与请求窗口完全一致；不提供时只能验证结构，不能证明中间交易日完整。"
        ),
    )
    parser.add_argument(
        "--require-coverage",
        action="store_true",
        help="没有 --trading-calendar 时拒绝写出未验证覆盖的文件。",
    )
    parser.add_argument(
        "--allow-unverified-coverage",
        action="store_true",
        help="明确允许没有交易日历时写出文件（会打印 coverage_unverified 警告）。",
    )
    return parser.parse_args(argv)


def _read_trading_calendar(path: Path) -> tuple[Any, ...]:
    """读取并初步校验外部提供的交易日历，不推断节假日。"""
    calendar_path = path.expanduser().resolve()
    if not calendar_path.exists() or not calendar_path.is_file():
        raise FileNotFoundError(f"交易日历文件不存在: {calendar_path}")
    suffix = calendar_path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(calendar_path)
    elif suffix == ".parquet":
        frame = pd.read_parquet(calendar_path)
    elif suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(calendar_path)
    else:
        raise ValueError("交易日历仅支持 CSV、Parquet、XLSX 或 XLS")
    if frame.empty or frame.shape[1] == 0:
        raise CSMARDataError(f"交易日历为空: {calendar_path}")

    selected = None
    for column in frame.columns:
        key = str(column).strip().replace("-", "_").replace(" ", "").casefold()
        if key in _CALENDAR_COLUMN_KEYS:
            selected = column
            break
    if selected is None:
        if frame.shape[1] == 1:
            selected = frame.columns[0]
        else:
            raise CSMARDataError(
                "交易日历必须包含 date/TradingDate 列，或仅有一列日期"
            )

    selected_values = frame[selected]
    if selected_values.isna().any():
        raise CSMARDataError(
            f"交易日历列 {selected!r} 包含缺失日期: {calendar_path}"
        )
    values = selected_values.tolist()
    if not values:
        raise CSMARDataError(f"交易日历没有有效日期: {calendar_path}")
    parsed = []
    seen = set()
    for value in values:
        try:
            date = CSMARFactorProvider._parse_date(value, "trading_calendar")
        except (CSMARDataError, TypeError, ValueError, OverflowError) as exc:
            raise CSMARDataError(
                f"交易日历包含非法日期: {value!r} ({calendar_path})"
            ) from exc
        if date in seen:
            raise CSMARDataError(
                f"交易日历包含重复日期: {date.strftime('%Y-%m-%d')}"
            )
        seen.add(date)
        parsed.append(date)
    return tuple(parsed)


def download_factors(args: argparse.Namespace) -> int:
    """执行一次真实 SDK 查询，校验通过后原子写入标准 CSV。"""
    min_rows = int(getattr(args, "min_rows", 1500))
    if min_rows <= 0:
        raise ValueError("--min-rows 必须为正整数")
    calendar_path = getattr(args, "trading_calendar", None)
    require_coverage = bool(getattr(args, "require_coverage", False))
    allow_unverified = bool(getattr(args, "allow_unverified_coverage", False))
    if calendar_path is None and require_coverage and not allow_unverified:
        raise CSMARDataError(
            "未提供 --trading-calendar；如需结构校验后继续写出，请明确加 "
            "--allow-unverified-coverage"
        )
    if calendar_path is None:
        expected_dates = None
    elif isinstance(calendar_path, (str, Path)):
        expected_dates = _read_trading_calendar(Path(calendar_path))
    else:
        # 便于离线调用方直接注入已经读取的日期序列；CLI 仍使用文件路径。
        try:
            expected_dates = tuple(calendar_path)
        except TypeError as exc:
            raise CSMARDataError(
                "trading_calendar 必须是文件路径或日期序列"
            ) from exc
    output = Path(getattr(args, "output", DEFAULT_OUTPUT)).expanduser().resolve()
    if output.exists() and not getattr(args, "overwrite", False):
        raise FileExistsError(f"输出文件已存在，拒绝覆盖: {output}")

    try:
        from csmarapi.CsmarService import CsmarService
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "未找到 csmarapi。请在学校已安装 CSMAR SDK 且已登录的 Python 环境运行此脚本。"
        ) from exc

    # 使用任务包示例的关键字调用；Provider 会在查询前后执行连接与数据契约校验。
    provider = CSMARFactorProvider(
        service=CsmarService(),
        query_method="query",
        query_params={
            "table_name": getattr(args, "table_name", DEFAULT_TABLE),
            "fields": list(DEFAULT_FIELDS),
        },
        source="CSMAR",
        expected_trading_dates=expected_dates,
    )
    factors = provider.get_daily_factors(
        getattr(args, "start_date", "2020-01-01"),
        getattr(args, "end_date", "2026-09-01"),
    )
    if len(factors) < min_rows:
        raise CSMARDataError(
            f"有效因子记录仅 {len(factors)} 行，低于 --min-rows={min_rows}；"
            "请确认表名、字段、日期范围和账号权限。"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    try:
        factors.to_csv(temporary, index=False, encoding="utf-8")
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()

    print(f"已写入 {len(factors)} 条经过校验的 CSMAR 日频因子记录: {output}")
    print(f"时间跨度: {factors['date'].min()} 至 {factors['date'].max()}")
    if expected_dates is None:
        print(
            "警告: coverage_unverified；未提供已确认交易日历，结果不能证明请求区间内"
            "每个交易日均有记录。",
            file=sys.stderr,
        )
    else:
        print("交易日覆盖校验: 已按提供的交易日历严格核对")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return download_factors(args)
    except (CSMARProviderError, FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(f"下载失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
