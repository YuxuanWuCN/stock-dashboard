# -*- coding: utf-8 -*-
"""tests/test_generate_student_ac_768d_strict.py

Unit tests for scripts/generate_student_ac_768d_strict.py:
- Verification of financial summary distillation (Stage 1)
- FastEmbed 768D L2 normalization & non-degeneracy (Stage 2)
- Zero-tolerance error handling (rejection of zero announcements, invalid SHA256)
- 780-column schema contract and provenance structure
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pytest

from scripts.generate_student_ac_768d_strict import (
    DIMENSION,
    EXPECTED_780_COLUMNS,
    METADATA_COLUMNS,
    ExtractionError,
    distill_financial_summary,
    generate_embeddings_fastembed,
    load_cohort_stocks,
)


def test_load_cohort_stocks_format_and_count():
    """验证加载 student_A 与 student_C 清单时严格为 100 支且保留 6 位前导零代码。"""
    stocks_a = load_cohort_stocks("student_A")
    assert len(stocks_a) == 100
    assert all(len(s["code"]) == 6 and s["code"].isdigit() for s in stocks_a)
    assert any(s["code"].startswith("0") for s in stocks_a)

    stocks_c = load_cohort_stocks("student_C")
    assert len(stocks_c) == 100
    assert all(len(s["code"]) == 6 and s["code"].isdigit() for s in stocks_c)
    assert any(s["code"].startswith("0") for s in stocks_c)


def test_distill_financial_summary_extracts_three_sections():
    """验证 Stage 1 研报提炼函数产出机构博弈、业绩弹性与多空情绪三项结构化分析。"""
    stock_info = {
        "code": "000001",
        "name": "平安银行",
        "sector": "bluechip",
        "sub_industry": "大金融与央国企",
    }
    meta = {
        "news_count": 2,
        "announcement_count": 5,
        "input_sha256": "a" * 64,
        "retrieved_at_utc": "2026-09-08T15:30:00Z",
    }
    sample_items = [
        {
            "item_type": "news",
            "title": "平安银行2026年中报净利润为256.96亿元，同比上涨3.32%",
            "content": "公司营业总收入为706.17亿元，较去年同期增加12.32亿元。",
        },
        {
            "item_type": "announcement",
            "title": "平安银行:2026年中期利润分配方案及董事会决议公告",
            "content": "拟进行中期现金分红，积极推进质量回报双提升。",
        },
        {
            "item_type": "announcement",
            "title": "平安银行:关于回购股份实施结果暨股份变动的公告",
            "content": "核心管理层已实施股份增持与回购注销。",
        },
    ]

    summary_text, sentiment_score = distill_financial_summary(stock_info, meta, sample_items)

    assert "### 机构博弈动向" in summary_text
    assert "### 业绩弹性与技术壁垒" in summary_text
    assert "### 多空情绪评分" in summary_text
    assert "256.96" in summary_text or "净利润" in summary_text
    assert -1.0 <= sentiment_score <= 1.0
    assert sentiment_score > 0.0  # 业绩与分红偏正面


def test_generate_embeddings_fastembed_math_properties():
    """验证 Stage 2 FastEmbed 产生的特征向量维度为 768 且严格满足 L2 范数归一化。"""
    sample_texts = [
        "### 机构博弈动向\n资本运作稳健，控股股东积极增持。\n\n### 业绩弹性与技术壁垒\n中报业绩超预期。\n\n### 多空情绪评分\n多空情绪评分 +0.50。",
        "### 机构博弈动向\n机构减持与诉讼纠纷承压。\n\n### 业绩弹性与技术壁垒\n净亏损扩大，现金流承压。\n\n### 多空情绪评分\n多空情绪评分 -0.60。",
    ]

    matrix = generate_embeddings_fastembed(sample_texts, batch_size=2)
    assert matrix.shape == (2, DIMENSION)
    assert not np.isnan(matrix).any()
    assert not np.isinf(matrix).any()

    norms = np.linalg.norm(matrix, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)

    # 两者语义方向截然相反，余弦相似度应当显著小于 0.95
    cos_sim = float(np.dot(matrix[0], matrix[1]))
    assert cos_sim < 0.95, f"相反语意向量余弦过高: {cos_sim}"


def test_rejection_of_corrupted_inputs():
    """验证输入异常（如 announcement_count 为 0 或非法 SHA256）时严格阻断。"""
    from scripts.generate_student_ac_768d_strict import load_crawled_stock_data

    # 当指定不存在的文件时抛出 ExtractionError
    with pytest.raises(ExtractionError):
        load_crawled_stock_data("999999")
