"""src/llm/citation 引用审计测试。"""

from src.llm.citation import (
    audit_citations,
    build_citation,
    build_inference,
    build_uncertain,
)


def test_build_citation_has_evidence_type():
    c = build_citation(
        "净利润增长",
        {"source": "东方财富", "publish_time": "2026-08-05", "url": "http://x"},
        snippet="净利润增长超预期",
    )
    assert c["type"] == "evidence"
    assert c["source"] == "东方财富 2026-08-05"
    assert c["date"] == "2026-08-05"
    assert c["url"] == "http://x"
    assert c["snippet"] == "净利润增长超预期"


def test_build_citation_without_date():
    c = build_citation("x", {"source": "新浪财经"})
    assert c["source"] == "新浪财经"
    assert c["date"] == ""


def test_build_inference():
    c = build_inference("基于规则引擎数据推断")
    assert c["type"] == "inference"
    assert c["source"] == "规则引擎推断"


def test_build_uncertain():
    c = build_uncertain("数据不足")
    assert c["type"] == "uncertain"
    assert c["source"] == "数据不足"


def test_audit_healthy_with_complete_evidence():
    citations = [
        build_citation("a", {"source": "S", "publish_time": "2026-01-01", "url": "u"}, "snip"),
        build_inference("b"),
        build_uncertain("c"),
    ]
    audit = audit_citations(citations)
    assert audit["total"] == 3
    assert audit["evidence"] == 1
    assert audit["inference"] == 1
    assert audit["uncertain"] == 1
    assert audit["missing_source"] == 0
    assert audit["missing_snippet"] == 0
    assert audit["healthy"] is True


def test_audit_flags_missing_source_and_snippet():
    citations = [
        build_citation("a", {"publish_time": "2026-01-01"}, snippet=""),  # 无 source 无 snippet
    ]
    audit = audit_citations(citations)
    assert audit["missing_source"] == 1
    assert audit["missing_snippet"] == 1
    assert audit["healthy"] is False


def test_audit_empty_list():
    audit = audit_citations([])
    assert audit["total"] == 0
    assert audit["healthy"] is True
