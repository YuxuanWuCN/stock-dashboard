# tests/test_market_feedback_realized.py —— 情绪信号度量与数据口径修复单元测试（spec-kit 004）
#
# 覆盖：realized_return 手算对照、record_event 契约、回填幂等、
#       compute_summary directional_accuracy、泄漏注入、诊断脚本。

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "tools"))

from src.market_feedback import MarketFeedbackTracker, realized_return  # noqa: E402

import diagnose_sentiment_alignment as diag  # noqa: E402


# ============================================================
# T002: 夹具工具
# ============================================================

def synthetic_close(n=300, seed=5, start=100.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.001, 0.02, n)
    return pd.Series(start * np.cumprod(1 + rets))


def make_kline_json(code, dates, closes):
    """项目 K 线 JSON 结构（fetch_data.build_kline_json 同构）。"""
    rows = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        rows.append([round(o, 2), round(c, 2), round(min(o, c) * 0.99, 2), round(max(o, c) * 1.01, 2)])
    return {
        "code": code, "name": f"测试{code}", "type": "stock", "adjust": "qfq",
        "dates": dates,
        "kline": rows,
        "volume": [1000] * len(dates),
    }


def write_feedback(path, samples):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"samples": samples}, fh, ensure_ascii=False, indent=2)


def make_sample(code, event_date, score=None, ret_5d=None, forecast_5d=None,
                realized_5d=None, realized_3d=None):
    s = {
        "code": code, "name": f"测试{code}", "event_date": event_date,
        "event_type": "daily_analysis", "sentiment_score": score,
        "ret_3d_pct": None, "ret_5d_pct": ret_5d,
        "benchmark_ret_3d_pct": None, "benchmark_ret_5d_pct": None,
        "excess_3d_pct": None, "excess_5d_pct": ret_5d,
        "rlsp_reward_3d": None, "rlsp_reward_5d": None,
        "label": "neutral",
        "soft_label": {"hard_label": "neutral", "soft_label": 0.0, "weight": 0.0, "aligned": False},
    }
    if forecast_5d is not None:
        s["forecast_ret_5d_pct"] = forecast_5d
    if realized_5d is not None:
        s["realized_ret_5d_pct"] = realized_5d
        s["realized_available"] = True
    if realized_3d is not None:
        s["realized_ret_3d_pct"] = realized_3d
    return s


# ============================================================
# T001: realized_return 手算对照
# ============================================================

def test_realized_return_hand_computed():
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    assert realized_return(closes, 0, 5) == pytest.approx(5.0)
    assert realized_return(closes, 2, 3) == pytest.approx((105.0 - 102.0) / 102.0 * 100.0)
    # 精确浮点一致（同公式同序列）
    assert realized_return(closes, 0, 5) == (closes[5] - closes[0]) / closes[0] * 100.0


def test_realized_return_boundaries():
    closes = [100.0, 101.0, 102.0]
    assert realized_return(closes, 0, 3) is None       # 窗口不足
    assert realized_return(closes, -1, 2) is None      # 非法下标
    assert realized_return(closes, 5, 2) is None
    assert realized_return([0.0, 1.0], 0, 1) is None   # 基准价为 0
    assert realized_return([100.0, None], 0, 1) is None


# ============================================================
# T003: 诊断脚本（先失败：diag 模块当前不存在）
# ============================================================

def test_diagnose_report_three_sections(tmp_path):
    dates = [f"2026-08-{d:02d}" for d in range(1, 21)]
    closes = [100.0 + i for i in range(20)]  # 每天 +1
    kline_dir = tmp_path / "kline"
    kline_dir.mkdir()
    with open(kline_dir / "A001.json", "w", encoding="utf-8") as fh:
        json.dump(make_kline_json("A001", dates, closes), fh, ensure_ascii=False)

    samples = [
        make_sample("A001", "2026-08-05", score=0.5, ret_5d=8.0),   # 正分（旧数据口径：ret 为预测值）
        make_sample("A001", "2026-08-10", score=None, ret_5d=1.0),  # 无情感分
        make_sample("A001", "2026-08-12", score=0.05, ret_5d=1.0),  # 中性分
        make_sample("B002", "2026-08-05", score=-0.5, ret_5d=-2.0), # 无 K 线 → 不可算
    ]
    fb = tmp_path / "market_feedback.json"
    write_feedback(fb, samples)

    report = diag.generate_report(fb, kline_dir)
    assert "根因审计" in report
    assert "分母构成" in report
    assert "真实方向统计" in report
    for token in ("正相关", "无关", "反转"):
        if f"结论：{token}" in report:
            break
    else:
        raise AssertionError("报告结论必须三选一")
    # 不可算样本被标注而非编造
    assert "不可算" in report


