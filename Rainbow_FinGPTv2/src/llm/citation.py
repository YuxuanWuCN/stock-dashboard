# src/llm/citation.py —— 引用审计与来源追踪
#
# 每个 LLM 断言必须能追溯到一个文档块。无法追溯的声明标记为"推断"或"不确定"。
# 职责：从 RAG 检索结果中提取证据、检查来源完整性、构造引用条目。

import logging
from typing import Optional

logger = logging.getLogger("stock-dashboard.llm.citation")


def _source_label(metadata: dict) -> str:
    """构造引用来源标签，例如 '东方财富 2026-08-05'。无 source 时返回空。"""
    source = (metadata.get("source") or "").strip()
    date = metadata.get("publish_time") or metadata.get("date") or ""
    date = str(date)[:10] if date else ""
    if source and date:
        return f"{source} {date}"
    if source:
        return source
    return ""


def build_citation(
    claim: str,
    metadata: dict,
    snippet: Optional[str] = None,
) -> dict:
    """
    构造一条引用。

    Returns:
        {
            "claim": 断言文本,
            "source": 来源标签,
            "date": 发布日期,
            "url": 原文链接,
            "snippet": 原文片段（用于人工复核）,
            "type": "evidence" | "inference" | "uncertain",
        }
    """
    date = str(metadata.get("publish_time") or metadata.get("date") or "")[:10]
    return {
        "claim": claim,
        "source": _source_label(metadata),
        "date": date,
        "url": metadata.get("url", ""),
        "snippet": snippet or metadata.get("text", ""),
        "type": "evidence",
    }


def build_inference(claim: str) -> dict:
    """构造一条推断型引用（无直接来源，仅基于规则引擎数据的逻辑推断）。"""
    return {
        "claim": claim,
        "source": "规则引擎推断",
        "date": "",
        "url": "",
        "snippet": "",
        "type": "inference",
    }


def build_uncertain(claim: str, reason: str = "数据不足") -> dict:
    """构造一条不确定性说明。"""
    return {
        "claim": claim,
        "source": reason,
        "date": "",
        "url": "",
        "snippet": "",
        "type": "uncertain",
    }


def audit_citations(citations: list[dict]) -> dict:
    """
    审计引用列表：统计证据/推断/不确定的比例，检查证据型引用是否完整。

    Returns:
        {
            "total": int,
            "evidence": int,
            "inference": int,
            "uncertain": int,
            "missing_source": int,   # evidence 类型但缺 source
            "missing_snippet": int,  # evidence 类型但缺 snippet
            "healthy": bool,
        }
    """
    total = len(citations)
    evidence = sum(1 for c in citations if c.get("type") == "evidence")
    inference = sum(1 for c in citations if c.get("type") == "inference")
    uncertain = sum(1 for c in citations if c.get("type") == "uncertain")

    missing_source = sum(
        1 for c in citations
        if c.get("type") == "evidence" and not c.get("source")
    )
    missing_snippet = sum(
        1 for c in citations
        if c.get("type") == "evidence" and not c.get("snippet")
    )

    return {
        "total": total,
        "evidence": evidence,
        "inference": inference,
        "uncertain": uncertain,
        "missing_source": missing_source,
        "missing_snippet": missing_snippet,
        "healthy": (missing_source == 0 and missing_snippet == 0),
    }
