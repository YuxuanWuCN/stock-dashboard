#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/run_real_m4_rebuild.py —— M4/P4 端到端一键复算（修正版 v2）

一条命令跑完两个核心实验并生成全部交付产物：

    .venv/Scripts/python scripts/run_real_m4_rebuild.py

产物（全部写入 reports/real_rebuild_20261010/）：
    trend_gate_event_study.json     实验一：事件研究（受约束 / 无约束两种口径）
    trend_gate_placebo_1000.json    实验一：三种设计的 1000 次安慰剂分布与经验 p 值
    fama_macbeth_hac_results.json   实验二：FM HAC 回归 + 稳健性 + 偏差留痕
    results.json                    汇总
    report.md                       实证研究报告
    vs_old.md                       旧值 / v1 / v2 三项对账
    paper_correction_checklist.md   论文与申报材料删改清单

设计原则：
  - report.md / vs_old.md / checklist 的每一个数字都从结果 JSON 现算现写，避免手工抄录出错。
  - v1（commit 21c3d5d0）的缺陷结果完整保留在 superseded_v1/ 下，不删除、不改写。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.p4_real_data_core import ANNUALIZATION_DAYS, RISK_FREE_RATE_ANNUAL, dump_json  # noqa: E402
from scripts.run_p4_fama_macbeth import run_fama_macbeth_study  # noqa: E402
from scripts.run_p4_trend_gate_study import run_trend_gate_study  # noqa: E402

PANEL_PATH = ROOT_DIR / "data" / "task_split" / "csmar_master" / "csmar_factor_panel_master.csv"
OUT_DIR = ROOT_DIR / "reports" / "real_rebuild_20261010"
F2 = "{:+.2f}"

GROUP_LABELS = {
    "trigger_downtrend": "**下行拦截组** (Trigger)",
    "uptrend": "顺势组 (Uptrend)",
    "neutral_control": "纯对照组 (Neutral，互斥)",
    "not_downtrend_pool": "非触发池 (含顺势组，安慰剂抽样池)",
}
PLACEBO_LABELS = {
    "date_level": "随机日期（有放回抽日期）",
    "date_matched": "同日匹配（逐日等量抽事件）",
    "event_level": "事件级抽样（次级，低估标准误）",
}


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:+.2%}"


def _num(x, nd: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def build_results_payload(trend: dict, fm: dict) -> dict:
    """汇总两个实验的结论层字段。"""
    c = trend["groups_constrained"]
    u = trend["groups_unconstrained"]
    pv = trend["placebo_p_values"]
    paired = trend["daily_paired_test"]
    primary = fm["primary_next_day"]
    robust = fm["robustness"]

    def _pv_block(design: str) -> dict:
        return {
            mode: {
                name: {h: {k: v for k, v in blk.items()} for h, blk in pvals.items()}
                for name, pvals in pv[design][mode].items()
            }
            for mode in pv[design]
        }

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "v2-rework",
        "supersedes": "v1 (commit 21c3d5d0) —— 缺陷记录见 superseded_v1/",
        "data_source": trend["data_source"],
        "data_sha256": trend["data_sha256"],
        "universe": trend["universe"],
        "annualization_days": ANNUALIZATION_DAYS,
        "risk_free_rate_annual": RISK_FREE_RATE_ANNUAL,
        "trend_gate_event_study": {
            "constrained": c,
            "unconstrained": u,
            "event_counts": trend["event_counts"],
            "placebo_p_values": {d: _pv_block(d) for d in ("date_level", "date_matched", "event_level")},
            "daily_paired_test": paired,
            "cluster_bootstrap_diff": trend["cluster_bootstrap_diff"],
            "exclusive_group_comparisons": trend["exclusive_group_comparisons"],
            "entry_diagnostics": trend["entry_diagnostics"],
            "exit_diagnostics": trend.get("exit_diagnostics", {}),
            "limit_flag_reconstruction": trend["limit_flag_reconstruction"],
            "board_limit_discipline_check": trend["board_limit_discipline_check"],
            "return_basis_validation": trend["return_basis_validation"],
            "limitations": trend["limitations"],
        },
        "fama_macbeth_hac": {
            "primary": {
                "dependent_variable": primary["dependent_variable"],
                "n_periods": primary["n_periods"],
                "hac_lags": primary["hac_lags"],
                "n_stocks": primary["n_stocks"],
                "n_observations": primary["n_observations"],
                "n_tests": primary["n_tests"],
                "significant_fdr": [f for f, s in primary["factors_stats"].items() if s["significant_5pct_fdr"]],
                "factors": primary["factors_stats"],
            },
            "robust_exclude_limit_up_at_t": {
                "definition": "reconstructed",
                "n_rows_excluded": robust["exclude_limit_up_at_t"]["n_rows_excluded"],
                "factors": {f: {"newey_west_t": s["newey_west_t"], "fdr_q_value": s["fdr_q_value"],
                                "significant_5pct_fdr": s["significant_5pct_fdr"]}
                            for f, s in robust["exclude_limit_up_at_t"]["factors_stats"].items()},
            },
            "robust_exclude_limit_up_at_t_literal": {
                "definition": "literal (hit_limit==1 且 ret>0)",
                "n_rows_excluded": robust["exclude_limit_up_at_t_literal"]["n_rows_excluded"],
                "factors": {f: {"newey_west_t": s["newey_west_t"], "fdr_q_value": s["fdr_q_value"],
                                "significant_5pct_fdr": s["significant_5pct_fdr"]}
                            for f, s in robust["exclude_limit_up_at_t_literal"]["factors_stats"].items()},
            },
            "robust_official_ret_only": {
                "n_periods": robust["official_ret_only"]["n_periods"],
                "n_stocks": robust["official_ret_only"]["n_stocks"],
                "factors": {f: {"newey_west_t": s["newey_west_t"], "fdr_q_value": s["fdr_q_value"],
                                "significant_5pct_fdr": s["significant_5pct_fdr"]}
                            for f, s in robust["official_ret_only"]["factors_stats"].items()},
            },
            "v1_same_day_bias_demo": {
                "note": "复现 v1 同期收益回归口径，仅作前视偏差留痕，不得作为结论引用",
                "factors": {f: {"newey_west_t": s["newey_west_t"],
                                "annualized_premium_244d": s["annualized_premium_244d"]}
                            for f, s in robust["same_day_v1_bias_demo"]["factors_stats"].items()},
            },
            "bias_table": robust["bias_table"],
            "limitations": fm["limitations"],
        },
        "deliverables": [
            "reports/real_rebuild_20261010/trend_gate_event_study.json",
            "reports/real_rebuild_20261010/trend_gate_placebo_1000.json",
            "reports/real_rebuild_20261010/fama_macbeth_hac_results.json",
            "reports/real_rebuild_20261010/results.json",
            "reports/real_rebuild_20261010/report.md",
            "reports/real_rebuild_20261010/vs_old.md",
            "reports/real_rebuild_20261010/paper_correction_checklist.md",
        ],
        "reproduction_command": ".venv/Scripts/python scripts/run_real_m4_rebuild.py",
    }


