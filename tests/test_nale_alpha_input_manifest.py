import hashlib
import json

from src.data.nale_alpha_input_manifest import SOURCE_NAMES, verify_input_manifest


def _fixture(tmp_path):
    root = tmp_path / "inputs"
    root.mkdir()
    sources = {}
    for name in SOURCE_NAMES:
        path = root / f"{name}.csv"
        payload = f"{name}\n".encode()
        path.write_bytes(payload)
        sources[name] = {
            "path": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "source_name": "fixture only",
            "source_uri": "fixture://local",
            "acquired_at": "2024-01-01T00:00:00+08:00",
            "available_at_column": "available_at",
            "coverage_start": "2024-01-01",
            "coverage_end": "2024-12-31",
        }
    sources["prices"].update(adjustment="adjusted", trade_status_column="trade_status")
    sources["benchmark"].update(benchmark_code="000300", adjustment="adjusted")
    sources["features"].update(
        feature_version="fixture-v1",
        embedding_model_version="fixture-v1",
        pretraining_cutoff="2023-12-31T00:00:00+08:00",
    )
    sources["s0"].update(score_version="fixture-v1")
    sources["edges"].update(
        effective_from_column="effective_from",
        effective_to_column="effective_to",
        source_time_column="source_available_at",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": "nale-alpha-input-v1", "sources": sources}))
    return manifest, root, sources


def test_complete_fixture_is_only_integrity_checked(tmp_path):
    manifest, root, _ = _fixture(tmp_path)
    result = verify_input_manifest(manifest, root)
    assert result.status == "INTEGRITY_PASS_PROVENANCE_UNVERIFIED"
    assert len(result.verified_sha256) == 5
    assert result.usable_as_real_backtest_evidence is False


def test_changed_file_fails_closed(tmp_path):
    manifest, root, _ = _fixture(tmp_path)
    (root / "features.csv").write_text("changed")
    result = verify_input_manifest(manifest, root)
    assert result.status == "BLOCKED"
    assert "features: sha256 mismatch" in result.issues


def test_path_traversal_fails_closed(tmp_path):
    manifest, root, sources = _fixture(tmp_path)
    sources["edges"]["path"] = "../manifest.json"
    manifest.write_text(json.dumps({"schema_version": "nale-alpha-input-v1", "sources": sources}))
    result = verify_input_manifest(manifest, root)
    assert result.status == "BLOCKED"
    assert any("outside data_root" in issue for issue in result.issues)


def test_missing_lineage_and_naive_time_fail_closed(tmp_path):
    manifest, root, sources = _fixture(tmp_path)
    del sources["features"]["pretraining_cutoff"]
    sources["prices"]["acquired_at"] = "2024-01-01T00:00:00"
    manifest.write_text(json.dumps({"schema_version": "nale-alpha-input-v1", "sources": sources}))
    result = verify_input_manifest(manifest, root)
    assert result.status == "BLOCKED"
    assert "features: pretraining_cutoff missing" in result.issues
    assert "prices: acquired_at needs timezone" in result.issues