# ============================================================
# US2: record_event 契约与回填（T006/T007，先失败）
# ============================================================

def test_record_event_contract_realized_only(tmp_path):
    """契约：ret 字段只收真实收益；预测值独立保存（先失败：现契约无 forecast 参数）。"""
    tracker = MarketFeedbackTracker(path=str(tmp_path / "fb.json"))
    tracker.record_event(
        code="A001", name="测试", event_date="2026-08-05",
        event_type="daily_analysis",
        ret_3d=None, ret_5d=6.54,
        sentiment_score=0.5, sentiment_confidence=1.0,
        forecast_ret_5d=8.8,  # KNN 预测值，不得落入 ret 字段
    )
    s = tracker.samples[-1]
    assert s["ret_5d_pct"] == 6.54          # 真实收益
    assert s["realized_ret_5d_pct"] == 6.54
    assert s["forecast_ret_5d_pct"] == 8.8  # 预测值独立保存
    assert s["realized_available"] is True


def test_record_event_contract_none_when_missing(tmp_path):
    """无真实收益 → None + realized_available False（不伪造）。"""
    tracker = MarketFeedbackTracker(path=str(tmp_path / "fb.json"))
    tracker.record_event(
        code="A001", name="测试", event_date="2026-08-05",
        event_type="daily_analysis",
        ret_3d=None, ret_5d=None,
        sentiment_score=0.5,
    )
    s = tracker.samples[-1]
    assert s["ret_5d_pct"] is None
    assert s["realized_ret_5d_pct"] is None
    assert s["realized_available"] is False


def test_backfill_snapshot_idempotent_and_flags(tmp_path):
    """回填：快照只建一次、两次运行逐字节一致、不可算样本显式标注（先失败：工具不存在）。"""
    import backfill_market_feedback as backfill

    dates = [f"2026-08-{d:02d}" for d in range(1, 15)]
    closes = [100.0 + i for i in range(14)]
    kline_dir = tmp_path / "kline"
    kline_dir.mkdir()
    with open(kline_dir / "A001.json", "w", encoding="utf-8") as fh:
        json.dump(make_kline_json("A001", dates, closes), fh, ensure_ascii=False)

    samples = [
        make_sample("A001", "2026-08-05", score=0.5, ret_5d=8.8),   # 旧口径（ret=预测值）
        make_sample("B002", "2026-08-05", score=-0.5, ret_5d=-2.0), # 无 K 线 → 不可算
    ]
    fb = tmp_path / "market_feedback.json"
    write_feedback(fb, samples)

    stats1 = backfill.backfill(fb, kline_dir)
    first_bytes = fb.read_bytes()
    assert stats1["computable"] == 1
    assert stats1["not_computable"] == 1
    snapshots = list(tmp_path.glob("market_feedback.backup_*.json"))
    assert len(snapshots) == 1

    # 字段核验
    data = json.loads(first_bytes)
    by_code = {s["code"]: s for s in data["samples"]}
    assert by_code["A001"]["forecast_ret_5d_pct"] == 8.8  # 旧预测值保留
    assert by_code["A001"]["ret_5d_pct"] is not None and by_code["A001"]["ret_5d_pct"] != 8.8
    assert by_code["A001"]["realized_available"] is True
    assert by_code["B002"]["realized_available"] is False
    assert by_code["B002"]["ret_5d_pct"] is None

    # 幂等：第二次运行结果逐字节一致、无新变更，且快照不新增
    stats2 = backfill.backfill(fb, kline_dir)
    assert fb.read_bytes() == first_bytes
    assert stats2["changed"] == 0
    assert stats2["computable"] == stats1["computable"]
    assert stats2["not_computable"] == stats1["not_computable"]
    assert len(list(tmp_path.glob("market_feedback.backup_*.json"))) == 1


# ============================================================
# US3: compute_summary directional_accuracy（T012，先失败）
# ============================================================

