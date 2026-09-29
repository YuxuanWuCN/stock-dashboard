# -*- coding: utf-8 -*-
"""scripts/enrich_master_panel_bc_technical.py —— 把 B/C 组技术因子并入 CSMAR master 面板。

背景（M4 扩域）：master 面板的技术类特征（mom_*/vol_*/turnover_20d/amihud/
price_pos/amplitude/gap/hit_limit/abnormal_trd）只有 A 组 99 支有值（BUG-0027），
B/C 组缺失 ⇒ M4 走步评测的 ``price_technical_v1`` 特征族无法用于 B/C 域。

本脚本消费 ``scripts/build_csmar_daily_panel_factors.py --cohort student_B/student_C``
产出的真实 TRD_Dalyr 日频因子面板（date,ticker,ret,close,...,abnormal_trd），把
12 个技术列按 (stock_code, trade_date) 精确并入 master 面板的 B/C 行。

纪律（对应 AGENTS.md 与口径声明）：
1. **绝不覆盖原始数据**：只改派生的 master 合并表（git 历史即备份）；student_*/csmar
   与 data/task_split/factors_daily_panel_student_*.csv 等原始导出一概只读。
2. **绝不触碰 ret 与 close 等标准列**：B/C 的收益口径是"前复权 close 日收益率"
   （config/data_caliber/csmar_master_close_basis.json 已声明），并入 Dretwd 反而
   会污染已声明的 caliber；本脚本只写 12 个技术列。
3. **fail-closed**：代码集不符、重复键、B/C 行已有技术值、A 组行任何变动、
   覆盖率塌陷、布尔列非 0/1 —— 任一命中即整体拒绝写盘。
4. **无跨股票填充**：逐 (code, date) 内连，停牌缺行保持 NaN，由下游 as-of 面板
   记为"缺失即不可用"并计数，绝不静默补 0。

用法::

    python scripts/enrich_master_panel_bc_technical.py            # 正式并入（写盘前全检）
    python scripts/enrich_master_panel_bc_technical.py --dry-run  # 只出检查报告，不写盘
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 与 scripts/evaluate_pca_nale_integration.py 的 TECHNICAL_FEATURES 逐字一致。
TECHNICAL_FEATURES: tuple[str, ...] = (
    "mom_5d", "mom_20d", "mom_60d", "vol_20d", "vol_60d", "turnover_20d",
    "amihud", "price_pos", "amplitude", "gap", "hit_limit", "abnormal_trd",
)
#: 0/1 布尔型技术列。
BOOLEAN_FEATURES: tuple[str, ...] = ("hit_limit", "abnormal_trd")

DEFAULT_MASTER = ROOT / "data/task_split/csmar_master/csmar_factor_panel_master"
DEFAULT_SOURCES = {
    "student_B": ROOT / "data/task_split/factors_daily_panel_student_B.csv",
    "student_C": ROOT / "data/task_split/factors_daily_panel_student_C.csv",
}
DEFAULT_COHORT_LISTS = {
    "student_B": ROOT / "data/task_split/student_B_energy_materials_100.csv",
    "student_C": ROOT / "data/task_split/student_C_finance_consumer_100.csv",
}
#: 逐支最低技术覆盖率（停牌日按日历仍在 master 中，但 TRD_Dalyr 无行 ⇒ 允许少量缺失）。
MIN_PER_STOCK_COVERAGE = 0.90
#: 组内总体最低覆盖率。
MIN_COHORT_COVERAGE = 0.95


class EnrichmentError(ValueError):
    """富集输入或纪律被违反（fail-closed，拒绝写盘）。"""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_cohort_codes(path: Path) -> list[str]:
    frame = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig")
    return [str(code).zfill(6) for code in frame["code"]]


def _load_daily_panel(path: Path, label: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"ticker": str}, encoding="utf-8-sig")
    missing_columns = [column for column in ("date", "ticker", *TECHNICAL_FEATURES) if column not in frame.columns]
    if missing_columns:
        raise EnrichmentError(f"{label} 缺少必需列：{missing_columns}")
    frame = frame.rename(columns={"ticker": "stock_code", "date": "trade_date"})
    frame["stock_code"] = frame["stock_code"].str.zfill(6)
    frame["trade_date"] = frame["trade_date"].astype(str).str.slice(0, 10)
    duplicated = frame.duplicated(subset=["stock_code", "trade_date"], keep=False)
    if bool(duplicated.any()):
        offenders = frame.loc[duplicated, ["stock_code", "trade_date"]].drop_duplicates().head(5).values.tolist()
        raise EnrichmentError(f"{label} 存在重复 (stock_code, trade_date) 键：{offenders}")
    return frame.loc[:, ["stock_code", "trade_date", *TECHNICAL_FEATURES]].copy()


def enrich(
    master: pd.DataFrame,
    sources: dict[str, pd.DataFrame],
    cohort_codes: dict[str, list[str]],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """返回 (并入后的 master 副本, 审计信息)；不修改传入的 master。"""
    result = master.copy()
    codes_before = set(result["stock_code"])
    if result.duplicated(subset=["stock_code", "trade_date"]).any():
        raise EnrichmentError("master 面板本身存在重复 (stock_code, trade_date)（fail-closed）")
    audit: dict[str, object] = {"cohorts": {}}

    # A 组行快照：并入完成后必须逐位不变（A 组技术值来自既有交付，绝不允许被触碰）。
    source_cohort_of: dict[str, str] = {}
    for group, codes in cohort_codes.items():
        for code in codes:
            if code in source_cohort_of and source_cohort_of[code] != group:
                raise EnrichmentError(f"代码 {code} 同时出现在两组清单中")
            source_cohort_of[code] = group
    source_codes = set(source_cohort_of)
    a_snapshot = result.loc[~result["stock_code"].isin(source_codes)].copy()

    for group, panel in sources.items():
        codes = cohort_codes[group]
        if sorted(set(codes)) != sorted(panel["stock_code"].unique()):
            missing = sorted(set(codes) - set(panel["stock_code"].unique()))
            extra = sorted(set(panel["stock_code"].unique()) - set(codes))
            raise EnrichmentError(
                f"{group} 日频面板代码集与任务清单不符：缺 {missing[:5]}… 多 {extra[:5]}…（fail-closed）"
            )
        existing_non_null = result.loc[
            result["stock_code"].isin(set(codes)), list(TECHNICAL_FEATURES)
        ].notna().to_numpy().sum()
        if int(existing_non_null) > 0:
            raise EnrichmentError(
                f"{group} 行在 master 中已有 {int(existing_non_null)} 个非空技术值，疑似重复并入（fail-closed）"
            )

        boolean_values = set(
            np.unique(panel[list(BOOLEAN_FEATURES)].dropna().to_numpy(dtype=float)).tolist()
        )
        if not boolean_values <= {0.0, 1.0}:
            raise EnrichmentError(f"{group} 布尔技术列含 0/1 之外取值：{sorted(boolean_values)[:8]}")
        duplicated = panel.duplicated(subset=["stock_code", "trade_date"], keep=False)
        if bool(duplicated.any()):
            offenders = panel.loc[duplicated, ["stock_code", "trade_date"]].drop_duplicates().head(5).values.tolist()
            raise EnrichmentError(f"{group} 源面板存在重复 (stock_code, trade_date) 键：{offenders}")
        price_pos = panel["price_pos"].dropna()
        if bool(((price_pos < -0.01) | (price_pos > 1.01)).any()):
            raise EnrichmentError(f"{group} price_pos 越出 [0,1]（公式上不可能，数据可疑）")
        amplitude = panel["amplitude"].dropna()
        if bool((amplitude < 0).any()):
            raise EnrichmentError(f"{group} amplitude 出现负值（公式上不可能，数据可疑）")

        keep = panel.drop_duplicates(subset=["stock_code", "trade_date"], keep="first")
        merged = result.merge(
            keep, on=["stock_code", "trade_date"], how="left", suffixes=("", "_incoming"),
            validate="one_to_one",
        )
        for column in TECHNICAL_FEATURES:
            incoming = merged[f"{column}_incoming"]
            base = merged[column]
            # 只允许向"当前为 NaN 的单元格"写值：A 组既有值与标准列一概不动
            overridden = base.notna() & incoming.notna() & ~merged["stock_code"].isin(set(codes))
            if bool(overridden.any()):
                raise EnrichmentError(f"列 {column} 有 {int(overridden.sum())} 个非 B/C 行会被改动（fail-closed）")
            merged[column] = base.where(base.notna(), incoming)
            merged.drop(columns=[f"{column}_incoming"], inplace=True)
        result = merged

        rows_mask = result["stock_code"].isin(set(codes))
        cohort_frame = result.loc[rows_mask, list(TECHNICAL_FEATURES)]
        per_stock = cohort_frame.notna().groupby(result.loc[rows_mask, "stock_code"]).mean()
        low_stock = (per_stock.mean(axis=1) < MIN_PER_STOCK_COVERAGE)
        if bool(low_stock.any()):
            offenders = per_stock.index[low_stock].tolist()[:8]
            raise EnrichmentError(
                f"{group} 逐支技术覆盖率低于 {MIN_PER_STOCK_COVERAGE:.0%}：{offenders}（取数不完整，拒绝写盘）"
            )
        coverage = {column: round(float(cohort_frame[column].notna().mean()), 6) for column in TECHNICAL_FEATURES}
        overall = float(cohort_frame.notna().to_numpy().mean())
        if overall < MIN_COHORT_COVERAGE:
            raise EnrichmentError(f"{group} 总体技术覆盖率 {overall:.2%} < {MIN_COHORT_COVERAGE:.0%}（拒绝写盘）")
        audit["cohorts"][group] = {
            "n_stocks": len(codes),
            "n_rows": int(rows_mask.sum()),
            "overall_coverage": round(overall, 6),
            "per_column_coverage": coverage,
        }

    # A 组行守卫：并入后的非 B/C 行必须与并入前逐位一致
    after = result.loc[~result["stock_code"].isin(source_codes)].reset_index(drop=True)
    before = a_snapshot.reset_index(drop=True)
    if not after.equals(before):
        raise EnrichmentError("A 组（非 B/C）行在并入后被改动（fail-closed）")

    if set(result["stock_code"]) != codes_before:
        raise EnrichmentError("并入后股票集合发生变化（fail-closed）")
    if result.duplicated(subset=["stock_code", "trade_date"]).any():
        raise EnrichmentError("并入后出现重复 (stock_code, trade_date)（fail-closed）")
    audit["touched_rows"] = int(sum(item["n_rows"] for item in audit["cohorts"].values()))
    return result, audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 B/C 组 TRD_Dalyr 技术因子并入 master 面板")
    parser.add_argument("--dry-run", action="store_true", help="只做全部检查并打印报告，不写任何文件")
    parser.add_argument("--only", choices=sorted(DEFAULT_SOURCES), default=None,
                        help="只并入指定组（按组幂等；用于当日额度不足时分批并入）")
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER.with_suffix(".parquet"),
                        help="master 面板（parquet 优先；.csv 亦可）")
    for group, path in DEFAULT_SOURCES.items():
        parser.add_argument(f"--{group.replace('_', '-')}-panel", type=Path, default=path)
    for group, path in DEFAULT_COHORT_LISTS.items():
        parser.add_argument(f"--{group.replace('_', '-')}-list", type=Path, default=path)
    args = parser.parse_args(argv)

    master_path = Path(args.master)
    if master_path.suffix == ".parquet" and not master_path.exists():
        master_path = DEFAULT_MASTER.with_suffix(".csv")
    master = (
        pd.read_parquet(master_path)
        if master_path.suffix == ".parquet"
        else pd.read_csv(master_path, dtype={"stock_code": str})
    )
    master["stock_code"] = master["stock_code"].astype(str).str.zfill(6)
    missing = [column for column in ("stock_code", "trade_date", *TECHNICAL_FEATURES) if column not in master.columns]
    if missing:
        raise EnrichmentError(f"master 面板缺少列：{missing}")

    # --only：按组分批并入（当日额度只够拉一组时使用）。并入是按组幂等的——
    # 重复并入同一组会因"该组行已有非空技术值"被拒绝，跨组互不影响。
    only = getattr(args, "only", None)
    groups = list(DEFAULT_SOURCES)
    if only is not None:
        if only not in DEFAULT_SOURCES:
            raise EnrichmentError(f"--only 只支持 {'/'.join(DEFAULT_SOURCES)}：{only!r}")
        groups = [only]
    sources = {
        group: _load_daily_panel(getattr(args, f"{group}_panel"), group)
        for group in groups
    }
    cohort_codes = {
        group: _load_cohort_codes(getattr(args, f"{group}_list"))
        for group in groups
    }

    enriched, audit = enrich(master, sources, cohort_codes)

    print("=== B/C 技术因子并入检查报告 ===")
    for group, item in audit["cohorts"].items():
        print(f"\n[{group}] {item['n_stocks']} 支 / {item['n_rows']} 行，总体覆盖率 {item['overall_coverage']:.2%}")
        for column, value in item["per_column_coverage"].items():
            print(f"  {column:<15} {value:.2%}")
    print(f"\n合计将被写入的技术值行数：{audit['touched_rows']}")

    if args.dry_run:
        print("\n[dry-run] 未写任何文件。")
        return 0

    enriched.to_csv(DEFAULT_MASTER.with_suffix(".csv"), index=False)
    enriched.to_parquet(DEFAULT_MASTER.with_suffix(".parquet"), index=False)
    manifest_path = DEFAULT_MASTER.parent / "csmar_factor_panel_master_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest["bc_technical_enrichment"] = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script": "scripts/enrich_master_panel_bc_technical.py",
        "note": "B/C 组 12 个技术列来自 CSMAR TRD_Dalyr 真实导出（build_csmar_daily_panel_factors.py），"
                "A 组与标准 9 列、ret 口径一概未动；停牌缺行保持 NaN。",
        "source_sha256": {group: sha256_of(getattr(args, f"{group}_panel")) for group in groups},
        "fabrication_check": {"synthetic": False, "random": False},
        **audit,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 已写盘：{DEFAULT_MASTER.with_suffix('.csv')} / .parquet，manifest 已更新。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
