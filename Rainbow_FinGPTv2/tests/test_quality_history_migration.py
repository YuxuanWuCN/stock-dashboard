"""Focused tests for the one-time quality-history migration adapter."""

from tools.migrate_quality_history import convert_issue


def test_convert_issue_preserves_identity_and_report_reference():
    record = convert_issue(
        {
            "id": "BUG-0001",
            "status": "open",
            "created_at": "2026-08-07T11:13:36+08:00",
            "stage": "heavy",
            "title": "Quality gate failed",
            "failed_checks": ["pytest"],
            "report": ".quality-state/reports/old.json",
        }
    )

    assert record["id"] == "BUG-0001"
    assert record["status"] == "open"
    assert "pytest" in record["details"]
    assert ".quality-state/reports/old.json" in record["details"]
    assert record["receipt_binding"] is False
