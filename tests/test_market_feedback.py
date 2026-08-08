"""src/market_feedback 市场反馈标签 + RLSP 奖励测试。"""

import json

from src.market_feedback import (
    MarketFeedbackTracker,
    _excess_return,
    _label_from_excess,
    compute_rlsp_reward,
    compute_rlsp_reward_continuous,
    compute_ranking_discrimination,
    generate_soft_label,
)


# ---- 基础函数 ----

def test_excess_return_with_benchmark():
    assert _excess_return(5.0, 2.0) == 3.0
    assert _excess_return(-3.0, 1.0) == -4.0


def test_excess_return_without_benchmark():
    assert _excess_return(5.0, None) == 5.0
    assert _excess_return(None, 2.0) is None


def test_label_from_excess():
    assert _label_from_excess(1.5) == "positive_surprise"
    assert _label_from_excess(-1.5) == "negative_surprise"
    assert _label_from_excess(0.0) == "neutral"
    assert _label_from_excess(None) == "neutral"


# ---- RLSP 奖励 ----

def test_rlsp_reward_sign_matches_returns():
    # 预测正面 & 股价涨 → 正奖励
    assert compute_rlsp_reward(1.0, 2.0) == 2.0
    # 预测正面 & 股价跌 → 负奖励
    assert compute_rlsp_reward(1.0, -2.0) == -2.0
    # 预测负面 & 股价涨 → 负奖励
    assert compute_rlsp_reward(-1.0, 3.0) == -3.0
    # 中性 → 0
    assert compute_rlsp_reward(0.0, 5.0) == 0.0


def test_rlsp_reward_returns_none_when_return_missing():
    assert compute_rlsp_reward(1.0, None) is None
    assert compute_rlsp_reward_continuous(0.5, None) is None


def test_rlsp_reward_continuous_uses_score():
    # 连续版本：分数越大对收益越敏感
    r1 = compute_rlsp_reward_continuous(1.0, 2.0)
    r2 = compute_rlsp_reward_continuous(0.5, 2.0)
    assert r1 == 2.0
    assert r2 == 1.0
    # 分数方向与收益方向相反 → 负奖励
    assert compute_rlsp_reward_continuous(0.8, -1.0) == -0.8


# ---- 软标签 ----

def test_soft_label_aligned_positive():
    sl = generate_soft_label(0.8, 5.0)
    assert sl["hard_label"] == "positive"
    assert sl["aligned"] is True
    assert sl["weight"] > 0.5


def test_soft_label_aligned_negative():
    sl = generate_soft_label(-0.8, -5.0)
    assert sl["hard_label"] == "negative"
    assert sl["aligned"] is True
    assert sl["weight"] > 0.5


def test_soft_label_conflicting_reduces_weight():
    aligned = generate_soft_label(0.8, 5.0)
    conflicting = generate_soft_label(0.8, -5.0)
    assert conflicting["aligned"] is False
    assert conflicting["weight"] < aligned["weight"]


def test_soft_label_no_return_zero_weight():
    sl = generate_soft_label(0.8, None)
    assert sl["weight"] == 0.0
    assert sl["hard_label"] == "neutral"


# ---- 排序区分度 ----

def test_ranking_discrimination_separates():
    items = [
        {"code": "a", "sentiment_score": 0.9, "excess_5d_pct": 5.0},
        {"code": "b", "sentiment_score": 0.6, "excess_5d_pct": 3.0},
        {"code": "c", "sentiment_score": 0.1, "excess_5d_pct": 0.5},
        {"code": "d", "sentiment_score": -0.4, "excess_5d_pct": -2.0},
        {"code": "e", "sentiment_score": -0.8, "excess_5d_pct": -4.0},
    ]
    result = compute_ranking_discrimination(items, top_k=2)
    assert result["top_k_avg_return"] > 0
    assert result["bottom_k_avg_return"] < 0
    assert result["spread"] > 0
    assert result["rank_ic"] > 0
    assert result["top_k_codes"] == ["a", "b"]
    assert result["bottom_k_codes"] == ["d", "e"]


def test_ranking_discrimination_empty():
    result = compute_ranking_discrimination([])
    assert result["total_items"] == 0
    assert result["spread"] is None


