#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/run_p4_fama_macbeth.py —— 实验二：Fama-MacBeth HAC 截面回归（修正版 v2）

修正版 v2 相对 v1（commit 21c3d5d0）的关键修正：

1. **前视偏差（致命）**：v1 用 t 日收益 `ret` 回归 t 日因子。而面板中的 `mom_20d`
   （含 ret_t 的滚动累乘）、`amihud`（= |ret_t| / 成交额）、`price_pos`
   （= (close_t - low_t) / (high_t - low_t)）都以当日数据构造，与同期收益机械相关，
   于是得到 mom_20d t=14.09、price_pos t=33.92、年化溢价 +298.86% 这类虚高结果。
   v2 被解释变量统一改为 **t → t+1 的可交易收益 `ret_next`**，并把 v1 的同端口径
   作为「偏差演示」一并落盘留痕（`robustness.same_day_v1_bias_demo`），不作为结论使用。

2. 口径与检验补全：q 由有效截面期数 T 计算并落盘；普通 IID t 与 Newey-West HAC t 并列；
   移动区块 Bootstrap 区间（区块长度 T^(1/3)）；BH-FDR 与 Bonferroni 均给出并写明检验次数；
   Harvey |t|≥3 只作为「多因子发现」语境的标注，不单独充当结论。

3. 可交易性稳健性：另行给出剔除 t 日涨停观测（收盘价买不进）的版本。

