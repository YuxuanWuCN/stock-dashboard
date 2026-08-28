"""src/llm/report_generator 报告生成测试。"""

import json
from unittest.mock import patch

from src.llm.llm_client import LLMClient
from src.llm.report_generator import ReportGenerator, _parse_llm_json
from src.llm.rag_engine import RAGEngine
from src.llm.embeddings import Embedder


def _scores():
    return {
        "fundamental": 62.5,
        "risk_adjusted": 58.3,
        "risk": 40.0,
        "technical": 65.0,
        "industry": 55.0,
        "total": 60.4,
    }


def _news_items():
    return [
        {
            "title": "佰维存储发布业绩预告",
            "content": "净利润大幅增长，存储芯片需求旺盛。",
            "source": "东方财富",
            "publish_time": "2026-08-05",
            "url": "http://example.com/1",
            "code": "688525",
            "name": "佰维存储",
        },
        {
            "title": "佰维存储存货减值风险提示",
            "content": "行业需求疲软，存在存货减值风险。",
            "source": "新浪财经",
            "publish_time": "2026-08-04",
            "url": "http://example.com/2",
            "code": "688525",
            "name": "佰维存储",
        },
    ]


def test_template_report_structure_without_llm():
    gen = ReportGenerator(llm_client=LLMClient(""), rag=None)
    report = gen.generate(
        "688525", "佰维存储", _scores(), _news_items(), trade_date="2026-08-07"
    )
    assert report["schema_version"] == "2.1"
    assert report["code"] == "688525"
    assert report["name"] == "佰维存储"
    assert report["scores"]["fundamental"] == 62.5
    assert report["research_report"]["title"] == "佰维存储（688525）综合分析报告"
    assert report["research_report"]["elder_friendly"]
    assert report["disclaimer"]
    assert report["citation_audit"]["total"] >= 0
    assert report["llm_metadata"]["mode"] == "template"
    assert report["llm_metadata"]["fallback_reason"] == "llm_disabled"
    assert "api_key" not in json.dumps(report["llm_metadata"])


def test_template_report_with_news_sentiment():
    gen = ReportGenerator(llm_client=LLMClient(""), rag=None)
    report = gen.generate("688525", "佰维存储", _scores(), _news_items(), "2026-08-07")
    news = report["news_sentiment"]
    assert news["total_articles"] == 2
    assert 0 <= news["positive_ratio"] <= 1
    assert 0 <= news["negative_ratio"] <= 1
    assert abs(news["positive_ratio"] + news["negative_ratio"] + news["neutral_ratio"] - 1) < 1e-6


def test_template_report_no_news_adds_uncertain():
    gen = ReportGenerator(llm_client=LLMClient(""), rag=None)
    report = gen.generate("688525", "佰维存储", _scores(), [], "2026-08-07")
    assert report["news_sentiment"]["total_articles"] == 0
    # 应包含不确定性说明
    assert report["confidence"] == "low"


def test_report_with_rag_adds_citations():
    rag = RAGEngine(enabled=True, embedder=Embedder(backend="hash"))
    gen = ReportGenerator(llm_client=LLMClient(""), rag=rag)
    report = gen.generate("688525", "佰维存储", _scores(), _news_items(), "2026-08-07")
    audit = report["citation_audit"]
    assert audit["evidence"] >= 1


def test_report_save_writes_json(tmp_path):
    gen = ReportGenerator(llm_client=LLMClient(""), rag=None)
    gen.report_dir = str(tmp_path)
    report = gen.generate("688525", "佰维存储", _scores(), [], "2026-08-07")
    path = gen.save(report)
    assert path.endswith("688525_2026-08-07.json")
    with open(path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["code"] == "688525"


def test_llm_report_uses_llm_when_available():
    fake_llm_json = json.dumps({
        "summary": "佰维存储基本面评分62.5，风险中等。",
        "sections": [
            {"heading": "基本面评价", "content": "评分中等偏上。"},
            {"heading": "短期行情分析", "content": "风险分40。"},
            {"heading": "近期消息面", "content": "正面新闻占多数。"},
            {"heading": "主要风险", "content": "存货减值风险。"},
            {"heading": "不确定性说明", "content": "数据可能不完整。"},
        ],
        "elder_friendly": "公司赚钱能力还行，风险中等，注意别追高。",
    })

    class _FakeClient:
        is_available = True
        backend = "deepseek"
        model = "deepseek-v4-flash"
        unavailable_reason = ""

        def __init__(self):
            self.calls = 0

        def complete(self, system_prompt, user_prompt, max_tokens=None, temperature=0.3):
            self.calls += 1
            if self.calls == 1:
                return json.dumps([
                    {"sentiment": "positive", "score": 0.7},
                    {"sentiment": "negative", "score": -0.6},
                ])
            return fake_llm_json

    fake_client = _FakeClient()
    gen = ReportGenerator(llm_client=fake_client, rag=None)
    report = gen.generate("688525", "佰维存储", _scores(), _news_items(), "2026-08-07")
    assert report["research_report"]["summary"] == "佰维存储基本面评分62.5，风险中等。"
    assert report["research_report"]["elder_friendly"] == "公司赚钱能力还行，风险中等，注意别追高。"
    assert len(report["research_report"]["sections"]) == 5
    assert report["scores"] == _scores()
    assert report["llm_metadata"]["pipeline"] == "fingpt_style_rag"
    assert report["llm_metadata"]["backend"] == "deepseek"
    assert report["llm_metadata"]["model"] == "deepseek-v4-flash"
    assert report["llm_metadata"]["mode"] == "deepseek_api"
    assert report["llm_metadata"]["fallback_reason"] == ""
    assert fake_client.calls == 2


def test_llm_failure_degrades_to_template():
    class _FailingClient:
        is_available = True
        unavailable_reason = ""

        def __init__(self):
            self.calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            raise Exception("API 500")

    fake_client = _FailingClient()
    gen = ReportGenerator(llm_client=fake_client, rag=None)
    report = gen.generate("688525", "佰维存储", _scores(), [], "2026-08-07")
    assert report["schema_version"] == "2.1"
    assert report["research_report"]["sections"][0]["heading"] == "核心摘要"
    assert report["llm_metadata"]["mode"] == "template"
    assert report["llm_metadata"]["fallback_reason"] == "invalid_response"
    assert fake_client.calls == 3


def test_llm_invalid_shape_retries_then_degrades():
    class _InvalidShapeClient:
        is_available = True
        backend = "deepseek"
        model = "deepseek-v4-flash"
        unavailable_reason = ""

        def __init__(self):
            self.calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            return json.dumps({
                "summary": "摘要",
                "sections": [],
                "elder_friendly": "简明摘要",
            })

    fake_client = _InvalidShapeClient()
    gen = ReportGenerator(llm_client=fake_client, rag=None)
    report = gen.generate("688525", "佰维存储", _scores(), [], "2026-08-07")

    assert fake_client.calls == 3
    assert report["llm_metadata"]["mode"] == "template"
    assert report["llm_metadata"]["fallback_reason"] == "invalid_response"
    assert report["confidence"] == "low"


def test_parse_llm_json_handles_fences():
    raw = '```json\n{"a": 1}\n```'
    assert _parse_llm_json(raw) == {"a": 1}


def test_parse_llm_json_handles_surrounding_text():
    raw = '以下是结果：\n{"summary": "x", "sections": []}\n结束'
    assert _parse_llm_json(raw)["summary"] == "x"
