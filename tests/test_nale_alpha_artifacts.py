"""Artifact contract engineering fixtures; never market evidence."""

from hashlib import sha256

import pandas as pd
import pytest

from src.analysis.nale_alpha_artifacts import (
    ALL_VERSIONS, ArtifactDocuments, ArtifactTables, PAIRS,
    PREDICTION_COLUMNS, write_artifact_bundle,
)
from src.analysis.nale_alpha_pipeline import DataEvidence


def _tables():
    rows = []
    for version in ("B0", "V1", "V2", "V3"):
        row = {column: 0.0 for column in PREDICTION_COLUMNS}
        row.update(date="2025-09-10", code="000001", version=version,
                   phase="test", train_cutoff="2025-09-09", fallback_reason="")
        rows.append(row)
    comparison = pd.DataFrame([
        {"version": version, "phase": "test",
         "status": "available" if version in {"B0", "V1", "V2", "V3"} else "not_evaluable",
         "rank_ic_mean": 0.1 if version in {"B0", "V1", "V2", "V3"} else None}
        for version in ALL_VERSIONS
    ])
    paired = pd.DataFrame([{"comparison": pair, "phase": "test", "status": "not_evaluable"} for pair in PAIRS])
    weights = pd.DataFrame([
        {"version": version, "fit_date": "2025-09-10", "fit_cutoff": "2025-09-09",
         "status": "fitted", "b": 0.0,
         **{f"w_PC{k:02d}": 0.0 for k in range(1, 11)}}
        for version in ("V1", "V2", "V3")
    ])
    return ArtifactTables(pd.DataFrame(rows), weights, comparison, paired)


def _split_manifest():
    days = pd.bdate_range("2025-01-01", periods=222)
    train = days[:126]
    validation = days[132:174]
    test = days[180:222]
    return {
        "train_dates": [day.date().isoformat() for day in train],
        "validation_dates": [day.date().isoformat() for day in validation],
        "test_dates": [day.date().isoformat() for day in test],
        "horizon_trading_days": 5,
        "label_maturity_buffer_trading_days": 6,
        "train_label_available_at_max": "2025-07-01T16:00:00",
        "validation_first_prediction_cutoff": "2025-07-04T09:00:00",
        "validation_label_available_at_max": "2025-09-03T16:00:00",
        "test_first_prediction_cutoff": "2025-09-10T09:00:00",
    }


def test_fixture_bundle_is_isolated_and_has_hash_manifest(tmp_path):
    config = tmp_path / "fixture-config.json"
    source = tmp_path / "fixture-source.csv"
    config.write_text('{"seed":42}', encoding="utf-8")
    source.write_text("fixture-only", encoding="utf-8")
    docs = ArtifactDocuments("audit fixture", "requirement,status\nfixture,not_market", "literature fixture", "validation fixture")
    result = write_artifact_bundle(
        project_root=tmp_path, run_id="fixture-42",
        evidence=DataEvidence("fixture", "fixture-audit-42"),
        config_path=config, source_paths={"fixture-source": source},
        source_snapshot_id="fixture-code", split_manifest=_split_manifest(),
        tables=_tables(), documents=docs, allow_fixture=True,
    )
    assert result.fixture
    assert result.manifest["release_status"] == "NOT_READY"
    assert result.manifest["empirical_status"] == "engineering_fixture_no_market_claim"
    assert result.manifest["input_sha256"]["fixture-source"] == sha256(b"fixture-only").hexdigest()
    assert result.manifest["seed"] == 42
    assert result.manifest["prediction_versions"] == ["B0", "V1", "V2", "V3"]
    assert result.manifest["declared_horizon_trading_days"] == 5
    assert result.manifest["metrics_phase"] == "test"
    assert result.manifest["prediction_phases"] == ["test"]
    assert "research-outputs" in str(result.paths["predictions.parquet"])
    assert len(result.manifest["artifact_sha256"]) == 10
    assert result.manifest["figure_dpi"] >= 200
    assert result.paths["rank_ic_by_version.png"].is_file()


def test_synthetic_data_and_unsafe_ids_fail_before_writing(tmp_path):
    kwargs = dict(project_root=tmp_path, run_id="run-1", config_path=tmp_path / "unused",
                  source_paths={"x": tmp_path / "unused"}, source_snapshot_id="fixture",
                  split_manifest={}, tables=_tables(),
                  documents=ArtifactDocuments("a", "b", "c", "d"))
    with pytest.raises(ValueError, match="synthetic"):
        write_artifact_bundle(evidence=DataEvidence("synthetic", "audit"), **kwargs)
    with pytest.raises(ValueError, match="unsafe run ID"):
        write_artifact_bundle(evidence=DataEvidence("fixture", "audit"),
                              allow_fixture=True, **{**kwargs, "run_id": "../escape"})


