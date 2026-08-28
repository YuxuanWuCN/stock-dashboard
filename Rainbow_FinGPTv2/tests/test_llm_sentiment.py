"""src/llm/llm_sentiment LLM 情感分析测试。"""

import json

from src.llm.llm_client import LLMClient
from src.llm.llm_sentiment import (
    LLMSentimentAnalyzer,
    _label_from_score,
    _parse_llm_response,
)


# ---- 解析函数 ----

def test_parse_llm_response_clean_json():
    assert _parse_llm_response('{"sentiment": "positive", "score": 0.8}') == {
        "sentiment": "positive", "score": 0.8
    }


def test_parse_llm_response_with_fence():
    raw = '```json\n{"sentiment": "negative", "score": -0.5}\n```'
    parsed = _parse_llm_response(raw)
    assert parsed["sentiment"] == "negative"


def test_parse_llm_response_with_surrounding_text():
    raw = '结果如下：\n{"sentiment": "neutral", "score": 0.0}\n完成'
    parsed = _parse_llm_response(raw)
    assert parsed["sentiment"] == "neutral"


def test_parse_llm_response_invalid():
    assert _parse_llm_response("不是JSON") is None


def test_label_from_score():
    assert _label_from_score(0.8) == "positive"
    assert _label_from_score(-0.8) == "negative"
    assert _label_from_score(0.0) == "neutral"
    assert _label_from_score(0.05) == "neutral"


# ---- LLM 路径 ----

class _FakeLLMClient:
    """模拟 LLM 客户端。"""
    is_available = True

    def __init__(self, response):
        self.response = response
        self.calls = 0

    def complete(self, system_prompt, user_prompt, max_tokens=None, temperature=0.3):
        self.calls += 1
        return self.response


def test_analyze_with_llm_uses_llm():
    fake = _FakeLLMClient(json.dumps({"sentiment": "positive", "score": 0.8}))
    analyzer = LLMSentimentAnalyzer(llm_client=fake)
    result = analyzer.analyze("公司净利润大幅增长")
    assert result.label == "positive"
    assert result.score == 0.8
    assert result.source == "llm"
    assert fake.calls == 1


def test_analyze_with_llm_negative():
    fake = _FakeLLMClient(json.dumps({"sentiment": "negative", "score": -0.7}))
    analyzer = LLMSentimentAnalyzer(llm_client=fake)
    result = analyzer.analyze("公司业绩亏损")
    assert result.label == "negative"
    assert result.score == -0.7


def test_analyze_llm_failure_falls_back_to_rule():
    class _FailingClient:
        is_available = True
        def complete(self, *args, **kwargs):
            raise Exception("API 500")

    analyzer = LLMSentimentAnalyzer(llm_client=_FailingClient())
    result = analyzer.analyze("公司净利润大幅增长")
    assert result.source == "rule"
    assert result.label in ("positive", "negative", "neutral")


def test_analyze_llm_invalid_response_falls_back():
    class _GarbageClient:
        is_available = True
        def complete(self, *args, **kwargs):
            return "无法解析的内容"

    analyzer = LLMSentimentAnalyzer(llm_client=_GarbageClient())
    result = analyzer.analyze("公司发布公告")
    assert result.source == "rule"


# ---- 规则降级路径 ----

def test_analyze_without_llm_uses_rule():
    analyzer = LLMSentimentAnalyzer(llm_client=LLMClient(""))  # 空后端 -> 不可用
    assert analyzer.llm_available is False
    result = analyzer.analyze("公司净利润大幅增长")
    assert result.source == "rule"
    assert result.label == "positive"


def test_analyze_empty_text_neutral():
    analyzer = LLMSentimentAnalyzer(llm_client=LLMClient(""))
    result = analyzer.analyze("")
    assert result.label == "neutral"
    assert result.score == 0.0


# ---- 缓存与批量 ----

def test_analyze_caches_results():
    fake = _FakeLLMClient(json.dumps({"sentiment": "positive", "score": 0.8}))
    analyzer = LLMSentimentAnalyzer(llm_client=fake)
    analyzer.analyze("同一句话")
    analyzer.analyze("同一句话")
    assert fake.calls == 1


def test_analyze_batch_preserves_order():
    fake = _FakeLLMClient(json.dumps([
        {"sentiment": "positive", "score": 0.7},
        {"sentiment": "negative", "score": -0.6},
        {"sentiment": "neutral", "score": 0.0},
    ]))
    analyzer = LLMSentimentAnalyzer(llm_client=fake)
    results = analyzer.analyze_batch(["文本A", "文本B", "文本C"])
    assert [result.label for result in results] == [
        "positive",
        "negative",
        "neutral",
    ]
    assert fake.calls == 1


def test_analyze_batch_failure_falls_back_with_one_api_call():
    class _FailingBatchClient:
        is_available = True

        def __init__(self):
            self.calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            raise Exception("API 500")

    fake = _FailingBatchClient()
    analyzer = LLMSentimentAnalyzer(llm_client=fake)
    results = analyzer.analyze_batch(["公司盈利增长", "公司出现亏损"])

    assert len(results) == 2
    assert all(result.source == "rule" for result in results)
    assert fake.calls == 1


def test_analyze_batch_reuses_duplicate_text_without_extra_call():
    fake = _FakeLLMClient(json.dumps([
        {"sentiment": "positive", "score": 0.7},
    ]))
    analyzer = LLMSentimentAnalyzer(llm_client=fake)
    results = analyzer.analyze_batch(["同一新闻", "同一新闻"])

    assert [result.label for result in results] == ["positive", "positive"]
    assert fake.calls == 1


def test_to_dict_shape():
    fake = _FakeLLMClient(json.dumps({"sentiment": "positive", "score": 0.6}))
    analyzer = LLMSentimentAnalyzer(llm_client=fake)
    d = analyzer.analyze("公司盈利").to_dict()
    assert set(d.keys()) == {"label", "score", "source"}
