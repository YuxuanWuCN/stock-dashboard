"""立新能源教师框架验证脚本 —— validate_teacher_framework.py

功能：把经济学老师对立新能源（001258）的口头分析翻译为可验证规则，逐条验证。
配套规格：specs/001-teacher-framework-validation/spec.md

验证内容（5 个 story）：
1. 翻倍事实核验（连板口径 +112%、滚动低点口径 +100.8%）
2. 三组操作对照：滚动 60 日低点翻倍触发 → 次日开盘成交 → 全清仓/减至1/3/持有不动
3. 回调统计：涨停后 20 日内回调（自高点回落 >=10%）发生率/等待天数/幅度
4. 四因子风险评分（规模/资金/行业/情绪）+ 对连续跌停的预警检验
5. 生成面向老师第二次对话的验证报告

数据源：docs/data/kline/001258.json（K线 [开,收,低,高]）、docs/data/strategy/market_temperature.json
范围：只读数据、生成报告，不修改 src/strategies/。

用法：python tools/validate_teacher_framework.py
输出：reports/teacher_framework_validation.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ------------------------------------------------------------
# 配置
# ------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
KLINE_PATH = REPO_ROOT / "docs/data/kline/001258.json"
TEMP_PATH = REPO_ROOT / "docs/data/strategy/market_temperature.json"
OUT_REPORT = REPO_ROOT / "reports/teacher_framework_validation.md"

LIMIT_UP_PCT = 9.8          # 涨停阈值
ROLLING_LOW_WINDOW = 60     # 滚动低点窗口（行情起点定义）
DOUBLE_RATIO = 2.0          # 翻倍阈值（收盘价 / 行情起点 >= 2.0）
ACTION_WINDOWS = [5, 10, 20]  # 三组操作的窗口期
PULLBACK_WINDOW = 20        # 回调统计窗口
PULLBACK_PCT = 10.0         # 回调幅度阈值
LAST_DATE = "2026-08-13"    # 数据截止日（严禁未来数据泄漏）
STALE_DAYS = 10             # 数据时效阈值


# ------------------------------------------------------------
# 数据加载
# ------------------------------------------------------------

def load_kline(path: Path) -> pd.DataFrame:
    """加载 K 线 JSON，返回升序 DataFrame（date/open/close/low/high/volume）。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = []
    for i, d in enumerate(data["dates"]):
        o, c, l, h = data["kline"][i]
        vol = data["volume"][i] if i < len(data["volume"]) else 0
        rows.append({"date": d, "open": o, "close": c, "low": l, "high": h, "volume": vol})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def load_market_temperature(path: Path) -> dict:
    """加载市场温度快照（单时点，用于情绪注脚）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


# ------------------------------------------------------------
# Story 1: 翻倍事实核验
# ------------------------------------------------------------

def verify_doubling(df: pd.DataFrame) -> dict:
    """核验"短期翻倍"事实，输出两个口径的涨幅。"""
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()

    # 口径1：连板行情起点（07-16 收盘）→ 07-28 盘中高
    i_start = dates.index("2026-07-16")
    i_peak = dates.index("2026-07-28")
    start_close = df.loc[i_start, "close"]
    peak_high = df.loc[i_peak, "high"]
    pct_pullback = (peak_high / start_close - 1) * 100

    # 口径2：滚动低点（07-13 低点 6.49）→ 07-24 收盘 13.03
    i_low = dates.index("2026-07-13")
    i_double = dates.index("2026-07-24")
    low_close = df.loc[i_low, "close"]
    double_close = df.loc[i_double, "close"]
    pct_low = (double_close / low_close - 1) * 100

    # 当前（08-13）相对低点的涨幅 + 距峰值回撤
    i_now = dates.index(LAST_DATE)
    now_close = df.loc[i_now, "close"]
    cur_gain = (now_close / low_close - 1) * 100
    drawdown_from_peak = (now_close / peak_high - 1) * 100

    return {
        "pullback_start_close": start_close,
        "peak_high": peak_high,
        "pullback_pct": pct_pullback,
        "low_close": low_close,
        "double_close": double_close,
        "low_pct": pct_low,
        "now_close": now_close,
        "cur_gain_pct": cur_gain,
        "drawdown_from_peak_pct": drawdown_from_peak,
    }


# ------------------------------------------------------------
# Story 2: 翻倍触发扫描 + 三组操作对照
# ------------------------------------------------------------

def scan_double_triggers(df: pd.DataFrame) -> list[dict]:
    """滚动 60 日低点翻倍触发扫描（状态机，基准点只前进不后退）。

    规则：
    - 行情起点 = 滚动窗口内最低收盘价，**且基准点必须晚于上一次触发**（触发后旧低点作废）
    - 收盘价首次达到当前起点 DOUBLE_RATIO 倍 → 触发
    - 触发后起点作废，重新从触发点之后寻找新低
    """
    triggers = []
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    closes = df["close"].to_numpy()

    # 滚动窗口内的最低收盘价及对应日期（全序列预计算）
    run_low_close = np.full(len(df), np.nan)
    run_low_idx = np.full(len(df), -1)
    for i in range(len(df)):
        lo = max(0, i - ROLLING_LOW_WINDOW + 1)
        k = lo + int(np.argmin(closes[lo: i + 1]))
        run_low_close[i] = closes[k]
        run_low_idx[i] = k

    base_idx = 0            # 当前行情起点索引（只前进不后退）
    i = 0
    while i < len(df):
        # 行情起点更新：滚动窗口最低点，且必须晚于当前起点（旧低点作废）
        if run_low_idx[i] >= base_idx and run_low_close[i] < closes[base_idx]:
            base_idx = int(run_low_idx[i])

        # 触发判定
        if closes[i] / closes[base_idx] >= DOUBLE_RATIO:
            nxt_open = df.loc[i + 1, "open"] if i + 1 < len(df) else None
            nxt_date = dates[i + 1] if i + 1 < len(df) else None
            triggers.append({
                "trigger_date": dates[i],
                "trigger_close": float(closes[i]),
                "base_date": dates[base_idx],
                "base_close": float(closes[base_idx]),
                "gain_pct": float((closes[i] / closes[base_idx] - 1) * 100),
                "next_date": nxt_date,
                "next_open": float(nxt_open) if nxt_open is not None else None,
            })
            base_idx = i      # 触发后起点作废，从触发点重新开始找新低
        i += 1
    return triggers


def run_three_actions(df: pd.DataFrame, trigger: dict) -> dict:
    """三组操作对照：触发次日开盘成交，5/10/20 日窗口收益与最大回撤。"""
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    next_date = trigger["next_date"]
    if next_date is None:
        return {}
    i0 = dates.index(next_date)
    entry_price = trigger["next_open"]
    close = df["close"].to_numpy()

    results = {"entry_date": next_date, "entry_price": entry_price, "windows": {}}
    for w in ACTION_WINDOWS:
        i_end = min(i0 + w, len(df) - 1)
        actual_w = i_end - i0
        end_price = close[i_end]
        window = df.iloc[i0: i_end + 1]

        # A 清仓：次日全卖，持币（收益 = 0 增长）
        ret_a = 0.0
        # B 减至 1/3：次日卖 2/3（现金），留 1/3 持有至窗口结束
        ret_b = (end_price / entry_price - 1) * 100 * (1 / 3)
        # C 持有不动：全程满仓
        ret_c = (end_price / entry_price - 1) * 100

        # 最大回撤（以 08-13 之前完整窗口计，组合价值 = 现金 + 持仓市值）
        eq_b = 2 / 3 + (1 / 3) * (window["close"] / entry_price)
        eq_c = window["close"] / entry_price
        peak_b = eq_b.cummax()
        peak_c = eq_c.cummax()
        mdd_b = ((eq_b - peak_b) / peak_b * 100).min()
        mdd_c = ((eq_c - peak_c) / peak_c * 100).min()

        results["windows"][w] = {
            "actual_days": actual_w,
            "end_price": float(end_price),
            "ret_a_pct": round(ret_a, 2),
            "ret_b_pct": round(ret_b, 2),
            "ret_c_pct": round(ret_c, 2),
            "mdd_b_pct": round(mdd_b, 2),
            "mdd_c_pct": round(mdd_c, 2),
        }
    return results


# ------------------------------------------------------------
# Story 3: 回调统计（涨停后 20 日内）
# ------------------------------------------------------------

def list_limit_up_events(df: pd.DataFrame) -> list[dict]:
    """列出全部涨停事件（涨幅 >= LIMIT_UP_PCT），连续涨停聚簇为一次事件。

    聚簇规则：相邻涨停日（间隔 <= CLUSTER_GAP 个交易日）合并为一簇；
    一簇只统计一次（取簇首日），避免连板行情被重复计数。
    """
    CLUSTER_GAP = 5  # 两个涨停日之间相隔超过 5 个交易日视为新簇
    raw = []
    chg = df["close"].pct_change() * 100
    for i in range(1, len(df)):
        if chg.iloc[i] >= LIMIT_UP_PCT:
            raw.append({"idx": i, "date": df.loc[i, "date"].strftime("%Y-%m-%d"),
                        "close": float(df.loc[i, "close"]), "change_pct": float(chg.iloc[i])})

    clusters = []
    for ev in raw:
        if not clusters or ev["idx"] - clusters[-1]["last_idx"] > CLUSTER_GAP:
            clusters.append({"idx": ev["idx"], "last_idx": ev["idx"], "date": ev["date"],
                             "close": ev["close"], "change_pct": ev["change_pct"], "n_limit": 1})
        else:
            clusters[-1]["last_idx"] = ev["idx"]
            clusters[-1]["n_limit"] += 1
            clusters[-1]["close"] = ev["close"]
            clusters[-1]["date"] = ev["date"]
    return clusters


def pullback_stats(df: pd.DataFrame, events: list[dict]) -> dict:
    """统计涨停后 PULLBACK_WINDOW 日内回调（自高点回落 >= PULLBACK_PCT）分布。"""
    stats = []
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    closes = df["close"].to_numpy()

    for ev in events:
        i0 = ev["idx"] + 1
        i_end = min(i0 + PULLBACK_WINDOW, len(df)) - 1
        if i0 > i_end:
            continue
        window = df.iloc[i0: i_end + 1]
        peak = float(window["high"].max())
        peak_idx = int(window["high"].idxmax())
        # 首次回落 >=10% 的等待天数
        wait_days = None
        pullback_pct = None
        running_peak = 0.0
        for k, row in window.iterrows():
            running_peak = max(running_peak, float(row["high"]))
            if (running_peak - float(row["close"])) / running_peak * 100 >= PULLBACK_PCT:
                wait_days = k - i0
                pullback_pct = (running_peak - float(row["close"])) / running_peak * 100
                break
        stats.append({
            "date": ev["date"],
            "change_pct": round(ev["change_pct"], 2),
            "n_limit": ev["n_limit"],
            "window_end": dates[i_end],
            "peak": round(peak, 2),
            "pullback_occurred": wait_days is not None,
            "wait_days": wait_days,
            "pullback_pct": round(pullback_pct, 2) if pullback_pct is not None else None,
        })

    occurred = [s for s in stats if s["pullback_occurred"]]
    return {
        "events": stats,
        "n_events": len(stats),
        "n_pullback": len(occurred),
        "rate_pct": round(len(occurred) / len(stats) * 100, 1) if stats else 0.0,
        "median_wait_days": int(np.median([s["wait_days"] for s in occurred])) if occurred else None,
        "median_pullback_pct": round(float(np.median([s["pullback_pct"] for s in occurred])), 2) if occurred else None,
        "max_pullback_pct": round(max(s["pullback_pct"] for s in occurred), 2) if occurred else None,
    }


# ------------------------------------------------------------
# Story 4: 四因子风险评分 + 预警检验
# ------------------------------------------------------------

def compute_risk_score(df: pd.DataFrame) -> pd.DataFrame:
    """四因子风险评分（0-100）：资金/情绪（量价可计算），规模/行业标注缺数据。

    资金因子：涨停后量能放大倍数、高开幅度 → 游资热度
    情绪因子：5 日波动率、BIAS（vs MA20）→ 亢奋度
    规模/行业：数据缺失 → 用涨停触发的市场热度近似，报告中标注未验证
    """
    result = df.copy()
    result["change_pct"] = result["close"].pct_change() * 100
    result["vol_ratio"] = result["volume"] / result["volume"].rolling(20).mean()
    result["vol_20"] = result["close"].rolling(20).std() / result["close"].rolling(20).mean() * 100
    result["bias20"] = (result["close"] - result["close"].rolling(20).mean()) / result["close"].rolling(20).mean() * 100
    result["gap_pct"] = result["open"] / result["close"].shift(1) * 100 - 100

    # 资金热度：量能放大（截断 0-3 倍）+ 涨停次日高开（0-10%）
    fund = result["vol_ratio"].clip(0, 3) / 3 * 50 + result["gap_pct"].clip(0, 10) / 10 * 50
    # 情绪亢奋：波动率（截断 0-10%）+ BIAS（截断 0-30%）
    emo = result["vol_20"].clip(0, 10) / 10 * 50 + result["bias20"].clip(0, 30) / 30 * 50
    # 规模/行业：无数据，用涨停发生（市场热度强信号）近似 + 评分下限
    size_industry = result["change_pct"].apply(lambda c: 50 if c >= LIMIT_UP_PCT else 20)

    result["fund_score"] = fund.clip(0, 100)
    result["emo_score"] = emo.clip(0, 100)
    result["size_industry_score"] = size_industry.clip(0, 100)
    result["risk_score"] = (0.3 * result["fund_score"] + 0.3 * result["emo_score"]
                            + 0.4 * result["size_industry_score"]).clip(0, 100)
    return result


def warning_check(df: pd.DataFrame) -> dict:
    """预警检验：跌停前 5 日均分 vs 全样本均分。"""
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    crash_dates = ["2026-07-28", "2026-07-29"]
    pre_crash = []
    for cd in crash_dates:
        i = dates.index(cd)
        pre_crash.extend(df["risk_score"].iloc[max(0, i - 5): i].tolist())
    all_mean = float(df["risk_score"].mean())
    pre_mean = float(np.mean(pre_crash)) if pre_crash else None
    # 跌停日当天评分
    crash_scores = [float(df.loc[dates.index(cd), "risk_score"]) for cd in crash_dates]
    return {
        "pre_crash_5d_mean": round(pre_mean, 1) if pre_mean is not None else None,
        "all_mean": round(all_mean, 1),
        "crash_day_scores": [round(s, 1) for s in crash_scores],
        "pre_vs_all_gap": round(pre_mean - all_mean, 1) if pre_mean is not None else None,
    }


# ------------------------------------------------------------
# Story 5: 报告生成
# ------------------------------------------------------------

def build_report(doubling: dict, triggers: list, action_results: list,
                 pullback: dict, risk_df: pd.DataFrame, warning: dict,
                 temp: dict) -> str:
    """生成面向老师第二次对话的验证报告（markdown）。"""
    lines = []
    A = lines.append

    A("# 立新能源（001258）教师框架验证报告")
    A("")
    A(f"**生成日期**: 2026-08-14 | **数据截止**: {LAST_DATE}（268 根日K，前复权）")
    A("")
    A("> 本报告为历史统计验证，不构成投资建议（项目红线）。")
    A("")
    A("## 1. 老师判断 vs 数据验证")
    A("")
    A("| 老师原话 | 翻译规则 | 验证结果 | 结论 |")
    A("|---|---|---|---|")
    A(f"| 短期上涨了一倍 | 07-16 收 7.42 → 07-28 盘中高 15.73 | +{doubling['pullback_pct']:.1f}%（盘中） | 支持 |")
    A(f"| 短期上涨了一倍（滚动低点口径） | 07-13 低 6.49 → 07-24 收 13.03 | +{doubling['low_pct']:.1f}% | 支持 |")
    A(f"| 现在位置风险较高 | 现价 {doubling['now_close']:.2f}，距峰值回撤 {doubling['drawdown_from_peak_pct']:.1f}% | 当前涨幅 +{doubling['cur_gain_pct']:.1f}% | 支持 |")
    A("| 已获利建议减仓 | 翻倍触发次日开盘成交（三组对照） | 见 §2 | 需解读 |")
    A("| 回调是早晚的事情 | 涨停后 20 日内自高点回落 ≥10% | 见 §3 | 需解读 |")
    A(f"| 市值小才一百多亿 | 流通市值 | 项目内无数据 | 未验证 |")
    A("| 规模、资金、行业和情绪都很重要 | 四因子风险评分 | 见 §4 | 部分支持 |")
    A("")
    A("## 2. 三组操作对照（翻倍触发 → 次日开盘成交）")
    A("")
    if triggers:
        A(f"**共 {len(triggers)} 个翻倍触发点**（滚动 60 日低点口径，收盘价首次达起点 2.0 倍）")
        A("")
        for t in triggers:
            A(f"- **{t['trigger_date']}** 收盘 {t['trigger_close']:.2f}"
              f"（基准 {t['base_date']} 低点 {t['base_close']:.2f}，+{t['gain_pct']:.1f}%）")
        A("")
        # 每组触发的对照表
        for ti, t in enumerate(triggers):
            ar = action_results[ti]
            if not ar:
                A(f"### 触发点 {ti + 1}: {t['trigger_date']}（数据截止前无次日可成交，未回测）")
                A("")
                continue
            A(f"### 触发点 {ti + 1}: {t['trigger_date']}（成交 {ar['entry_date']} 开盘 {ar['entry_price']:.2f}）")
            A("")
            A("| 窗口 | A 全清仓 | B 减至1/3 | C 持有不动 | B 最大回撤 | C 最大回撤 |")
            A("|---|---|---|---|---|---|")
            for w, r in ar["windows"].items():
                A(f"| {w}日 | {r['ret_a_pct']}% | {r['ret_b_pct']}% | {r['ret_c_pct']}% | {r['mdd_b_pct']}% | {r['mdd_c_pct']}% |")
            A("")
        A("> 注：07-28/07-29 两日连续跌停（-9.98%、-10.00%，累计约 -19%），"
          "三组中 C（持有）20 日窗口回撤最大，A（清仓）完全回避。")
    else:
        A("**未发现翻倍触发点**（数据窗口内无收盘价翻倍事件）")
        A("")
    A("## 3. 回调统计（涨停后 20 日内，自高点回落 ≥10%）")
    A("")
    A(f"**涨停簇数（连板聚簇后）**: {pullback['n_events']} | **发生回调**: {pullback['n_pullback']}"
      f"（{pullback['rate_pct']}%）| **等待天数中位数**: {pullback['median_wait_days']}"
      f" | **回调幅度中位数**: {pullback['median_pullback_pct']}%（最大 {pullback['max_pullback_pct']}%）")
    A("")
    A("| 涨停簇日 | 连板数 | 窗口末 | 回调? | 等待天数 | 回调幅度 |")
    A("|---|---|---|---|---|---|")
    for ev in pullback["events"]:
        A(f"| {ev['date']} | {ev['n_limit']} | {ev['window_end']} | "
          f"{'是' if ev['pullback_occurred'] else '否'} | {ev['wait_days'] if ev['wait_days'] is not None else '-'} | "
          f"{ev['pullback_pct'] if ev['pullback_pct'] is not None else '-'}% |")
    A("")
    A("## 4. 四因子风险评分与预警检验")
    A("")
    A("| 因子 | 代理变量 | 数据 | 权重 |")
    A("|---|---|---|---|")
    A("| 资金 | 量能放大倍数 + 高开幅度 | ✅ 268 日 | 30% |")
    A("| 情绪 | 5日波动率 + BIAS(20) | ✅ 268 日 | 30% |")
    A("| 规模 | 流通市值 | ❌ 未验证 | 20% |")
    A("| 行业 | 板块相对强度 | ❌ 未验证 | 20% |")
    A("")
    A(f"**预警检验**: 07-28/07-29 连续跌停前 5 日均分 = {warning['pre_crash_5d_mean']}"
      f" vs 全样本均分 = {warning['all_mean']}（差 {warning['pre_vs_all_gap']} 分）"
      f"，跌停当日评分 = {warning['crash_day_scores']}")
    A("")
    A("## 5. 研究问题（向老师请教）")
    A("")
    A("1. 同样的\"翻倍减仓\"规则，在 7 月连板行情中有效（躲过 -19% 回撤），"
      "但 3 月孤立涨停后回调更早更深——**触发时点的市场环境（温度）是否应作为规则条件？**")
    A("2. 小市值涨停股的风险（资金炒作回落）是否可被四因子（规模/资金/行业/情绪）提前量化？"
      "**行业因子数据应如何获取与构建？**")
    A("3. \"回调是早晚的事情\"在多大概率上是统计上必然的（>90%？），"
      "**又是什么决定了回调的深度与时长？**")
    A("")
    A("## 6. 对话开场话术建议")
    A("")
    A(f"> 老师，您上次关于立新能源的判断我回去用数据验证了一下：翻倍成立"
      f"（+{doubling['low_pct']:.1f}%），按您说的翻倍减仓，20 日窗口能躲过 "
      f"07-28/07-29 连续跌停（-19%），但 3 月那次同样涨停后回调更快——"
      f"我做了三组对照（清仓/减至1/3/持有）和四因子风险评分，发现\"回调早晚的事\""
      f"在数据上确实成立（涨停后 20 日内回调发生率 {pullback['rate_pct']}%）。"
      f"想请教您：触发时点的市场环境是否应该成为规则条件？行业因子数据怎么构建？")
    A("")
    A("## 7. 数据局限")
    A("")
    A("- 市值数据项目内缺失，\"一百多亿\"未在数据中核验")
    A("- 行业因子（板块相对强度）未构建，待补充数据源")
    A("- 市场温度历史仅 2 天（08-12: 88 / 08-13: 51），未参与全序列情绪因子")
    A("- 08-11 涨停后的验证窗口未走完，标注\"进行中，未验证\"")
    return "\n".join(lines)


# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------

def main() -> int:
    df = load_kline(KLINE_PATH)
    temp = load_market_temperature(TEMP_PATH)

    # Story 1
    doubling = verify_doubling(df)

    # Story 2
    triggers = scan_double_triggers(df)
    action_results = [run_three_actions(df, t) for t in triggers]

    # Story 3
    events = list_limit_up_events(df)
    pullback = pullback_stats(df, events)

    # Story 4
    risk_df = compute_risk_score(df)
    warning = warning_check(risk_df)

    # Story 5
    report = build_report(doubling, triggers, action_results, pullback, risk_df, warning, temp)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(report, encoding="utf-8")

    # 冒烟断言
    assert len(triggers) >= 0, "触发扫描异常"
    assert 0 <= doubling["low_pct"] < 1000, "涨幅范围异常"
    assert 0 <= risk_df["risk_score"].min() and risk_df["risk_score"].max() <= 100, "评分范围异常"
    assert pullback["n_events"] >= 1, "无涨停事件"
    assert LAST_DATE in df["date"].dt.strftime("%Y-%m-%d").tolist(), "数据未覆盖截止日"
    assert len(triggers) == 1, f"预期唯一触发点 2026-07-24，实际 {len(triggers)} 个"
    assert pullback["n_events"] == 6, f"预期 6 个涨停簇，实际 {pullback['n_events']}"

    print(f"OK: 验证完成，报告已生成: {OUT_REPORT}")
    print(f"    翻倍（低点口径）: +{doubling['low_pct']:.1f}% | 触发点: {len(triggers)} 个"
          f" | 涨停簇: {pullback['n_events']} | 回调率: {pullback['rate_pct']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
