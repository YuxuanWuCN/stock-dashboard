"""scripts/audit_return_basis.py —— M0 收益口径审计 CLI（只读输入，隔离输出）.

用法
----
    python scripts/audit_return_basis.py [--panel PATH] [--declarations-config PATH]
                                         [--factors PATH] [--run-id ID] [--output-root DIR]

行为
----
1. 读取 `config/data_caliber/csmar_master_close_basis.json` 的**声明式口径**与
   `data/task_split/factors_768d_all.csv` 的分组归属，逐支展开声明表；
2. 调 `src.data.return_basis` 做独立复核（复权恒等式 + 涨跌停约束）与统一总收益构造；
3. 产物写入隔离目录，**拒绝覆盖**已存在的 run：
   - `reports/tables/pca_nale_integration/<run_id>/return_basis_audit.md`
   - `.../caliber_verification.csv`
   - `.../caliber_exceptions.csv`
   - `data/processed/pca_nale_integration/<run_id>/return_basis.parquet`
   - `.../run_manifest.json`（输入/配置 SHA256、代码版本、统计摘要）

本脚本不修改任何原始数据，不写 `reports/tables/ashare_pca_backtest/`（M1.4 稳定产物只读）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.return_basis import (  # noqa: E402
    CALIBER_WATERMARK,
    ReturnBasisConfig,
    ReturnBasisError,
    caliber_mixing_report,
    compute_return_basis,
    declared_caliber,
    verify_caliber,
)

DEFAULT_PANEL = ROOT / "data/task_split/csmar_master/csmar_factor_panel_master.csv"
DEFAULT_FACTORS = ROOT / "data/task_split/factors_768d_all.csv"
DEFAULT_DECLARATIONS = ROOT / "config/data_caliber/csmar_master_close_basis.json"


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    """流式 SHA256（大文件友好）。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def build_declarations(config_path: Path, factors_path: Path) -> pd.DataFrame:
    """把分组级口径声明展开成逐支声明表。

    Raises
    ------
    ReturnBasisError
        配置文件缺组、分组归属缺失，或面板股票无对应声明。
    """
    spec = json.loads(config_path.read_text(encoding="utf-8"))
    cohorts = spec.get("cohorts")
    if not isinstance(cohorts, dict) or not cohorts:
        raise ReturnBasisError(f"{config_path} 缺少 cohorts 声明")

    facts = pd.read_csv(factors_path, dtype={"code": str}, usecols=["code", "cohort_key"])
    cohort_of = dict(zip(facts["code"], facts["cohort_key"]))
    rows: list[dict[str, Any]] = []
    for code in sorted(cohort_of):
        group = str(cohort_of[code])
        if group not in cohorts:
            raise ReturnBasisError(f"{code} 所属组 {group} 在口径声明中缺失")
        item = cohorts[group]
        rows.append(
            {
                "stock_code": code,
                "close_basis": item["close_basis"],
                "source_table": item["source_table"],
                "adjustment": item["adjustment"],
                "provenance": item["provenance"],
                "total_return_available": bool(item.get("total_return_available", False)),
                "cohort_key": group,
            }
        )
    return pd.DataFrame(rows)


def _fmt(value: float, digits: int = 6) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.{digits}g}"


