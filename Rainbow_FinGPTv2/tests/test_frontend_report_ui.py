"""Static contracts for the research-report and observation UI."""

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_project_file(relative_path: str) -> str:
    """Read a UTF-8 frontend or contract source file from the project root."""
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _function_block(source: str, function_name: str, next_function_name: str) -> str:
    """Return the source between two named JavaScript function declarations."""
    start = source.index(f"function {function_name}")
    end = source.index(f"function {next_function_name}", start)
    return source[start:end]


def test_observation_panel_precedes_analysis_title_without_trade_commands() -> None:
    """Keep the study-only observation panel ahead of the detail title."""
    html = _read_project_file("docs/index.html")
    app_source = _read_project_file("docs/assets/app.js")

    assert html.index('id="analysis-observation"') < html.index('id="analysis-title"')
    assert 'id="analysis-observation-status"' in html
    assert 'id="analysis-observation-reason"' in html
    assert "仅供学习和研究，不构成投资建议" in html

    observation_source = html + app_source
    for prohibited_instruction in ("买入", "卖出", "BUY", "SELL"):
        assert prohibited_instruction not in observation_source


def test_research_report_version_and_structure_are_checked_before_rendering() -> None:
    """Reject incompatible or incomplete report payloads before UI rendering."""
    app_source = _read_project_file("docs/assets/app.js")
    validator = _function_block(
        app_source,
        "isCompatibleResearchReport",
        "isSafeCitationUrl",
    )

    assert "String(report.schema_version || '').split('.')[0] !== '2'" in validator
    assert "typeof report.code !== 'string'" in validator
    assert "typeof report.name !== 'string'" in validator
    assert "typeof researchReport.summary !== 'string'" in validator
    assert "typeof researchReport.elder_friendly !== 'string'" in validator
    assert "Array.isArray(researchReport.sections)" in validator
    assert "研究报告数据版本不兼容或结构不完整。" in app_source


def test_report_citation_links_allow_only_safe_protocols() -> None:
    """Only http(s) citations may be exposed as external links."""
    app_source = _read_project_file("docs/assets/app.js")
    url_validator = _function_block(
        app_source,
        "isSafeCitationUrl",
        "hideResearchReport",
    )

    assert "new URL(value)" in url_validator
    assert "url.protocol === 'https:' || url.protocol === 'http:'" in url_validator
    assert "link.target = '_blank'" in app_source
    assert "link.rel = 'noopener noreferrer'" in app_source
    assert "appendCitationDetail(citList," in app_source


def test_citation_audit_is_visible_when_total_is_positive() -> None:
    """Show uncertainty-only audit records instead of gating on evidence count."""
    app_source = _read_project_file("docs/assets/app.js")
    renderer = _function_block(app_source, "renderResearchReport", "confLabel")

    assert re.search(r"if\s*\(\s*audit\.total\s*>\s*0\s*\)", renderer)
    assert "report.citation_audit && report.citation_audit.evidence" not in renderer


def test_shared_contract_documents_report_path_and_schema_v21() -> None:
    """Keep the frontend's report endpoint and the shared JSON schema aligned."""
    contract = _read_project_file("项目规划/04-前后端共享数据合同.md")

    assert "合同版本：`2.1`" in contract
    assert "docs/data/llm/reports/{code}_{trade_date}.json" in contract
    assert '"schema_version": "2.1"' in contract
    assert '"research_report": {' in contract
    assert '"sections": [' in contract
    assert '"citation_audit": {' in contract
