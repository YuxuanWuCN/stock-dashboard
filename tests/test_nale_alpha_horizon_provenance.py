"""Fail closed when a 20-day study has no 20-day label declaration."""

from types import SimpleNamespace

import pandas as pd
import pytest

from src.analysis.nale_alpha_experiment import _require_declared_label_horizon


@pytest.mark.parametrize("values", [None, [5], [20, 5]])
def test_twenty_day_study_rejects_missing_or_mismatched_label_horizon(values):
    frame = pd.DataFrame({"label_horizon_days": values}) if values is not None else pd.DataFrame({"y_excess": [0.1]})
    with pytest.raises(ValueError, match="explicitly declared 20-day labels"):
        _require_declared_label_horizon(SimpleNamespace(predictions=frame), 20)


def test_declared_twenty_day_labels_are_accepted():
    output = SimpleNamespace(predictions=pd.DataFrame({"label_horizon_days": [20, 20]}))
    assert _require_declared_label_horizon(output, 20) is output


def test_five_day_study_keeps_existing_prediction_contract():
    output = SimpleNamespace(predictions=pd.DataFrame({"y_excess": [0.1]}))
    assert _require_declared_label_horizon(output, 5) is output