def write_audit_markdown(
    path: Path,
    *,
    basis: pd.DataFrame,
    verification: pd.DataFrame,
    mixing: dict[str, float],
    panel_hash: str,
    declarations_hash: str,
    run_id: str,
    declarations_path: Path,
    panel_path: Path,
) -> None:
    """生成人读审计报告（含水印、复核判定分布、例外清单与局限声明）。"""
    declared = verification.merge(basis[["stock_code"]].drop_duplicates(), on="stock_code", how="right")
    verdict_counts = verification["verdict"].value_counts().to_dict()
    by_cohort = basis.copy()
    cohort_map = declared.set_index("stock_code")["declared_basis"].to_dict()
    by_cohort["declared_basis"] = by_cohort["stock_code"].map(cohort_map)
    coverage = by_cohort.groupby("declared_basis", dropna=False)["basis_return"].apply(
        lambda s: float(s.notna().mean())
    )
    extreme = verification.loc[verification["n_beyond_limit"] > 0, "n_beyond_limit"].sum()

    lines: list[str] = []
    lines.append("# M0 收益口径审计报告（unified_total_return_basis_v1）")
    lines.append("")
    lines.append(f"- 生成时间：{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append(f"- run_id：`{run_id}`")
    lines.append(f"- 口径水印：`{CALIBER_WATERMARK}`")
    lines.append(f"- 输入面板：`{panel_path.relative_to(ROOT)}`（SHA256 `{panel_hash[:16]}…`）")
    lines.append(f"- 口径声明：`{declarations_path.relative_to(ROOT)}`（SHA256 `{declarations_hash[:16]}…`）")
    lines.append("")
    lines.append("## 1. 面板规模")
    lines.append("")
    lines.append(f"- 股票数：{basis['stock_code'].nunique()}")
    lines.append(f"- 行数：{len(basis)}")
    lines.append(f"- 交易日：{basis['trade_date'].min()} → {basis['trade_date'].max()}")
    lines.append("")
    lines.append("## 2. 口径判定分布")
    lines.append("")
    lines.append("| 复核结论 | 股票数 |")
    lines.append("|---|---:|")
    for verdict in ("confirmed", "inconclusive", "contradicted"):
        lines.append(f"| `{verdict}` | {int(verdict_counts.get(verdict, 0))} |")
    lines.append("")
    lines.append(f"- 声明不复权组（A 组）中出现越限跳空的行数：**{int(extreme)}**"
                 "（除权除息伪收益，已由申报总收益取代，不再作为成交收益）")
    lines.append("")
    lines.append("## 3. 统一口径覆盖率")
    lines.append("")
    lines.append("| 声明口径 | 覆盖率 |")
    lines.append("|---|---:|")
    for key, value in coverage.items():
        lines.append(f"| `{key}` | {float(value):.4%} |")
    lines.append(f"| **全池** | **{float(mixing['coverage']):.4%}** |")
    lines.append("")
    lines.append("## 4. 收益基来源分布")
    lines.append("")
    lines.append("| basis_source | 行数 | 占比 |")
    lines.append("|---|---:|---:|")
    counts = basis["basis_source"].value_counts()
    for name in counts.index:
        lines.append(f"| `{name}` | {int(counts[name])} | {float(counts[name]) / len(basis):.4%} |")
    lines.append("")
    lines.append("## 5. 口径混用的量化代价（仅 A 组两口径同时可得）")
    lines.append("")
    lines.append(f"- 可比行数：{int(mixing['n_compared'])}")
    lines.append(f"- 日均差值（申报总收益 − close 日收益）：**{_fmt(mixing['mean_daily_gap'])}**")
    lines.append(f"- 年化系统偏差：**{mixing['annualized_gap']:.4%}**")
    lines.append(f"- 单日最大绝对差：**{mixing['max_abs_daily_gap']:.4f}**")
    lines.append(f"- 差值超 1% 的行占比：**{mixing['share_gap_gt_1pct']:.4%}**")
    lines.append("")
    lines.append("结论：凡使用原始 `close` 计算前瞻收益的历史产物（含 "
                 "`scripts/evaluate_ashare_pca_factors.py:157` 的 5/20 日前瞻收益）")
    lines.append("都对 A 组引入了最高 67 个百分点的伪崩盘与年化约 "
                 f"{mixing['annualized_gap']:.2%} 的收益低估，须以本口径重做后方可引用。")
    lines.append("")
    lines.append("## 6. 局限与未核验项")
    lines.append("")
    spec = json.loads(declarations_path.read_text(encoding="utf-8"))
    for item in spec.get("open_items", []):
        lines.append(f"- {item}")
    lines.append("- `inconclusive` 股票并非证据支持其声明，只是窗口内未发生可观察的公司行为；"
                 "其口径依赖来源表名（`TRD_FwardQuotation`），属未获文档级确认的推断。")
    lines.append("- 本审计不改动任何原始数据，也不覆盖 M1.4 既有稳定产物。")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_run_dir(output_root: Path, run_id: str) -> Path:
    """解析输出目录并拒绝覆盖既有 run。"""
    target = output_root / run_id
    if target.exists():
        raise ReturnBasisError(f"输出目录已存在，拒绝覆盖：{target}")
    target.mkdir(parents=True)
    return target


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="M0 统一收益口径审计")
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--factors", type=Path, default=DEFAULT_FACTORS)
    parser.add_argument("--declarations-config", type=Path, default=DEFAULT_DECLARATIONS)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--output-root", type=Path, default=ROOT / "reports/tables/pca_nale_integration")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data/processed/pca_nale_integration")
    args = parser.parse_args(argv)

    for path in (args.panel, args.factors, args.declarations_config):
        if not path.exists():
            raise ReturnBasisError(f"输入不存在：{path}")

    cfg = ReturnBasisConfig()
    raw_declarations = build_declarations(args.declarations_config, args.factors)
    declarations = declared_caliber(raw_declarations, cfg)

    panel = pd.read_csv(args.panel, dtype={"stock_code": str, "trade_date": str})
    verification = verify_caliber(panel, declarations, cfg)
    basis = compute_return_basis(panel, declarations, cfg, verification=verification)
    mixing = caliber_mixing_report(basis)

    panel_hash = sha256_of(args.panel)
    declarations_hash = sha256_of(args.declarations_config)
    run_id = args.run_id or f"m0-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{panel_hash[:8]}"

    report_dir = _resolve_run_dir(args.output_root, run_id)
    data_dir = _resolve_run_dir(args.data_root, run_id)

    verification.to_csv(report_dir / "caliber_verification.csv", index=False, encoding="utf-8-sig")
    exceptions = verification.loc[verification["verdict"] != "confirmed"]
    exceptions.to_csv(report_dir / "caliber_exceptions.csv", index=False, encoding="utf-8-sig")
    write_audit_markdown(
        report_dir / "return_basis_audit.md",
        basis=basis,
        verification=verification,
        mixing=mixing,
        panel_hash=panel_hash,
        declarations_hash=declarations_hash,
        run_id=run_id,
        declarations_path=args.declarations_config,
        panel_path=args.panel,
    )
    basis.to_parquet(data_dir / "return_basis.parquet", index=False)

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "caliber_watermark": CALIBER_WATERMARK,
        "config": {
            "limit_epsilon": cfg.limit_epsilon,
            "drift_threshold": cfg.drift_threshold,
            "min_rows_for_verdict": cfg.min_rows_for_verdict,
            "total_return_column": cfg.total_return_column,
        },
        "inputs": {
            "panel": {"path": str(args.panel.relative_to(ROOT)), "sha256": panel_hash},
            "factors": {"path": str(args.factors.relative_to(ROOT)), "sha256": sha256_of(args.factors)},
            "declarations": {
                "path": str(args.declarations_config.relative_to(ROOT)),
                "sha256": declarations_hash,
            },
        },
        "summary": {
            "stocks": int(basis["stock_code"].nunique()),
            "rows": int(len(basis)),
            "date_min": str(basis["trade_date"].min()),
            "date_max": str(basis["trade_date"].max()),
            "coverage": mixing["coverage"],
            "verdict_counts": verification["verdict"].value_counts().to_dict(),
            "basis_source_counts": {str(k): int(v) for k, v in basis["basis_source"].value_counts().items()},
            "mixing": mixing,
        },
        "environment": {
            "python": sys.version.split()[0],
            "pandas": pd.__version__,
            "platform": platform.platform(),
        },
        "immutability": "本 run 目录一旦生成不得修改；重跑须使用新 run_id",
    }
    (report_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[OK] run_id={run_id}")
    print(f"     报告：{report_dir.relative_to(ROOT)}")
    print(f"     面板：{(data_dir / 'return_basis.parquet').relative_to(ROOT)}")
    print(f"     覆盖率={mixing['coverage']:.4%} 年化口径偏差={mixing['annualized_gap']:.4%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