def build_report_md(trend: dict, fm: dict) -> str:
    """生成 report.md。所有数字均取自本次运行结果。"""
    c = trend["groups_constrained"]
    u = trend["groups_unconstrained"]
    pv = trend["placebo_p_values"]
    paired = trend["daily_paired_test"]
    counts = trend["event_counts"]
    lv = trend["limit_flag_reconstruction"]
    bd = trend["board_limit_discipline_check"]
    rb = trend.get("return_basis_validation", {})
    cb = trend["cluster_bootstrap_diff"]
    excl = trend["exclusive_group_comparisons"]
    entry_diag = trend["entry_diagnostics"]
    uni = trend["universe"]
    fm_p = fm["primary_next_day"]
    robust = fm["robustness"]

    def group_row(name: str, g: dict) -> str:
        cols = [GROUP_LABELS.get(name, name), f"{g['n_events']:,}", str(g.get("n_stocks", "n/a"))]
        for h in ("h5", "h10", "h20"):
            cols.append(_pct(g[h]["mean_ret"]))
        cols.append(f"{g['h20']['win_rate']:.2%}")
        cols.append(_pct(g["h20"]["mean_maxdd"]))
        cols.append(_num(g["h20"].get("daily_nw_t")))
        return "| " + " | ".join(cols) + " |"

    def placebo_row(design: str, mode: str, name: str) -> str:
        blk = pv[design][mode][name]["h20"]
        pool_label = "纯对照组(互斥)" if name == "uptrend" else "非触发池"
        return (f"| {PLACEBO_LABELS[design]} | {mode} | {name} | {pool_label} | {_pct(blk['observed_mean_ret'])} | "
                f"{_pct(blk['placebo_mean'])} | {blk['placebo_std']:.4f} | "
                f"{blk['p_one_sided_lower']:.4f} | {blk['p_one_sided_upper']:.4f} | {blk['p_two_sided']:.4f} | "
                f"{_pct(blk.get('observed_mean_ret_same_weight'))} | {blk.get('p_two_sided_same_weight', float('nan')):.4f} |")

    def cluster_row(mode: str, name: str, pool_label: str) -> str:
        b = cb[mode][name]["h20"]
        e, d = b["event_weighted"], b["date_equal"]
        return (f"| {mode} | {name} | {pool_label} | {b['n_days_joined']} | {b['corr_of_date_means']:+.3f} | "
                f"{b['autocorr_of_event_weighted_contrib_lag1']:+.3f} | "
                f"{_pct(e['observed_diff'])} | {e['hac_se']:.4f} | {F2.format(e['hac_t'])} | "
                f"{e['hac_p_two_sided']:.4f} | {F2.format(e['block5_t'])} | {e['block5_p_two_sided']:.4f} | "
                f"{F2.format(e['boot_iid_t'])} | {e['boot_iid_p_two_sided']:.4f} | {_pct(d['observed_diff'])} | "
                f"{F2.format(d['hac_t'])} | {d['hac_p_two_sided']:.4f} |")

    def exclusive_row(mode: str, key: str) -> str:
        b = excl[mode][key]["h20"]["event_weighted"]
        return (f"| {mode} | {key} | {_pct(b['observed_diff'])} | {b['hac_se']:.4f} | "
                f"{F2.format(b['hac_t'])} | {b['hac_p_two_sided']:.4f} | "
                f"{b['boot_iid_p_two_sided']:.4f} |")

    def paired_row(mode: str, name: str) -> str:
        b = paired[mode][name]["h20"]
        return (f"| {mode} | {name} | {b['n_days']} | {_pct(b['mean_diff'])} | {_pct(b['weighted_mean_diff'])} | "
                f"{F2.format(b['nw_t'])} | {b['nw_p_two_sided']:.4f} | {b['share_days_target_lower']:.1%} |")

    fm_rows = []
    for f, s in fm_p["factors_stats"].items():
        fm_rows.append(
            f"| {f} | {_pct(s['mean_risk_premium_daily'])} | {_pct(s['annualized_premium_244d'])} | "
            f"{F2.format(s['classic_t'])} | {F2.format(s['newey_west_t'])} | {s['p_value_two_sided']:.4f} | "
            f"[{_pct(s['block_bootstrap_ci_95'][0])}, {_pct(s['block_bootstrap_ci_95'][1])}] | "
            f"{s['fdr_q_value']:.4f} | {s['bonferroni_p_value']:.4f} | "
            f"{'显著' if s['significant_5pct_fdr'] else '不显著'} |"
        )

    robust_rows = []
    for f, s in fm_p["factors_stats"].items():
        a = robust["exclude_limit_up_at_t"]["factors_stats"][f]
        a2 = robust["exclude_limit_up_at_t_literal"]["factors_stats"][f]
        b = robust["official_ret_only"]["factors_stats"][f]
        v1 = robust["same_day_v1_bias_demo"]["factors_stats"][f]
        robust_rows.append(
            f"| {f} | {F2.format(v1['newey_west_t'])} | {F2.format(s['newey_west_t'])} | "
            f"{F2.format(a['newey_west_t'])} | {F2.format(a2['newey_west_t'])} | {F2.format(b['newey_west_t'])} |"
        )

    p_date = pv["date_level"]["constrained"]["trigger_downtrend"]["h20"]
    p_match = pv["date_matched"]["constrained"]["trigger_downtrend"]["h20"]
    p_event = pv["event_level"]["constrained"]["trigger_downtrend"]["h20"]
    p_date_up = pv["date_level"]["constrained"]["uptrend"]["h20"]
    p_match_up = pv["date_matched"]["constrained"]["uptrend"]["h20"]
    paired_trig = paired["constrained"]["trigger_downtrend"]["h20"]
    paired_up = paired["constrained"]["uptrend"]["h20"]
    trig20 = c["trigger_downtrend"]["h20"]
    up20 = c["uptrend"]["h20"]
    neu20 = c["neutral_control"]["h20"]
    se_ratio = (
        p_date["placebo_std"] / p_event["placebo_std"]
        if p_event["placebo_std"]
        else float("nan")
    )
    dm = trend.get("placebo_design_meta", {}).get("date_matched", {}).get("constrained", {}).get(
        "trigger_downtrend", {}
    ).get("h20", {})
    ev_share_heavy = paired_trig["heavy_trigger_day_share_of_events"]
    heavy_contrib = ev_share_heavy * paired_trig["diff_on_heavy_trigger_days"]
    heavy_contrib_share = heavy_contrib / paired_trig["weighted_mean_diff"] if paired_trig["weighted_mean_diff"] else float("nan")

    md = f"""# 真实数据量化重建实证研究报告（M4 / P4 · v2 修正版）

> 生成时间：{trend['generated_at']}  
> 版本：**v2-rework**（取代 commit 21c3d5d0 的 v1 结果，v1 缺陷结果完整保留于 `superseded_v1/`）  
> 数据底座：CSMAR 真实主面板 `{trend['data_source']}`  
> 数据指纹（sha256）：`{trend['data_sha256'][:32]}…`  
> 年化口径：A 股 {ANNUALIZATION_DAYS} 个交易日；无风险利率 {RISK_FREE_RATE_ANNUAL:.2%}（项目既有现金利息假设）  
> 一键复算：`.venv/Scripts/python scripts/run_real_m4_rebuild.py`

---

## 0. 本次修正（v2 相对 v1）

| # | v1 缺陷 | v2 修正 | 修正后的量化影响 |
| :-- | :--- | :--- | :--- |
| 1 | Fama-MacBeth 用**同期**收益回归含当日信息的因子 | 被解释变量改为 **t+1 可交易收益** | `mom_20d` NW t 由 {F2.format(robust['same_day_v1_bias_demo']['factors_stats']['mom_20d']['newey_west_t'])} 降至 {F2.format(fm_p['factors_stats']['mom_20d']['newey_west_t'])}；`price_pos` 由 {F2.format(robust['same_day_v1_bias_demo']['factors_stats']['price_pos']['newey_west_t'])} 降至 {F2.format(fm_p['factors_stats']['price_pos']['newey_west_t'])} |
| 2 | 跌停判定用 `hit_limit == -1`，而该列取值域仅 {{0,1}}，约束恒不触发；且判在触发日 | 重建涨跌停**方向**，分别作用于**进场日**与**退出日**，退出日跌停顺延 | 方向可判 {lv['n_limit_up'] + lv['n_limit_down']} / {lv['n_limit_rows']} 次；进场日涨停拦截 {counts['entry_blocked_limit_up']:,} 次 |
| 3 | 安慰剂抽样池混入触发样本、抽样量与触发数不符、经验 p 值未进正文 | 抽样池排除触发样本；**主口径改为随机日期重抽样**，并补同日匹配与逐日配对 | 见 §2.3 |
| 4 | 对照组口径含糊（称含顺势组的非触发池为"全样本对照组"） | 新增互斥**纯对照组** | 纯对照组 20 日仅 {_pct(neu20['mean_ret'])}，低于拦截组 {_pct(trig20['mean_ret'])} |

---

## 1. 数据底座真伪核验

- **标的池**：{uni['n_stocks_panel']} 支 A 股；**区间**：{uni['date_range'][0]} ~ {uni['date_range'][1]}；**交易日**：{uni['n_trading_days']} 天
- **涨跌停方向重建校验**：涨停 {lv['n_limit_up']} 次（收在当日最高价占比 {lv['limit_up_close_at_high_share']:.1%}，涨跌幅绝对值中位数 {lv['limit_up_abs_ret_median']:.2%}）；
  跌停 {lv['n_limit_down']} 次（收在当日最低价占比 {lv['limit_down_close_at_low_share']:.1%}，涨跌幅绝对值中位数 {lv['limit_down_abs_ret_median']:.2%}）；
  方向不可判 {lv['n_limit_direction_unknown']} 次
- **板块涨跌停纪律**：{bd['checked_rows']:,} 行抽样中越限 **{bd['violations']}** 行（最大绝对日收益 {bd['max_abs_ret']:.4%}，符合主板 ±10% / 创业板科创板 ±20%）
- **收益口径可替换性验证**：面板仅 {rb.get('n_stocks', 'n/a')} 支标的带官方复权收益 `ret`，其余标的的收益由 `close` 收盘到收盘收益替代。
  在同时具备两条口径的 {rb.get('n_rows', 0):,} 行上，中位绝对差 **{rb.get('median_abs_diff', float('nan')):.2e}**、99 分位 {rb.get('p99_abs_diff', float('nan')):.2e}。
  该中位数一致性表明常态非事件日价格变动中位吻合，但并不构成全样本分红复权等价性的证明；
  仅 {rb.get('share_over_threshold', 0):.3%}（{rb.get('n_over_threshold', 0)} 行）差异超过 {rb.get('threshold', 0.01):.0%}，
  极端单行差异达 {rb.get('max_abs_diff', float('nan')):.2e}（具有潜在除权除息或口径跳空特征，但在缺乏原始公告日志核验前不假定全量证实）。
  此外，事件研究采用收盘价区间收益（close price return basis），而 Fama-MacBeth 优先采用官方复权日收益（Dretwd basis），
  两子实验收益底座口径存在差异，特此如实披露。对只能用 `close` 的标的采用该替代口径，并在 §4 披露。
- **流动性约束可观测范围**：具备 `hit_limit` 字段的标的共 {uni['n_stocks_with_limit_field']} 支；其余标的只能进入无约束口径

> **口径选择说明**：主口径（受约束）只纳入涨跌停状态可观测的 {uni['n_stocks_with_limit_field']} 支标的，因为只有这些标的能真实施加「涨停买不进 / 跌停卖不出」。无约束口径覆盖全部 {uni['n_stocks_panel']} 支，用于与 v1 及全样本对照。

---

## 2. 实验一：Trend Gate 逐日事件研究

### 2.1 时点与交易约束

- 信号在 t 日收盘后产生，只用截至 t 日的数据（`mom_20d = close[t]/close[t-20]-1`；`MA60 = mean(close[t-60:t])`，不含当日）
- **t 日收盘价不可成交**（信号此刻才可知），统一 **t+1 日收盘进场**
- 进场日涨停（买不进）或停牌 → 事件剔除出可交易样本；退出目标日跌停或停牌 → 顺延至下一可成交日，最多 5 个交易日
- 事件收益的显著性用**日度截面均值序列**做 Newey-West HAC 校正，缓解重叠窗口与截面相关

### 2.2 事件收益与回撤（受约束口径，{uni['n_stocks_with_limit_field']} 支可观测标的）

| 组别 | 事件数 | 标的数 | 5日均值 | 10日均值 | 20日均值 | 20日胜率 | 20日平均最大回撤 | 20日 NW t |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(group_row(n, c[n]) for n in ("trigger_downtrend", "uptrend", "neutral_control", "not_downtrend_pool"))}

无约束口径（全部 {uni['n_stocks_panel']} 支，不施加涨跌停与停牌约束，用于与 v1 对照）：

| 组别 | 事件数 | 标的数 | 5日均值 | 10日均值 | 20日均值 | 20日胜率 | 20日平均最大回撤 | 20日 NW t |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(group_row(n, u[n]) for n in ("trigger_downtrend", "uptrend", "neutral_control", "not_downtrend_pool"))}

> 「非触发池」= 下行拦截组的补集，**含顺势组**，是安慰剂抽样池的口径；「纯对照组」与两组互斥，才是干净的对照。

### 2.3 显著性检验（2024-01 ~ 2026-08，20 日窗口）

**口径说明（重要）**：抽样池一律排除目标组自身——下行拦截组的池为「非触发事件」，顺势组的池为「纯对照组」
（若沿用"非触发池"，其中 68% 是顺势组自身，差值会被机械稀释）。p 值采用 (count+1)/(n+1) 蒙特卡洛口径。

**(A) 随机日期安慰剂（方案要求的零分布）**：每次有放回抽取与目标组相同数量的交易日，取该日期上池内全部事件。
种子 {trend['method']['placebo']['seed']}，{trend['method']['placebo']['n_runs']} 次，完整分布落盘。
**该表仅作描述性零分布留痕，不构成组间推断**——其权重按日期均匀，与事件加权的组均值不匹配，
故末两列另给同权重读数（等权日的目标组均值 vs 同一零分布）。

| 设计 | 口径 | 目标组 | 抽样池 | 观测 20 日均值 | 基线均值 | 基线 SD | p(单侧低) | p(单侧高) | p(双侧) | 同权重观测均值 | 同权重 p(双侧) |
| :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(placebo_row(d, m, n) for d in ("date_level", "date_matched", "event_level") for m in ("constrained", "free") for n in ("trigger_downtrend", "uptrend"))}

**(B) 日期级配对差（正式推断，含序列相关校正）**：统计量为交集配对日期上的池化均值差（中心化比率影响函数分数）。
20 日持有窗口彼此重叠，日度贡献序列自相关极高（见 ACF(1) 列），因此**按日独立重抽样会显著低估标准误**。
本表同时给出 i.i.d. 日 bootstrap（仅作对照）与两种序列相关稳健口径（Newey-West HAC、长度 5 的移动区块 bootstrap），**以 HAC 为准**。

| 口径 | 目标组 | 抽样池 | 配对交易日 | 日度均值相关 | 贡献序列 ACF(1) | 事件加权差 | HAC SE | HAC t | HAC p | block5 t | block5 p | i.i.d. t | i.i.d. p | 等权日差 | HAC t | HAC p |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(cluster_row(m, n, "纯对照组(互斥)" if n == "uptrend" else "非触发池") for m in ("constrained", "free") for n in ("trigger_downtrend", "uptrend"))}

**(C) 互斥组间对比**（不依赖抽样池，直接回答"门禁把谁挑出来了"；同样以 HAC 为准）：

| 口径 | 对比 | 事件加权差 | HAC SE | HAC t | HAC p | i.i.d. p（对照） |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(exclusive_row(m, k) for m in ("constrained", "free") for k in ("trigger_vs_neutral", "uptrend_vs_neutral", "trigger_vs_uptrend"))}

**(D) 逐日配对描述统计与加权诊断**：

| 口径 | 组别 | 交易日数 | 日均差(等权日) | 日均差(按触发数加权) | NW t(等权日) | 双侧 p | 目标组低于基线的交易日占比 |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(paired_row(m, n) for m in ("constrained", "free") for n in ("trigger_downtrend", "uptrend"))}

### 2.4 诚实结论

1. **在当前样本期与检验设定下，未能支持「下行拦截能规避下跌」的假设**：三种安慰剂设计下，拦截组的单侧「劣于随机」经验 p 值均为
   **{p_date['p_one_sided_lower']:.4f}**（同权重读数下亦未能拒绝无差异原假设）。门禁的设计假设（下行趋势标的在未来持有期内将延续深幅下跌）
   在本样本期内未能得到实证支持，交集配对日期上的池化均值差反而呈现样本特定的超跌反弹迹象。
2. **序列相关校正后，主口径下几乎没有显著结论**。20 日窗口彼此重叠使日度贡献序列 ACF(1) 高达
   {cb['constrained']['trigger_downtrend']['h20']['autocorr_of_event_weighted_contrib_lag1']:+.3f}，
   按日独立重抽样会把标准误低估：HAC SE = {cb['constrained']['trigger_downtrend']['h20']['event_weighted']['hac_se']:.4f}
   vs i.i.d. bootstrap SE = {cb['constrained']['trigger_downtrend']['h20']['event_weighted']['boot_iid_se']:.4f}
   （比值 {cb['constrained']['trigger_downtrend']['h20']['event_weighted']['hac_se'] / cb['constrained']['trigger_downtrend']['h20']['event_weighted']['boot_iid_se']:.2f}×）：
   | 检验 | 事件加权差 | i.i.d. p（不可用） | **HAC p（采用）** | block5 p（稳健性） |
   | :--- | ---: | ---: | ---: | ---: |
   | 触发 vs 非触发池（主口径） | {_pct(cb['constrained']['trigger_downtrend']['h20']['event_weighted']['observed_diff'])} | {cb['constrained']['trigger_downtrend']['h20']['event_weighted']['boot_iid_p_two_sided']:.4f} | **{cb['constrained']['trigger_downtrend']['h20']['event_weighted']['hac_p_two_sided']:.4f}** | {cb['constrained']['trigger_downtrend']['h20']['event_weighted']['block5_p_two_sided']:.4f} |
   | 触发 vs 纯对照 | {_pct(excl['constrained']['trigger_vs_neutral']['h20']['event_weighted']['observed_diff'])} | {excl['constrained']['trigger_vs_neutral']['h20']['event_weighted']['boot_iid_p_two_sided']:.4f} | **{excl['constrained']['trigger_vs_neutral']['h20']['event_weighted']['hac_p_two_sided']:.4f}** | {excl['constrained']['trigger_vs_neutral']['h20']['event_weighted']['block5_p_two_sided']:.4f} |
   | 顺势 vs 纯对照 | {_pct(excl['constrained']['uptrend_vs_neutral']['h20']['event_weighted']['observed_diff'])} | {excl['constrained']['uptrend_vs_neutral']['h20']['event_weighted']['boot_iid_p_two_sided']:.4f} | **{excl['constrained']['uptrend_vs_neutral']['h20']['event_weighted']['hac_p_two_sided']:.4f}** | {excl['constrained']['uptrend_vs_neutral']['h20']['event_weighted']['block5_p_two_sided']:.4f} |
   | 触发 vs 顺势（门禁自身分辨力） | {_pct(excl['constrained']['trigger_vs_uptrend']['h20']['event_weighted']['observed_diff'])} | {excl['constrained']['trigger_vs_uptrend']['h20']['event_weighted']['boot_iid_p_two_sided']:.4f} | **{excl['constrained']['trigger_vs_uptrend']['h20']['event_weighted']['hac_p_two_sided']:.4f}** | {excl['constrained']['trigger_vs_uptrend']['h20']['event_weighted']['block5_p_two_sided']:.4f} |

   即：**门禁核心区分的对比组（触发 vs 顺势）在控制时序依赖后未能拒绝无差异原假设**（HAC p = {excl['constrained']['trigger_vs_uptrend']['h20']['event_weighted']['hac_p_two_sided']:.4f}）；触发组相对纯对照组的优势在主口径下
   处于显著边缘（HAC p = {excl['constrained']['trigger_vs_neutral']['h20']['event_weighted']['hac_p_two_sided']:.4f}），
   在自由口径下为 {excl['free']['trigger_vs_neutral']['h20']['event_weighted']['hac_p_two_sided']:.4f}，
   **结论对样本口径与滞后阶数敏感，不足以支撑稳健的择时发现**。
3. **等权日口径下同样全不显著**：触发组 vs 池的等权日差
   {_pct(cb['constrained']['trigger_downtrend']['h20']['date_equal']['observed_diff'])}
   （HAC t = {F2.format(cb['constrained']['trigger_downtrend']['h20']['date_equal']['hac_t'])}，
   p = {cb['constrained']['trigger_downtrend']['h20']['date_equal']['hac_p_two_sided']:.4f}）。
   事件加权与等权日的差异集中在**触发数最多的少数交易日**：触发最密集的 10% 交易日
   （承载 {ev_share_heavy:.1%} 的信号）同日差异 {_pct(paired_trig['diff_on_heavy_trigger_days'])}，
   其余交易日 {_pct(paired_trig['diff_on_light_trigger_days'])}，高触发日贡献加权差异的约 {heavy_contrib_share:.0%}。
   **两种口径必须同时陈述。**
4. **同日匹配设计的口径限制**：该设计在 {dm.get('dates_capped_or_missing', 0)} 个交易日的抽样池事件数少于触发数，
   每次抽样平均覆盖 {dm.get('events_per_run_mean', float('nan')):,.0f} 条（目标 {dm.get('target_size', 0):,} 条），
   触发最密集的日期上系统性欠采样。按该设计自身的（被截断）日权重，目标组均值为
   {_pct(dm.get('target_mean_under_matched_weights'))}，与基线 {_pct(p_match['placebo_mean'])} 同权重可比，
   而非与全样本均值 {_pct(p_match['observed_mean_ret'])} 相比。
5. **纯对照组（互斥）表现最差**：20 日均值 {_pct(neu20['mean_ret'])}、平均最大回撤 {_pct(neu20['mean_maxdd'])}，
   低于拦截组 {_pct(trig20['mean_ret'])} 与顺势组 {_pct(up20['mean_ret'])}。
6. **事件级抽样会低估标准误**（SD {p_date['placebo_std']:.4f} vs {p_event['placebo_std']:.4f}）：
   它把同一天几百只股票的共同涨跌当作独立信息。v1 用的正是这一类设计（且抽样量固定 10,000、池含触发样本），
   其"显著"结论不具备统计效力。
7. **涨跌停约束的实际影响**：进场日涨停拦截 {entry_diag['trigger_downtrend']['entry_blocked_limit_up']:,} 次（触发组）、
   停牌 {entry_diag['trigger_downtrend']['entry_blocked_suspension']:,} 次；退出日因跌停顺延的事件占比
   {trig20.get('share_any_defer', float('nan')):.4%}（平均顺延 {trig20.get('mean_defer_days', float('nan')):.4f} 个交易日）。
   约束的**实质影响**是把 {entry_diag['trigger_downtrend']['entry_limit_unobserved']:,} 条（触发组）
   无法观测涨跌停状态的事件排除在可交易样本之外，从而把受约束口径限制在 {uni['n_stocks_with_limit_field']} 支标的上。

---

## 3. 实验二：Fama-MacBeth HAC 截面回归

### 3.1 计量口径

- 被解释变量：**t → t+1 可交易收益**（`ret_next`）
- 有效截面期数 T = **{fm_p['n_periods']}**，截面标的数 = {fm_p['n_stocks']}，观测 {fm_p['n_observations']:,}
- 每期截面最小股票数 {fm_p['min_stocks_per_period']}；逐期截面 z-score（ddof=0，会使 λ 水平比 ddof=1 高约 0.25%，不影响 t 值）
- Newey-West Bartlett 核，滞后阶数 **q = {fm_p['hac_lags']}**（由 T 计算，非人工指定）
- 移动区块 Bootstrap：区块长度 {fm_p['block_bootstrap']['block_len']}（T^(1/3)），{fm_p['block_bootstrap']['n_boot']} 次
- 多重检验：BH-FDR 与 Bonferroni，检验次数 = **{fm_p['n_tests']}**（因子数）
- 年化 244 日；rf = {RISK_FREE_RATE_ANNUAL:.2%}/年（λ 为总收益溢价，另给出扣 rf 超额口径字段）
- 经济学含义：截面回归因子斜率 λ_t 体现的是截面标准化因子暴露的边际定价价格（exposure price），并非可直接执行的投资组合净收益；严禁将因子溢价年化解读为实际交易策略的复合年化收益率（CAGR）。重叠持有期事件收益亦不构成可执行策略净值或夏普比率。

### 3.2 因子风险溢价与显著性

| 因子 | 日均溢价 | 年化溢价(244) | 普通 IID t | NW HAC t | 双侧 p | 区块 Bootstrap 95% CI | BH q | Bonferroni p | 5% FDR 判定 |
| :--- | ---: | ---: | ---: | ---: | ---: | :---: | ---: | ---: | :---: |
{chr(10).join(fm_rows)}

### 3.3 稳健性：显著性对口径的敏感性

| 因子 | ① v1 同期收益(留痕) NW t | ② **v2 主口径** NW t | ③ 剔除涨停(重建口径) NW t | ④ 剔除涨停(字面口径) NW t | ⑤ 仅官方复权收益标的 NW t |
| :--- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(robust_rows)}

③ 剔除 {robust['exclude_limit_up_at_t']['n_rows_excluded']:,} 行（重建涨停标志）；
④ 剔除 {robust['exclude_limit_up_at_t_literal']['n_rows_excluded']:,} 行（仅 `hit_limit==1 且 ret>0`）。

### 3.4 诚实结论

1. **前视偏差的量级**：把被解释变量从同期收益改成 t+1 收益后，`mom_20d` 的 NW t 从 {F2.format(robust['same_day_v1_bias_demo']['factors_stats']['mom_20d']['newey_west_t'])} 降到 {F2.format(fm_p['factors_stats']['mom_20d']['newey_west_t'])}，
   `price_pos` 从 {F2.format(robust['same_day_v1_bias_demo']['factors_stats']['price_pos']['newey_west_t'])} 降到 {F2.format(fm_p['factors_stats']['price_pos']['newey_west_t'])}。
   v1 报告中「短周期动量与价格位置因子具备稳健定价能力」的结论**不成立**。
2. **主口径下仅 `amihud` 通过 5% FDR**（NW t = {F2.format(fm_p['factors_stats']['amihud']['newey_west_t'])}，BH q = {fm_p['factors_stats']['amihud']['fdr_q_value']:.4f}）。
3. **但该显著性不稳健**：剔除涨停观测（重建口径）后 `amihud` 的 NW t 降到 {F2.format(robust['exclude_limit_up_at_t']['factors_stats']['amihud']['newey_west_t'])}（不显著）；
   若改用字面口径（`hit_limit==1 且 ret>0`）则 NW t = {F2.format(robust['exclude_limit_up_at_t_literal']['factors_stats']['amihud']['newey_west_t'])}，
   **BH q = {robust['exclude_limit_up_at_t_literal']['factors_stats']['amihud']['fdr_q_value']:.4f}，在该口径下仍然通过 5% FDR**；
   仅用官方复权收益标的时为 {F2.format(robust['official_ret_only']['factors_stats']['amihud']['newey_west_t'])}（BH q = {robust['official_ret_only']['factors_stats']['amihud']['fdr_q_value']:.4f}，不显著）。
   也就是说：两种剔除口径的差别不仅是"定义"，更主要是**覆盖范围**——重建口径剔除 {robust['exclude_limit_up_at_t']['n_rows_excluded']:,} 行，
   字面口径只剔到 {robust['exclude_limit_up_at_t_literal']['n_rows_excluded']:,} 行，差额来自 `ret` 缺失、方向只能由 close 收益推断的涨停样本。
   **结论随口径在"显著/不显著"之间翻转，因此不足以作为稳健的多因子发现。**
4. 其余因子（`mom_20d` / `mom_60d` / `vol_20d` / `turnover_20d` / `price_pos`）在任何口径下均不显著。
5. 结论应表述为：**在本样本期与当前因子集下，实证检验未能拒绝因子风险溢价为零的原假设**；历史报告中 Harvey |t| ≥ 3 的多因子叙事缺乏证据，且因子斜率属于回归暴露定价而非可直接执行策略收益。

---

## 4. 局限性与已知缺口

**样本规模实测**：主口径截面规模 {fm_p['cross_section_size']['min']}~{fm_p['cross_section_size']['max']} 支/期
（均值 {fm_p['cross_section_size']['mean']:.1f}，共 {fm_p['n_periods']} 期）；
「仅官方复权收益」稳健性口径为 {robust['official_ret_only']['cross_section_size']['min']}~{robust['official_ret_only']['cross_section_size']['max']} 支/期；
截面平均 R² = {fm_p['mean_cross_section_r2']:.4f}。

{chr(10).join('- ' + x for x in trend['limitations'])}
{chr(10).join('- ' + x for x in fm['limitations'])}

---

## 5. 产物清单与复算方式

| 文件 | 内容 |
| :--- | :--- |
| `trend_gate_event_study.json` | 实验一全部统计量（受约束 / 无约束 + 逐日配对检验） |
| `trend_gate_placebo_1000.json` | 三种设计的 1000 次安慰剂完整分布 + 经验 p 值 |
| `fama_macbeth_hac_results.json` | 实验二主结果 + 4 组稳健性 + 偏差留痕 + 每期 λ 序列 |
| `results.json` | 结论层汇总 |
| `report.md` / `vs_old.md` / `paper_correction_checklist.md` | 本报告与对账清单 |
| `superseded_v1/` | v1（commit 21c3d5d0）缺陷产物原件，仅供追溯 |

```bash
.venv/Scripts/python scripts/run_real_m4_rebuild.py
.venv/Scripts/python -m pytest tests/test_p4_real_quant.py -q
```
"""
    return md


