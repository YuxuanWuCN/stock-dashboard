#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/run_p4_trend_gate_study.py —— 实验一：Trend Gate 逐日事件研究 + 1000 次安慰剂

修正版 v2（提交 21c3d5d0 的 M4 结果存在下列缺陷，本脚本逐条修正）：

| v1 缺陷 | v2 修正 |
|---|---|
| 跌停判定用 `hit_limit == -1`，而该列实际取值域为 {0,1}，条件恒不成立 | 从 `hit_limit` + 收益方向 + 收盘位置重建涨跌停**方向**，并做指纹校验 |
| 涨跌停判断的是**触发日**，且涨停分支算了不用 | 分别作用于**进场日**（涨停买不进）与**退出日**（跌停卖不出，顺延至下一可成交日） |
| 收益标签从触发日 t 的收盘价起算（t 日收盘在信号产生前已不可成交） | 统一改为 **t+1 收盘进场**，标签从进场价起算 |
| 安慰剂抽样池包含触发样本本身，抽样量固定 10,000 与触发数不符 | 抽样池严格排除触发样本；**主口径改为日期级重抽样**（真实的「随机日期」安慰剂），抽样量按各 horizon 分别匹配 |
| 经验 p 值只落盘、未进报告正文 | p 值落盘并强制写入 report.md |
| 对照组口径含糊（把含顺势组的非触发池称为"全样本对照组"） | 新增互斥的**纯对照组**（既非下行亦非顺势），原抽样池明确标注为含顺势组 |

用法：
    .venv\\Scripts\\python.exe scripts\\run_p4_trend_gate_study.py [--out-dir DIR] [--runs 1000]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.p4_real_data_core import (  # noqa: E402
    DEFAULT_HORIZONS,
    DEFAULT_MAX_DEFER,
    TREND_MA_WINDOW,
    TREND_MOM_WINDOW,
    assert_board_limit_discipline,
    attach_returns,
    build_trend_gate_events,
    daily_paired_test,
    date_cluster_bootstrap_diff,
    derive_limit_flags,
    dump_json,
    empirical_p_value,
    load_master_panel,
    run_date_placebo,
    run_date_matched_placebo,
    run_placebo,
    sha256_of_file,
    summarize_events,
    validate_return_basis,
)

PANEL_PATH = ROOT_DIR / "data" / "task_split" / "csmar_master" / "csmar_factor_panel_master.csv"
DEFAULT_OUT_DIR = ROOT_DIR / "reports" / "real_rebuild_20261010"
PLACEBO_SEED = 20261011
PLACEBO_RUNS = 1000
PRIMARY_PLACEBO_DESIGN = "date_level"


def _placebo_p_values(dist: dict, observed_by_horizon: dict, horizons) -> dict:
    """把安慰剂分布换算成经验 p 值。**每个 horizon 必须用它自己的观测均值。**

    v2 早期版本误用同一个（h20）观测值去算所有 horizon 的 p 值，导致 h5/h10 的
    p 值字段错得离谱；此处按 horizon 逐个取观测统计量，并有回归测试覆盖。
    """
    out = {}
    for h in horizons:
        block = dist.get(f"h{h}", {})
        observed = observed_by_horizon.get(f"h{h}")
        if "dist_ret_means" not in block:
            out[f"h{h}"] = {"error": block.get("error", "no_distribution")}
            continue
        out[f"h{h}"] = {
            "observed_mean_ret": observed,
            "placebo_mean": block["mean"],
            "placebo_std": block["std"],
            "placebo_ci_95": block["ci_95"],
            "p_one_sided_lower": empirical_p_value(block["dist_ret_means"], observed, "lower"),
            "p_one_sided_upper": empirical_p_value(block["dist_ret_means"], observed, "upper"),
            "p_two_sided": empirical_p_value(block["dist_ret_means"], observed, "two"),
        }
    return out


def _observed_by_horizon(group_summary: dict, horizons) -> dict:
    return {f"h{h}": group_summary[f"h{h}"]["mean_ret"] for h in horizons}


