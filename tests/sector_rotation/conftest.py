# -*- coding: utf-8 -*-
"""tests/sector_rotation/conftest.py —— 板块轮动单元测试公共 Fixtures"""

import pytest
from src.llm.llm_sentiment import LLMSentimentResult
from src.sector_rotation.config import SECTORS
from src.sector_rotation.sector_sentiment_aggregator import SectorSentimentAggregator
from src.sector_rotation.utils.sector_utils import StockSentimentInput


@pytest.fixture
def aggregator() -> SectorSentimentAggregator:
    """标准板块情绪聚合器实例"""
    return SectorSentimentAggregator(expected_stocks_per_sector=6, trend_threshold=0.05)


@pytest.fixture
def sample_green_stocks() -> list[StockSentimentInput]:
    """绿色新能源板块 6 只标的样本数据"""
    return [
        StockSentimentInput(
            code="001258",
            name="立新能源",
            sector="green",
            sentiment_score=0.45,
            sentiment_confidence=0.85,
            news_count=5,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="002459",
            name="晶澳科技",
            sector="green",
            sentiment_score=0.30,
            sentiment_confidence=0.80,
            news_count=3,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="002466",
            name="天齐锂业",
            sector="green",
            sentiment_score=-0.10,
            sentiment_confidence=0.75,
            news_count=4,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="601012",
            name="隆基绿能",
            sector="green",
            sentiment_score=0.20,
            sentiment_confidence=0.90,
            news_count=8,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="600438",
            name="通威股份",
            sector="green",
            sentiment_score=0.15,
            sentiment_confidence=0.80,
            news_count=2,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="300750",
            name="宁德时代",
            sector="green",
            sentiment_score=0.60,
            sentiment_confidence=0.95,
            news_count=10,
            timestamp="2026-10-12",
        ),
    ]


@pytest.fixture
def sample_storage_stocks() -> list[StockSentimentInput]:
    """存储芯片板块 6 只标的样本数据（高景气态）"""
    return [
        StockSentimentInput(
            code="688525",
            name="佰维存储",
            sector="storage",
            sentiment_score=0.75,
            sentiment_confidence=0.90,
            news_count=6,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="688123",
            name="聚辰股份",
            sector="storage",
            sentiment_score=0.65,
            sentiment_confidence=0.85,
            news_count=4,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="603986",
            name="兆易创新",
            sector="storage",
            sentiment_score=0.80,
            sentiment_confidence=0.92,
            news_count=7,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="688041",
            name="海光信息",
            sector="storage",
            sentiment_score=0.55,
            sentiment_confidence=0.88,
            news_count=5,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="688008",
            name="澜起科技",
            sector="storage",
            sentiment_score=0.70,
            sentiment_confidence=0.90,
            news_count=8,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="002049",
            name="紫光国微",
            sector="storage",
            sentiment_score=0.60,
            sentiment_confidence=0.80,
            news_count=3,
            timestamp="2026-10-12",
        ),
    ]


@pytest.fixture
def sample_gold_stocks() -> list[StockSentimentInput]:
    """黄金避险板块 7 只标的样本数据"""
    return [
        StockSentimentInput(
            code="600547",
            name="山东黄金",
            sector="gold",
            sentiment_score=0.40,
            sentiment_confidence=0.85,
            news_count=4,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="601899",
            name="紫金矿业",
            sector="gold",
            sentiment_score=0.50,
            sentiment_confidence=0.90,
            news_count=6,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="600489",
            name="中金黄金",
            sector="gold",
            sentiment_score=0.35,
            sentiment_confidence=0.80,
            news_count=3,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="002155",
            name="湖南黄金",
            sector="gold",
            sentiment_score=0.45,
            sentiment_confidence=0.82,
            news_count=2,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="000975",
            name="山金国际",
            sector="gold",
            sentiment_score=0.30,
            sentiment_confidence=0.78,
            news_count=2,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="600988",
            name="赤峰黄金",
            sector="gold",
            sentiment_score=0.42,
            sentiment_confidence=0.80,
            news_count=3,
            timestamp="2026-10-12",
        ),
        StockSentimentInput(
            code="600362",
            name="江西铜业",
            sector="gold",
            sentiment_score=0.28,
            sentiment_confidence=0.75,
            news_count=4,
            timestamp="2026-10-12",
        ),
    ]


@pytest.fixture
def sample_v26_dict_stocks() -> list[dict]:
    """v2.6 格式的原始字典列表"""
    return [
        {
            "code": "688525",
            "name": "佰维存储",
            "sentiment_score": 0.65,
            "sentiment_confidence": 0.85,
            "news_count": 4,
            "timestamp": "2026-10-12",
        },
        {
            "code": "688123",
            "name": "聚辰股份",
            "score": 0.55,
            "confidence": 0.80,
            "count": 3,
            "date": "2026-10-12",
        },
    ]


@pytest.fixture
def sample_llm_result_stocks() -> list[tuple[str, LLMSentimentResult]]:
    """真实 LLMSentimentResult 实例与代码元组"""
    return [
        (
            "603986",
            LLMSentimentResult(
                text="兆易创新发布高景气存储业绩",
                label="positive",
                score=0.82,
                source="llm",
            ),
        ),
        (
            "688008",
            LLMSentimentResult(
                text="澜起科技互联芯片出货符合预期",
                label="neutral",
                score=0.15,
                source="rule",
            ),
        ),
    ]
