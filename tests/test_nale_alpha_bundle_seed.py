"""Frozen run configuration must make the random seed explicit."""

import pytest

from src.analysis.nale_alpha_artifacts import _load_config_seed


@pytest.mark.parametrize("content", ["{}", '{"seed":true}', '{"seed":-1}'])
def test_missing_or_invalid_config_seed_is_rejected(tmp_path, content):
    path = tmp_path / "config.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="nonnegative integer seed"):
        _load_config_seed(path)


def test_explicit_seed_is_preserved(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"seed":42}', encoding="utf-8")
    assert _load_config_seed(path) == 42