def run_trend_gate_study(
    panel_path: Path | str = PANEL_PATH,
    out_dir: Path | str = DEFAULT_OUT_DIR,
    horizons=DEFAULT_HORIZONS,
    n_runs: int = PLACEBO_RUNS,
    seed: int = PLACEBO_SEED,
) -> dict:
    """执行实验一并落盘 `trend_gate_event_study.json` 与 `trend_gate_placebo_1000.json`。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panel_path = Path(panel_path)

    print("[P4-1/2] Trend Gate 事件研究（修正版：无前视 + 真实涨跌停约束）")
    df = load_master_panel(panel_path)
    df = attach_returns(df)
    df, limit_validation = derive_limit_flags(df)
    board_discipline = assert_board_limit_discipline(df)
    return_basis = validate_return_basis(df)
    print(f"  > 面板 {len(df):,} 行 / {df['stock_code'].nunique()} 支 / {df['trade_date'].nunique()} 个交易日")
    print(f"  > 涨跌停重建：涨停 {limit_validation['n_limit_up']} 次，跌停 {limit_validation['n_limit_down']} 次，"
          f"方向不可判 {limit_validation['n_limit_direction_unknown']} 次")
    print(f"  > 板块越限校验：{board_discipline['checked_rows']:,} 行中越限 {board_discipline['violations']} 行")

    t0 = time.time()
    events = build_trend_gate_events(df, horizons=horizons, max_defer=DEFAULT_MAX_DEFER)
    print(f"  > 事件构造完成：{len(events):,} 条，用时 {time.time() - t0:.1f}s")

    trig = events["is_downtrend"].to_numpy()
    up = events["is_uptrend"].to_numpy()
    not_trig = ~trig
    neutral = not_trig & ~up          # 互斥纯对照：既非下行拦截，也非顺势
    tradable = events["entry_tradable"].to_numpy()

    groups = {
        "trigger_downtrend": trig,
        "uptrend": up,
        "neutral_control": neutral,
        "not_downtrend_pool": not_trig,   # 安慰剂抽样池口径（含顺势组），非互斥对照
    }

    constrained = {
        name: summarize_events(events, mask & tradable, horizons, mode="constrained")
        for name, mask in groups.items()
    }
    free = {
        name: summarize_events(events, mask, horizons, mode="free")
        for name, mask in groups.items()
    }

    print(f"  > 真实执行安慰剂：主口径=日期级重抽样（随机日期），次级=事件级抽样；各 {n_runs} 次")
    # 目标组各自的抽样池必须**排除目标组自身**，否则差值会被机械稀释：
    #   - 下行拦截组：池 = 非触发事件（= 顺势 + 纯对照），不含触发样本
    #   - 顺势组    ：池 = 纯对照组（互斥），因为"非触发池"里有 68% 是顺势组自身
    contexts = (
        ("constrained", "trigger_downtrend", not_trig & tradable, trig & tradable),
        ("constrained", "uptrend", neutral & tradable, up & tradable),
        ("free", "trigger_downtrend", not_trig, trig),
        ("free", "uptrend", neutral, up),
    )
    placebo: dict = {}
    placebo_p_values: dict = {}
    for design, fn in (
        ("date_level", run_date_placebo),
        ("date_matched", run_date_matched_placebo),
        ("event_level", run_placebo),
    ):
        placebo[design] = {}
        placebo_p_values[design] = {}
        for mode, name, pool_mask, gmask in contexts:
            dist = fn(events, pool_mask, gmask, horizons, n_runs=n_runs, seed=seed, mode=mode)
            placebo[design].setdefault(mode, {})[name] = dist
            observed = (constrained if mode == "constrained" else free)[name]
            placebo_p_values[design].setdefault(mode, {})[name] = _placebo_p_values(
                dist, _observed_by_horizon(observed, horizons), horizons
            )

    print("  > 日期级 cluster bootstrap 配对差（正式显著性检验）")
    bootstrap_diff: dict = {"constrained": {}, "free": {}}
    for mode, name, pool_mask, gmask in contexts:
        bootstrap_diff[mode][name] = date_cluster_bootstrap_diff(
            events, gmask, pool_mask, horizons, n_runs=n_runs, seed=seed, mode=mode
        )

    print("  > 逐日配对检验（同日目标组截面均值 − 抽样池截面均值，NW HAC）")
    paired = {
        "constrained": {
            name: daily_paired_test(events, gmask, pool_mask, horizons, mode="constrained")
            for mode, name, pool_mask, gmask in contexts if mode == "constrained"
        },
        "free": {
            name: daily_paired_test(events, gmask, pool_mask, horizons, mode="free")
            for mode, name, pool_mask, gmask in contexts if mode == "free"
        },
    }

    # 互斥组间对比（不依赖抽样池），直接回答"门禁把谁挑出来了"
    print("  > 互斥组间对比：触发 vs 纯对照、顺势 vs 纯对照、触发 vs 顺势")
    exclusive_pairs: dict = {"constrained": {}, "free": {}}
    for mode, tg, upv, nt, trad_flt in (
        ("constrained", trig, up, neutral, tradable),
        ("free", trig, up, neutral, np.ones(len(events), dtype=bool)),
    ):
        exclusive_pairs[mode]["trigger_vs_neutral"] = date_cluster_bootstrap_diff(
            events, tg & trad_flt, nt & trad_flt, horizons, n_runs=n_runs, seed=seed, mode=mode)
        exclusive_pairs[mode]["uptrend_vs_neutral"] = date_cluster_bootstrap_diff(
            events, upv & trad_flt, nt & trad_flt, horizons, n_runs=n_runs, seed=seed, mode=mode)
        exclusive_pairs[mode]["trigger_vs_uptrend"] = date_cluster_bootstrap_diff(
            events, tg & trad_flt, upv & trad_flt, horizons, n_runs=n_runs, seed=seed, mode=mode)

    # 进场拦截诊断必须在本组全部事件上统计（受约束样本已按 tradable 过滤，直接统计会恒为 0）
    entry_diagnostics = {
        name: {
            "n_events": int(mask.sum()),
            "entry_blocked_limit_up": int((mask & events["entry_block_limit_up"].to_numpy()).sum()),
            "entry_blocked_suspension": int((mask & events["entry_block_suspension"].to_numpy()).sum()),
            "entry_limit_unobserved": int((mask & events["entry_limit_unobserved"].to_numpy()).sum()),
            "entry_tradable": int((mask & tradable).sum()),
        }
        for name, mask in (("trigger_downtrend", trig), ("uptrend", up),
                           ("neutral_control", neutral), ("not_downtrend_pool", not_trig))
    }

    payload = {
        "experiment": "trend_gate_event_study",
        "version": "v2-rework",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": str(panel_path.relative_to(ROOT_DIR)).replace("\\", "/"),
        "data_sha256": sha256_of_file(panel_path),
        "placebo_design_meta": {
            design: {
                mode: {
                    name: {
                        f"h{h}": {k: v for k, v in dist.get(f"h{h}", {}).items() if not isinstance(v, list)}
                        for h in horizons
                    }
                    for name, dist in placebo[design][mode].items()
                }
                for mode in placebo[design]
            }
            for design in placebo
        },
        "universe": {
            "n_stocks_panel": int(df["stock_code"].nunique()),
            "n_stocks_with_limit_field": int(df.loc[df["limit_known"], "stock_code"].nunique()),
            "n_trading_days": int(df["trade_date"].nunique()),
            "date_range": [str(df["trade_date"].min()), str(df["trade_date"].max())],
        },
        "method": {
            "signal": f"mom_{TREND_MOM_WINDOW}d = close[t]/close[t-{TREND_MOM_WINDOW}] - 1; "
                      f"MA{TREND_MA_WINDOW} = mean(close[t-{TREND_MA_WINDOW}:t])（不含当日，仅用截至 t 日数据）",
            "downtrend_rule": "mom_20d <= 0 且 close[t] < MA60",
            "uptrend_rule": "mom_20d > 0 且 close[t] > MA60",
            "neutral_control_rule": "非下行拦截且非顺势（与两组互斥）",
            "entry": "t+1 日收盘进场（信号在 t 日收盘后才可知，t 日收盘价不可成交）",
            "exit": f"进场后第 H 个交易日；若该日跌停或停牌则顺延，最多 {DEFAULT_MAX_DEFER} 个交易日",
            "horizons": list(horizons),
            "liquidity_constraints": [
                "进场日涨停（收在最高价且涨跌幅触限）→ 无法买入，事件剔除出可交易样本",
                "进场日停牌/异常交易 → 无法买入，事件剔除",
                "退出日跌停 → 无法卖出，顺延至下一可成交日",
                "涨跌停状态不可观测的标的（100 支无 hit_limit 字段）→ 不进入可交易样本",
            ],
            "significance": "对每日截面均值序列做 Newey-West HAC 校正（重叠窗口与截面相关的处理）",
            "placebo": {
                "primary_design": PRIMARY_PLACEBO_DESIGN,
                "date_level_design": "每次有放回抽取与目标组相同数量的交易日，取该日期上抽样池内的全部事件；"
                                     "保留交易日内的横截面相关性，不低估标准误",
                "date_matched_design": "逐日从抽样池中抽取与该日目标组样本数相同的事件；"
                                       "额外把「事件数在日期上的分布」也固定住，排除日期加权差异带来的假显著",
                "event_level_design": "每次不放回抽取与目标组相同数量的事件（标的×日期）；"
                                      "把同一天的横截面相关性误当独立信息，会低估标准误，仅作次级参考",
                "pool": "同标的非触发事件，严格排除触发样本",
                "sample_size": "日期级按目标组占用的交易日数匹配；事件级按目标组该 horizon 的有效样本数匹配",
                "n_runs": int(n_runs),
                "seed": int(seed),
                "p_value_convention": "(count + 1) / (n + 1) 蒙特卡洛口径（Phipson & Smyth 2010）",
                "supplementary_test": "逐日配对检验：同日「目标组截面均值 − 抽样池截面均值」序列的 NW HAC t 值，"
                                      "配对消掉市场共同波动，效力更高，但不替代随机日期安慰剂",
            },
        },
        "limit_flag_reconstruction": limit_validation,
        "board_limit_discipline_check": board_discipline,
        "return_basis_validation": return_basis,
        "event_counts": {
            "total_events": int(len(events)),
            "trigger_downtrend": int(trig.sum()),
            "uptrend": int(up.sum()),
            "neutral_control": int(neutral.sum()),
            "not_downtrend_pool": int(not_trig.sum()),
            "trigger_tradable": int((trig & tradable).sum()),
            "uptrend_tradable": int((up & tradable).sum()),
            "neutral_tradable": int((neutral & tradable).sum()),
            "entry_blocked_limit_up": int(events["entry_block_limit_up"].sum()),
            "entry_blocked_suspension": int(events["entry_block_suspension"].sum()),
            "entry_limit_unobserved": int(events["entry_limit_unobserved"].sum()),
        },
        "groups_constrained": constrained,
        "groups_unconstrained": free,
        "entry_diagnostics": entry_diagnostics,
        "placebo_p_values": placebo_p_values,
        "daily_paired_test": paired,
        "cluster_bootstrap_diff": bootstrap_diff,
        "exclusive_group_comparisons": exclusive_pairs,
        "limitations": [
            "面板不含 ST 标记，无法识别 ±5% 涨跌幅限制的 ST 标的，其涨停/跌停判定按 10% 处理。",
            "hit_limit 字段仅覆盖 199 支标的，其余 100 支只能进入无约束口径。",
            "面板无开盘价与最高/最低价（A/C 组），进场价只能用收盘价近似，无法建模盘中成交。",
            "同一标的连续触发日的持有窗口高度重叠，已用日度截面均值 + NW HAC 与日期级 cluster bootstrap 缓解，但仍非独立同分布样本。",
            "「随机日期安慰剂」的分布只覆盖抽样池一侧的抽样方差；目标组自身的方差与两侧协方差由 "
            "cluster_bootstrap_diff（日期级 cluster bootstrap 配对差）承担，结论以后者为准。",
            "同日匹配安慰剂在触发最密集的交易日上会因池子事件不足而被截断，其基线与被检验统计量存在权重错配，"
            "故同时报告 target_mean_under_matched_weights 供同权重比较。",
        ],
    }

    study_path = dump_json(payload, out_dir / "trend_gate_event_study.json")
    placebo_path = dump_json(
        {
            "experiment": "trend_gate_placebo_1000",
            "version": "v2-rework",
            "generated_at": payload["generated_at"],
            "n_runs": int(n_runs),
            "seed": int(seed),
            "primary_design": PRIMARY_PLACEBO_DESIGN,
            "p_value_convention": "(count + 1) / (n + 1)",
            "distributions": placebo,
            "p_values": placebo_p_values,
        },
        out_dir / "trend_gate_placebo_1000.json",
    )
    print(f"  > 落盘: {study_path.name}, {placebo_path.name}")

    for name, mask in groups.items():
        c = constrained[name]
        f = free[name]
        print(f"  [{name}] 受约束 n={c['n_events']:,} 20日均值={c['h20']['mean_ret']:+.4f} "
              f"| 无约束 n={f['n_events']:,} 20日均值={f['h20']['mean_ret']:+.4f}")
    for design in ("date_level", "date_matched", "event_level"):
        for mode in ("constrained", "free"):
            for name, pv in placebo_p_values[design][mode].items():
                print(f"  [placebo/{design}/{mode}/{name}] 20日 p_lower={pv['h20']['p_one_sided_lower']:.4f} "
                      f"p_upper={pv['h20']['p_one_sided_upper']:.4f} p_two={pv['h20']['p_two_sided']:.4f} "
                      f"(观测 {pv['h20']['observed_mean_ret']:+.4f} vs 安慰剂 {pv['h20']['placebo_mean']:+.4f} "
                      f"± {pv['h20']['placebo_std']:.4f})")
    for mode in ("constrained", "free"):
        for name, blk in paired[mode].items():
            b20 = blk["h20"]
            print(f"  [paired/{mode}/{name}] 20日 日均差={b20['mean_diff']:+.4f} NW t={b20['nw_t']:+.2f} "
                  f"p={b20['nw_p_two_sided']:.4f}（目标组低于池子的交易日占比 {b20['share_days_target_lower']:.1%}）")
    for mode in ("constrained", "free"):
        for name, blk in bootstrap_diff[mode].items():
            e = blk["h20"]["event_weighted"]
            d = blk["h20"]["date_equal"]
            print(f"  [clusterboot/{mode}/{name}] 20日 事件加权差={e['observed_diff']:+.4f} "
                  f"SE={e['boot_se']:.4f} t={e['boot_t']:+.2f} p={e['boot_p_two_sided']:.4f} | "
                  f"等权日差={d['observed_diff']:+.4f} t={d['boot_t']:+.2f} p={d['boot_p_two_sided']:.4f}")
    for mode in ("constrained", "free"):
        for name, blk in exclusive_pairs[mode].items():
            e = blk["h20"]["event_weighted"]
            print(f"  [exclusive/{mode}/{name}] 20日 事件加权差={e['observed_diff']:+.4f} "
                  f"t={e['boot_t']:+.2f} p={e['boot_p_two_sided']:.4f}")

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="P4 实验一：Trend Gate 事件研究与 1000 次安慰剂")
    parser.add_argument("--panel", default=str(PANEL_PATH))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--runs", type=int, default=PLACEBO_RUNS)
    args = parser.parse_args()
    run_trend_gate_study(args.panel, args.out_dir, n_runs=args.runs)


if __name__ == "__main__":
    main()
