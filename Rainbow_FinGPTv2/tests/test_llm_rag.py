"""src/llm 嵌入、向量存储、RAG 检索测试。"""

import numpy as np

from src.llm.embeddings import Embedder, HashEmbedder
from src.llm.rag_engine import RAGEngine
from src.llm.vector_store import VectorStore


# ---- Embeddings ----

def test_hash_embedding_deterministic():
    e = HashEmbedder(dim=256)
    v1 = e.encode(["公司净利润增长"])
    v2 = e.encode(["公司净利润增长"])
    np.testing.assert_array_equal(v1, v2)


def test_hash_embedding_dimension():
    e = HashEmbedder(dim=256)
    v = e.encode(["测试文本"])
    assert v.shape == (1, 256)


def test_hash_embedding_different_text_differs():
    e = HashEmbedder(dim=256)
    v1 = e.encode(["净利润增长"])
    v2 = e.encode(["业绩亏损"])
    # 不同文本向量应不同
    assert not np.allclose(v1, v2)


def test_embedder_factory_uses_hash_backend():
    e = Embedder(backend="hash")
    v = e.encode_one("测试")
    assert v.shape == (e.dim,)


def test_embedder_empty_text_returns_zero_vector():
    e = HashEmbedder(dim=256)
    v = e.encode_one("")
    np.testing.assert_array_equal(v, np.zeros(256, dtype=np.float32))


# ---- Vector Store ----

def test_vector_store_add_and_query():
    store = VectorStore(dim=8)
    store.add(np.ones(8), payload={"text": "盈利", "code": "600519"})
    store.add(np.zeros(8) + 0.1, payload={"text": "亏损", "code": "000001"})
    assert len(store) == 2

    hits = store.query(np.ones(8), top_k=2)
    assert len(hits) == 2
    assert hits[0].metadata["text"] == "盈利"
    assert hits[0].score > hits[1].score


def test_vector_store_query_empty_returns_empty():
    store = VectorStore(dim=8)
    assert store.query(np.ones(8)) == []


def test_vector_store_query_with_code_filter():
    store = VectorStore(dim=8)
    store.add(np.ones(8), payload={"text": "a", "code": "600519"})
    store.add(np.ones(8) * 2, payload={"text": "b", "code": "000001"})
    hits = store.query(np.ones(8), top_k=5, code_filter="600519")
    assert len(hits) == 1
    assert hits[0].metadata["code"] == "600519"


def test_vector_store_add_batch():
    store = VectorStore(dim=4)
    vectors = np.ones((3, 4), dtype=np.float32)
    payloads = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    store.add_batch(vectors, payloads)
    assert len(store) == 3


def test_vector_store_rejects_wrong_dim():
    store = VectorStore(dim=4)
    try:
        store.add(np.ones(8))
        assert False, "应拒绝错误维度"
    except ValueError:
        pass


# ---- RAG Engine ----

def _make_documents():
    return [
        {
            "title": "贵州茅台业绩预告",
            "content": "贵州茅台发布业绩预告，净利润大幅增长，超出市场预期。",
            "source": "东方财富",
            "publish_time": "2026-08-05",
            "url": "http://x.com/1",
            "code": "600519",
            "name": "贵州茅台",
        },
        {
            "title": "平安银行不良贷款",
            "content": "平安银行公布不良贷款率上升，存在资产质量压力。",
            "source": "新浪财经",
            "publish_time": "2026-08-04",
            "url": "http://x.com/2",
            "code": "000001",
            "name": "平安银行",
        },
    ]


def test_rag_index_and_query():
    engine = RAGEngine(enabled=True, embedder=Embedder(backend="hash"))
    n = engine.index_documents(_make_documents())
    assert n > 0
    assert engine.indexed_count == n

    hits = engine.query("净利润增长", top_k=3)
    assert len(hits) >= 1
    assert all(h.text for h in hits)


def test_rag_query_filters_by_code():
    engine = RAGEngine(enabled=True, embedder=Embedder(backend="hash"))
    engine.index_documents(_make_documents())
    hits = engine.query("业绩 增长 盈利", top_k=5, code_filter="600519")
    assert hits
    assert all(h.metadata["code"] == "600519" for h in hits)


def test_rag_query_for_report_combines_topics():
    engine = RAGEngine(enabled=True, embedder=Embedder(backend="hash"))
    engine.index_documents(_make_documents())
    hits = engine.query_for_report("600519", ["业绩 增长", "风险 减值"], top_k=5)
    assert hits
    assert all(h.metadata["code"] == "600519" for h in hits)


def test_rag_normalizes_fingpt_metadata_aliases():
    engine = RAGEngine(enabled=True, embedder=Embedder(backend="hash"))
    engine.index_documents([
        {
            "text": "公司公告净利润增长，经营现金流改善。",
            "ticker": "SH600519",
            "date": "2026-08-05",
            "metadata": {
                "publisher": "FinGPT fixture",
                "link": "http://x.com/fingpt",
                "document_id": "doc-1",
                "title": "业绩公告",
            },
        }
    ])

    hits = engine.query("净利润 现金流", top_k=3, code_filter="600519")
    assert hits
    assert hits[0].metadata["code"] == "600519"
    assert hits[0].metadata["publish_time"] == "2026-08-05"
    assert hits[0].metadata["source"] == "FinGPT fixture"
    assert hits[0].metadata["document_id"] == "doc-1"


def test_rag_report_query_deduplicates_same_chunk_stably():
    engine = RAGEngine(enabled=True, embedder=Embedder(backend="hash"))
    engine.index_documents([_make_documents()[0]])

    hits = engine.query_for_report(
        "600519",
        ["业绩 增长", "净利润 增长", "盈利"],
        top_k=5,
    )
    assert len(hits) == 1


def test_rag_disabled_indexes_nothing():
    engine = RAGEngine(enabled=False, embedder=Embedder(backend="hash"))
    n = engine.index_documents(_make_documents())
    assert n == 0
    assert engine.query("业绩") == []


def test_rag_empty_index_returns_empty():
    engine = RAGEngine(enabled=True, embedder=Embedder(backend="hash"))
    assert engine.query("业绩") == []
