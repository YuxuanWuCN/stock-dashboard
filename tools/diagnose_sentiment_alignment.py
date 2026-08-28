# tools/diagnose_sentiment_alignment.py —— 情绪信号离线诊断（spec-kit 004 / Phase 0 / US1）
#
# 三段式报告（零网络、可复现）：
#   1. 根因审计：ret 字段来源（预测值 vs 已实现）的代码证据与数据证据
#   2. 分母构成：alignment_rate 分母中的无情感分/中性样本分解
#   3. 真实方向统计：用 K 线已实现收益重算方向一致率（Wilson 95% CI vs 50% 基线）
#   结论三选一：正相关 / 无关 / 反转（附置信区间，不夸大）
#
# 用法: python tools/diagnose_sentiment_alignment.py [--feedback PATH] [--kline-dir PATH]

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.market_feedback import realized_return  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FEEDBACK = REPO_ROOT / "docs" / "data" / "llm" / "market_feedback.json"
DEFAULT_KLINE_DIR = REPO_ROOT / "docs" / "data" / "kline"
REPORT_PATH = REPO_ROOT / "reports" / "sentiment_signal_diagnosis.md"

NEUTRAL_THRESHOLD = 0.1

# 根因审计的静态代码证据（spec 004 侦察结论，修复前代码口径）
SOURCE_AUDIT_NOTE = (
    "src/llm/generate_reports.py 的 _record_market_feedback 曾把 KNN 预测值"
    "（forecast.return_5d_pct）当作后续实际收益写入 ret_5d_pct"
    "（docstring 原话：'用相似走势预测的 5 日收益作为后续收益的近似'）。"
    "因此旧 alignment_rate 度量的是'情绪 vs KNN 预测'的一致性，"
    "与'情绪 vs 实际涨跌'无关。"
)


def load_feedback(path) -> list:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("samples", []) if isinstance(data, dict) else []


def load_kline(code: str, kline_dir) -> Optional[pd.DataFrame]:
    """读项目 K 线 JSON（docs/data/kline/{code}.json），返回 date/close 两列。"""
    p = Path(kline_dir) / f"{code}.json"
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    dates = data.get("dates", [])
    rows = data.get("kline", [])
    if not dates or len(dates) != len(rows):
        return None
    closes = [r[1] for r in rows]  # 列序 [开, 收, 低, 高]
    return pd.DataFrame({"date": [str(d) for d in dates], "close": closes})


def realized_for_sample(sample: dict, close_df) -> Tuple[Optional[float], Optional[float]]:
    """按 event_date 在 K 线中的位置计算真实 3/5 日收益；不可算返回 (None, None)。"""
    if close_df is None:
        return None, None
    event = str(sample.get("event_date", ""))
    idx = close_df.index[close_df["date"] == event]
    if len(idx) == 0:
        return None, None
    t = int(idx[0])
    closes = close_df["close"].tolist()
    return realized_return(closes, t, 3), realized_return(closes, t, 5)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """二项比例的 Wilson 95% 置信区间。"""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def source_audit(samples: list) -> dict:
    with_forecast = sum(1 for s in samples if "forecast_ret_5d_pct" in s)
    return {
        "code_finding": SOURCE_AUDIT_NOTE,
        "old_style_samples": len(samples) - with_forecast,
        "new_style_samples": with_forecast,
    }


def time_distribution(samples: list) -> dict:
    """事件日分布：单日聚集会破坏时间维度推断（横截面收益相关）。"""
    from collections import Counter
    counter = Counter(str(s.get("event_date")) for s in samples)
    return {"distinct_days": len(counter), "distribution": dict(sorted(counter.items()))}


def denominator_breakdown(samples: list) -> dict:
    total = len(samples)
    no_score = sum(1 for s in samples if s.get("sentiment_score") is None)
    scored = total - no_score
    neutral = sum(
        1 for s in samples
        if s.get("sentiment_score") is not None
        and abs(s["sentiment_score"]) < NEUTRAL_THRESHOLD
    )
    return {
        "total": total,
        "no_score": no_score,
        "neutral_sentiment": neutral,
        "decisive": scored - neutral,
    }


