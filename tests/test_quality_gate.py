"""Tests for the project quality-gate implementation."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from tools import quality_gate


def test_quality_config_and_source_hash_are_valid_and_stable():
    config = quality_gate.load_config()

    assert quality_gate.iter_source_files(config)
    assert quality_gate.source_hash(config) == quality_gate.source_hash(config)


def test_python_syntax_check_reports_invalid_source():
    with tempfile.TemporaryDirectory() as temp_dir:
        invalid_file = Path(temp_dir) / "invalid.py"
        invalid_file.write_text("def broken(:\n", encoding="utf-8")

        result = quality_gate.check_python_syntax([invalid_file])

    assert not result["passed"]
    assert "invalid.py" in result["detail"]


def test_javascript_syntax_check_includes_the_dashboard_script():
    script = quality_gate.ROOT / "docs" / "assets" / "app.js"

    result = quality_gate.check_javascript_syntax([script])

    assert result["passed"], result["detail"]


def test_only_a_successful_heavy_gate_closes_an_active_unit():
    with tempfile.TemporaryDirectory() as temp_dir:
        active_path = Path(temp_dir) / "active-unit.json"
        active_path.write_text("{}", encoding="utf-8")
        with patch.object(quality_gate, "ACTIVE_UNIT_PATH", active_path):
            quality_gate.close_active_unit_after_heavy_gate("medium")
            assert active_path.exists()

            quality_gate.close_active_unit_after_heavy_gate("heavy")
            assert not active_path.exists()
