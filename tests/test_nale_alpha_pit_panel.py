import pandas as pd
import pytest

from src.data.nale_alpha_asof import AsOfError
from src.data.nale_alpha_pit_panel import materialize_point_in_time_panel


CUTOFFS = {
    "2024-01-02": "2024-01-02T17:00:00+08:00",
    "2024-01-03": "2024-01-03T17:00:00+08:00",
}


def _inputs():
    features = pd.DataFrame(
        [
            {"date": "2024-01-02", "code": "000001", "available_at": "2024-01-02T16:00:00+08:00", "embedding_000": 1.0},
            {"date": "2024-01-03", "code": "000001", "available_at": "2024-01-03T16:00:00+08:00", "embedding_000": 2.0},
        ]
    )
    s0 = pd.DataFrame(
        [
            {"date": "2024-01-02", "code": "000001", "available_at": "2024-01-02T16:00:00+08:00", "s0": 0.2},
            {"date": "2024-01-03", "code": "000001", "available_at": "2024-01-03T16:00:00+08:00", "s0": 0.3},
        ]
    )
    edges = pd.DataFrame(
        [
            {"source_code": "000001", "target_code": "000002", "source_available_at": "2024-01-02T12:00:00+08:00", "effective_from": "2024-01-02", "effective_to": "2024-01-02", "weight": 1.0},
        ]
    )
    return features, s0, edges


def test_daily_materialization_respects_available_and_effective_time():
    panel = materialize_point_in_time_panel(*_inputs(), CUTOFFS)
    assert panel.features["embedding_000"].tolist() == [1.0, 2.0]
    assert panel.edges["signal_date"].tolist() == ["2024-01-02"]
    assert panel.decision_cutoffs == CUTOFFS


def test_future_revision_does_not_change_past_materialization():
    features, s0, edges = _inputs()
    original = materialize_point_in_time_panel(features, s0, edges, CUTOFFS)
    future = pd.DataFrame(
        [{"date": "2024-01-02", "code": "000001", "available_at": "2024-01-04T10:00:00+08:00", "embedding_000": 999.0}]
    )
    changed = materialize_point_in_time_panel(pd.concat([features, future]), s0, edges, CUTOFFS)
    pd.testing.assert_frame_equal(original.features, changed.features)


def test_missing_s0_day_fails_closed():
    features, s0, edges = _inputs()
    with pytest.raises(AsOfError, match="no candidate rows"):
        materialize_point_in_time_panel(features, s0.iloc[:1], edges, CUTOFFS)


def test_feature_s0_stock_mismatch_fails_closed():
    features, s0, edges = _inputs()
    s0.loc[0, "code"] = "000003"
    with pytest.raises(AsOfError, match="stock keys differ"):
        materialize_point_in_time_panel(features, s0, edges, CUTOFFS)