def test_duplicate_prediction_key_is_rejected(tmp_path):
    tables = _tables()
    tables.predictions.loc[1, "version"] = "B0"
    with pytest.raises(ValueError, match="duplicate"):
        write_artifact_bundle(project_root=tmp_path, run_id="fixture", evidence=DataEvidence("fixture", "audit"),
                              config_path=tmp_path / "unused", source_paths={"x": tmp_path / "unused"},
                              source_snapshot_id="fixture", split_manifest={}, tables=tables,
                              documents=ArtifactDocuments("a", "b", "c", "d"), allow_fixture=True)


def test_missing_ten_pc_weights_rejected_before_writing(tmp_path):
    tables = _tables()
    tables.monthly_weights.drop(columns=["w_PC10"], inplace=True)
    with pytest.raises(ValueError, match="missing V1 coefficient columns"):
        write_artifact_bundle(project_root=tmp_path, run_id="fixture", evidence=DataEvidence("fixture", "audit"),
                              config_path=tmp_path / "unused", source_paths={"x": tmp_path / "unused"},
                              source_snapshot_id="fixture", split_manifest=_split_manifest(), tables=tables,
                              documents=ArtifactDocuments("a", "b", "c", "d"), allow_fixture=True)


def test_split_overlap_and_unmatured_labels_rejected(tmp_path):
    config = tmp_path / "config"
    config.write_text("fixture", encoding="utf-8")
    kwargs = dict(project_root=tmp_path, run_id="fixture", evidence=DataEvidence("fixture", "audit"),
                  config_path=config, source_paths={"x": config}, source_snapshot_id="fixture",
                  tables=_tables(), documents=ArtifactDocuments("a", "b", "c", "d"), allow_fixture=True)
    overlap = _split_manifest()
    overlap["validation_dates"][0] = overlap["train_dates"][-1]
    with pytest.raises(ValueError, match="ordered and disjoint"):
        write_artifact_bundle(split_manifest=overlap, **kwargs)
    immature = _split_manifest()
    immature["train_label_available_at_max"] = "2025-07-20T16:00:00"
    with pytest.raises(ValueError, match="mature before"):
        write_artifact_bundle(split_manifest=immature, **kwargs)


def test_metric_phase_requires_matching_prediction_rows(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"seed":42}', encoding="utf-8")
    tables = _tables()
    tables.version_comparison["phase"] = "validation"
    tables.paired_differences["phase"] = "validation"
    with pytest.raises(ValueError, match="predictions in their phase"):
        write_artifact_bundle(
            project_root=tmp_path, run_id="fixture", evidence=DataEvidence("fixture", "audit"),
            config_path=config, source_paths={"fixture": config}, source_snapshot_id="fixture",
            split_manifest=_split_manifest(), tables=tables,
            documents=ArtifactDocuments("a", "b", "c", "d"), allow_fixture=True,
        )


def test_prediction_date_must_belong_to_declared_phase(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"seed":42}', encoding="utf-8")
    tables = _tables()
    tables.predictions.loc[0, "date"] = "2025-09-09"
    with pytest.raises(ValueError, match="dates must belong to the test split"):
        write_artifact_bundle(
            project_root=tmp_path, run_id="fixture", evidence=DataEvidence("fixture", "audit"),
            config_path=config, source_paths={"fixture": config}, source_snapshot_id="fixture",
            split_manifest=_split_manifest(), tables=tables,
            documents=ArtifactDocuments("a", "b", "c", "d"), allow_fixture=True,
        )


def test_paired_phase_must_match_version_comparison(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"seed":42}', encoding="utf-8")
    tables = _tables()
    tables.paired_differences["phase"] = "validation"
    with pytest.raises(ValueError, match="paired differences phase must match"):
        write_artifact_bundle(
            project_root=tmp_path, run_id="fixture", evidence=DataEvidence("fixture", "audit"),
            config_path=config, source_paths={"fixture": config}, source_snapshot_id="fixture",
            split_manifest=_split_manifest(), tables=tables,
            documents=ArtifactDocuments("a", "b", "c", "d"), allow_fixture=True,
        )
