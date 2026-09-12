"""Immutable, provenance-labeled NALE Week1 artifact bundle writer.

This writer cannot certify an upstream data source or a profitable strategy.
It refuses synthetic sources and keeps engineering fixtures out of official
processed/tables/figures directories.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Mapping

import numpy as np
import pandas as pd

from src.analysis.nale_alpha_figures import FIGURE_DPI, render_rank_ic_figure
from src.analysis.nale_alpha_pipeline import ALL_VERSIONS, CORE_VERSIONS, DataEvidence


PAIRS = ("V1-B0", "V2-V1", "V3-V2", "V4-V3", "V5-V4")
PC_COLUMNS = tuple(f"PC{k:02d}" for k in range(1, 11))
CONTRIBUTION_COLUMNS = tuple(f"contribution_PC{k:02d}" for k in range(1, 11))
WEIGHT_COLUMNS = tuple(f"w_PC{k:02d}" for k in range(1, 11))
MARKET_INTERACTION_COLUMNS = tuple(f"v_PC{k:02d}" for k in range(1, 11))
RELIABILITY_INTERACTION_COLUMNS = tuple(f"r_PC{k:02d}" for k in range(1, 11))
PREDICTION_COLUMNS = (
    "date", "code", "version", "phase", "S0", "N", "D", *PC_COLUMNS,
    *CONTRIBUTION_COLUMNS, "u", "alpha_nale", "S",
    "predicted_excess_return", "train_cutoff", "fallback_reason",
)


@dataclass(frozen=True)
class ArtifactTables:
    predictions: pd.DataFrame
    monthly_weights: pd.DataFrame
    version_comparison: pd.DataFrame
    paired_differences: pd.DataFrame


@dataclass(frozen=True)
class ArtifactDocuments:
    data_audit: str
    requirements_traceability_csv: str
    literature_difference: str
    validation_report: str


@dataclass(frozen=True)
class BundleWriteResult:
    run_id: str
    fixture: bool
    manifest: Mapping[str, object]
    paths: Mapping[str, Path]


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_config_seed(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("experiment config must be UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("experiment config must be a JSON object")
    seed = payload.get("seed", payload.get("random_seed"))
    if type(seed) is not int or seed < 0:
        raise ValueError("experiment config requires a nonnegative integer seed")
    return seed


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str) + "\n").encode("utf-8")


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")


def _validate_tables(tables: ArtifactTables) -> None:
    prediction = tables.predictions
    missing = set(PREDICTION_COLUMNS) - set(prediction.columns)
    if missing:
        raise ValueError(f"missing prediction columns: {sorted(missing)}")
    if prediction.empty:
        raise ValueError("prediction snapshot is empty")
    if not prediction["code"].map(lambda value: isinstance(value, str) and re.fullmatch(r"[0-9]{6}", value) is not None).all():
        raise ValueError("codes must be six-character strings")
    if prediction.duplicated(["date", "code", "version"]).any():
        raise ValueError("duplicate date/code/version prediction key")
    if not set(prediction["version"]).issubset(ALL_VERSIONS):
        raise ValueError("prediction contains unknown version")
    if tables.monthly_weights.empty or not {"version", "fit_date", "fit_cutoff", "status"}.issubset(tables.monthly_weights.columns):
        raise ValueError("monthly weights need version/date/cutoff/status rows")

    comparison = tables.version_comparison
    if not {"version", "phase", "status", "rank_ic_mean"}.issubset(comparison.columns):
        raise ValueError("version comparison needs version/phase/status/rank_ic_mean")
    if comparison["version"].duplicated().any() or set(comparison["version"]) != set(ALL_VERSIONS):
        raise ValueError("version comparison must explicitly cover B0/B1/V1-V5 once")
    if not comparison["status"].isin(["available", "not_evaluable"]).all():
        raise ValueError("invalid version status")
    if comparison.loc[comparison["status"] == "not_evaluable", "rank_ic_mean"].notna().any():
        raise ValueError("unavailable version cannot have a Rank IC")
    available = set(comparison.loc[comparison["status"] == "available", "version"])
    if not set(CORE_VERSIONS).issubset(available) or not available.issubset(set(prediction["version"])):
        raise ValueError("available versions must have actual prediction rows, including core versions")

    weights = tables.monthly_weights
    if weights.duplicated(["version", "fit_date"]).any():
        raise ValueError("duplicate monthly weight version/fit_date")
    fit_dates = pd.to_datetime(weights["fit_date"], errors="raise")
    fit_cutoffs = pd.to_datetime(weights["fit_cutoff"], errors="raise")
    if not (fit_cutoffs < fit_dates).all():
        raise ValueError("monthly fit cutoff must precede fit date")
    for version in sorted(available - {"B0", "B1"}):
        rows = weights.loc[weights["version"] == version]
        if rows.empty:
            raise ValueError(f"missing monthly coefficients for {version}")
        required = {"b", *WEIGHT_COLUMNS}
        if version in {"V4", "V5"}:
            required.update({"eta", *MARKET_INTERACTION_COLUMNS})
        if version == "V5":
            required.update({"xi", *RELIABILITY_INTERACTION_COLUMNS})
        missing_weights = required - set(rows.columns)
        if missing_weights:
            raise ValueError(f"missing {version} coefficient columns: {sorted(missing_weights)}")
        fitted = rows.loc[rows["status"] == "fitted", sorted(required)]
        if fitted.empty or not np.isfinite(
            fitted.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        ).all():
            raise ValueError(f"{version} needs finite fitted coefficients")

    paired = tables.paired_differences
    if not {"comparison", "phase", "status"}.issubset(paired.columns):
        raise ValueError("paired differences need comparison/phase/status")
    if paired["comparison"].duplicated().any() or set(paired["comparison"]) != set(PAIRS):
        raise ValueError("paired differences must explicitly cover all planned comparisons")
    if not paired["status"].isin(["available", "not_evaluable"]).all():
        raise ValueError("invalid paired-difference status")


def _validate_split_manifest(split_manifest: Mapping[str, object]) -> None:
    groups = {}
    for key, minimum in (("train_dates", 126), ("validation_dates", 42), ("test_dates", 42)):
        values = split_manifest.get(key)
        if not isinstance(values, list) or len(values) < minimum:
            raise ValueError(f"{key} needs at least {minimum} signal dates")
        if any(not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in values):
            raise ValueError(f"{key} must contain ISO date strings")
        pd.to_datetime(values, format="%Y-%m-%d", errors="raise")
        if values != sorted(set(values)):
            raise ValueError(f"{key} must be strictly ordered and unique")
        groups[key] = values
    if not (groups["train_dates"][-1] < groups["validation_dates"][0]
            and groups["validation_dates"][-1] < groups["test_dates"][0]):
        raise ValueError("train/validation/test signal dates must be ordered and disjoint")
    horizon = split_manifest.get("horizon_trading_days")
    buffer = split_manifest.get("label_maturity_buffer_trading_days")
    if type(horizon) is not int or horizon not in (5, 20) or type(buffer) is not int or buffer < horizon + 1:
        raise ValueError("invalid horizon or label maturity buffer")
    required_cutoffs = (
        "train_label_available_at_max", "validation_first_prediction_cutoff",
        "validation_label_available_at_max", "test_first_prediction_cutoff",
    )
    if any(not isinstance(split_manifest.get(key), str) for key in required_cutoffs):
        raise ValueError("split manifest lacks label/prediction cutoffs")
    cutoffs = [pd.Timestamp(split_manifest[key]) for key in required_cutoffs]
    if any(pd.isna(value) for value in cutoffs) or not (cutoffs[0] < cutoffs[1] and cutoffs[2] < cutoffs[3]):
        raise ValueError("partition labels must mature before next prediction cutoff")
    if (cutoffs[0].date().isoformat() <= groups["train_dates"][-1]
            or cutoffs[2].date().isoformat() <= groups["validation_dates"][-1]):
        raise ValueError("partition label maturity must follow its last signal date")
    if (cutoffs[1].date().isoformat() != groups["validation_dates"][0]
            or cutoffs[3].date().isoformat() != groups["test_dates"][0]):
        raise ValueError("prediction cutoffs must match the first listed signal dates")


def _validate_phase_provenance(tables: ArtifactTables, split_manifest: Mapping[str, object]) -> str:
    comparison = tables.version_comparison
    phases = comparison["phase"].drop_duplicates().tolist()
    if len(phases) != 1 or phases[0] not in ("validation", "test"):
        raise ValueError("version comparison requires one validation or test phase")
    metric_phase = phases[0]
    if not tables.paired_differences["phase"].eq(metric_phase).all():
        raise ValueError("paired differences phase must match version comparison")
    predictions = tables.predictions
    if not predictions["phase"].isin(("validation", "test")).all():
        raise ValueError("prediction phase must be validation or test")
    for phase, rows in predictions.groupby("phase"):
        dates = pd.to_datetime(rows["date"], errors="raise")
        listed_dates = set(split_manifest[f"{phase}_dates"])
        if dates.isna().any() or not set(dates.dt.strftime("%Y-%m-%d")).issubset(listed_dates):
            raise ValueError(f"prediction dates must belong to the {phase} split")
    available = set(comparison.loc[comparison["status"] == "available", "version"])
    predicted = set(predictions.loc[predictions["phase"] == metric_phase, "version"])
    if not available.issubset(predicted):
        raise ValueError("available metric versions need predictions in their phase")
    return metric_phase


def write_artifact_bundle(
    *,
    project_root: Path,
    run_id: str,
    evidence: DataEvidence,
    config_path: Path,
    source_paths: Mapping[str, Path],
    source_snapshot_id: str,
    split_manifest: Mapping[str, object],
    tables: ArtifactTables,
    documents: ArtifactDocuments,
    allow_fixture: bool = False,
) -> BundleWriteResult:
    """Preflight all inputs, then create isolated no-overwrite artifact files."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
        raise ValueError("unsafe run ID")
    if evidence.kind == "synthetic" or not evidence.audit_id.strip():
        raise ValueError("synthetic or unaudited source is forbidden")
    fixture = evidence.kind == "fixture"
    if fixture and not allow_fixture:
        raise ValueError("fixture output requires explicit engineering mode")
    if not fixture and (evidence.kind != "observed" or not evidence.independently_verified or not evidence.source_ids):
        raise ValueError("official output requires independently verified observed sources")
    if not source_snapshot_id.strip() or not source_paths:
        raise ValueError("source snapshot and input file paths are required")
    for field in (documents.data_audit, documents.requirements_traceability_csv,
                  documents.literature_difference, documents.validation_report):
        if not field.strip():
            raise ValueError("all required narrative artifacts must be nonempty")
    _validate_tables(tables)
    _validate_split_manifest(split_manifest)
    metrics_phase = _validate_phase_provenance(tables, split_manifest)

    root = Path(project_root).resolve()
    config = Path(config_path).resolve(strict=True)
    seed = _load_config_seed(config)
    inputs = {name: Path(path).resolve(strict=True) for name, path in source_paths.items()}
    if not all(name and re.fullmatch(r"[A-Za-z0-9_.-]+", name) for name in inputs):
        raise ValueError("unsafe source key")
    config_hash = _hash_file(config)
    input_hashes = {name: _hash_file(path) for name, path in sorted(inputs.items())}

    if fixture:
        base = root / "research-outputs" / "nale_alpha_week1" / "fixtures" / run_id
        processed, tables_dir, figures = base / "processed", base / "tables", base / "figures"
    else:
        processed = root / "data" / "processed" / "nale_alpha_week1" / run_id
        tables_dir = root / "reports" / "tables" / "nale_alpha_week1" / run_id
        figures = root / "reports" / "figures" / "nale_alpha_week1" / run_id
    directories = (processed, tables_dir, figures)
    if any(path.exists() for path in directories):
        raise FileExistsError("run ID already has an output directory; immutable snapshots are not overwritten")

    parquet = BytesIO()
    tables.predictions.to_parquet(parquet, index=False, engine="pyarrow")
    payloads: dict[Path, bytes] = {
        processed / "predictions.parquet": parquet.getvalue(),
        processed / "split_manifest.json": _json_bytes(split_manifest),
        tables_dir / "monthly_weights.csv": _csv_bytes(tables.monthly_weights),
        tables_dir / "version_comparison.csv": _csv_bytes(tables.version_comparison),
        tables_dir / "paired_differences.csv": _csv_bytes(tables.paired_differences),
        tables_dir / "data_audit.md": documents.data_audit.encode("utf-8"),
        tables_dir / "requirements_traceability.csv": documents.requirements_traceability_csv.encode("utf-8"),
        tables_dir / "literature_difference.md": documents.literature_difference.encode("utf-8"),
        tables_dir / "validation_report.md": documents.validation_report.encode("utf-8"),
        figures / "rank_ic_by_version.png": render_rank_ic_figure(tables.version_comparison, fixture=fixture),
    }
    hashes = {str(path.relative_to(root)).replace("\\", "/"): sha256(content).hexdigest()
              for path, content in payloads.items()}
    manifest: dict[str, object] = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshot_id": source_snapshot_id,
        "source_audit_id": evidence.audit_id,
        "source_kind": evidence.kind,
        "source_ids": list(evidence.source_ids),
        "independently_verified": evidence.independently_verified,
        "config_sha256": config_hash,
        "seed": seed,
        "prediction_versions": sorted(set(tables.predictions["version"])),
        "prediction_phases": sorted(set(tables.predictions["phase"])),
        "metrics_phase": metrics_phase,
        "declared_horizon_trading_days": split_manifest["horizon_trading_days"],
        "input_sha256": input_hashes,
        "artifact_sha256": hashes,
        "figure_dpi": FIGURE_DPI,
        "figure_outputs": ["rank_ic_by_version.png"],
        "empirical_status": "engineering_fixture_no_market_claim" if fixture else "observed_candidate_pending_review",
        "release_status": "NOT_READY",
        "unmet_requirements": ["full_completion_audit_pending"],
    }
    payloads[processed / "run_manifest.json"] = _json_bytes(manifest)

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=False)
    for path, content in payloads.items():
        with path.open("xb") as handle:
            handle.write(content)
    return BundleWriteResult(run_id, fixture, manifest,
                             {path.name: path for path in payloads})
