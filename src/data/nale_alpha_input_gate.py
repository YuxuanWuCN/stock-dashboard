"""Fail-closed composition of NALE file integrity and panel structure audits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.data.nale_alpha_input_manifest import verify_input_manifest
from src.data.nale_alpha_source_contract import audit_candidate_sources


@dataclass(frozen=True)
class InputGateResult:
    status: str
    manifest_status: str
    structure_status: str
    issues: tuple[str, ...]
    verified_sha256: dict[str, str]

    @property
    def usable_as_real_backtest_evidence(self) -> bool:
        """Neither of these mechanical checks certifies point-in-time authenticity."""
        return False


def audit_input_gate(
    manifest_path: str | Path,
    data_root: str | Path,
    sources: Any,
    *,
    minimum_stocks: int,
    minimum_days: int,
) -> InputGateResult:
    """Require both checks before human source and availability review."""
    manifest = verify_input_manifest(manifest_path, data_root)
    if manifest.status != "INTEGRITY_PASS_PROVENANCE_UNVERIFIED":
        return InputGateResult(
            "BLOCKED",
            manifest.status,
            "NOT_RUN",
            tuple(f"manifest: {issue}" for issue in manifest.issues),
            manifest.verified_sha256,
        )
    structure = audit_candidate_sources(
        sources,
        minimum_stocks=minimum_stocks,
        minimum_days=minimum_days,
    )
    if structure.status != "STRUCTURAL_PASS_PROVENANCE_UNVERIFIED":
        return InputGateResult(
            "BLOCKED",
            manifest.status,
            structure.status,
            tuple(f"structure: {issue}" for issue in structure.issues),
            manifest.verified_sha256,
        )
    return InputGateResult(
        "PENDING_PROVENANCE_REVIEW",
        manifest.status,
        structure.status,
        ("Historical source, revisions, and point-in-time availability are not authenticated.",),
        manifest.verified_sha256,
    )