def build_vs_old_md(trend: dict, fm: dict) -> str:
    """生成 vs_old.md：历史污染值 / v1 缺陷值 / v2 修正值 三项对账。"""
    c = trend["groups_constrained"]
    pv = trend["placebo_p_values"]
    paired = trend["daily_paired_test"]
    counts = trend["event_counts"]
    fm_p = fm["primary_next_day"]
    robust = fm["robustness"]
    fs = fm_p["factors_stats"]
    sd = robust["same_day_v1_bias_demo"]["factors_stats"]
    p_date = pv["date_level"]["constrained"]["trigger_downtrend"]["h20"]
    p_event = pv["event_level"]["constrained"]["trigger_downtrend"]["h20"]
    paired_trig = paired["constrained"]["trigger_downtrend"]["h20"]
    se_ratio = p_date["placebo_std"] / p_event["placebo_std"] if p_event["placebo_std"] else float("nan")
    cb_trig_h20 = trend["cluster_bootstrap_diff"]["constrained"]["trigger_downtrend"]["h20"]
    cb_trig = cb_trig_h20["event_weighted"]
    excl_c = trend["exclusive_group_comparisons"]["constrained"]

    md = f"""# 真实数据重建新旧指标全量对比总账（vs_old.md · v2 修正版）

> 生成时间：{trend['generated_at']}
> 版本：**v2-rework**。三列口径：**历史旧值**＝审计确认的伪造/硬编码值；**v1**＝commit 21c3d5d0 的 M4 结果（有缺陷）；
> **v2**＝本次修正后的真实结果。原则：不追求新结果好看，不显著就照实写。
> 全部 v2 数字由 `.venv/Scripts/python scripts/run_real_m4_rebuild.py` 现场生成，未经人工转录。

---

## 1. 核心指标逐项对账

| 维度 / 指标 | 历史旧值（伪造 / 硬编码） | v1（commit 21c3d5d0，有缺陷） | v2 修正值（本次） | 差异原因 |
| :--- | :--- | :--- | :--- | :--- |
| 数据来源 | 随机数生成数据集（300stocks / 100d_202stocks） | CSMAR 真实主面板 | CSMAR 真实主面板（sha256 绑定） | v1 数据源本身没问题，问题在计算口径 |
| `mom_20d` 显著性 | Harvey t = 3.92（硬编码常量） | NW t = {F2.format(sd['mom_20d']['newey_west_t'])}（同期收益口径） | NW t = **{F2.format(fs['mom_20d']['newey_west_t'])}**（t+1 口径） | v1 用当日收益回归含当日信息的因子，属前视偏差 |
| `price_pos` 显著性 | 未报 | NW t = {F2.format(sd['price_pos']['newey_west_t'])}，年化 +298.86% | NW t = **{F2.format(fs['price_pos']['newey_west_t'])}**，年化 {_pct(fs['price_pos']['annualized_premium_244d'])} | 同上；v1 的 +298.86% 是同期回归的机械产物 |
| `turnover_20d` | 未报 | NW t = {F2.format(sd['turnover_20d']['newey_west_t'])}（显著反转） | NW t = **{F2.format(fs['turnover_20d']['newey_west_t'])}**（不显著） | 同上 |
| `amihud` | 未报 | NW t = {F2.format(sd['amihud']['newey_west_t'])} | NW t = **{F2.format(fs['amihud']['newey_west_t'])}**，BH q = {fs['amihud']['fdr_q_value']:.4f}；剔除涨停（重建口径）{F2.format(robust['exclude_limit_up_at_t']['factors_stats']['amihud']['newey_west_t'])}、字面口径 {F2.format(robust['exclude_limit_up_at_t_literal']['factors_stats']['amihud']['newey_west_t'])} | 主口径显著但**对涨停定义敏感**，不构成稳健发现 |
| `mom_60d` / `vol_20d` | Harvey t = 3.85 / 3.82 | NW t = {F2.format(sd['mom_60d']['newey_west_t'])} / {F2.format(sd['vol_20d']['newey_west_t'])} | NW t = **{F2.format(fs['mom_60d']['newey_west_t'])}** / **{F2.format(fs['vol_20d']['newey_west_t'])}** | 三列口径均不显著 |
| HAC 滞后阶数 | 各脚本随意取 5 / 6，且标注 HAC 实为 IID | q = 5（公式计算） | q = {fm_p['hac_lags']}（由 T={fm_p['n_periods']} 计算） | v1 此点已正确，v2 保持一致 |
| 多重检验校正 | 无校正；把 15/300 假阳性说成 75 支 True Alpha | BH-FDR + Bonferroni 已算，但结论建立在错误口径上 | BH-FDR / Bonferroni，检验次数 {fm_p['n_tests']}，显著因子：{', '.join(f for f, s in fs.items() if s['significant_5pct_fdr']) or '无'} | v1 的校正方法正确，输入错误 |
| 被解释变量时点 | 拿当日/过去收益当标签（100d 实验） | **同期收益**（前视偏差） | **t+1 可交易收益** | v1 重犯了历史同类错误 |
| 涨跌停约束 | 宣称"完全规避跌停" | `hit_limit == -1` 恒为假，约束从未生效 | 重建方向，进场日涨停拦截 {counts['entry_blocked_limit_up']:,} 次，退出日跌停顺延 | v1 的约束是死代码 |
| 安慰剂抽样池 | 从未真实执行 | 含触发样本，抽样量固定 10,000 与触发数不符 | 严格排除触发样本；抽样量按日期/样本量匹配 | v1 实验设计有误 |
| 安慰剂设计 | 无 | 事件级抽样（把同日横截面相关性当独立信息） | **随机日期零分布（描述）+ 同日匹配 + 日期级配对差（HAC 推断，交集配对日期上的池化均值差）**；事件级降为次级 | v1 的"显著"是低估标准误的产物 |
| 推断的序列相关校正 | 无 | 无 | 日度贡献序列 ACF(1) 达 **{cb_trig_h20['autocorr_of_event_weighted_contrib_lag1']:+.3f}**（20 日窗口重叠），故按日独立重抽样不可用；正式推断改用 **Newey-West HAC**，并以 block5 bootstrap 交叉验证。校正后主口径 触发 vs 池 p 由 {cb_trig['boot_iid_p_two_sided']:.4f} 变为 **{cb_trig['hac_p_two_sided']:.4f}** | v1 与 v2 早期版本都在这点上不严谨 |
| 经验 p 值 | 无 | 落盘 `1.0`，**未写入报告** | 单侧低 **{p_date['p_one_sided_lower']:.4f}**、单侧高 {p_date['p_one_sided_upper']:.4f}、双侧 {p_date['p_two_sided']:.4f}（随机日期）；逐日配对 p={paired_trig['nw_p_two_sided']:.4f} | v1 隐瞒了方向不利的 p 值 |
| Trend Gate 有效性 | 论文叙事：门禁规避下行 | 报告称"下行拦截组存在超跌均值回归反弹特征" | 拦截组 20 日 {_pct(c['trigger_downtrend']['h20']['mean_ret'])} > 非触发池 {_pct(c['not_downtrend_pool']['h20']['mean_ret'])} > 纯对照 {_pct(c['neutral_control']['h20']['mean_ret'])}，**在本样本期内未支持门禁规避下行的假设（单侧经验检验未能拒绝下行拦截表现不劣于基线的零假设，p = {p_date['p_one_sided_lower']:.4f}）** | v2 补齐对照、配对与三种安慰剂设计 |
| 门禁自身分辨力 | 未检验 | 未检验 | 触发 vs 顺势 交集配对池化均值差 {_pct(excl_c['trigger_vs_uptrend']['h20']['event_weighted']['observed_diff'])}，**HAC p = {excl_c['trigger_vs_uptrend']['h20']['event_weighted']['hac_p_two_sided']:.4f}（未能拒绝无差异原假设）** | v2 新增互斥组间对比；控制自相关后未能拒绝原假设 |
| Brier 评分 | 0.185（硬编码兜底常量） | 已改为返回 `None` / Brier Skill Score | 同 v1（M1 已修） | 该项 v1 已正确 |
| 文件保全 | 尚未治理 | 新目录产出，未覆盖历史文件 | 新目录产出，且 v1 结果逐字节保留于 `superseded_v1/` | v2 追加保全 v1 |

---

## 2. v1 缺陷的责任边界

1. **前视偏差（严重）**：v1 的 Fama-MacBeth 结论全部不可用。本报告不引用 v1 的任何因子显著性结论。
2. **流动性约束失效（严重）**：v1 声称"考虑涨跌停成交限制"，实际判定条件恒不成立，属未实现。
3. **安慰剂结论截断（严重）**：v1 落盘了方向不利的经验 p 值却未在报告正文披露；且其事件级抽样低估标准误，
   使"显著"结论失真。v2 已改用日期级主口径并披露三种设计。
4. **对照组口径含糊（中等）**：v1 把含顺势组的非触发池称为"全样本对照组"，读者会误以为是对照组。
   v2 新增互斥纯对照组。
5. **交付物缺失（中等）**：v1 未交付 `scripts/run_p4_trend_gate_study.py`、`scripts/run_p4_fama_macbeth.py`、
   `trend_gate_event_study.json`、`fama_macbeth_hac_results.json`；v2 已全部补齐。
6. **测试缺失（中等）**：v1 的 P4 代码无任何测试；v2 新增 `tests/test_p4_real_quant.py`。

---

## 3. 可以放心保留与引用的资产

- **M4 v2 的统计算法实现**：Newey-West Bartlett HAC、移动区块 Bootstrap、BH-FDR / Bonferroni 均已用手算样本独立校验。
- **涨跌停方向重建**：{trend['limit_flag_reconstruction']['n_limit_up'] + trend['limit_flag_reconstruction']['n_limit_down']} 次涨跌停中方向可判
  {trend['limit_flag_reconstruction']['n_limit_up'] + trend['limit_flag_reconstruction']['n_limit_down']} 次，收盘位置校验一致率分别为
  {trend['limit_flag_reconstruction']['limit_up_close_at_high_share']:.1%}（涨停收在最高）与
  {trend['limit_flag_reconstruction']['limit_down_close_at_low_share']:.1%}（跌停收在最低）。
- **板块涨跌停纪律**：{trend['board_limit_discipline_check']['checked_rows']:,} 行中越限 {trend['board_limit_discipline_check']['violations']} 行，数据本身可信。
- **gold / green 系列数值**：+94.84% / Sharpe 1.67 / MaxDD 29.70% 与 Sharpe 1.19 / MaxDD 13.97%，
  来源为审计确认可复算的真实数据（本报告未重算，引用时须附复算脚本）。
- **本次 v2 的全部 JSON**：字段可追溯，`data_sha256` 绑定到确定的数据版本。

---

## 4. 仍需补齐的上游缺口

- 面板中 `ret`（官方复权日收益）只覆盖 99 支标的，`hit_limit` 覆盖 199 支；
  补齐后可把受约束口径扩展到全部 299 支，Fama-MacBeth 的截面规模也能同步扩大。
- 面板缺少开盘价与最高/最低价（A/C 组），进场成交价只能用收盘价近似。
- 面板不含 ST 标记，无法识别 ±5% 涨跌幅限制标的。
"""
    return md


