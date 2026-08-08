"""src/llm/generate_reports 报告生成入口测试。"""

import json
import os
from unittest.mock import patch

import pytest

from src.llm import generate_reports
from src.llm.config import DEEPSEEK_V4_FLASH_MODEL
from src.llm.generate_reports import (
    _load_all_details,
    _load_detail,
    _scores_from_detail,
    generate_reports as run_generate_reports,
)


def _make_detail(tmp_path, code="688525", name="佰维存储"):
    """构造一个最小的个股详情 JSON。"""
    detail_dir = tmp_path / "analysis"
    detail_dir.mkdir(parents=True, exist_ok=True)
    detail = {
        "schema_version": "2.0",
        "generated_at": "2026-08-07T17:30:00+08:00",
        "trade_date": "2026-08-07",
        "code": code,
        "name": name,
        "type": "stock",
        "category": "科技",
        "scores": {"risk_adjusted": 45.0, "risk": 74.2, "technical": 81.0, "industry": 32.0},
        "forecast": {"return_5d_pct": 6.54, "confidence": "medium", "sample_size": 30},
        "fundamental": None,
        "risk": {"level": "high", "label": "高风险"},
        "technical": {"trend": "uptrend"},
        "industry": {"name": "科技"},
        "similarity": {},
        "reasons": [],
    }
    path = detail_dir / f"{code}.json"
    path.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
    return path, detail


def test_load_detail(tmp_path):
    path, detail = _make_detail(tmp_path)
    # 覆盖 DATA_DIR，使其指向测试目录
    with patch.object(generate_reports, "DATA_DIR", str(tmp_path)):
        loaded = _load_detail("688525")
    assert loaded is not None
    assert loaded["code"] == "688525"


def test_load_detail_missing(tmp_path):
    with patch.object(generate_reports, "DATA_DIR", str(tmp_path)):
        assert _load_detail("000000") is None


def test_load_all_details(tmp_path):
    path1, _ = _make_detail(tmp_path, code="688525")
    path2, _ = _make_detail(tmp_path, code="600519")
    with patch.object(generate_reports, "DATA_DIR", str(tmp_path)):
        details = _load_all_details(["688525", "600519"])
    assert len(details) == 2


def test_scores_from_detail(tmp_path):
    _, detail = _make_detail(tmp_path)
    scores = _scores_from_detail(detail)
    assert scores["risk_adjusted"] == 45.0
    assert scores["risk"] == 74.2
    assert scores["technical"] == 81.0
    assert scores["industry"] == 32.0
    assert scores["fundamental"] is None


def test_generate_reports_offline(tmp_path):
    """离线（no-llm + no-news）应成功生成模板报告。"""
    with patch.object(generate_reports, "DATA_DIR", str(tmp_path)):
        with patch.object(generate_reports, "REPORT_DIR", str(tmp_path / "reports")):
            with patch("src.llm.llm_client.LLMClient.complete") as complete:
                _make_detail(tmp_path)
                result = run_generate_reports(
                    codes=["688525"],
                    use_llm=False,
                    news_enabled=False,
                    feedback_path=str(tmp_path / "feedback.json"),
                )
                complete.assert_not_called()
    assert result["total"] == 1
    assert result["generated"] == 1
    assert result["failed"] == []

    # 验证报告文件生成
    report_path = os.path.join(str(tmp_path / "reports"), "688525_2026-08-07.json")
    assert os.path.exists(report_path)
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    assert report["code"] == "688525"
    assert report["schema_version"] == "2.1"
    assert report["research_report"]["title"] == "佰维存储（688525）综合分析报告"
    assert report["llm_metadata"]["mode"] == "template"
    assert report["llm_metadata"]["fallback_reason"] == "llm_disabled"