def _sample_for_summary(score, realized_5d, realized_3d=None, forecast_5d=0.0):
    return {
        "code": "X001", "name": "测试", "event_date": "2026-08-07",
        "sentiment_score": score,
        "ret_5d_pct": realized_5d, "ret_3d_pct": realized_3d,
        "realized_ret_5d_pct": realized_5d, "realized_ret_3d_pct": realized_3d,
        "forecast_ret_5d_pct": forecast_5d,
        "realized_available": (realized_5d is not None or realized_3d is not None),
        "benchmark_ret_3d_pct": None, "benchmark_ret_5d_pct": None,
        "excess_3d_pct": realized_3d, "excess_5d_pct": realized_5d,
        "rlsp_reward_3d": None, "rlsp_reward_5d": None,
        "label": "neutral",
        "soft_label": {"aligned": False},
    }


def test_compute_summary_directional_accuracy():
    tracker = MarketFeedbackTracker(path=str(Path(__file__).parent / "nonexistent_fb.json"))
    tracker.samples = [
        *_build_decisive_samples(),
    ]
    summary = tracker.compute_summary()
    # 3 一致 + 2 不一致 + 2 中性 + 3 无分（见 _build_decisive_samples）
    assert summary["decisive_sample_count"] == 5
    assert summary["no_score_sample_count"] == 3
    assert summary["directional_accuracy"] == pytest.approx(3 / 5)
    # 旧字段仍在
    assert "alignment_rate" in summary


def _build_decisive_samples():
    samples = []
    # 3 无情感分
    for _ in range(3):
        samples.append(_sample_for_summary(None, 1.0))
    # 2 中性分
    for _ in range(2):
        samples.append(_sample_for_summary(0.05, 1.0))
    # 3 方向一致（正分+正收益 ×2，负分+负收益 ×1）
    samples.append(_sample_for_summary(0.5, 2.0))
    samples.append(_sample_for_summary(0.6, 1.0))
    samples.append(_sample_for_summary(-0.5, -2.0))
    # 2 方向不一致
    samples.append(_sample_for_summary(0.5, -1.0))
    samples.append(_sample_for_summary(-0.5, 1.0))
    return samples


def test_compute_summary_fallback_and_skip():
    """5d 缺失回退 3d；两者皆缺 → 跳过（不计入决定性样本）。"""
    tracker = MarketFeedbackTracker(path=str(Path(__file__).parent / "nonexistent_fb.json"))
    tracker.samples = [
        _sample_for_summary(0.5, None, realized_3d=2.0),
        _sample_for_summary(0.5, None, realized_3d=None),
        _sample_for_summary(None, 1.0),
    ]
    summary = tracker.compute_summary()
    assert summary["decisive_sample_count"] == 1
    assert summary["directional_accuracy"] == pytest.approx(1.0)


def test_compute_summary_zero_decisive():
    tracker = MarketFeedbackTracker(path=str(Path(__file__).parent / "nonexistent_fb.json"))
    tracker.samples = [_sample_for_summary(None, 1.0), _sample_for_summary(0.05, 1.0)]
    summary = tracker.compute_summary()
    assert summary["decisive_sample_count"] == 0
    assert summary["directional_accuracy"] is None  # 不除零、不伪造


# ============================================================
# US4: 无前视泄漏注入（T014）
# ============================================================

def test_realized_return_no_backward_leak():
    """泄漏注入：篡改 event_date 之前的数据不影响结果；篡改未来数据必然影响。"""
    closes = [100.0] * 10
    closes[9] = 200.0
    base = realized_return(closes, 4, 5)  # t=4 → j=9
    assert base == 100.0

    closes[0] = 999.0  # 过去数据污染 → 结果不得变化
    assert realized_return(closes, 4, 5) == base

    closes[9] = 300.0  # 窗口内未来数据 → 结果必然变化（证明只读 forward）
    assert realized_return(closes, 4, 5) == 200.0


# ============================================================
# US4 补充：工具边界与 CLI 覆盖（T016 覆盖率）
# ============================================================

def test_backfill_missing_file_raises(tmp_path):
    import backfill_market_feedback as backfill
    with pytest.raises(FileNotFoundError):
        backfill.backfill(tmp_path / "nope.json", tmp_path)