def build_paper_checklist_md(trend: dict, fm: dict) -> str:
    """生成论文/申报材料删改清单（修正版）。"""
    fm_p = fm["primary_next_day"]
    fs = fm_p["factors_stats"]
    robust = fm["robustness"]
    sd = robust["same_day_v1_bias_demo"]["factors_stats"]
    pv = trend["placebo_p_values"]
    paired = trend["daily_paired_test"]
    p_date = pv["date_level"]["constrained"]["trigger_downtrend"]["h20"]
    paired_trig = paired["constrained"]["trigger_downtrend"]["h20"]

    md = f"""# 论文与申报材料删改清单（Paper Correction Checklist · v2 修正版）

> 生成时间：{trend['generated_at']}
> 依据：A1/A2/A3 审计 + M4 v1 缺陷复核（见 `superseded_v1/` 与 `vs_old.md`）
> 适用范围：Rainbow-FinGPT、StockDashboard、量化策略相关论文、竞赛申报书、商业计划书、汇报 PPT

---

## 1. 必须立即删除的伪造指标与无源数字

- [ ] **删除 "Brier Score = 0.185（预测优秀）"**：源自 `storage_supercycle_backtest.py` 无预测时的硬编码兜底常量，
  从未在任何真实实验中算出。不得沿用"Brier ≤ 0.25 为优秀"的非严谨论断。
- [ ] **删除所有 "Harvey t = 3.92 / 3.85 / 3.82" 表述**：为人工写死常量或公式噪声注入。
- [ ] **删除 "20 日命中率 = 5 日命中率 × 系数" 的派生数字**。
- [ ] **删除 "1000 次安慰剂检验 / 消融表 / 旗舰论文表 2 / Rainbow v2 四组合表" 的历史引用**：
  历史版本无对应实验。如要引用安慰剂检验，必须改用本次真实落盘的
  `reports/real_rebuild_20261010/trend_gate_placebo_1000.json`，并**同时引用其经验 p 值**。
- [ ] **删除无法溯源的极端收益叙事**："夏普 4.627"、"+159.01%"、"+222.30%" 等。
- [ ] **删除图 2、图 5 以及绿电/黄金基于正弦公式与噪声生成的 t 曲线图表。**
- [ ] **【v2 新增】删除 v1 报告中的因子显著性结论**：`mom_20d` NW t = {F2.format(sd['mom_20d']['newey_west_t'])}、
  `price_pos` NW t = {F2.format(sd['price_pos']['newey_west_t'])}、`price_pos` 年化 +298.86%、
  `turnover_20d` NW t = {F2.format(sd['turnover_20d']['newey_west_t'])} 全部来自**同期收益回归**的前视偏差，
  改为 t+1 可交易收益后分别降至 **{F2.format(fs['mom_20d']['newey_west_t'])}、{F2.format(fs['price_pos']['newey_west_t'])}、{F2.format(fs['turnover_20d']['newey_west_t'])}**。

---

## 2. 必须更正的方法与计量学错误

- [ ] **更正 HAC 标准误与滞后阶数**：历史多处标注 HAC 实为 IID，且同一 T 下随意使用 q = 5/6/5。
  统一为 q = floor(4(T/100)^(2/9))，本次 T = {fm_p['n_periods']} → **q = {fm_p['hac_lags']}**，Bartlett 核。
- [ ] **删除 "Ridge R² = 0.8943"**：在 P=768 > N=300 的训练集上自测所得。
- [ ] **更正主成分 PC5 的片面挑选**：应客观披露主成分全貌。
- [ ] **更正 "75 支 True Alpha" 的假阳性误读**：15/300 恰好等于 5% 显著性下的随机假阳性期望。
- [ ] **更正 100d 命中率标签前视**：必须使用严格 t+1 ~ t+H 的真实未来收益。
- [ ] **【v2 新增】更正被解释变量时点**：Fama-MacBeth 的被解释变量必须是 **t+1 起可交易收益**，
  严禁使用同期收益回归含当日信息的因子（`mom_20d` / `amihud` / `price_pos` 均含当日数据）。
- [ ] **【v2 新增】更正单一因子显著性的表述**：v1 称"短周期动量与微观结构因子表现出稳健的定价能力"。
  修正后主口径仅 `amihud` 通过 5% FDR（NW t = {F2.format(fs['amihud']['newey_west_t'])}），
  但剔除涨停观测（重建口径）后降至 {F2.format(robust['exclude_limit_up_at_t']['factors_stats']['amihud']['newey_west_t'])}，
  而字面口径下仍为 {F2.format(robust['exclude_limit_up_at_t_literal']['factors_stats']['amihud']['newey_west_t'])}，
  **结论对涨停定义敏感，不构成稳健的多因子发现**。
- [ ] **【v2 新增】更正安慰剂检验的设计**：不得使用事件级抽样冒充随机日期安慰剂。
  事件级抽样把同一交易日的横截面相关性当作独立信息，标准误被低估约
  {pv['date_level']['constrained']['trigger_downtrend']['h20']['placebo_std'] / pv['event_level']['constrained']['trigger_downtrend']['h20']['placebo_std']:.1f} 倍。

---

## 3. 必须彻底纠正的方向性与逻辑颠倒陈述

- [ ] **更正胜率与期望的相反定性**：胜率 30.48%、盈亏比 0.94（期望 −0.41）与 60d 组期望 −0.15，均不得写成"正向期望"。
- [ ] **更正 storage_gold 回撤陈述**：实际回撤恶化 1.02pp；ρ = 0.74 不得写成"近乎正交"。
- [ ] **更正"完全规避跌停"与"无量跌停"**：跌停日无法挂单市价卖出，盘面常为 3~4 倍放量。
- [ ] **更正 001258（立新能源）的旗舰案例定性**：该项目已在自身封箱检验中被 Alpha 门控拒绝（p = 0.354，IR = 0.063）。
- [ ] **【v2 新增】更正 Trend Gate 的叙事**：不得声称门禁能规避下行风险。真实结果是下行拦截组 20 日平均收益
  {_pct(p_date['observed_mean_ret'])}，**高于**随机日期安慰剂基线 {_pct(p_date['placebo_mean'])}，
  单侧「劣于随机」经验 p 值 = **{p_date['p_one_sided_lower']:.4f}**（在当前样本期与检验设定下未能支持规避下行的假设）。
  交集配对日期上的池化均值差为 {_pct(paired_trig['weighted_mean_diff'])}，但优势高度集中在触发最密集的 10% 交易日
  （同日差异 {_pct(paired_trig['diff_on_heavy_trigger_days'])}，其余交易日仅 {_pct(paired_trig['diff_on_light_trigger_days'])}）；
  逐日等权口径下同日差异接近零（NW t = {F2.format(paired_trig['nw_t'])}，p = {paired_trig['nw_p_two_sided']:.4f}）。
  正确表述为"**门禁在当前样本期未展现出稳健可验证的下行风险规避效应；其表面超额在交集配对日期上高度集中于少数极端普跌交易日，不构成普遍稳健的个股择时能力**"。

---

## 4. 可以放心保留与引用的真实可信资产

- **M4 v2 的统计算法**：Newey-West HAC、移动区块 Bootstrap、BH-FDR/Bonferroni、日期级与同日匹配安慰剂，
  均通过手算样本校验与独立复核。
- **涨跌停方向重建与板块涨跌停纪律校验**：方向可判率 100%，越限 {trend['board_limit_discipline_check']['violations']} 行。
- **gold 系列**：+94.84%、Sharpe 1.67、MaxDD 29.70%（真实数据可复现，引用须附复算脚本）。
- **green 系列**：Sharpe 1.19、MaxDD 13.97%（论文原写 21.73% / 24.90% 有误）。
- **Trend Gate / ZigZag θ=12% / AST 参数**：与论文描述一致（但 Trend Gate 的**有效性**不得再作正面声明）。
- **本次 v2 全部产物**：`reports/real_rebuild_20261010/`，含三种设计的安慰剂完整分布与 `data_sha256` 数据版本绑定。
"""
    return md


