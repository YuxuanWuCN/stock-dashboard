"""The figure is a labeled artifact, not empirical performance evidence."""

from io import BytesIO

from PIL import Image
import pandas as pd
import pytest

from src.analysis.nale_alpha_figures import VERSION_ORDER, render_rank_ic_figure


def _comparison():
    return pd.DataFrame([
        {"version": version, "phase": "test",
         "status": "available" if version in {"B0", "V1"} else "not_evaluable",
         "rank_ic_mean": 0.02 if version == "B0" else -0.03 if version == "V1" else None}
        for version in VERSION_ORDER
    ])


def test_fixture_figure_has_dpi_and_nonmarket_label():
    content = render_rank_ic_figure(_comparison(), fixture=True)
    with Image.open(BytesIO(content)) as image:
        assert image.format == "PNG"
        assert min(image.info["dpi"]) >= 200
        assert image.width >= 1800
        assert "ENGINEERING FIXTURE" in image.info["Description"]


def test_rank_ic_figure_rejects_invalid_available_value():
    rows = _comparison()
    rows.loc[rows["version"] == "V1", "rank_ic_mean"] = float("inf")
    with pytest.raises(ValueError, match="finite"):
        render_rank_ic_figure(rows, fixture=False)


def test_rank_ic_figure_rejects_mixed_phases():
    rows = _comparison()
    rows.loc[rows["version"] == "V1", "phase"] = "validation"
    with pytest.raises(ValueError, match="one declared"):
        render_rank_ic_figure(rows, fixture=False)
