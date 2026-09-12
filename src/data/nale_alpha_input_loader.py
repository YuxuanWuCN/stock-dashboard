"""Load hash-checked NALE inputs without asserting point-in-time provenance."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.data.nale_alpha_input_manifest import SOURCE_NAMES, verify_input_manifest


IDENTIFIER_COLUMNS = frozenset(
    {"code", "stock_code", "src", "dst", "source_code", "target_code", "from_code", "to_code"}
)


@dataclass(frozen=True)
class InputFrames:
    prices: pd.DataFrame
    benchmark: pd.DataFrame
    features: pd.DataFrame
    s0: pd.DataFrame
    edges: pd.DataFrame


@dataclass(frozen=True)
class InputLoadResult:
    status: str
    issues: tuple[str, ...]
    frames: InputFrames | None
    verified_sha256: dict[str, str]

    @property
    def usable_as_real_backtest_evidence(self) -> bool:
        return False


def load_input_frames(manifest_path: str | Path, data_root: str | Path) -> InputLoadResult:
    """Read five immutable-looking inputs, checking hashes before and after parsing."""
    manifest_path = Path(manifest_path)
    try:
        original_manifest = manifest_path.read_bytes()
        declarations = json.loads(original_manifest)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return InputLoadResult("BLOCKED", (f"manifest unreadable: {exc}",), None, {})
    first = verify_input_manifest(manifest_path, data_root)
    if first.status != "INTEGRITY_PASS_PROVENANCE_UNVERIFIED":
        return InputLoadResult("BLOCKED", first.issues, None, first.verified_sha256)
    root = Path(data_root).resolve()
    loaded: dict[str, pd.DataFrame] = {}
    for name in SOURCE_NAMES:
        relative = Path(declarations["sources"][name]["path"])
        candidate = (root / relative).resolve()
        if relative.is_absolute() or not candidate.is_relative_to(root):
            return InputLoadResult("BLOCKED", (f"{name}: path outside data_root",), None, {})
        try:
            if candidate.suffix.lower() == ".csv":
                columns = pd.read_csv(candidate, nrows=0).columns
                string_ids = {column: "string" for column in columns if column in IDENTIFIER_COLUMNS}
                frame = pd.read_csv(candidate, dtype=string_ids, low_memory=False)
            elif candidate.suffix.lower() == ".parquet":
                frame = pd.read_parquet(candidate)
                for column in frame.columns.intersection(IDENTIFIER_COLUMNS):
                    if not frame[column].dropna().map(lambda value: isinstance(value, str)).all():
                        return InputLoadResult(
                            "BLOCKED", (f"{name}: {column} must be stored as a string",), None, {}
                        )
            else:
                return InputLoadResult("BLOCKED", (f"{name}: unsupported file format",), None, {})
        except (OSError, UnicodeError, ValueError, ImportError, pd.errors.ParserError) as exc:
            return InputLoadResult("BLOCKED", (f"{name}: parse failed: {exc}",), None, {})
        loaded[name] = frame
    second = verify_input_manifest(manifest_path, data_root)
    try:
        manifest_unchanged = manifest_path.read_bytes() == original_manifest
    except OSError:
        manifest_unchanged = False
    if second.status != "INTEGRITY_PASS_PROVENANCE_UNVERIFIED" or not manifest_unchanged:
        issues = second.issues if second.issues else ("manifest changed during load",)
        return InputLoadResult("BLOCKED", issues, None, second.verified_sha256)
    return InputLoadResult(
        "LOADED_PROVENANCE_UNVERIFIED",
        ("Historical source and as-of availability still require independent review.",),
        InputFrames(**loaded),
        second.verified_sha256,
    )
