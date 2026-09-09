# -*- coding: utf-8 -*-
"""src/data/factor_panel.py —— 300 支 A 股全池标准因子面板数据层（同学 A / B / C 共用）

契约（对齐 AGENTS.md「数据与测试」与 data/school_factors/README.md 的 CSMAR 规范）：

1. 股票代码一律是 **6 位字符串**（保留前导 0，如 ``"002594"``）。任何整数、
   去零字符串、带交易所后缀的证券代码在入口即被规范化或拒绝。
2. 缺失值 **只在单只股票内部** 前向/后向填充。填充全部按
   ``groupby("stock_code")`` 分组执行，绝不跨股票借值；跨股票填充没有入口。
3. **不生成合成数据**：源文件缺失的字段保持 ``NaN``，并写入覆盖报告。本模块
   没有任何随机数、常数兜底或估算分支。
4. 基本面季度指标（如 ROE）按 ``stock_code`` 做 ``merge_asof`` 向后锚定到
   日频交易日历，无未来信息泄漏。
5. 输入/输出列名、字段别名、校验口径全部集中在本文件，便于单元测试直接断言。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger("factor_panel")

#: 标准输出列顺序（写入 CSV / Parquet 的字段契约）。
STANDARD_COLUMNS: tuple[str, ...] = (
    "stock_code",
    "trade_date",
    "close",
    "volume",
    "turnover_rate",
    "market_value",
    "pe_ttm",
    "pb",
    "roe",
)

#: 数值型因子列（填充与校验的对象）。
FACTOR_COLUMNS: tuple[str, ...] = tuple(
    column for column in STANDARD_COLUMNS if column not in ("stock_code", "trade_date")
)

def _field_key(value: Any) -> str:
    """归一化字段名：去空白/连字符/下划线差异并转小写。

    ``PE_TTM``、``PE-TTM``、``PE TTM``、``pe ttm`` 必须得到同一个键，
    否则 CSMAR 中英文导出与仓库自有列名无法对齐。
    """
    return "".join(
        str(value).strip().replace("-", "").replace("_", "").split()
    ).casefold()


#: CSMAR 常用字段别名 -> 标准列名。键已按 _field_key() 归一化。
CSMAR_FIELD_ALIASES: dict[str, str] = {
    # 证券代码
    "code": "stock_code",
    "stockcode": "stock_code",
    "securitycode": "stock_code",
    "secucode": "stock_code",
    "securcode": "stock_code",
    "secucd": "stock_code",
    "symbol": "stock_code",
    "stkcd": "stock_code",
    "stkcode": "stock_code",
    "stkcode_1": "stock_code",
    "sinfocode": "stock_code",
    "证券代码": "stock_code",
    "股票代码": "stock_code",
    "证券代码前6位": "stock_code",
    # 日期
    "date": "trade_date",
    "tradingdate": "trade_date",
    "tradedate": "trade_date",
    "trade_date": "trade_date",
    "trdtrddt": "trade_date",
    "capdate": "trade_date",
    "accper": "trade_date",
    "证券交易日期": "trade_date",
    "交易日期": "trade_date",
    "交易日": "trade_date",
    # 收盘价（STK_MF_Q / STK_TRADE_DAYADJ 均为除权调整后收盘价）
    "close": "close",
    "closeprice": "close",
    "trdclsp": "close",
    "trdclsprc": "close",
    "trdclsprc": "close",
    "sinfocls": "close",
    "收盘价": "close",
    "除权后收盘价": "close",
    "收盘价后复权": "close",
    # 成交量
    "volume": "volume",
    "trdvol": "volume",
    "trdvol_total": "volume",
    "trdvol_total_a": "volume",
    "trdvol_total_a_shsz": "volume",
    "sinfovol": "volume",
    "成交量": "volume",
    "成交量股": "volume",
    "沪深总成交量": "volume",
    # 换手率
    "turnoverrate": "turnover_rate",
    "turnover_rate": "turnover_rate",
    "trdturn": "turnover_rate",
    "trdtnrate": "turnover_rate",
    "trdtnrate_total": "turnover_rate",
    "trdtnrate_total_a": "turnover_rate",
    "trdtnrate_total_a_shsz": "turnover_rate",
    "turnoverrate1": "turnover_rate",
    "换手率": "turnover_rate",
    "换手率_": "turnover_rate",
    "成交量换手率": "turnover_rate",
    # 总市值（STK_CAPITALS / STK_SHARE）
    "market_value": "market_value",
    "marketvalue": "market_value",
    "mv_total": "market_value",
    "mv_total_a": "market_value",
    "trdmv_total": "market_value",
    "trdmv_total_a": "market_value",
    "mktcap": "market_value",
    "totalmarketcap": "market_value",
    "总市值": "market_value",
    "总市值元": "market_value",
    "流通市值": "market_value",
    # 市盈率 TTM
    "pe_ttm": "pe_ttm",
    "pe": "pe_ttm",
    "perttm": "pe_ttm",
    "perf_ttm": "pe_ttm",
    "pe_ratio": "pe_ttm",
    "市盈率ttm": "pe_ttm",
    "市盈率t_ttm": "pe_ttm",
    "市盈率": "pe_ttm",
    "f100103c": "pe_ttm",
    # 市净率
    "pb": "pb",
    "pbr": "pb",
    "pbratio": "pb",
    "pbttm": "pb",
    "pb_ttm": "pb",
    "市净率": "pb",
    "f100401a": "pb",
    # 净资产收益率
    "roe": "roe",
    "roettm": "roe",
    "roe_ttm": "roe",
    "sinfowroer": "roe",
    "sinfo_wroer": "roe",
    "净资产收益率": "roe",
    "加权净资产收益率": "roe",
    "f050504c": "roe",
}

#: 季度报告锚定所需字段（用于无未来信息的 asof 锚定）。
REPORT_ANCHOR_ALIASES: dict[str, str] = {
    "reportdate": "report_date",
    "report_date": "report_date",
    "enddate": "report_date",
    "end_date": "report_date",
    "finreportdate": "report_date",
    "finedingdate": "report_date",
    "fin_ending_date": "report_date",
    "accper": "report_date",
    "报告期": "report_date",
    "财务报告结束日": "report_date",
    "announcemodifydate": "announce_date",
    "announcemodifieddate": "announce_date",
    "declaredate": "announce_date",
    "announcedate": "announce_date",
    "announce_date": "announce_date",
    "disclosuredate": "announce_date",
    "公告日": "announce_date",
    "公告日期": "announce_date",
}

_CODE_PATTERN = re.compile(r"^\d{6}$")


# ---------------------------------------------------------------------------
# 错误类型
# ---------------------------------------------------------------------------


class FactorPanelError(Exception):
    """因子面板数据层错误基类。"""


class StockCodeError(FactorPanelError):
    """证券代码无法规范化为 6 位字符串。"""


class SourceReadError(FactorPanelError):
    """源文件无法读取或格式不受支持。"""


class SourceSchemaError(FactorPanelError):
    """源文件缺少必需的代码/日期列，或字段无法对齐。"""


class CoverageError(FactorPanelError):
    """标的或日期覆盖不满足要求。"""


# ---------------------------------------------------------------------------
# 代码规范化
# ---------------------------------------------------------------------------


#: 别名表键统一按 _field_key() 归一化，保证 ``PE_TTM``/``PE-TTM``/``pe_ttm``
#: 与 ``TrdTNRate_Total_A``/``换手率`` 等写法都能命中同一条映射。
CSMAR_FIELD_ALIASES = {
    _field_key(key): value for key, value in CSMAR_FIELD_ALIASES.items()
}
REPORT_ANCHOR_ALIASES = {
    _field_key(key): value for key, value in REPORT_ANCHOR_ALIASES.items()
}


def normalize_stock_code(value: Any) -> str:
    """把证券代码规范化为 6 位字符串（保留前导 0）。

    接受形态：
    - 6 位字符串 ``"002594"``（原样保留）
    - 去零整数/字符串 ``2594``、``"2594"``（左补 0 至 6 位）
    - 带后缀的证券代码 ``"002594.SZ"``、``"688981.SH"``、``"603986.SS"``（剥离后缀）

    拒绝形态：含非数字字符（剥离后缀后）、长度大于 6、空白、None。
    """
    if value is None:
        raise StockCodeError("证券代码不能为空")
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(float(value)) or float(value) != int(value):
            raise StockCodeError(f"证券代码不是合法整数形式: {value!r}")
        text = str(int(value))
    elif isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
        text = str(int(value))
    else:
        text = str(value).strip()
    if not text:
        raise StockCodeError("证券代码不能为空字符串")

    # 剥离交易所后缀（CSMAR/Wind 常见形态）
    text = re.split(r"[.\s|]+", text)[0]
    if not text.isdigit():
        raise StockCodeError(f"证券代码含非数字字符: {value!r}")
    if len(text) > 6:
        raise StockCodeError(f"证券代码长度超过 6 位: {value!r}")
    if len(text) > 6 or not _CODE_PATTERN.fullmatch(text.zfill(6)):
        raise StockCodeError(f"证券代码无法规范化为 6 位字符串: {value!r}")
    return text.zfill(6)


def normalize_stock_codes(values: Iterable[Any]) -> list[str]:
    """批量规范化并保序去重。"""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(normalize_stock_code(value))
    return list(seen)


# ---------------------------------------------------------------------------
# 源文件读取与字段对齐
# ---------------------------------------------------------------------------


def read_source(path: Path | str, source_label: str | None = None) -> pd.DataFrame:
    """读取 CSV / Parquet / Excel 源文件，全部列先按字符串读取。

    先按字符串读取是为了避免 ``002594`` 被推断成整数 ``2594`` 导致前导 0 丢失；
    数值列在字段对齐阶段再显式转数值。
    """
    source_path = Path(path).expanduser().resolve()
    label = source_label or source_path.name
    if not source_path.is_file():
        raise SourceReadError(f"源文件不存在: {source_path}")
    suffix = source_path.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(source_path, dtype=str, keep_default_na=False)
        if suffix == ".parquet":
            return pd.read_parquet(source_path)
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(source_path, dtype=str)
    except Exception as exc:  # noqa: BLE001 - 统一包装成数据层错误
        raise SourceReadError(f"读取源文件失败 {label}: {exc}") from exc
    raise SourceReadError(f"不支持的源文件格式 {suffix}: {source_path}")


def detect_column(columns: Iterable[Any], aliases: Mapping[str, str], standard: str) -> str | None:
    """在源列名中查找映射到 ``standard`` 的列，返回原始列名。"""
    for column in columns:
        if CSMAR_FIELD_ALIASES.get(_field_key(column)) == standard:
            return str(column)
    return None


def _to_number(series: pd.Series) -> pd.Series:
    """字符串列转数值：千分位、括号负数、百分号等常见导出形态。"""
    text = series.astype("string").str.strip()
    text = text.str.replace(",", "", regex=False)
    text = text.str.replace("%", "", regex=False)
    text = text.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    text = text.mask(text.isin({"", "nan", "NaN", "None", "NULL", "-", "--"}), pd.NA)
    return pd.to_numeric(text, errors="coerce")


def ingest_long_source(
    frame: pd.DataFrame,
    source_label: str,
    expected_columns: Iterable[str] = (),
) -> pd.DataFrame:
    """把长表格式（一行一个 证券代码×日期）的 CSMAR 导出转成标准长表。

    只保留能在别名表中对齐的标准列；缺失列直接不产生（保持 NaN 语义在
    ``build_panel`` 的 ``reindex`` 阶段统一补齐）。
    """
    columns = {column: str(column) for column in frame.columns}
    picks: dict[str, str] = {}
    for standard in ("stock_code", "trade_date", *FACTOR_COLUMNS):
        found = None
        for column, name in columns.items():
            if CSMAR_FIELD_ALIASES.get(_field_key(name)) == standard:
                found = column
                break
        if found is not None:
            picks[standard] = str(found)

    if "stock_code" not in picks:
        raise SourceSchemaError(f"{source_label} 缺少证券代码列")
    if "trade_date" not in picks:
        raise SourceSchemaError(f"{source_label} 缺少交易日期列")

    out = pd.DataFrame()
    out["stock_code"] = frame[picks["stock_code"]].map(normalize_stock_code)
    out["trade_date"] = pd.to_datetime(frame[picks["trade_date"]], errors="coerce")
    for standard in FACTOR_COLUMNS:
        if standard in picks:
            out[standard] = _to_number(frame[picks[standard]])

    bad_dates = int(out["trade_date"].isna().sum())
    if bad_dates:
        raise SourceSchemaError(
            f"{source_label} 有 {bad_dates} 行交易日期无法解析"
        )
    if out["stock_code"].isna().any():
        raise SourceSchemaError(f"{source_label} 存在无法规范化的证券代码")

    for standard in expected_columns:
        if standard not in picks and standard in FACTOR_COLUMNS:
            logger.warning("%s 未提供字段 %s", source_label, standard)

    out.attrs["source"] = source_label
    return out[["stock_code", "trade_date", *tuple(p for p in FACTOR_COLUMNS if p in out)]].copy()


def ingest_quarterly_source(frame: pd.DataFrame, source_label: str) -> pd.DataFrame:
    """把 CSMAR 季度财务源表保留为报告日/公告日长表。

    季度源表没有日频交易日期，不能复用 ``ingest_long_source``。保留公告日是
    为了让调用方把 ROE 锚定到当时已经公开的信息，避免把报告期末日误当成
    投资者可知日。
    """
    columns = {column: str(column) for column in frame.columns}
    picks: dict[str, str] = {}
    for column, name in columns.items():
        normalized = _field_key(name)
        if CSMAR_FIELD_ALIASES.get(normalized) == "stock_code":
            picks.setdefault("stock_code", str(column))
        elif REPORT_ANCHOR_ALIASES.get(normalized) == "report_date":
            picks.setdefault("report_date", str(column))
        elif REPORT_ANCHOR_ALIASES.get(normalized) == "announce_date":
            picks.setdefault("announce_date", str(column))
        elif CSMAR_FIELD_ALIASES.get(normalized) == "roe":
            picks.setdefault("roe", str(column))

    missing = [name for name in ("stock_code", "report_date", "announce_date", "roe") if name not in picks]
    if missing:
        raise SourceSchemaError(f"{source_label} 缺少季度源字段：{missing}")

    out = pd.DataFrame()
    out["stock_code"] = frame[picks["stock_code"]].map(normalize_stock_code)
    out["report_date"] = pd.to_datetime(frame[picks["report_date"]], errors="coerce")
    out["announce_date"] = pd.to_datetime(frame[picks["announce_date"]], errors="coerce")
    out["roe"] = _to_number(frame[picks["roe"]])

    for column in ("report_date", "announce_date"):
        if out[column].isna().any():
            raise SourceSchemaError(f"{source_label} 的 {column} 含无法解析的日期")
    if out["stock_code"].isna().any():
        raise SourceSchemaError(f"{source_label} 存在无法规范化的证券代码")

    out.attrs["source"] = source_label
    return out[["stock_code", "report_date", "announce_date", "roe"]].copy()


def melt_wide_price_matrix(frame: pd.DataFrame, source_label: str) -> pd.DataFrame:
    """把「行=日期、列=证券代码」的宽表收盘价矩阵熔成标准长表。

    仅产出 ``close`` 列。宽表格式天然不含成交量/换手率/市值等字段，这些字段
    必须由长表源文件补齐，本函数不做任何推断。
    """
    if frame.shape[1] == 0:
        raise SourceSchemaError(f"{source_label} 宽表没有证券代码列")
    codes = list(frame.columns)
    normalized = [normalize_stock_code(code) for code in codes]
    if len(set(normalized)) != len(normalized):
        raise SourceSchemaError(f"{source_label} 存在规范化后重复的证券代码列")

    long = frame.copy()
    long.columns = normalized
    long = long.stack().rename("close").reset_index()
    long.columns = ["trade_date", "stock_code", "close"]
    long["stock_code"] = long["stock_code"].map(normalize_stock_code)
    long["trade_date"] = pd.to_datetime(long["trade_date"], errors="coerce")
    if long["trade_date"].isna().any():
        raise SourceSchemaError(f"{source_label} 宽表索引含无法解析的日期")
    long["close"] = pd.to_numeric(long["close"], errors="coerce")
    long.attrs["source"] = source_label
    return long


# ---------------------------------------------------------------------------
# 股票内填充（禁止跨股票）
# ---------------------------------------------------------------------------


def _require_groupable(frame: pd.DataFrame) -> None:
    if "stock_code" not in frame.columns or "trade_date" not in frame.columns:
        raise SourceSchemaError("填充操作要求数据同时包含 stock_code 与 trade_date 列")


def fill_within_stock(
    frame: pd.DataFrame,
    columns: Sequence[str],
    method: str = "ffill",
    max_gap: int | None = None,
) -> tuple[pd.DataFrame, dict[str, dict[str, int]]]:
    """**仅在同一只股票内部**填充缺失值，返回填充后数据与逐股票填充计数。

    参数：
        frame: 标准长表，已包含 stock_code / trade_date。
        columns: 需要填充的因子列名。
        method: ``ffill`` 前向填充、``bfill`` 后向填充、``both`` 先前向后向。
        max_gap: 最多连续填充的交易日数；超出则保留 NaN。

    返回：
        ``(填充后的 DataFrame, {stock_code: {column: 填充个数}})``

    实现要点：所有填充都经 ``groupby("stock_code")`` 分组执行，分组边界即
    股票边界，因此结构上不存在跨股票借值的路径。
    """
    if method not in ("ffill", "bfill", "both"):
        raise ValueError(f"未知填充方式: {method!r}")
    _require_groupable(frame)
    columns = list(dict.fromkeys(columns))
    unknown = [c for c in columns if c not in frame.columns]
    if unknown:
        raise ValueError(f"待填充列不存在: {unknown}")

    grouped = frame.groupby("stock_code", sort=False)
    filled = frame.copy()
    stats: dict[str, dict[str, int]] = {}
    for code, group in grouped:
        before = group[columns].isna()
        piece = group[columns]
        if method in ("ffill", "both"):
            piece = piece.ffill(limit=max_gap)
        if method in ("bfill", "both"):
            piece = piece.bfill(limit=max_gap)
        filled.loc[group.index, columns] = piece
        stats[str(code)] = {
            column: int((before[column] & ~piece[column].isna()).sum())
            for column in columns
        }
    return filled, stats


def anchor_quarterly_to_daily(
    panel: pd.DataFrame,
    quarterly: pd.DataFrame,
    column: str,
    anchor: str = "announce_date",
    label: str = "quarterly",
) -> pd.DataFrame:
    """把季度基本面指标按 ``stock_code`` 向后锚定到日频交易日历。

    ``anchor`` 为锚定列：优先使用公告日（``announce_date``），没有公告日时
    退化为报告期结束日（``report_date``）。退化到报告期意味着存在最长一个
    会计期的信息提前，调用方必须知道自己在接受什么。

    使用 ``pd.merge_asof(..., by="stock_code")``，分组即股票，无未来信息
    泄漏，也不跨股票取值。
    """
    if column not in FACTOR_COLUMNS:
        raise ValueError(f"锚定列 {column!r} 不是标准因子列")
    merged = quarterly.copy()
    if anchor == "announce_date" and "announce_date" not in merged.columns:
        raise SourceSchemaError(f"{label} 未提供公告日列，无法执行无未来信息锚定")
    anchor_col = anchor if anchor in merged.columns else "report_date"
    if anchor_col not in merged.columns:
        raise SourceSchemaError(f"{label} 缺少锚定列 {anchor_col}")
    if "stock_code" not in merged.columns or column not in merged.columns:
        raise SourceSchemaError(f"{label} 缺少 stock_code 或 {column} 列")

    values = merged[["stock_code", anchor_col, column]].dropna(subset=[anchor_col])
    values = values.rename(columns={anchor_col: "_anchor"})
    values["_anchor"] = pd.to_datetime(values["_anchor"], errors="coerce")
    values = values.dropna(subset=["_anchor"])
    values["_anchor"] = values["_anchor"].dt.normalize()
    # 同一股票同一公告日只保留最后一条，避免重复披露造成歧义
    values = (
        values.sort_values("_anchor")
        .drop_duplicates(subset=["stock_code", "_anchor"], keep="last")
        .reset_index(drop=True)
    )

    # merge_asof 要求两侧按日期升序；携带原始行号以便回写时精确对齐。
    # _row 直接取自 panel 的整数位置，因此要求 panel 使用 0..N-1 连续索引。
    if not isinstance(panel.index, pd.RangeIndex) or panel.index.stop != len(panel):
        panel = panel.reset_index(drop=True)
    left = panel[["stock_code", "trade_date"]].copy().reset_index(names="_row")
    left = left.sort_values(["trade_date", "_row"]).reset_index(drop=True)
    right = values.rename(columns={"_anchor": "trade_date"}).sort_values("trade_date")
    anchored = pd.merge_asof(
        left,
        right,
        on="trade_date",
        by="stock_code",
        direction="backward",
        allow_exact_matches=True,
    )
    # 按原始行号还原顺序，此时第 i 行与 panel 第 i 行一一对应
    anchored = anchored.sort_values("_row").reset_index(drop=True)

    result = panel.copy()
    result[column] = np.nan
    result[column] = anchored[column].to_numpy()
    return result


# ---------------------------------------------------------------------------
# 构建 / 校验 / 写出
# ---------------------------------------------------------------------------


def build_panel(
    task_codes: Iterable[Any],
    long_sources: Mapping[str, pd.DataFrame],
    start_date: str,
    end_date: str,
    trade_calendar: pd.Index | None = None,
    fill_columns: Sequence[str] = (),
    fill_method: str = "ffill",
    max_gap: int | None = None,
    require_columns: Iterable[str] = (),
) -> tuple[pd.DataFrame, dict[str, dict[str, int]]]:
    """构建标准化因子面板。

    参数：
        task_codes: 任务池证券代码（会被规范化为 6 位字符串）。
        long_sources: ``{源标签: 标准长表}``，同名字段按源出现顺序左接覆盖。
        start_date / end_date: 闭区间交易日窗口。
        trade_calendar: 显式交易日历。缺省时取所有源数据的日期并集。
        fill_columns: 需要填充的因子列。
        require_columns: 必须存在的因子列；缺失会抛 CoverageError。

    返回 ``(panel, fill_stats)``。panel 排序为 stock_code 升序、trade_date 升序。
    """
    codes = normalize_stock_codes(task_codes)
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if end < start:
        raise CoverageError(f"结束日期 {end_date} 早于开始日期 {start_date}")

    merged: pd.DataFrame | None = None
    for label, source in long_sources.items():
        if source is None or source.empty:
            continue
        chunk = source.copy()
        chunk = chunk[(chunk["trade_date"] >= start) & (chunk["trade_date"] <= end)]
        chunk = chunk[chunk["stock_code"].isin(set(codes))]
        chunk = chunk.drop_duplicates(subset=["stock_code", "trade_date"], keep="last")
        merged = chunk if merged is None else _merge_factor_frame(merged, chunk)

    if merged is None or merged.empty:
        raise CoverageError("源数据在任务池与请求窗口内没有任何记录")

    if trade_calendar is None:
        calendar = pd.DatetimeIndex(sorted(merged["trade_date"].unique()))
    else:
        calendar = pd.DatetimeIndex(pd.to_datetime(pd.Index(trade_calendar)))
        calendar = calendar[(calendar >= start) & (calendar <= end)]
    if len(calendar) == 0:
        raise CoverageError("交易日历在请求窗口内为空")

    full_index = pd.MultiIndex.from_product([codes, calendar], names=["stock_code", "trade_date"])
    panel = merged.set_index(["stock_code", "trade_date"]).reindex(full_index).reset_index()
    panel = panel.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)

    panel["stock_code"] = panel["stock_code"].astype(str).map(normalize_stock_code)
    for column in FACTOR_COLUMNS:
        if column not in panel.columns:
            panel[column] = np.nan

    panel = panel[list(STANDARD_COLUMNS)]
    if merged["stock_code"].nunique() < len(codes):
        missing = sorted(set(codes) - set(merged["stock_code"].unique()))
        raise CoverageError(f"{len(missing)} 只标的在源数据中没有任何记录: {missing[:10]}")

    missing_required = [c for c in require_columns if c in FACTOR_COLUMNS and c not in merged.columns]
    if missing_required:
        raise CoverageError(f"必需字段缺失，源数据未提供: {missing_required}")

    filled, stats = fill_within_stock(panel, list(fill_columns), method=fill_method, max_gap=max_gap)
    filled = filled[list(STANDARD_COLUMNS)]
    filled.attrs["source_labels"] = list(long_sources.keys())
    filled.attrs["window"] = [start_date, end_date]
    filled.attrs["fill_method"] = fill_method
    filled.attrs["fill_max_gap"] = max_gap
    return filled, stats


def _merge_factor_frame(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    """按 证券代码×日期 合并两份标准长表。

    两侧共有字段取左表非空值优先（左接覆盖语义）；右侧独有字段直接左连接。
    合并键做外连接，避免任意一侧的 证券代码×日期 组合被静默丢弃。
    """
    keys = ["stock_code", "trade_date"]
    shared = [c for c in FACTOR_COLUMNS if c in left.columns and c in right.columns]
    right_only = [c for c in FACTOR_COLUMNS if c in right.columns and c not in left.columns]

    if shared:
        joined = pd.merge(
            left, right[keys + shared], on=keys, how="outer", suffixes=("", "_right")
        )
        for column in shared:
            joined[column] = joined[column].where(joined[column].notna(), joined[column + "_right"])
            joined = joined.drop(columns=[column + "_right"])
    else:
        joined = left.copy()

    if right_only:
        joined = pd.merge(joined, right[keys + right_only], on=keys, how="outer")
    return joined


def validate_panel(
    panel: pd.DataFrame,
    expected_codes: Iterable[str],
    start_date: str,
    end_date: str,
    expected_dates: pd.Index | None = None,
) -> dict[str, Any]:
    """校验输出面板并返回结构化报告（不修改输入）。"""
    codes = [normalize_stock_code(c) for c in expected_codes]
    report: dict[str, Any] = {
        "n_rows": int(len(panel)),
        "n_stocks": int(panel["stock_code"].nunique()) if len(panel) else 0,
        "n_trading_dates": int(panel["trade_date"].nunique()) if len(panel) else 0,
        "start_date": str(panel["trade_date"].min().date()) if len(panel) else None,
        "end_date": str(panel["trade_date"].max().date()) if len(panel) else None,
        "window_request": [str(start_date), str(end_date)],
        "code_all_6_digit_strings": bool(
            panel["stock_code"].astype(str).str.fullmatch(r"\d{6}").all()
        )
        if len(panel)
        else False,
        "code_dtype_is_string": str(panel["stock_code"].dtype) == "object",
        "leading_zero_codes_preserved": sorted(
            str(c) for c in set(panel["stock_code"].astype(str)) if str(c).startswith("0")
        )[:20]
        if len(panel)
        else [],
        "duplicate_stock_date_rows": int(
            panel.duplicated(subset=["stock_code", "trade_date"]).sum()
        )
        if len(panel)
        else 0,
        "date_gaps_inside_window": _date_gaps(panel, expected_dates, start_date, end_date),
        "missing_stocks": sorted(set(codes) - set(panel["stock_code"].astype(str))),
        "columns": list(panel.columns),
        "factor_completeness": {},
        "factor_ranges": {},
        "non_finite_count": {},
    }
    for column in FACTOR_COLUMNS:
        if column not in panel.columns:
            report["factor_completeness"][column] = None
            continue
        series = panel[column]
        numeric = pd.to_numeric(series, errors="coerce")
        report["factor_completeness"][column] = {
            "non_null": int(numeric.notna().sum()),
            "null": int(numeric.isna().sum()),
            "coverage": float(numeric.notna().mean()) if len(numeric) else 0.0,
        }
        if numeric.notna().any():
            report["factor_ranges"][column] = {
                "min": float(numeric.min()),
                "max": float(numeric.max()),
            }
        report["non_finite_count"][column] = int(
            (~np.isfinite(numeric.to_numpy(dtype="float64"))).sum()
        )
    return report


def _date_gaps(
    panel: pd.DataFrame,
    expected_dates: pd.Index | None,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """报告请求窗口内的交易日历缺失情况（仅在提供期望日历时给出确定结论）。"""
    if not len(panel):
        return {"expected_calendar_provided": expected_dates is not None, "note": "面板为空"}
    observed = set(pd.to_datetime(panel["trade_date"]).unique())
    if expected_dates is None:
        return {"expected_calendar_provided": False, "note": "未提供交易日历，无法判定窗口内交易日是否完整"}
    expected = set(pd.to_datetime(pd.Index(expected_dates)).unique())
    return {
        "expected_calendar_provided": True,
        "expected_trading_dates": len(expected),
        "observed_trading_dates": len(observed),
        "missing_dates": sorted(str(pd.Timestamp(d).date()) for d in (expected - observed)),
    }


def write_panel(
    panel: pd.DataFrame,
    output_dir: Path | str,
    stem: str,
    manifest: dict[str, Any],
) -> tuple[Path, Path, Path]:
    """写出 CSV + Parquet + 覆盖清单，返回三个路径。"""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{stem}.csv"
    parquet_path = out_dir / f"{stem}.parquet"
    manifest_path = out_dir / f"{stem}_manifest.json"

    ordered = panel[list(STANDARD_COLUMNS)].copy()
    ordered["stock_code"] = ordered["stock_code"].astype(str).str.zfill(6)
    ordered["trade_date"] = pd.to_datetime(ordered["trade_date"]).dt.strftime("%Y-%m-%d")
    ordered.to_csv(csv_path, index=False, encoding="utf-8")

    export = panel[list(STANDARD_COLUMNS)].copy()
    export["stock_code"] = export["stock_code"].astype(str).str.zfill(6)
    export["trade_date"] = pd.to_datetime(export["trade_date"])
    export.to_parquet(parquet_path, index=False, engine="pyarrow")

    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, default=str)
    return csv_path, parquet_path, manifest_path
