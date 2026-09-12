import json
from types import SimpleNamespace
from unittest.mock import patch

from tools.audit_nale_alpha_inputs import main


ARGS = [
    "--manifest", "manifest.json",
    "--data-root", "data",
    "--minimum-stocks", "30",
    "--minimum-days", "230",
]


def test_failed_load_stops_before_structure(capsys):
    with patch("tools.audit_nale_alpha_inputs.load_input_frames") as load, patch(
        "tools.audit_nale_alpha_inputs.audit_input_gate"
    ) as gate:
        load.return_value = SimpleNamespace(
            status="BLOCKED", frames=None, issues=("features: sha256 mismatch",), verified_sha256={}
        )
        exit_code = main(ARGS)
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert report["status"] == "BLOCKED"
    assert report["historical_authenticity"] == "UNVERIFIED"
    gate.assert_not_called()


def test_structural_pass_still_exits_nonzero(capsys):
    frames = object()
    with patch("tools.audit_nale_alpha_inputs.load_input_frames") as load, patch(
        "tools.audit_nale_alpha_inputs.audit_input_gate"
    ) as gate:
        load.return_value = SimpleNamespace(
            status="LOADED_PROVENANCE_UNVERIFIED", frames=frames, issues=(), verified_sha256={}
        )
        gate.return_value = SimpleNamespace(
            status="PENDING_PROVENANCE_REVIEW",
            manifest_status="INTEGRITY_PASS_PROVENANCE_UNVERIFIED",
            structure_status="STRUCTURAL_PASS_PROVENANCE_UNVERIFIED",
            issues=("Historical source is not authenticated.",),
            verified_sha256={"prices": "a" * 64},
        )
        exit_code = main(ARGS)
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert report["status"] == "PENDING_PROVENANCE_REVIEW"
    assert report["historical_authenticity"] == "UNVERIFIED"
    assert report["verified_sha256"]["prices"] == "a" * 64
    gate.assert_called_once()


def test_structural_failure_exits_blocked(capsys):
    with patch("tools.audit_nale_alpha_inputs.load_input_frames") as load, patch(
        "tools.audit_nale_alpha_inputs.audit_input_gate"
    ) as gate:
        load.return_value = SimpleNamespace(
            status="LOADED_PROVENANCE_UNVERIFIED", frames=object(), issues=(), verified_sha256={}
        )
        gate.return_value = SimpleNamespace(
            status="BLOCKED",
            manifest_status="INTEGRITY_PASS_PROVENANCE_UNVERIFIED",
            structure_status="BLOCKED",
            issues=("features: missing date",),
            verified_sha256={},
        )
        exit_code = main(ARGS)
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert report["structure_status"] == "BLOCKED"
