"""tests/test_evaluate_nale_alpha_cli.py - End-to-end tests for evaluate_nale_alpha CLI."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_SCRIPT = REPO_ROOT / "scripts" / "evaluate_nale_alpha.py"
DEFAULT_CONFIG = REPO_ROOT / "config" / "experiments" / "nale_alpha_week1.json"


def test_cli_blocks_unverified_data_default():
    """Default run must fail-closed with code 2 and audit block report."""
    res = subprocess.run(
        [
            sys.executable,
            str(CLI_SCRIPT),
            "--config",
            str(DEFAULT_CONFIG),
            "--run-id",
            "cli_test_blocked_001",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 2
    report = json.loads(res.stdout)
    assert report["status"] == "BLOCKED"
    assert report["historical_authenticity"] == "UNVERIFIED"
    assert "provenance audit" in report["reason"]


def test_cli_audit_only_flag():
    """--audit-only exits 2 when unverified, and exits 0 when --allow-fixture is set."""
    res_blocked = subprocess.run(
        [
            sys.executable,
            str(CLI_SCRIPT),
            "--config",
            str(DEFAULT_CONFIG),
            "--run-id",
            "cli_audit_test_001",
            "--audit-only",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res_blocked.returncode == 2

    res_pass = subprocess.run(
        [
            sys.executable,
            str(CLI_SCRIPT),
            "--config",
            str(DEFAULT_CONFIG),
            "--run-id",
            "cli_audit_test_002",
            "--allow-fixture",
            "--audit-only",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res_pass.returncode == 0
    report = json.loads(res_pass.stdout)
    assert report["status"] == "AUDIT_ONLY_PASS"
    assert report["fixture"] is True


def test_cli_invalid_run_id():
    """CLI rejects invalid run_id containing prohibited characters."""
    res = subprocess.run(
        [
            sys.executable,
            str(CLI_SCRIPT),
            "--config",
            str(DEFAULT_CONFIG),
            "--run-id",
            "invalid/run/id!",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 1
    assert "Invalid run_id" in res.stderr


def test_cli_rejects_existing_run_id(tmp_path):
    """Refuse to overwrite an existing run directory."""
    run_id = "existing_run_001"
    existing_dir = REPO_ROOT / "research-outputs" / "nale_alpha_week1" / "fixtures" / run_id / "processed"
    existing_dir.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            [
                sys.executable,
                str(CLI_SCRIPT),
                "--config",
                str(DEFAULT_CONFIG),
                "--run-id",
                run_id,
                "--allow-fixture",
                "--smoke",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert res.returncode == 1
        assert "already exists" in res.stderr
    finally:
        shutil.rmtree(REPO_ROOT / "research-outputs" / "nale_alpha_week1" / "fixtures" / run_id, ignore_errors=True)


def test_cli_smoke_fixture_emits_full_artifacts():
    """--allow-fixture --smoke completes end-to-end and writes all 11 artifacts."""
    run_id = "test_smoke_cli_e2e_999"
    fixture_dir = REPO_ROOT / "research-outputs" / "nale_alpha_week1" / "fixtures" / run_id
    if fixture_dir.exists():
        shutil.rmtree(fixture_dir, ignore_errors=True)

    try:
        res = subprocess.run(
            [
                sys.executable,
                str(CLI_SCRIPT),
                "--config",
                str(DEFAULT_CONFIG),
                "--run-id",
                run_id,
                "--allow-fixture",
                "--smoke",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert res.returncode == 0, f"CLI execution failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"

        summary = json.loads(res.stdout)
        assert summary["status"] == "SUCCESS"
        assert summary["fixture"] is True
        assert summary["artifacts_generated"] >= 10

        # Check required files
        expected_files = [
            fixture_dir / "processed" / "predictions.parquet",
            fixture_dir / "processed" / "split_manifest.json",
            fixture_dir / "processed" / "run_manifest.json",
            fixture_dir / "tables" / "monthly_weights.csv",
            fixture_dir / "tables" / "version_comparison.csv",
            fixture_dir / "tables" / "paired_differences.csv",
            fixture_dir / "tables" / "data_audit.md",
            fixture_dir / "tables" / "requirements_traceability.csv",
            fixture_dir / "tables" / "literature_difference.md",
            fixture_dir / "tables" / "validation_report.md",
            fixture_dir / "figures" / "rank_ic_by_version.png",
        ]
        for path in expected_files:
            assert path.exists(), f"Missing artifact: {path}"
            assert path.stat().st_size > 0, f"Empty artifact: {path}"

        # Inspect run_manifest.json
        manifest_text = (fixture_dir / "processed" / "run_manifest.json").read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        assert manifest["source_kind"] == "fixture"
        assert manifest["empirical_status"] == "engineering_fixture_no_market_claim"
        assert manifest["release_status"] == "NOT_READY"

    finally:
        if fixture_dir.exists():
            shutil.rmtree(fixture_dir, ignore_errors=True)
