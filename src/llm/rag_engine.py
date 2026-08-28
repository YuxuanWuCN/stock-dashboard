# src/llm/rag_engine.py —— RAG 检索引擎（主入口）
#
# 流程: 文档 -> chunker -> embeddings -> VectorStore
#        查询 -> 嵌入查询 -> 余弦检索 top-K -> 引用审计
#
# 不直接调用 LLM；只负责"给报告生成器提供带引用的上下文"。

import logging
import re
from typing import Any, Optional

from .chunker import Chunk, chunk_financial_document
from .embeddings import Embedder
from .vector_store import RetrievedChunk, VectorStore
from .config import RAG_ENABLED, RAG_TOP_K, RAG_MIN_SCORE

logger = logging.getLogger("stock-dashboard.llm.rag")


def _first_value(*values: Any) -> str:
    """返回第一个非空元数据值的字符串形式。"""
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_code(value: Any) -> str:
    """把 FinGPT 常见 ticker 写法归一为项目使用的六位代码。"""
    raw = _first_value(value)
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", raw)
    return match.group(1) if match else raw


def _normalize_document(document: dict) -> tuple[str, dict[str, str]]:
    """归一 FinGPT 数据集与项目新闻结构的正文和 metadata。"""
    nested = document.get("metadata")
    metadata = nested if isinstance(nested, dict) else {}
    text = _first_value(
        document.get("content"),
        document.get("text"),
        document.get("body"),
        metadata.get("content"),
        metadata.get("text"),
    )
    title = _first_value(document.get("title"), metadata.get("title"))
    if not text:
        text = title

    normalized = {
        "code": _normalize_code(_first_value(
            document.get("code"),
            document.get("symbol"),
            document.get("ticker"),
            metadata.get("code"),
            metadata.get("symbol"),
            metadata.get("ticker"),
        )),
        "name": _first_value(document.get("name"), metadata.get("name")),
        "title": title,
        "source": _first_value(
            document.get("source"),
            document.get("publisher"),
            metadata.get("source"),
            metadata.get("publisher"),
        ),
        "publish_time": _first_value(
            document.get("publish_time"),
            document.get("published_at"),
            document.get("date"),
            metadata.get("publish_time"),
            metadata.get("published_at"),
            metadata.get("date"),
        ),
        "url": _first_value(
            document.get("url"),
            document.get("link"),
            metadata.get("url"),
            metadata.get("link"),
        ),
        "item_type": _first_value(
            document.get("item_type"),
            document.get("document_type"),
            metadata.get("item_type"),
            metadata.get("document_type"),
            "news",
        ),
        "document_id": _first_value(
            document.get("document_id"),
            document.get("id"),
            metadata.get("document_id"),
            metadata.get("id"),
        ),
    }
    return text, normalized


class RAGEngine:
    """
    检索增强生成引擎。

    用法:
        engine = RAGEngine()
        engine.index_documents([{title, content, source, publish_time, url, code, name}])
        hits = engine.query("存货减值风险", top_k=5)
    """

    def __init__(self, enabled: bool = RAG_ENABLED, embedder: Optional[Embedder] = None):
        self.enabled = enabled
        self._embedder = embedder or Embedder()
        self._store = VectorStore(dim=self._embedder.dim)
        self._indexed_count = 0

    @property
    def indexed_count(self) -> int:
        return self._indexed_count

    def index_documents(self, documents: list[dict]) -> int:
        """
        把一组文档（含 title/content/metadata）索引化。
        返回成功索引的块数。
        """
        if not self.enabled:
            return 0
        chunks: list[Chunk] = []
        for doc in documents:
            text, meta = _normalize_document(doc)
            for chunk in chunk_financial_document(text, metadata=meta):
                chunk.metadata["text"] = chunk.text  # 供引用审计直接取原文
                chunks.append(chunk)
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        try:
            vectors = self._embedder.encode(texts)
        except Exception:
            logger.warning("嵌入失败，跳过 RAG 索引", exc_info=True)
            return 0

        payloads = [c.to_dict()["metadata"] for c in chunks]
        self._store.add_batch(vectors, payloads)
        self._indexed_count += len(chunks)
        logger.info("RAG 索引完成：%d 块", self._indexed_count)
        return len(chunks)

    def query(
        self,
        query_text: str,
        top_k: int = RAG_TOP_K,
        code_filter: Optional[str] = None,
    ) -> list[RetrievedChunk]:
        """语义检索。未启用/无索引时返回 []。"""
        if not self.enabled or not query_text:
            return []
        if len(self._store) == 0:
            return []
        try:
            qvec = self._embedder.encode_one(query_text)
        except Exception:
            logger.warning("查询嵌入失败", exc_info=True)
            return []
        return self._store.query(qvec, top_k=top_k, min_score=RAG_MIN_SCORE, code_filter=code_filter)

    def query_for_report(
        self,
        code: str,
        topics: list[str],
        top_k: int = RAG_TOP_K,
    ) -> list[RetrievedChunk]:
        """为某只标的组合多个主题词检索证据。"""
        seen: dict[tuple[str, str, str, str], RetrievedChunk] = {}
        for topic in topics:
            if not topic:
                continue
            hits = self.query(topic, top_k=top_k, code_filter=code)
            for h in hits:
                metadata = h.metadata or {}
                key = (
                    str(metadata.get("document_id") or ""),
                    str(metadata.get("url") or ""),
                    str(metadata.get("title") or ""),
                    h.text.strip(),
                )
                if key not in seen:
                    seen[key] = h
        # 按分数降序
        return sorted(seen.values(), key=lambda h: h.score, reverse=True)[:top_k]