def test_ranking_discrimination_filters_invalid():
    items = [
        {"code": "a", "sentiment_score": None, "excess_5d_pct": 5.0},
        {"code": "b", "sentiment_score": 0.5, "excess_5d_pct": None},
        {"code": "c", "sentiment_score": 0.3, "excess_5d_pct": 1.0},
    ]
    result = compute_ranking_discrimination(items)
    assert result["total_items"] == 1
    assert result["top_k_codes"] == ["c"]


# ---- Tracker 集成 ----

def test_record_event_with_sentiment_and_rlsp():
    tracker = MarketFeedbackTracker(path="/nonexistent/path.json")
    sample = tracker.record_event(
        "600519", "贵州茅台", "2026-08-05", "业绩预告",
        ret_3d=5.0, ret_5d=8.0, benchmark_ret_3d=1.0, benchmark_ret_5d=2.0,
        sentiment_score=0.8,
    )
    assert sample["label"] == "positive_surprise"
    assert sample["excess_5d_pct"] == 6.0
    assert sample["rlsp_reward_5d"] == round(0.8 * 6.0, 4)
    assert sample["soft_label"]["aligned"] is True


def test_record_event_without_sentiment():
    tracker = MarketFeedbackTracker(path="/nonexistent/path.json")
    sample = tracker.record_event(
        "000001", "平安银行", "2026-08-05", "不良率上升",
        ret_3d=-3.0, ret_5d=-5.0,
    )
    assert sample["sentiment_score"] is None
    assert sample["rlsp_reward_5d"] is None
    assert sample["soft_label"]["hard_label"] == "neutral"


def test_compute_summary_empty():
    tracker = MarketFeedbackTracker(path="/nonexistent/path.json")
    summary = tracker.compute_summary()
    assert summary["total"] == 0
    assert summary["avg_excess_5d_pct"] is None


def test_compute_summary_counts():
    tracker = MarketFeedbackTracker(path="/nonexistent/path.json")
    tracker.record_event("a", "A", "2026-08-01", "t", 5, 8, 0, 0, sentiment_score=0.8)
    tracker.record_event("b", "B", "2026-08-01", "t", -5, -8, 0, 0, sentiment_score=-0.8)
    tracker.record_event("c", "C", "2026-08-01", "t", 0.5, 0.5, 0, 0)
    summary = tracker.compute_summary()
    assert summary["total"] == 3
    assert summary["positive_surprise"] == 1
    assert summary["negative_surprise"] == 1
    assert summary["neutral"] == 1
    assert summary["avg_rlsp_reward_5d"] > 0
    assert summary["alignment_rate"] >= 0.0


def test_export_training_samples_filters_by_weight():
    tracker = MarketFeedbackTracker(path="/nonexistent/path.json")
    tracker.record_event("a", "A", "2026-08-01", "业绩", 5, 8, sentiment_score=0.8)
    tracker.record_event("b", "B", "2026-08-01", "公告", 0, 0, sentiment_score=0.0)
    samples = tracker.export_training_samples(min_weight=0.1)
    assert len(samples) == 1
    assert samples[0]["code"] if "code" in samples[0] else True
    assert samples[0]["weight"] >= 0.1


def test_export_aligned_samples():
    tracker = MarketFeedbackTracker(path="/nonexistent/path.json")
    tracker.record_event("a", "A", "2026-08-01", "t", 5, 8, sentiment_score=0.8)   # 方向一致
    tracker.record_event("b", "B", "2026-08-01", "t", -5, -8, sentiment_score=0.8)  # 方向矛盾
    aligned = tracker.export_aligned_samples()
    assert len(aligned) == 1
    assert aligned[0]["code"] == "a"


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "feedback.json")
    tracker = MarketFeedbackTracker(path=path)
    tracker.record_event("600519", "贵州茅台", "2026-08-05", "业绩", 5, 8, 1, 2, sentiment_score=0.8)
    tracker.save()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["schema_version"] == "2.1"
    assert len(data["samples"]) == 1
    assert data["samples"][0]["rlsp_reward_5d"] == round(0.8 * 6.0, 4)

    tracker2 = MarketFeedbackTracker(path=path)
    assert len(tracker2.samples) == 1
    assert tracker2.samples[0]["code"] == "600519"


def test_export_samples():
    tracker = MarketFeedbackTracker(path="/nonexistent/path.json")
    tracker.record_event("600519", "贵州茅台", "2026-08-05", "业绩", 5, 8)
    samples = tracker.export_samples()
    assert len(samples) == 1
    assert set(samples[0].keys()) >= {"code", "event_date", "label", "ret_5d_pct"}