用法：
    .venv\\Scripts\\python.exe scripts\\run_p4_fama_macbeth.py [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.p4_real_data_core import (  # noqa: E402
    ANNUALIZATION_DAYS,
    DEFAULT_FACTORS,
    RISK_FREE_RATE_ANNUAL,
    attach_returns,
    derive_limit_flags,
    dump_json,
    load_master_panel,
    run_fama_macbeth,
    sha256_of_file,
)

import numpy as np  # noqa: E402

PANEL_PATH = ROOT_DIR / "data" / "task_split" / "csmar_master" / "csmar_factor_panel_master.csv"
DEFAULT_OUT_DIR = ROOT_DIR / "reports" / "real_rebuild_20261010"
MIN_STOCKS_PER_PERIOD = 30
BOOTSTRAP_RUNS = 1000
BOOTSTRAP_SEED = 42


def _compact(run: dict) -> dict:
    """只保留结论层面字段，避免把每期系数重复塞进汇总。"""
    keep = {k: v for k, v in run.items() if k not in ("per_period_lambdas", "per_period_alpha", "per_period_dates")}
    return keep


def run_fama_macbeth_study(
    panel_path: Path | str = PANEL_PATH,
    out_dir: Path | str = DEFAULT_OUT_DIR,
) -> dict:
    """执行实验二并落盘 `fama_macbeth_hac_results.json`。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panel_path = Path(panel_path)

    print("[P4-2/2] Fama-MacBeth HAC 截面回归（被解释变量：t+1 可交易收益）")
    df = load_master_panel(panel_path)
    df = attach_returns(df)
    df, limit_validation = derive_limit_flags(df)

    primary = run_fama_macbeth(
        df,
        factors=DEFAULT_FACTORS,
        dependent="ret_next",
        min_stocks=MIN_STOCKS_PER_PERIOD,
        bootstrap_runs=BOOTSTRAP_RUNS,
        bootstrap_seed=BOOTSTRAP_SEED,
    )
    print(f"  > 有效截面期数 T={primary['n_periods']}，HAC 滞后阶数 q={primary['hac_lags']}，"
          f"标的数 {primary['n_stocks']}，观测 {primary['n_observations']:,}")

    print("  > 稳健性口径 A：剔除 t 日涨停（收盘价买不进）的观测 —— 重建口径")
    tradable = run_fama_macbeth(
        df,
        factors=DEFAULT_FACTORS,
        dependent="ret_next",
        min_stocks=MIN_STOCKS_PER_PERIOD,
        bootstrap_runs=BOOTSTRAP_RUNS,
        bootstrap_seed=BOOTSTRAP_SEED,
        drop_limit_up_at_t=True,
        limit_up_definition="reconstructed",
    )

    print("  > 稳健性口径 A2：同上，但只剔除字面口径 hit_limit==1 且 ret>0 的观测")
    tradable_literal = run_fama_macbeth(
        df,
        factors=DEFAULT_FACTORS,
        dependent="ret_next",
        min_stocks=MIN_STOCKS_PER_PERIOD,
        bootstrap_runs=BOOTSTRAP_RUNS,
        bootstrap_seed=BOOTSTRAP_SEED,
        drop_limit_up_at_t=True,
        limit_up_definition="literal",
    )
    print(f"    重建口径剔除 {tradable['n_rows_excluded']:,} 行 / 字面口径剔除 {tradable_literal['n_rows_excluded']:,} 行"
          "（差额来自 ret 缺失、方向只能由 close 收益推断的涨停样本）")

    print("  > 稳健性口径 B：仅使用官方复权收益 ret（不使用 close 回落收益）的标的")
    official = run_fama_macbeth(
        df[df["ret_next_official"].notna()],
        factors=DEFAULT_FACTORS,
        dependent="ret_next_official",
        min_stocks=MIN_STOCKS_PER_PERIOD,
        bootstrap_runs=BOOTSTRAP_RUNS,
        bootstrap_seed=BOOTSTRAP_SEED,
    )

    print("  > 偏差留痕口径 C：复现 v1 的同期收益回归，用于量化前视偏差幅度")
    same_day = run_fama_macbeth(
        df,
        factors=DEFAULT_FACTORS,
        dependent="ret",
        min_stocks=MIN_STOCKS_PER_PERIOD,
        bootstrap_runs=BOOTSTRAP_RUNS,
        bootstrap_seed=BOOTSTRAP_SEED,
    )

    bias_table = {}
    for f in primary["factors"]:
        t_same = same_day["factors_stats"][f]["newey_west_t"]
        t_next = primary["factors_stats"][f]["newey_west_t"]
        ratio = (
            abs(t_same) / abs(t_next)
            if np.isfinite(t_same) and np.isfinite(t_next) and abs(t_next) > 1e-12
            else None
        )
        bias_table[f] = {
            "same_day_t_v1_style": t_same,
            "next_day_t_corrected": t_next,
            "same_day_annualized_premium": same_day["factors_stats"][f]["annualized_premium_244d"],
            "next_day_annualized_premium": primary["factors_stats"][f]["annualized_premium_244d"],
            # >1 表示同期口径把 t 值放大（膨胀）；<1 表示同期口径反而更弱（收缩）
            "abs_t_ratio_same_day_over_next_day": ratio,
            "interpretation": "inflation" if (ratio or 0) > 1 else ("shrinkage" if ratio else "undefined"),
        }

    payload = {
        "experiment": "fama_macbeth_hac",
        "version": "v2-rework",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": str(panel_path.relative_to(ROOT_DIR)).replace("\\", "/"),
        "data_sha256": sha256_of_file(panel_path),
        "method": {
            "design": "两阶段 Fama-MacBeth：逐期截面 OLS 估计因子收益 λ_t，再对 λ_t 时序做 HAC 检验",
            "dependent_variable": "ret_next = 个股 t → t+1 日复权收益（可交易口径）",
            "factor_standardization": "逐期截面 z-score",
            "min_stocks_per_period": MIN_STOCKS_PER_PERIOD,
            "hac": "Newey-West Bartlett 核，滞后阶数 q = floor(4 * (T/100)^(2/9))，T 取有效截面期数",
            "block_bootstrap": f"移动区块 Bootstrap，区块长度 round(T^(1/3))，{BOOTSTRAP_RUNS} 次，种子 {BOOTSTRAP_SEED}",
            "multiple_testing": "Benjamini-Hochberg FDR 与 Bonferroni，检验次数 = 因子数",
            "annualization_days": ANNUALIZATION_DAYS,
            "risk_free_rate_annual": RISK_FREE_RATE_ANNUAL,
            "rf_note": "被解释变量为个股总收益（未扣无风险利率），λ 为总收益溢价；"
                       "另给出扣除日度 rf 后的超额年化溢价字段",
            "harvey_convention": "|NW t| >= 3.0 仅作为多因子发现语境的标注，检验次数随表附出",
        },
        "primary_next_day": _compact(primary),
        "per_period": {
            "note": "每期截面回归得到的因子收益 λ_t 与截距（第一阶段「滚动估计 β」的逐期结果）",
            "dates": primary["per_period_dates"],
            "factors": list(primary["factors"]),
            "lambdas": primary["per_period_lambdas"],
            "alpha": primary["per_period_alpha"],
        },
        "robustness": {
            "exclude_limit_up_at_t": _compact(tradable),
            "exclude_limit_up_at_t_literal": _compact(tradable_literal),
            "official_ret_only": _compact(official),
            "same_day_v1_bias_demo": _compact(same_day),
            "bias_table": bias_table,
        },
        "limit_flag_reconstruction": limit_validation,
        "limitations": [
            "面板中具备官方复权日收益 ret 的只有 99 支标的；主口径对其余标的采用 close 的收盘到收盘收益替代，"
            "替代误差已在 report.md §1 量化披露，但仍属测量噪声来源。",
            "ret 字段在约 100 支标的上缺失，属于上游数据交付缺口，本轮按可用真实数据如实报告，不补齐、不插值。",
            "被解释变量为个股总收益而非超额收益，λ 中混入市场收益成分；已同时给出扣除 rf 的超额口径字段。",
            "因子集合沿用 v1 的 6 个，未做因子正交化，因子间相关性会削弱单个 t 值的解释力。",
            "面板不含 ST 标记，无法识别 ±5% 涨跌幅限制标的；剔除涨停的稳健性口径按 |涨幅触限| 判定。",
        ],
        "reproduction_command": ".venv/Scripts/python scripts/run_p4_fama_macbeth.py",
    }

    path = dump_json(payload, out_dir / "fama_macbeth_hac_results.json")
    print(f"  > 落盘: {path.name}")
    print("  > 修正后（t+1 可交易收益）因子结果：")
    for f, st in primary["factors_stats"].items():
        print(f"    {f:<14} λ日={st['mean_risk_premium_daily']:+.5f}  年化={st['annualized_premium_244d']:+.2%}  "
              f"IID t={st['classic_t']:+.2f}  NW t={st['newey_west_t']:+.2f}  p={st['p_value_two_sided']:.4f}  "
              f"BH q={st['fdr_q_value']:.4f}  {'显著' if st['significant_5pct_fdr'] else '不显著'}")
    print("  > v1 同期收益口径（偏差留痕，不可作为结论）：")
    for f, st in same_day["factors_stats"].items():
        print(f"    {f:<14} NW t={st['newey_west_t']:+.2f}  年化={st['annualized_premium_244d']:+.2%}")

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="P4 实验二：Fama-MacBeth HAC 回归")
    parser.add_argument("--panel", default=str(PANEL_PATH))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    run_fama_macbeth_study(args.panel, args.out_dir)


if __name__ == "__main__":
    main()
