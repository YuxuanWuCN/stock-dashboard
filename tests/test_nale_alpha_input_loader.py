import hashlib
import json

from src.data.nale_alpha_input_loader import load_input_frames
from src.data.nale_alpha_input_manifest import SOURCE_NAMES


def _fixture(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    sources = {}
    for name in SOURCE_NAMES:
        path = root / f"{name}.csv"
        payload = b"date,code,value\n2024-01-02,000001,0.5\n"
        path.write_bytes(payload)
        sources[name] = {
            "path": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "source_name": "fixture only",
            "source_uri": "fixture://local",
            "acquired_at": "2024-01-02T18:00:00+08:00",
            "available_at_column": "available_at",
            "coverage_start": "2024-01-02",
            "coverage_end": "2024-01-02",
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
    return manifest, root


def test_loader_preserves_leading_zero_codes_but_not_provenance(tmp_path):
    manifest, root = _fixture(tmp_path)
    result = load_input_frames(manifest, root)
    assert result.status == "LOADED_PROVENANCE_UNVERIFIED"
    assert result.frames.features.loc[0, "code"] == "000001"
    assert result.usable_as_real_backtest_evidence is False


def test_hash_mismatch_prevents_loading(tmp_path):
    manifest, root = _fixture(tmp_path)
    (root / "prices.csv").write_text("changed")
    result = load_input_frames(manifest, root)
    assert result.status == "BLOCKED"
    assert result.frames is None
    assert "prices: sha256 mismatch" in result.issues


def test_unsupported_format_is_blocked(tmp_path):
    manifest, root = _fixture(tmp_path)
    source = root / "edges.csv"
    renamed = root / "edges.txt"
    source.rename(renamed)
    declaration = json.loads(manifest.read_text())
    declaration["sources"]["edges"]["path"] = renamed.name
    manifest.write_text(json.dumps(declaration))
    result = load_input_frames(manifest, root)
    assert result.status == "BLOCKED"
    assert result.frames is None
    assert "edges: unsupported file format" in result.issues