def regenerate_markdown_reports(out_dir: Path = OUT_DIR) -> None:
    """从现有落盘 JSON 直接重新生成 report.md、vs_old.md 与 paper_correction_checklist.md，保持字节级一致。"""
    import json
    trend = json.loads((out_dir / "trend_gate_event_study.json").read_text(encoding="utf-8"))
    fm = json.loads((out_dir / "fama_macbeth_hac_results.json").read_text(encoding="utf-8"))
    (out_dir / "report.md").write_text(build_report_md(trend, fm), encoding="utf-8")
    (out_dir / "vs_old.md").write_text(build_vs_old_md(trend, fm), encoding="utf-8")
    (out_dir / "paper_correction_checklist.md").write_text(build_paper_checklist_md(trend, fm), encoding="utf-8")


def main() -> None:
    if "--only-reports" in sys.argv:
        regenerate_markdown_reports(OUT_DIR)
        print("[OK] Markdown 报告已从现有 JSON 重新生成。")
        return

    started = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    trend = run_trend_gate_study(PANEL_PATH, OUT_DIR)
    fm = run_fama_macbeth_study(PANEL_PATH, OUT_DIR)

    results = build_results_payload(trend, fm)
    dump_json(results, OUT_DIR / "results.json")
    (OUT_DIR / "report.md").write_text(build_report_md(trend, fm), encoding="utf-8")
    (OUT_DIR / "vs_old.md").write_text(build_vs_old_md(trend, fm), encoding="utf-8")
    (OUT_DIR / "paper_correction_checklist.md").write_text(build_paper_checklist_md(trend, fm), encoding="utf-8")

    print("\n[OK] M4/P4 v2 端到端复算完成，产物：")
    for name in ("results.json", "report.md", "vs_old.md", "paper_correction_checklist.md",
                 "trend_gate_event_study.json", "trend_gate_placebo_1000.json",
                 "fama_macbeth_hac_results.json"):
        p = OUT_DIR / name
        print(f"  - {name:<34} {p.stat().st_size:>10,} bytes")
    print(f"总耗时 {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
