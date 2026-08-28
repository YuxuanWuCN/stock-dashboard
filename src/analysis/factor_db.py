# src/analysis/factor_db.py —— 因子数据层（spec-kit 003 / v3.0 Phase 1 / US1）
#
# 职责（对应 FR-001/002/003/012 与 contracts/factors-csv.md）：
#   1. CSV 契约校验（表头/列序、重复日期、缺口率、乱序、覆盖区间、rf 默认填充）
#   2. SQLite 因子库幂等入库（UPSERT、事务）与区间查询
#   3. 因子序列与个股 K 线按交易日交集对齐（剔除记录，无前视）
#   4. 数据质量报告输出
#
# 用法:
#   python -m src.analysis.factor_db import --csv <path> [--db <path>]

import argparse
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from .config import (
    FACTOR_DB_PATH,
    FACTORS_DIR_NAME,
    GAP_RATE_MAX,
    MIN_OBS_DAYS,
    RF_ANNUAL_DEFAULT,
    TRADING_DAYS_PER_YEAR,
)

REQUIRED_COLS = ["date", "MKT", "SMB", "HML", "MOM"]
FACTOR_COLS = REQUIRED_COLS[1:]
OPTIONAL_COLS = ["rf", "source", "version"]
CANONICAL = {c.lower(): c for c in REQUIRED_COLS + OPTIONAL_COLS}
CANONICAL_OUT = ["date"] + FACTOR_COLS + ["rf"]


def default_db_path() -> Path:
    """因子库默认路径（docs/data/factors/factors.db）。"""
    if FACTOR_DB_PATH:
        return Path(FACTOR_DB_PATH)
    root = Path(__file__).resolve().parent.parent.parent
    return root / "docs" / "data" / FACTORS_DIR_NAME / "factors.db"


def _default_rf_daily() -> float:
    return (1 + RF_ANNUAL_DEFAULT) ** (1 / TRADING_DAYS_PER_YEAR) - 1


def _read_csv(csv_source) -> pd.DataFrame:
    """读取 CSV（支持路径、file-like、CSV 文本），表头大小写不敏感规范化。"""
    if hasattr(csv_source, "read"):
        raw = pd.read_csv(csv_source)
    else:
        s = str(csv_source)
        if "\n" in s or "\r" in s:
            raw = pd.read_csv(io.StringIO(s))
        else:
            raw = pd.read_csv(s)
    rename = {}
    for col in raw.columns:
        key = str(col).strip().lower()
        if key in CANONICAL:
            rename[col] = CANONICAL[key]
    return raw.rename(columns=rename)


def validate_factors_csv(csv_source) -> Tuple[pd.DataFrame, dict]:
    """校验因子 CSV 契约，返回 (规范 DataFrame, 校验报告)。

    规范 DataFrame 列序固定: date,MKT,SMB,HML,MOM,rf；date 为 datetime64；
    数值列已转 float；缺口行已剔除。
    违规行为（按 contracts/factors-csv.md）：缺失必需列 / 重复日期 /
    缺口率 > GAP_RATE_MAX / 覆盖区间 < MIN_OBS_DAYS → ValueError。
    乱序仅排序并告警（disordered 标记）。
    """
    df = _read_csv(csv_source)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"因子 CSV 缺失必需列: {missing}")

    for c in FACTOR_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if df["date"].isna().any():
        raise ValueError("因子 CSV 存在无法解析的日期")

    dup = df["date"].duplicated()
    if dup.any():
        bad = df.loc[dup, "date"].dt.strftime("%Y-%m-%d").tolist()[:5]
        raise ValueError(f"因子 CSV 存在重复日期: {bad}")

    disordered = not bool(df["date"].is_monotonic_increasing)
    df = df.sort_values("date").reset_index(drop=True)

    na_mask = df[FACTOR_COLS].isna().any(axis=1)
    gap_rate = float(na_mask.mean())
    if gap_rate > GAP_RATE_MAX:
        raise ValueError(
            f"因子缺口率 {gap_rate:.2%} 超过阈值 {GAP_RATE_MAX:.2%}（缺口行 {int(na_mask.sum())}/{len(df)}）"
        )
    df = df.loc[~na_mask].reset_index(drop=True)

    if len(df) < MIN_OBS_DAYS:
        raise ValueError(f"因子覆盖区间不足: {len(df)} 个有效观测日 < {MIN_OBS_DAYS}")

    # rf 可选列：缺失或空值用可配置年化固定近似填充（research.md R6）
    rf_source = "csv"
    if "rf" not in df.columns:
        df["rf"] = _default_rf_daily()
        rf_source = "default"
    else:
        df["rf"] = pd.to_numeric(df["rf"], errors="coerce")
        if df["rf"].isna().any():
            df["rf"] = df["rf"].fillna(_default_rf_daily())
            rf_source = "csv_with_default_fill"

    extra = {}
    for c in ("source", "version"):
        if c in df.columns:
            values = df[c].dropna().astype(str)
            extra[c] = values.iloc[0] if len(values) else None

    df = df[CANONICAL_OUT].reset_index(drop=True)

    report = {
        "row_count": int(len(df)),
        "gap_rate": gap_rate,
        "disordered": disordered,
        "rf_source": rf_source,
        "min_date": df["date"].iloc[0].strftime("%Y-%m-%d"),
        "max_date": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        **extra,
    }
    return df, report


