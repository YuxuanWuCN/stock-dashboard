"""严格真实来源 768D 文本因子生成器的离线契约测试。"""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


try:
    strict = importlib.import_module("scripts.generate_student_b_768d_strict")
except ModuleNotFoundError:
    strict = None


class FakeAkshare:
    @staticmethod
    def stock_news_em(symbol):
        return pd.DataFrame(
            [{"新闻标题": f"{symbol} 真实公告标题", "新闻内容": "真实内容", "发布时间": "2026-09-01", "新闻链接": "https://example.test/news"}]
        )

    @staticmethod
    def stock_individual_notice_report(security, symbol="全部", begin_date=None, end_date=None):
        return pd.DataFrame(
            [{"公告标题": f"{security} 真实公告", "公告内容": "真实公告内容", "公告日期": "2026-09-02", "公告链接": "https://example.test/notice"}]
        )


class EmptyAkshare:
    @staticmethod
    def stock_news_em(symbol):
        return pd.DataFrame()

    @staticmethod
    def stock_individual_notice_report(security, symbol="全部", begin_date=None, end_date=None):
        return pd.DataFrame()


class FakeEmbedder:
    def embed(self, texts):
        assert len(texts) == 1
        yield np.ones(768, dtype=np.float32)


def _row():
    return pd.Series(
        {
            "code": "000591",
            "name": "太阳能",
            "sub_industry": "绿电与清洁公用",
            "sector": "growth",
            "beta": 1.0,
            "alpha": 0.1,
            "cohort_key": "student_B",
        }
    )


def test_strict_module_exists():
    assert strict is not None


def test_empty_external_corpus_is_rejected_without_fallback():
    assert strict is not None
    with pytest.raises(strict.StrictSourceError):
        strict.collect_real_news_corpus("000591", "太阳能", ak_module=EmptyAkshare)


def test_record_uses_real_source_metadata_and_exact_768_dimensions():
    assert strict is not None

    def fake_chat(prompt, config):
        assert "真实公告标题" in prompt
        return "真实 DeepSeek 摘要"

    record = strict.generate_strict_record(
        _row(),
        llm_config={"is_valid_key": True},
        embedder=FakeEmbedder(),
        ak_module=FakeAkshare,
        chat_call=fake_chat,
    )

    assert record["feature_source"] == "llm_deepseek_extracted_strict"
    assert record["embedding_source"] == "fastembed:jinaai/jina-embeddings-v2-base-zh"
    assert record["news_count"] == 1
    assert record["announcement_count"] == 1
    assert len([k for k in record if k.startswith("dim_")]) == 768
    assert record["input_sha256"]


def test_deepseek_failure_is_not_replaced_by_template():
    assert strict is not None

    def failed_chat(prompt, config):
        return None

    with pytest.raises(strict.StrictGenerationError):
        strict.generate_strict_record(
            _row(),
            llm_config={"is_valid_key": True},
            embedder=FakeEmbedder(),
            ak_module=FakeAkshare,
            chat_call=failed_chat,
        )
