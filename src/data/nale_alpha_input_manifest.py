"""Verify declared NALE input files without asserting historical authenticity."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "nale-alpha-input-v1"
SOURCE_NAMES = ("prices", "benchmark", "features", "s0", "edges")
COMMON_FIELDS = (
    "path",
    "sha256",
    "source_name",
    "source_uri",
    "acquired_at",
    "available_at_column",
    "coverage_start",
    "coverage_end",
)
SOURCE_FIELDS = {
    "prices": ("adjustment", "trade_status_column"),
    "benchmark": ("benchmark_code", "adjustment"),
    "features": ("feature_version", "embedding_model_version", "pretraining_cutoff"),
    "s0": ("score_version",),
    "edges": ("effective_from_column", "effective_to_column", "source_time_column"),
}


@dataclass(frozen=True)
class InputManifestAudit:
    status: str
    issues: tuple[str, ...]
    verified_sha256: dict[str, str]

    @property
    def usable_as_real_backtest_evidence(self) -> bool:
        """A local hash check cannot authenticate source or point-in-time history."""
        return False


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _day(value: Any) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def verify_input_manifest(manifest_path: str | Path, data_root: str | Path) -> InputManifestAudit:
    """Check local paths, required declarations and SHA-256; never certify provenance."""
    issues: list[str] = []
    verified: dict[str, str] = {}
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return InputManifestAudit("BLOCKED", (f"manifest unreadable: {exc}",), verified)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        return InputManifestAudit("BLOCKED", (f"schema_version must be {SCHEMA_VERSION}",), verified)
    sources = manifest.get("sources")
    if not isinstance(sources, dict):
        return InputManifestAudit("BLOCKED", ("sources must be an object",), verified)
    root = Path(data_root).resolve()
    for name in SOURCE_NAMES:
        entry = sources.get(name)
        if not isinstance(entry, dict):
            issues.append(f"{name}: source entry missing")
            continue
        for field in (*COMMON_FIELDS, *SOURCE_FIELDS[name]):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                issues.append(f"{name}: {field} missing")
        if any(issue.startswith(f"{name}: ") for issue in issues):
            continue
        if not _aware_timestamp(entry["acquired_at"]):
            issues.append(f"{name}: acquired_at needs timezone")
        if name == "features" and not _aware_timestamp(entry["pretraining_cutoff"]):
            issues.append("features: pretraining_cutoff needs timezone")
        start, end = _day(entry["coverage_start"]), _day(entry["coverage_end"])
        if start is None or end is None or start > end:
            issues.append(f"{name}: invalid coverage dates")
        expected = entry["sha256"].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            issues.append(f"{name}: invalid sha256")
            continue
        relative = Path(entry["path"])
        if relative.is_absolute():
            issues.append(f"{name}: path must be relative to data_root")
            continue
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            issues.append(f"{name}: path absent or outside data_root")
            continue
        digest = hashlib.sha256()
        try:
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            issues.append(f"{name}: file unreadable: {exc}")
            continue
        actual = digest.hexdigest()
        if actual != expected:
            issues.append(f"{name}: sha256 mismatch")
        else:
            verified[name] = actual
    unknown = sorted(set(sources) - set(SOURCE_NAMES))
    if unknown:
        issues.append(f"unknown sources: {', '.join(unknown)}")
    status = "BLOCKED" if issues else "INTEGRITY_PASS_PROVENANCE_UNVERIFIED"
    return InputManifestAudit(status, tuple(issues), verified)
