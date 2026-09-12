from types import SimpleNamespace
from unittest.mock import patch

from src.data.nale_alpha_input_gate import audit_input_gate


def _manifest(status, issues=()):
    return SimpleNamespace(status=status, issues=issues, verified_sha256={"prices": "a" * 64})


def _structure(status, issues=()):
    return SimpleNamespace(status=status, issues=issues)


def test_manifest_failure_short_circuits_structure():
    with patch("src.data.nale_alpha_input_gate.verify_input_manifest") as manifest, patch(
        "src.data.nale_alpha_input_gate.audit_candidate_sources"
    ) as structure:
        manifest.return_value = _manifest("BLOCKED", ("prices: sha256 mismatch",))
        result = audit_input_gate("manifest.json", "data", object(), minimum_stocks=30, minimum_days=210)
    assert result.status == "BLOCKED"
    assert result.structure_status == "NOT_RUN"
    assert "manifest: prices: sha256 mismatch" in result.issues
    structure.assert_not_called()


def test_structure_failure_blocks_after_manifest_pass():
    with patch("src.data.nale_alpha_input_gate.verify_input_manifest") as manifest, patch(
        "src.data.nale_alpha_input_gate.audit_candidate_sources"
    ) as structure:
        manifest.return_value = _manifest("INTEGRITY_PASS_PROVENANCE_UNVERIFIED")
        structure.return_value = _structure("BLOCKED", ("features: missing date",))
        result = audit_input_gate("manifest.json", "data", object(), minimum_stocks=30, minimum_days=210)
    assert result.status == "BLOCKED"
    assert result.structure_status == "BLOCKED"
    assert "structure: features: missing date" in result.issues
    structure.assert_called_once()


def test_both_pass_still_requires_provenance_review():
    with patch("src.data.nale_alpha_input_gate.verify_input_manifest") as manifest, patch(
        "src.data.nale_alpha_input_gate.audit_candidate_sources"
    ) as structure:
        manifest.return_value = _manifest("INTEGRITY_PASS_PROVENANCE_UNVERIFIED")
        structure.return_value = _structure("STRUCTURAL_PASS_PROVENANCE_UNVERIFIED")
        result = audit_input_gate("manifest.json", "data", object(), minimum_stocks=30, minimum_days=210)
    assert result.status == "PENDING_PROVENANCE_REVIEW"
    assert result.usable_as_real_backtest_evidence is False
    assert result.verified_sha256["prices"] == "a" * 64


def test_unrecognized_status_fails_closed():
    with patch("src.data.nale_alpha_input_gate.verify_input_manifest") as manifest, patch(
        "src.data.nale_alpha_input_gate.audit_candidate_sources"
    ) as structure:
        manifest.return_value = _manifest("UNKNOWN")
        result = audit_input_gate("manifest.json", "data", object(), minimum_stocks=30, minimum_days=210)
    assert result.status == "BLOCKED"
    structure.assert_not_called()
