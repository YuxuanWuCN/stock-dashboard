# -*- coding: utf-8 -*-
"""src/llm/summarizer.py —— 新闻自动摘要模块

用途：
- 把完整新闻（3000字）压缩成高质量摘要（150-300字）
- 降低 LLM 情绪打分的 token 消耗（↓ 90%）
- 提高情绪分析的准确率（去除噪音）

技术栈：
- 优先使用轻量 Transformer 模型（BERTSum、BART-Chinese）
- 降级为 TextRank 关键句提取（离线、零依赖）
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("stock-dashboard.llm.summarizer")

# 是否启用深度学习摘要（需要 transformers 库）
_USE_TRANSFORMERS = False
_SUMMARIZER_PIPELINE = None

try:
    from transformers import pipeline
    _SUMMARIZER_PIPELINE = pipeline(
        "summarization",
        model="uer/pegasus-base-chinese-cluecorpussmall",  # 轻量中文摘要模型
        device=-1,  # CPU
    )
    _USE_TRANSFORMERS = True
    logger.info("摘要器已启用深度学习模型: pegasus-base-chinese")
except Exception as e:
    logger.warning("Transformers 摘要器不可用，降级到 TextRank: %s", e)


def summarize_text(text: str, max_length: int = 200, min_length: int = 50) -> str:
    """自动摘要主入口。

    Args:
        text: 完整新闻文本（3000字）
        max_length: 摘要最大长度（字）
        min_length: 摘要最小长度（字）

    Returns:
        高质量摘要（150-300字）
    """
    if not text or len(text) < min_length:
        return text.strip()

    # 清洗文本
    text = _clean_text(text)

    # 策略1: 深度学习摘要（准确率最高）
    if _USE_TRANSFORMERS and _SUMMARIZER_PIPELINE is not None:
        try:
            return _summarize_with_transformers(text, max_length, min_length)
        except Exception as e:
            logger.warning("Transformers 摘要失败，降级到 TextRank: %s", e)

    # 策略2: TextRank 关键句提取（离线降级）
    return _summarize_with_textrank(text, max_length)


def _clean_text(text: str) -> str:
    """清洗文本：去除HTML标签、多余空白、特殊符号。"""
    # 去除HTML标签
    text = re.sub(r"<[^>]+>", "", text)
    # 去除多余空白
    text = re.sub(r"\s+", " ", text)
    # 去除特殊符号（保留中文、数字、常用标点、中英文引号）
    text = re.sub(r"""[^一-龥a-zA-Z0-9，。！？、；：“”‘’"'（）《》\s%]""", "", text)
    return text.strip()


def _summarize_with_transformers(
    text: str, max_length: int, min_length: int
) -> str:
    """使用 Transformers 管道进行摘要。"""
    if _SUMMARIZER_PIPELINE is None:
        raise RuntimeError("Transformers pipeline 未初始化")

    # Pegasus 模型的 token 限制（约 512 tokens）
    # 中文按 1.5 字/token 估算，输入最大约 700 字
    if len(text) > 700:
        text = text[:700]

    result = _SUMMARIZER_PIPELINE(
        text,
        max_length=max_length,
        min_length=min_length,
        do_sample=False,
    )

    summary = result[0]["summary_text"]
    return summary.strip()


def _summarize_with_textrank(text: str, max_length: int) -> str:
    """TextRank 关键句提取（离线降级方案）。

    算法：
    1. 分句
    2. 计算句子间相似度（基于词重叠）
    3. PageRank 算法选出最重要的句子
    4. 按原文顺序返回
    """
    sentences = _split_sentences(text)
    if len(sentences) <= 3:
        return text[:max_length]

    # 计算句子重要性（简化版 TextRank）
    scores = _textrank_scores(sentences)

    # 选择 top-K 句子（累计长度不超过 max_length）
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    selected_indices = []
    total_len = 0

    for idx, score in ranked:
        sent_len = len(sentences[idx])
        if total_len + sent_len <= max_length:
            selected_indices.append(idx)
            total_len += sent_len
        if len(selected_indices) >= 5:  # 最多5句
            break

    # 按原文顺序拼接
    selected_indices.sort()
    summary = "".join(sentences[i] for i in selected_indices)

    return summary.strip()


