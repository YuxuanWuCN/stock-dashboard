# src/llm/chunker.py —— 金融文本分块
#
# 按中文标点分句、按语义段落组块，保留来源元数据用于引用审计。
# 纯标准库实现，无第三方依赖。

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import CHUNK_MAX_CHARS, CHUNK_OVERLAP_SENTENCES, CHUNK_MAX_SENTENCES


@dataclass
class Chunk:
    """一个文本块：内容 + 来源元数据。"""
    text: str
    metadata: dict = field(default_factory=dict)
    chunk_index: int = 0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "chunk_index": self.chunk_index,
            "metadata": self.metadata,
        }


# 中英文分句标点
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*")


def split_sentences(text: str) -> list[str]:
    """按中文/英文句末标点切分句子，返回非空句子列表。"""
    if not text or not text.strip():
        return []
    parts = _SENTENCE_SPLIT_RE.split(text)
    sentences = []
    for p in parts:
        p = p.strip()
        if p:
            sentences.append(p)
    return sentences


def _combine_sentences(
    sentences: list[str],
    max_chars: int = CHUNK_MAX_CHARS,
    max_sentences: int = CHUNK_MAX_SENTENCES,
) -> list[str]:
    """把句子组合成块：不超过 max_chars 与 max_sentences。"""
    chunks = []
    current = []
    current_len = 0
    for s in sentences:
        if current and (
            current_len + len(s) > max_chars
            or len(current) >= max_sentences
        ):
            chunks.append("".join(current))
            # 重叠：保留末尾 CHUNK_OVERLAP_SENTENCES 句
            overlap = current[-CHUNK_OVERLAP_SENTENCES:] if CHUNK_OVERLAP_SENTENCES > 0 else []
            current = list(overlap)
            current_len = sum(len(x) for x in current)
        current.append(s)
        current_len += len(s)
    if current:
        chunks.append("".join(current))
    return chunks


def chunk_financial_document(
    text: str,
    metadata: Optional[dict] = None,
    max_chars: int = CHUNK_MAX_CHARS,
    max_sentences: int = CHUNK_MAX_SENTENCES,
) -> list[Chunk]:
    """
    将一篇金融文本拆成若干 Chunk。

    metadata 建议包含：code, name, source, publish_time, url, title。
    空文本返回 []。
    """
    sentences = split_sentences(text)
    if not sentences:
        return []
    meta = dict(metadata or {})
    chunk_texts = _combine_sentences(sentences, max_chars, max_sentences)
    return [
        Chunk(text=t, metadata=meta, chunk_index=i)
        for i, t in enumerate(chunk_texts)
    ]
