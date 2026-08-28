# src/llm/embeddings.py —— 文本向量化
#
# 支持两种后端：
#   "sentence-transformers" —— 多语言 SBERT 模型（需下载，约 118MB）
#   "hash"                 —— 确定性哈希向量（零依赖，离线可复现，用于测试与降级）
#
# 接口统一：Embedder.encode(list[str]) -> np.ndarray (n, dim)

import hashlib
import logging
import re
from typing import Optional

import numpy as np

from .config import (
    EMBEDDING_BACKEND,
    EMBEDDING_MODEL_NAME,
    EMBEDDING_HASH_DIM,
)

logger = logging.getLogger("stock-dashboard.llm.embeddings")


def _char_hash_token(ch: str) -> int:
    """把单字符映射到固定 token（0~65535）。"""
    return int.from_bytes(ch.encode("utf-8", errors="ignore")[:4].ljust(4, b"\x00"), "big") % 65536


def _hash_embedding(text: str, dim: int) -> np.ndarray:
    """
    确定性哈希嵌入：对每个字符取哈希 token，做带权 bag-of-tokens 归一化。
    保证相同文本 -> 相同向量，支持余弦相似度。
    """
    vec = np.zeros(dim, dtype=np.float32)
    norm_text = re.sub(r"\s+", "", text or "")
    if not norm_text:
        return vec
    for ch in norm_text:
        token = _char_hash_token(ch)
        idx = token % dim
        sign = 1.0 if (token // dim) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


class HashEmbedder:
    """确定性哈希嵌入器（离线、零依赖）。"""

    def __init__(self, dim: int = EMBEDDING_HASH_DIM):
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.stack([_hash_embedding(t, self.dim) for t in texts])

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


class SbertEmbedder:
    """sentence-transformers 嵌入器（需下载模型）。"""

    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "sentence-transformers 未安装；请 pip install sentence-transformers "
                "或改用 EMBEDDING_BACKEND=hash"
            ) from exc
        logger.info("加载嵌入模型 %s ...", model_name)
        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str]) -> np.ndarray:
        emb = self._model.encode(texts, normalize_embeddings=True)
        return np.asarray(emb, dtype=np.float32)


class Embedder:
    """统一嵌入接口，按 EMBEDDING_BACKEND 选择实现。"""

    def __init__(self, backend: Optional[str] = None):
        backend = backend or EMBEDDING_BACKEND
        if backend == "sentence-transformers":
            self._impl = SbertEmbedder()
        elif backend == "hash":
            self._impl = HashEmbedder()
        elif backend:
            raise ValueError(f"未知嵌入后端: {backend}")
        else:
            self._impl = HashEmbedder()
        self.dim = self._impl.dim

    def encode(self, texts: list[str]) -> np.ndarray:
        return self._impl.encode(texts)

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]