def directional_stats(samples: list, kline_dir) -> dict:
    """决定性样本（|score|>=0.1）的情绪方向 vs 真实收益方向统计。"""
    pos_n = pos_up = neg_n = neg_up = 0
    not_computable = 0
    for s in samples:
        score = s.get("sentiment_score")
        if score is None:
            continue
        if abs(score) < NEUTRAL_THRESHOLD:
            continue
        r5 = s.get("realized_ret_5d_pct")
        if r5 is None:
            close_df = load_kline(str(s.get("code")), kline_dir)
            _, r5 = realized_for_sample(s, close_df)
            if r5 is None:
                not_computable += 1
                continue
        if score > 0:
            pos_n += 1
            if r5 > 0:
                pos_up += 1
        else:
            neg_n += 1
            if r5 > 0:
                neg_up += 1

    total = pos_n + neg_n
    aligned = pos_up + (neg_n - neg_up)
    accuracy = aligned / total if total else None
    ci = wilson_interval(aligned, total) if total else None
    if ci is None or total == 0:
        verdict = "无关（决定性样本不足，无法判断）"
    elif ci[0] > 0.5:
        verdict = "正相关（显著高于抛硬币基线 50%）"
    elif ci[1] < 0.5:
        verdict = "反转（显著低于抛硬币基线 50%）"
    else:
        verdict = "无关（与抛硬币基线 50% 无显著差异）"

    return {
        "positive_n": pos_n, "positive_up_rate": (pos_up / pos_n) if pos_n else None,
        "negative_n": neg_n, "negative_up_rate": (neg_up / neg_n) if neg_n else None,
        "decisive_total": total, "aligned": aligned,
        "directional_accuracy": accuracy,
        "wilson_ci": ci,
        "verdict": verdict,
        "not_computable": not_computable,
    }


def generate_report(feedback_path, kline_dir) -> str:
    samples = load_feedback(feedback_path)
    audit = source_audit(samples)
    breakdown = denominator_breakdown(samples)
    stats = directional_stats(samples, kline_dir)

    def fmt_rate(v):
        return f"{v:.1%}" if v is not None else "-"

    def fmt_ci(ci):
        return f"[{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "-"

    time_dist = time_distribution(samples)

    lines = [
        "# LLM 情绪信号离线诊断报告（spec-kit 004 / Phase 0）",
        "",
        f"- 生成时间：{pd.Timestamp.now().isoformat(timespec='seconds')}",
        f"- 数据文件：{feedback_path}（{len(samples)} 样本）",
        "",
        "## 样本时间分布（时间维度推断的前提）",
        "",
        f"- 不同事件日：{time_dist['distinct_days']} 天",
        f"- 分布：{time_dist['distribution']}",
        "- 注：单日横截面样本的 5 日收益彼此相关，有效独立样本数远小于样本数；单日数据只能做描述性判断，时间维度的结论需多日积累。",
        "",
        "## 根因审计",
        "",
        f"- 代码证据：{audit['code_finding']}",
        f"- 数据证据：旧口径样本 {audit['old_style_samples']} 条 / 已修复口径样本 {audit['new_style_samples']} 条（forecast_ret_5d_pct 字段存在与否）",
        "",
        "## 分母构成（旧 alignment_rate 为何失真）",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 总样本 | {breakdown['total']} |",
        f"| 无情感分样本（aligned 恒为 False） | {breakdown['no_score']} |",
        f"| 中性情感样本（绝对分 < {NEUTRAL_THRESHOLD}，aligned 恒为 False） | {breakdown['neutral_sentiment']} |",
        f"| 决定性样本（绝对分 >= {NEUTRAL_THRESHOLD}） | {breakdown['decisive']} |",
        "",
        "## 真实方向统计（K 线已实现收益重算）",
        "",
        "| 分组 | 样本数 | 上涨占比 |",
        "|---|---|---|",
        f"| 正情感（score>0） | {stats['positive_n']} | {fmt_rate(stats['positive_up_rate'])} |",
        f"| 负情感（score<0） | {stats['negative_n']} | {fmt_rate(stats['negative_up_rate'])} |",
        f"| 合计（决定性样本方向准确率） | {stats['decisive_total']} | {fmt_rate(stats['directional_accuracy'])} |",
        "",
        f"- Wilson 95% 置信区间：{fmt_ci(stats['wilson_ci'])}",
        f"- 不可算样本（K 线缺失或收益窗口不足）：{stats['not_computable']}（如实标注，未编造）",
        f"- 结论：{stats['verdict']}",
        "",
        "## 局限说明",
        "",
        f"- 决定性样本 < 30 时统计功效不足，结论仅为描述性（当前决定性样本 {stats['decisive_total']}）。",
        f"- 样本时间分布：{time_dist['distinct_days']} 个事件日" + (
            "，全部集中在单日——上述显著性结论仅对当日横截面成立，不能外推到时间维度" if time_dist["distinct_days"] == 1 else "") + "。",
        "- 收益口径：ret_N = (close[t+N] − close[t]) / close[t] × 100（前复权，交易日计数）。",
        "- 本报告为离线重算；修复后的日常样本由 record_event 契约保证真实收益入库。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="情绪信号离线诊断（spec-kit 004）")
    parser.add_argument("--feedback", default=str(DEFAULT_FEEDBACK))
    parser.add_argument("--kline-dir", default=str(DEFAULT_KLINE_DIR))
    parser.add_argument("--report", default=str(REPORT_PATH))
    args = parser.parse_args()

    report = generate_report(args.feedback, args.kline_dir)
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"报告已写入: {out}")
    print(report)
    return 0


if __name__ == "__main__":  # pragma: no cover - 仅直接脚本执行路径
    raise SystemExit(main())
