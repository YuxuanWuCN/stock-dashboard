"""src/llm/chunker 文本分块测试。"""

from src.llm.chunker import (
    Chunk,
    chunk_financial_document,
    split_sentences,
)


def test_split_sentences_handles_chinese_and_english():
    text = "公司发布业绩预告。净利润增长超预期！营收也创新高?"
    sentences = split_sentences(text)
    assert len(sentences) == 3
    assert all(s.strip() for s in sentences)


def test_split_sentences_empty_text():
    assert split_sentences("") == []
    assert split_sentences("   ") == []
    assert split_sentences(None) == []


def test_split_sentences_no_punctuation_keeps_single_sentence():
    assert split_sentences("净利润增长超预期") == ["净利润增长超预期"]


def test_chunk_financial_document_splits_long_text():
    # 构造超过 max_chars 的长文本
    long_text = "公司发布季度业绩报告。" * 30
    chunks = chunk_financial_document(long_text, metadata={"code": "600519"})
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= 512
        assert c.metadata["code"] == "600519"


def test_chunk_financial_document_short_text_single_chunk():
    text = "公司发布业绩预告，净利润增长超预期。"
    chunks = chunk_financial_document(text)
    assert len(chunks) == 1
    assert chunks[0].text == text


def test_chunk_financial_document_empty_returns_empty():
    assert chunk_financial_document("") == []
    assert chunk_financial_document("   ") == []


def test_chunk_overlap_preserves_context():
    # 很多短句会触发 overlap，确保 chunk_index 递增且内容非空
    sentences = "业绩增长。" * 30
    chunks = chunk_financial_document(sentences, metadata={"title": "test"})
    assert len(chunks) >= 1
    indexes = [c.chunk_index for c in chunks]
    assert indexes == list(range(len(chunks)))


def test_chunk_to_dict_shape():
    c = Chunk(text="abc", metadata={"code": "1"}, chunk_index=0)
    d = c.to_dict()
    assert d["text"] == "abc"
    assert d["chunk_index"] == 0
    assert d["metadata"]["code"] == "1"