def test_backfill_empty_samples(tmp_path):
    import backfill_market_feedback as backfill
    fb = tmp_path / "market_feedback.json"
    write_feedback(fb, [])
    stats = backfill.backfill(fb, tmp_path)
    assert stats["total"] == 0
    assert len(list(tmp_path.glob("market_feedback.backup_*.json"))) == 0  # 空数据不建快照


def test_backfill_cli_main(monkeypatch, tmp_path, capsys):
    import backfill_market_feedback as backfill
    fb = tmp_path / "market_feedback.json"
    write_feedback(fb, [])
    monkeypatch.setattr("sys.argv", ["backfill", "--feedback", str(fb), "--kline-dir", str(tmp_path)])
    assert backfill.main() == 0
    capsys.readouterr()


def test_load_kline_bad_json_and_mismatch(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{invalid json", encoding="utf-8")
    assert diag.load_kline("bad", tmp_path) is None
    mismatch = tmp_path / "mismatch.json"
    mismatch.write_text(json.dumps({"dates": ["2026-08-01"], "kline": []}), encoding="utf-8")
    assert diag.load_kline("mismatch", tmp_path) is None


def test_realized_for_sample_date_missing():
    close_df = pd.DataFrame({"date": ["2026-08-10"], "close": [100.0]})
    sample = make_sample("A001", "2026-08-05")
    r3, r5 = diag.realized_for_sample(sample, close_df)
    assert r3 is None and r5 is None
    r3, r5 = diag.realized_for_sample(sample, None)
    assert r3 is None and r5 is None


def test_wilson_interval_zero_n():
    low, high = diag.wilson_interval(5, 0)
    assert low == 0.0 and high == 1.0


def test_directional_stats_negative_branch_and_verdicts(tmp_path):
    """负分样本分支 + 三选一结论分支（正相关/无关样本不足）。"""
    dates = [f"2026-08-{d:02d}" for d in range(1, 15)]
    rising = [100.0 + i for i in range(14)]
    falling = [200.0 - i for i in range(14)]
    kline_dir = tmp_path / "kline"
    kline_dir.mkdir()
    for code, closes in (("RISE", rising), ("FALL", falling)):
        with open(kline_dir / f"{code}.json", "w", encoding="utf-8") as fh:
            json.dump(make_kline_json(code, dates, closes), fh, ensure_ascii=False)

    samples = []
    for i in range(12):
        code = "RISE" if i < 6 else "FALL"
        score = 0.5 if i < 6 else -0.5
        samples.append(make_sample(code, "2026-08-05", score=score))
    fb = tmp_path / "market_feedback.json"
    write_feedback(fb, samples)

    report = diag.generate_report(fb, kline_dir)
    # RISE 正分命中上涨；FALL 负分命中下跌 → 全部一致 → 正相关
    assert "结论：正相关" in report

    # 无决定性样本 → 无关（样本不足）
    empty_samples = [make_sample("X", "2026-08-05", score=None)]
    write_feedback(fb, empty_samples)
    report2 = diag.generate_report(fb, kline_dir)
    assert "结论：无关（决定性样本不足" in report2

    # 全部方向相反 → 反转（覆盖负分误判分支与反转结论分支）
    flipped = []
    for i in range(12):
        code = "FALL" if i < 6 else "RISE"
        score = 0.5 if i < 6 else -0.5
        flipped.append(make_sample(code, "2026-08-05", score=score))
    write_feedback(fb, flipped)
    report3 = diag.generate_report(fb, kline_dir)
    assert "结论：反转" in report3


def test_diagnose_cli_main(monkeypatch, tmp_path, capsys):
    fb = tmp_path / "market_feedback.json"
    write_feedback(fb, [])
    report_path = tmp_path / "report.md"
    monkeypatch.setattr("sys.argv", [
        "diagnose", "--feedback", str(fb), "--kline-dir", str(tmp_path), "--report", str(report_path),
    ])
    assert diag.main() == 0
    capsys.readouterr()
    assert report_path.exists()


def test_wilson_interval_bounds():
    low, high = diag.wilson_interval(30, 100)
    assert 0.0 < low < 0.3 < high < 0.6
    low2, high2 = diag.wilson_interval(0, 100)
    assert low2 == 0.0 and high2 < 0.1
    low3, high3 = diag.wilson_interval(100, 100)
    assert low3 > 0.9 and high3 == pytest.approx(1.0, abs=1e-6)
