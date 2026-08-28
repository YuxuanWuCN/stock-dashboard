# src/llm/vector_store.py —— 内存向量存储与检索
#
# 用 numpy 余弦相似度实现，纯 CPU、无第三方向量库依赖。
# 索引在每次运行时内存构建，不做磁盘持久化（数据量小，性价比最高）。

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .config import RAG_TOP_K, RAG_MIN_SCORE

logger = logging.getLogger("stock-dashboard.llm.vector_store")


@dataclass
class RetrievedChunk:
    """检索命中的文本块 + 相似度分数 + 来源元数据。"""
    text: str
    score: float
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "score": round(float(self.score), 4),
            "metadata": self.metadata,
        }


class VectorStore:
    """简单的内存向量存储：追加向量 + 余弦相似度 top-K 检索。"""

    def __init__(self, dim: int):
        self.dim = dim
        self._vectors: list[np.ndarray] = []
        self._payloads: list[dict] = []

    def __len__(self) -> int:
        return len(self._vectors)

    def add(self, vector: np.ndarray, payload: Optional[dict] = None) -> None:
        v = np.asarray(vector, dtype=np.float32).reshape(-1)
        if v.shape[0] != self.dim:
            raise ValueError(f"向量维度 {v.shape[0]} != 期望 {self.dim}")
        self._vectors.append(v)
        self._payloads.append(dict(payload or {}))

    def add_batch(self, vectors: np.ndarray, payloads: list[dict]) -> None:
        for v, p in zip(vectors, payloads):
            self.add(v, p)

    def query(
        self,
        query_vector: np.ndarray,
        top_k: int = RAG_TOP_K,
        min_score: float = RAG_MIN_SCORE,
        code_filter: Optional[str] = None,
    ) -> list[RetrievedChunk]:
        """按余弦相似度检索 top_k 个块。可指定 code_filter 过滤个股。"""
        if not self._vectors:
            return []
        q = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        q_norm = q / (np.linalg.norm(q) + 1e-9)
        mat = np.stack(self._vectors)
        # mat 已归一化
        scores = mat @ q_norm

        order = np.argsort(-scores)
        results: list[RetrievedChunk] = []
        for idx in order:
            payload = self._payloads[int(idx)]
            if code_filter and payload.get("code") != code_filter:
                continue
            score = float(scores[int(idx)])
            if score < min_score:
                continue
            results.append(RetrievedChunk(
                text=payload.get("text", ""),
                score=score,
                metadata=payload,
            ))
            if len(results) >= top_k:
                break
        return results