def _split_sentences(text: str) -> list[str]:
    """中文分句（按标点符号）。"""
    # 按句号、问号、感叹号分句
    sentences = re.split(r"([。！？；])", text)
    # 重新组合（保留标点）
    result = []
    for i in range(0, len(sentences) - 1, 2):
        sent = sentences[i] + sentences[i + 1] if i + 1 < len(sentences) else sentences[i]
        sent = sent.strip()
        if sent:
            result.append(sent)
    return result


def _textrank_scores(sentences: list[str]) -> list[float]:
    """简化版 TextRank：基于词重叠计算句子重要性。"""
    import math

    n = len(sentences)
    if n == 0:
        return []

    # 句子转词集合
    word_sets = [set(_tokenize_simple(s)) for s in sentences]

    # 构建相似度矩阵
    similarity = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if not word_sets[i] or not word_sets[j]:
                continue
            overlap = len(word_sets[i] & word_sets[j])
            denom = math.log(len(word_sets[i])) + math.log(len(word_sets[j]))
            if denom > 0:
                similarity[i][j] = similarity[j][i] = overlap / denom

    # PageRank 迭代
    scores = [1.0] * n
    damping = 0.85
    for _ in range(10):  # 10轮迭代
        new_scores = [0.0] * n
        for i in range(n):
            for j in range(n):
                if i != j:
                    new_scores[i] += damping * similarity[i][j] * scores[j]
            new_scores[i] += (1 - damping)
        scores = new_scores

    return scores


def _tokenize_simple(text: str) -> list[str]:
    """简单分词（中文按字，英文按空格）。"""
    # 提取中文字符和英文单词
    chinese = re.findall(r"[一-龥]", text)
    english = re.findall(r"[a-zA-Z]+", text.lower())
    return chinese + english


# ============================================================
# 去重模块：基于 Simhash 的近似去重
# ============================================================

def compute_simhash(text: str, hash_bits: int = 64) -> int:
    """计算文本的 Simhash 值（用于近似去重）。

    Simhash 是一种局部敏感哈希（LSH）算法，
    相似文本的 Simhash 值汉明距离小。
    """
    tokens = _tokenize_simple(text)
    if not tokens:
        return 0

    # 初始化哈希向量
    vector = [0] * hash_bits

    for token in tokens:
        # 计算 token 的哈希值
        h = hash(token) & ((1 << hash_bits) - 1)

        # 更新向量
        for i in range(hash_bits):
            if h & (1 << i):
                vector[i] += 1
            else:
                vector[i] -= 1

    # 生成 Simhash
    fingerprint = 0
    for i in range(hash_bits):
        if vector[i] > 0:
            fingerprint |= (1 << i)

    return fingerprint


def hamming_distance(hash1: int, hash2: int) -> int:
    """计算两个哈希值的汉明距离。"""
    xor = hash1 ^ hash2
    distance = 0
    while xor:
        distance += 1
        xor &= xor - 1
    return distance


def is_duplicate(text1: str, text2: str, threshold: int = 3) -> bool:
    """判断两篇文本是否为近似重复（基于 Simhash）。

    Args:
        text1, text2: 待比较的文本
        threshold: 汉明距离阈值（≤3 视为重复）

    Returns:
        True 表示重复
    """
    hash1 = compute_simhash(text1)
    hash2 = compute_simhash(text2)
    distance = hamming_distance(hash1, hash2)
    return distance <= threshold


def deduplicate_texts(texts: list[str], threshold: int = 3) -> list[int]:
    """对文本列表去重，返回保留的索引列表。

    Args:
        texts: 文本列表
        threshold: 汉明距离阈值

    Returns:
        保留的索引列表（去重后）
    """
    if not texts:
        return []

    hashes = [compute_simhash(t) for t in texts]
    kept_indices = [0]  # 保留第一篇

    for i in range(1, len(texts)):
        is_dup = False
        for j in kept_indices:
            if hamming_distance(hashes[i], hashes[j]) <= threshold:
                is_dup = True
                break
        if not is_dup:
            kept_indices.append(i)

    return kept_indices
