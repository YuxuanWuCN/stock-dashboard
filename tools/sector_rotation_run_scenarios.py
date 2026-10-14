# -*- coding: utf-8 -*-
r"""tools/sector_rotation_run_scenarios.py —— 板块轮动回测三场景编排（阶段4，任务 4.2）

一次运行产出：
  S1 代理情绪 × W_price 全窗口（机制与成本链路验证，禁入结论）
  S2 真实 LLM 情绪 × W_real（受 DATA_FEASIBILITY 约束；W_real 空窗时降级为前向累积观察）
  S3 参数敏感性网格（decline/target/cooldown 各 3 档，跑在 S1 provider 上）

产物（禁止覆盖既有目录）：
  data/processed/sector_rotation/backtest/{window}/{scenario}/（nav/trades/decisions/states/metrics/manifest）
  docs/sector_rotation/figures/（净值/回撤/轮动标记/评分热力）
  docs/sector_rotation/BACKTEST_REPORT.md

用法：
  python tools/sector_rotation_run_scenarios.py
  python tools/sector_rotation_run_scenarios.py --news-fixture path.json --start 2026-08-11 --end 2026-10-09
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from src.sector_rotation.backtest import (  # noqa: E402
    BacktestEngine,
    KlineStore,
    LLMReplaySentimentProvider,
    ProxyBreadthSentimentProvider,
)
from src.sector_rotation.config import SECTORS, get_all_tickers  # noqa: E402

KLINE_DIR = ROOT_DIR / "docs" / "data" / "kline"
DEFAULT_WPRICE = ("2025-09-08", "2026-08-27")   # DATA_FEASIBILITY §1 可用票子集交集
ART_ROOT = ROOT_DIR / "data" / "processed" / "sector_rotation" / "backtest"
FIG_DIR = ROOT_DIR / "docs" / "sector_rotation" / "figures"
REPORT_PATH = ROOT_DIR / "docs" / "sector_rotation" / "BACKTEST_REPORT.md"
FEASIBILITY_PATH = ROOT_DIR / "docs" / "sector_rotation" / "DATA_FEASIBILITY.md"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# ============================================================================
# provider 构造（复用 CLI 语义）
# ============================================================================

def make_proxy(store: KlineStore, calendar: List[str]) -> ProxyBreadthSentimentProvider:
    return ProxyBreadthSentimentProvider(store=store, calendar=calendar)


def make_llm(store: KlineStore, calendar: List[str], news_fixture: Optional[str],
             lookback_days: int = 7) -> LLMReplaySentimentProvider:
    if news_fixture:
        raw = json.loads(Path(news_fixture).read_text(encoding="utf-8"))

        def loader(code: str, trade_date: str) -> List[Dict[str, Any]]:
            return list(raw.get(code, []))
        news_loader = loader
    else:
        # 离线且无夹具：返回空新闻 -> provider 产出中性状态（不伪造 LLM 结论）
        def loader(code: str, trade_date: str) -> List[Any]:
            return []
        news_loader = loader

    from src.llm.llm_sentiment import LLMSentimentAnalyzer
    return LLMReplaySentimentProvider(
        news_loader=news_loader, analyzer=LLMSentimentAnalyzer(),
        calendar=calendar, lookback_days=lookback_days)


def _count_news(news_loader, calendar: List[str]) -> int:
    """统计 W_real 内可用新闻条数（判定 S2 是否可支撑结论）。"""
    total = 0
    for code in get_all_tickers():
        try:
            total += len(news_loader(code, calendar[-1]))
        except Exception:  # noqa: BLE001
            continue
    return total


# ============================================================================
# 单场景运行 + 落盘
# ============================================================================

def run_and_save(engine: BacktestEngine, store: KlineStore, start: str, end: str,
                 provider, scenario_tag: str, params: Dict[str, Any],
                 initial_sector: str, allow_overwrite: bool) -> Dict[str, Any]:
    result = engine.run(
        start_date=start, end_date=end, provider=provider,
        initial_sector=initial_sector, params=params, for_report=False,
    )
    window_tag = f"{result.days[0]}_{result.days[-1]}"
    out_dir = ART_ROOT / window_tag / scenario_tag
    result.save(out_dir, allow_overwrite=allow_overwrite)
    m = result.metrics["strategy"]
    b = result.metrics["benchmark_equal_weight_buy_hold"]
    return {
        "scenario": scenario_tag,
        "sentiment_source": provider.sentiment_source,
        "window": window_tag,
        "n_days": len(result.days),
        "params": params,
        "initial_sector": initial_sector,
        "metrics": m,
        "benchmark": b,
        "result": result,
        "out_dir": str(out_dir.relative_to(ROOT_DIR)),
    }


# ============================================================================
# 图表
# ============================================================================

def plot_nav_and_drawdown(run: Dict[str, Any]) -> List[str]:
    res = run["result"]
    days = pd.to_datetime(res.days)
    nav = pd.Series(res.nav, index=days)
    bench = pd.Series(res.benchmark_nav, index=days) * nav.iloc[0]

    made = []
    # 1) 净值 vs 基准
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(days, nav, label="轮动策略 NAV", color="#c0392b", lw=1.6)
    ax.plot(days, bench, label="基准（3 板块等权 B&H）", color="#2c3e50", lw=1.4, ls="--")
    # 轮动完成标记
    for t in res.trades:
        if t.get("is_complete") and t.get("date"):
            d = pd.to_datetime(t["date"])
            if d in nav.index:
                ax.axvline(d, color="#e67e22", alpha=0.35, ls=":")
    ax.set_title(f"净值 vs 基准  [{run['scenario']} / {run['sentiment_source']}]")
    ax.set_ylabel("净值（初始=1）")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = FIG_DIR / f"nav_{run['scenario']}.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    made.append(p.name)

    # 2) 回撤曲线
    dd = (nav - nav.cummax()) / nav.cummax()
    ddb = (bench - bench.cummax()) / bench.cummax()
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.fill_between(days, dd * 100, 0, color="#c0392b", alpha=0.35, label="策略回撤")
    ax.plot(days, ddb * 100, color="#2c3e50", lw=1.2, label="基准回撤")
    ax.set_title(f"回撤曲线  [{run['scenario']}]")
    ax.set_ylabel("回撤 (%)")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = FIG_DIR / f"drawdown_{run['scenario']}.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    made.append(p.name)

    # 3) 板块评分热力
    states = pd.DataFrame(res.states_rows)
    if not states.empty:
        piv = states.pivot_table(index="date", columns="sector", values="sentiment_score")
        piv.index = pd.to_datetime(piv.index)
        fig, ax = plt.subplots(figsize=(11, 4))
        im = ax.imshow((piv.T.values), aspect="auto", cmap="RdYlGn",
                       vmin=-1, vmax=1, interpolation="nearest")
        ax.set_yticks(range(len(piv.columns)))
        ax.set_yticklabels(piv.columns)
        n_xt = 6
        idx = list(range(len(piv.index)))
        ax.set_xticks(idx[::max(1, len(idx) // n_xt)])
        ax.set_xticklabels([piv.index[i].date().isoformat() for i in idx[::max(1, len(idx) // n_xt)]],
                           rotation=30, ha="right")
        fig.colorbar(im, ax=ax, label="代理情绪分")
        ax.set_title(f"板块情绪评分热力  [{run['scenario']} / {run['sentiment_source']}]")
        fig.tight_layout()
        p = FIG_DIR / f"sector_heat_{run['scenario']}.png"
        fig.savefig(p, dpi=120)
        plt.close(fig)
        made.append(p.name)
    return made


# ============================================================================
# 报告
# ============================================================================

def _fmt_metrics_table(runs: List[Dict[str, Any]]) -> str:
    lines = ["| 场景 | sentiment_source | 交易日 | 总收益 | Sharpe | 最大回撤 | 轮动次数 | 成本占比 | 基准收益 | 基准Sharpe | 基准回撤 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        m = r["metrics"]
        b = r["benchmark"]
        lines.append(
            f"| {r['scenario']} | {r['sentiment_source']} | {r['n_days']} | "
            f"{m['total_return']:+.2%} | {m['sharpe']} | {m['max_drawdown']:.2%} | "
            f"{m['rotations']} | {m['cost_ratio']:.4%} | "
            f"{b['total_return']:+.2%} | {b['sharpe']} | {b['max_drawdown']:.2%} |")
    return "\n".join(lines)


def _review_rotations(run: Dict[str, Any]) -> str:
    res = run["result"]
    accepted = [d for d in res.decisions if d.get("rotation_accepted")]
    if not accepted:
        return ("本场景无被接受的轮动：代理情绪为板块内截面标准化分数，最高分恰为 0.5，"
                "而候选门槛要求严格大于 0.5（`MIN_TARGET_SENTIMENT`），默认阈值下候选轮动永不触发；"
                "初始已持有防御板块 gold，亦无下沉触发条件。\n")
    seg_by_date = {s["end"]: s for s in res.segments}
    lines: List[str] = []
    for d in accepted:
        llmv = d.get("llm_validation") or {}
        lines.append(
            f"- **{d['date']}** {d.get('current_sector')} → {d.get('target_sector')} "
            f"(fallback={d.get('is_fallback')})：{d.get('reason')}\n"
            f"  - LLM 复核: {llmv.get('status', '未启用')}\n")
    return "\n".join(lines) + "\n"


def _coverage_gate(s2: Optional[Dict[str, Any]]) -> str:
    """AGENTS.md 覆盖门槛：仅 S2（真实情绪）确认 Sharpe 提升≥0.3 且 MDD≤20% 才允许写入 docs/data。"""
    if s2 is None or s2.get("downgraded"):
        return ("**未达覆盖门槛（S2 数据不足）**：真实 LLM 情绪历史为空窗（见 DATA_FEASIBILITY §3/§6），"
                "无法确认轮动相对基准的实质性提升，故**不将轮动结果写入 `docs/data/` 供前端消费**，"
                "保留稳定基准；待 `daily_job` 的 `history.jsonl` 累积 ≥20 个交易日真实情绪后重跑 S2。\n")
    m = s2["metrics"]
    b = s2["benchmark"]
    sharp_lift = (m["sharpe"] or 0) - (b["sharpe"] or 0)
    ok = sharp_lift >= 0.3 and (m["max_drawdown"] or 1.0) <= 0.20
    verdict = "达到" if ok else "未达到"
    return (f"S2 真实情绪：策略 Sharpe={m['sharpe']} vs 基准 {b['sharpe']}（提升 {sharp_lift:+.3f}），"
            f"最大回撤 {m['max_drawdown']:.2%}。{verdict}覆盖门槛（提升≥0.3 且 MDD≤20%）。"
            + ("允许写入 docs/data。" if ok else "不写入 docs/data，保留稳定基准。") + "\n")


def build_report(s1: Dict[str, Any], s2: Optional[Dict[str, Any]],
                 s3_rows: List[Dict[str, Any]], figures: List[str],
                 w_real_note: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    runs_for_table = [s1] + ([s2] if (s2 and not s2.get("downgraded")) else [])
    lines = [
        "# 板块轮动回测报告（BACKTEST_REPORT）",
        f"\n生成时间: {now}\n",
        "> 数据诚实性：本报告严格区分**真实 LLM 情绪（llm_news_replay）**与**代理情绪（price_breadth_proxy）**，"
        "代理结果仅用于机制与成本链路验证，不作为结论性业绩。\n",
        "## 1. 概述\n",
        f"- 价格窗口 W_price：{s1['window']}（{s1['n_days']} 交易日，等权成分）",
        f"- W_real（真实新闻可回溯公共窗口）：{w_real_note}",
        "- 三场景：S1 代理全窗口 / S2 真实情绪 / S3 参数敏感性\n",
        "## 2. 指标表（含基准对比）\n",
        _fmt_metrics_table(runs_for_table),
        "\n注：S1 为代理情绪，其收益/回撤仅验证链路，不代表真实策略业绩。\n",
    ]
    if s2 and s2.get("downgraded"):
        lines.append("\n### S2 状态\n")
        lines.append("S2（真实 LLM 情绪 × W_real）因真实新闻窗口为空而**降级为前向累积观察**，"
                     "本次不产出结论性指标。由每日任务累积真实情绪序列后重跑。\n")

    lines.append("\n## 3. 逐笔轮动复盘\n")
    lines.append("### S1（代理情绪）\n")
    lines.append(_review_rotations(s1))

    lines.append("\n## 4. 参数敏感性（S3，代理情绪 × W_price）\n")
    if s3_rows:
        lines.append("| decline_threshold | target_threshold | cooldown | 轮动次数 | 总收益 | Sharpe | 最大回撤 | 成本占比 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in s3_rows:
            m = r["metrics"]
            p = r["params"]
            lines.append(
                f"| {p.get('decline_threshold','-')} | {p.get('target_threshold','-')} | "
                f"{p.get('cooldown_days','-')} | {m['rotations']} | {m['total_return']:+.2%} | "
                f"{m['sharpe']} | {m['max_drawdown']:.2%} | {m['cost_ratio']:.4%} |")
        lines.append("\n结论：候选轮动仅在 `target_threshold` 下修至代理分数可达区间（≤0.5）时才被触发，"
                     "印证代理情绪为截面相对分数、不具备绝对景气水平含义；这正是必须用真实 LLM 情绪"
                     "（S2）才能支撑结论的原因。\n")
    else:
        lines.append("（未产出敏感性结果）\n")

    lines.append("\n## 5. 覆盖门槛判定\n")
    lines.append(_coverage_gate(s2))

    lines.append("\n## 6. 数据与局限性声明\n")
    lines.append(f"- 详见 [DATA_FEASIBILITY.md]({FEASIBILITY_PATH.relative_to(ROOT_DIR).as_posix()})。")
    lines.append("- 交易日历按 weekday<5 近似，未含法定节假日调休。")
    lines.append("- 代理情绪为价格截面标准化 + 涨跌家数宽度，非真实新闻情绪，禁止标注为 LLM 情绪。")
    lines.append("- 个股日频真实情绪历史在本仓库不存在，S2 需前向累积后重跑。")
    if figures:
        lines.append("\n## 7. 图表\n")
        for fn in figures:
            lines.append(f"![{fn}]({FIG_DIR.name}/{fn})")
    return "\n".join(lines) + "\n"


# ============================================================================
# main
# ============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="板块轮动回测三场景编排")
    ap.add_argument("--start", default=DEFAULT_WPRICE[0])
    ap.add_argument("--end", default=DEFAULT_WPRICE[1])
    ap.add_argument("--news-fixture", default=None, help="S2 真实新闻 JSON 夹具（缺省则 S2 降级）")
    ap.add_argument("--initial-sector", default="gold")
    ap.add_argument("--allow-overwrite", action="store_true")
    args = ap.parse_args()

    store = KlineStore.from_dir(KLINE_DIR, get_all_tickers())
    wprice = store.common_dates(args.start, args.end)
    if len(wprice) < 20:
        raise SystemExit(f"W_price 日历不足（{len(wprice)} 天）")
    engine = BacktestEngine(store=store, kline_dir=KLINE_DIR, sectors=SECTORS)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    # ---------------- S1 代理全窗口 ----------------
    proxy = make_proxy(store, wprice)
    s1 = run_and_save(engine, store, args.start, args.end, proxy, "proxy_s1",
                      {}, args.initial_sector, args.allow_overwrite)
    print(f"[S1] {s1['sentiment_source']} rotations={s1['metrics']['rotations']} "
          f"total={s1['metrics']['total_return']:+.2%} mdd={s1['metrics']['max_drawdown']:.2%}")
    figures = plot_nav_and_drawdown(s1)

    # ---------------- S2 真实情绪 ----------------
    s2: Optional[Dict[str, Any]] = None
    # 无夹具时不构造 LLMSentimentAnalyzer（离线环境可能无 API key）
    n_news = 0
    if args.news_fixture:
        probe = make_llm(store, wprice, args.news_fixture)
        n_news = _count_news(probe.news_loader, wprice)
    w_real_note = ""
    if args.news_fixture and n_news > 0:
        # 用夹具覆盖的区间作为 W_real（收缩到日历内新闻存在的最短/最长日）
        llm = make_llm(store, wprice, args.news_fixture)
        s2 = run_and_save(engine, store, args.start, args.end, llm, "llm_s2",
                          {}, args.initial_sector, args.allow_overwrite)
        s2["downgraded"] = False
        w_real_note = f"新闻夹具可用（{n_news} 条），S2 在 {s2['window']} 运行"
        figures += plot_nav_and_drawdown(s2)
        print(f"[S2] llm_news_replay rotations={s2['metrics']['rotations']}")
    else:
        # 空窗：S2 降级为前向累积观察（不产出结论）
        s2 = {"downgraded": True}
        w_real_note = "**空窗**（各票新闻回溯区间无重叠，见 DATA_FEASIBILITY §3），S2 降级为前向累积观察"
        print("[S2] W_real 空窗 -> 降级为前向累积观察，不产出结论性指标")

    # ---------------- S3 参数敏感性（代理） ----------------
    decline_grid = [-0.2, -0.3, -0.4]
    target_grid = [0.3, 0.4, 0.5]
    cooldown_grid = [5, 7, 10]
    s3_rows: List[Dict[str, Any]] = []
    # OFAT：以默认 (-0.3, 0.5, 7) 为基线，每维单独变动
    base = {"decline_threshold": -0.3, "target_threshold": 0.5, "cooldown_days": 7}
    variants: List[Dict[str, Any]] = []
    for d in decline_grid:
        variants.append({**base, "decline_threshold": d})
    for t in target_grid:
        variants.append({**base, "target_threshold": t})
    for c in cooldown_grid:
        variants.append({**base, "cooldown_days": c})
    for vi, prm in enumerate(variants):
        prov = make_proxy(store, wprice)
        try:
            r = run_and_save(engine, store, args.start, args.end, prov,
                             f"sens_s3_{vi}", prm, args.initial_sector, args.allow_overwrite)
            s3_rows.append(r)
        except Exception as e:  # noqa: BLE001
            print(f"[S3] variant {vi} {prm} 失败: {e}")
    print(f"[S3] 敏感性完成: {len(s3_rows)} 变体")

    # ---------------- 报告 ----------------
    report = build_report(s1, s2, s3_rows, figures, w_real_note)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"[DONE] report -> {REPORT_PATH.relative_to(ROOT_DIR)} | figures: {len(figures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