def import_to_db(csv_source, db_path: Optional[str] = None) -> dict:
    """校验后幂等入库（UPSERT + 事务），返回入库统计。

    校验失败在触碰数据库前抛出（先校验后写），保证失败导入不留半写。
    """
    db = str(db_path or default_db_path())
    Path(db).parent.mkdir(parents=True, exist_ok=True)

    df, report = validate_factors_csv(csv_source)

    rows = [
        (
            row["date"].strftime("%Y-%m-%d"),
            float(row["MKT"]), float(row["SMB"]), float(row["HML"]),
            float(row["MOM"]), float(row["rf"]),
        )
        for _, row in df.iterrows()
    ]
    now = datetime.now().isoformat(timespec="seconds")
    meta = {
        "source": report.get("source") or "unknown",
        "version": report.get("version") or "unspecified",
        "imported_at": now,
        "row_count": str(report["row_count"]),
        "min_date": report["min_date"],
        "max_date": report["max_date"],
        "gap_rate": f"{report['gap_rate']:.6f}",
        "rf_source": report["rf_source"],
    }

    con = sqlite3.connect(db)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS factors ("
            "date TEXT PRIMARY KEY, mkt REAL NOT NULL, smb REAL NOT NULL, "
            "hml REAL NOT NULL, mom REAL NOT NULL, rf REAL NOT NULL)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS source_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        con.executemany(
            "INSERT OR REPLACE INTO factors (date, mkt, smb, hml, mom, rf) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        con.executemany(
            "INSERT OR REPLACE INTO source_meta (key, value) VALUES (?, ?)",
            list(meta.items()),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    return {"db_path": db, **{k: v for k, v in report.items() if k in (
        "row_count", "gap_rate", "min_date", "max_date", "rf_source",
        "source", "version",
    )}}


def query_range(db_path: str, start: str, end: str) -> pd.DataFrame:
    """按日期区间（含端点，ISO 字符串）查询因子序列。

    返回列: date(字符串 YYYY-MM-DD),MKT,SMB,HML,MOM,rf，按日期升序。
    """
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT date, mkt AS MKT, smb AS SMB, hml AS HML, mom AS MOM, rf "
            "FROM factors WHERE date >= ? AND date <= ? ORDER BY date",
            con,
            params=(start, end),
        )
    finally:
        con.close()
    return df


def _date_str(series: pd.Series) -> pd.Series:
    """统一转成 YYYY-MM-DD 字符串（兼容 datetime64 与字符串输入）。"""
    return pd.to_datetime(series).dt.strftime("%Y-%m-%d")


def align_with_kline(
    factors_df: pd.DataFrame, kline_df: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """因子与 K 线按交易日交集对齐（无前视、不伪造）。

    返回 (aligned_factors, aligned_kline, dropped)：
      dropped = {"dropped_factor_dates": [...], "dropped_kline_dates": [...]}
    两个输出按日期升序、长度一致、日期一致。
    """
    f = factors_df.copy()
    k = kline_df.copy()
    f["_d"] = _date_str(f["date"])
    k["_d"] = _date_str(k["date"])

    f_dates = set(f["_d"])
    k_dates = set(k["_d"])
    common = f_dates & k_dates

    dropped = {
        "dropped_factor_dates": sorted(f_dates - common),
        "dropped_kline_dates": sorted(k_dates - common),
    }

    f_out = f[f["_d"].isin(common)].drop(columns="_d").reset_index(drop=True)
    k_out = k[k["_d"].isin(common)].drop(columns="_d").reset_index(drop=True)
    f_out["date"] = _date_str(f_out["date"])
    k_out["date"] = _date_str(k_out["date"])
    f_out = f_out.sort_values("date").reset_index(drop=True)
    k_out = k_out.sort_values("date").reset_index(drop=True)
    return f_out, k_out, dropped


def write_quality_report(report: dict, path: str) -> str:
    """原子写入数据质量报告 JSON，返回路径。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    tmp.replace(p)
    return str(p)


def write_factor_quality_report(
    db_path: Optional[str] = None, out_path: Optional[str] = None
) -> str:
    """从因子库生成质量报告（含半衰期/拥挤度，005 融合 US3），写入 JSON。

    默认 db: docs/data/factors/factors.db；默认 out: docs/data/factors/quality_report.json。
    返回输出路径。
    """
    db = str(db_path or default_db_path())
    con = sqlite3.connect(db)
    try:
        df = pd.read_sql_query(
            "SELECT date, mkt AS MKT, smb AS SMB, hml AS HML, mom AS MOM, rf "
            "FROM factors ORDER BY date",
            con,
        )
    finally:
        con.close()

    from .factor_quality import compute_factor_quality_report  # 惰性导入避免耦合

    report = compute_factor_quality_report(df)
    out = out_path or str(Path(db).parent / "quality_report.json")
    return write_quality_report(report, out)


def main() -> int:
    parser = argparse.ArgumentParser(description="因子数据层（spec-kit 003 / Fama-MacBeth Phase 1）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="导入因子 CSV 到 SQLite 因子库（幂等）")
    imp.add_argument("--csv", required=True, help="因子 CSV 路径（契约见 contracts/factors-csv.md）")
    imp.add_argument("--db", default=None, help="SQLite 因子库路径（默认 docs/data/factors/factors.db）")
    qual = sub.add_parser("quality", help="生成因子质量报告（含半衰期/拥挤度）")
    qual.add_argument("--db", default=None, help="SQLite 因子库路径")
    qual.add_argument("--out", default=None, help="质量报告输出路径（默认 docs/data/factors/quality_report.json）")
    args = parser.parse_args()

    if args.cmd == "import":
        stats = import_to_db(args.csv, db_path=args.db)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    elif args.cmd == "quality":
        out = write_factor_quality_report(db_path=args.db, out_path=args.out)
        print(json.dumps({"report_path": out}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - 仅直接脚本执行路径
    raise SystemExit(main())