def test_generate_reports_require_live_llm_skips_without_available_adapter(tmp_path):
    """核心流水线无可用 DeepSeek 时不抓新闻，也不覆盖深度报告。"""
    class UnavailableAdapter:
        is_available = False
        unavailable_reason = "missing_api_key"

    with patch.object(generate_reports, "DATA_DIR", str(tmp_path)):
        with patch.object(generate_reports, "REPORT_DIR", str(tmp_path / "reports")):
            with patch.object(
                generate_reports,
                "FinGPTDeepSeekAdapter",
                return_value=UnavailableAdapter(),
            ):
                with patch.object(generate_reports, "NewsFetcher") as news_fetcher:
                    _make_detail(tmp_path)
                    result = run_generate_reports(
                        codes=["688525"],
                        use_llm=True,
                        news_enabled=True,
                        feedback_path=str(tmp_path / "feedback.json"),
                        require_live_llm=True,
                    )

    assert result["status"] == "skipped"
    assert result["reason"] == "missing_api_key"
    assert result["generated"] == 0
    news_fetcher.assert_not_called()


@pytest.mark.parametrize(
    ("metadata", "should_save"),
    [
        ({"mode": "template", "model": DEEPSEEK_V4_FLASH_MODEL}, False),
        ({"mode": "deepseek_api", "model": "unexpected-model"}, False),
        ({"mode": "deepseek_api", "model": DEEPSEEK_V4_FLASH_MODEL}, True),
    ],
)
def test_generate_reports_require_live_llm_saves_only_verified_deepseek_output(
    tmp_path,
    metadata,
    should_save,
):
    """Core dispatch saves only verified DeepSeek V4 Flash reports."""
    adapter = type(
        "AvailableAdapter",
        (),
        {"is_available": True, "unavailable_reason": ""},
    )()
    with (
        patch.object(generate_reports, "NewsFetcher") as news_fetcher_class,
        patch.object(generate_reports, "ReportGenerator") as report_generator_class,
        patch.object(generate_reports, "MarketFeedbackTracker") as tracker_class,
        patch.object(generate_reports, "DATA_DIR", str(tmp_path)),
        patch.object(generate_reports, "REPORT_DIR", str(tmp_path / "reports")),
        patch.object(
            generate_reports,
            "FinGPTDeepSeekAdapter",
            return_value=adapter,
        ),
        patch.object(generate_reports, "Embedder"),
        patch.object(generate_reports, "RAGEngine"),
    ):
        fetcher = news_fetcher_class.return_value
        generator = report_generator_class.return_value
        tracker = tracker_class.return_value
        fetcher.fetch_stock.return_value = []
        generator.last_sentiment_results = []
        generator.generate.return_value = {"llm_metadata": metadata}
        generator.save.return_value = str(tmp_path / "saved-report.json")
        tracker.samples = []

        _make_detail(tmp_path)
        result = run_generate_reports(
            codes=["688525"],
            use_llm=True,
            news_enabled=False,
            feedback_path=str(tmp_path / "feedback.json"),
            require_live_llm=True,
        )

    assert result["generated"] == int(should_save)
    assert result["failed"] == ([] if should_save else ["688525"])
    if should_save:
        generator.save.assert_called_once()
        tracker.save.assert_called_once()
    else:
        generator.save.assert_not_called()
        tracker.save.assert_not_called()


def test_generate_reports_no_codes_loads_all(tmp_path):
    with patch.object(generate_reports, "DATA_DIR", str(tmp_path)):
        with patch.object(generate_reports, "REPORT_DIR", str(tmp_path / "reports")):
            _make_detail(tmp_path, code="688525")
            _make_detail(tmp_path, code="600519")
            result = run_generate_reports(
                use_llm=False,
                news_enabled=False,
                feedback_path=str(tmp_path / "feedback.json"),
            )
    assert result["total"] == 2
    assert result["generated"] == 2


def test_generate_reports_handles_failure(tmp_path):
    """详情缺失时应跳过而非崩溃。"""
    with patch.object(generate_reports, "DATA_DIR", str(tmp_path)):
        with patch.object(generate_reports, "REPORT_DIR", str(tmp_path / "reports")):
            result = run_generate_reports(
                codes=["999999"],  # 不存在的代码
                use_llm=False,
                news_enabled=False,
                feedback_path=str(tmp_path / "feedback.json"),
            )
    assert result["total"] == 0
    assert result["generated"] == 0
    assert result["failed"] == []
