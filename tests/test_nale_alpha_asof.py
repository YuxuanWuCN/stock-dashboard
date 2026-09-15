import pandas as pd
import pytest

from src.data.nale_alpha_asof import AsOfError, select_asof_revision


def _features():
    return pd.DataFrame(
        [
            {"date": "2024-01-02", "code": "000001", "available_at": "2024-01-02T16:00:00+08:00", "score": 1.0},
            {"date": "2024-01-02", "code": "000001", "available_at": "2024-01-03T10:00:00+08:00", "score": 2.0},
            {"date": "2024-01-03", "code": "000001", "available_at": "2024-01-03T16:00:00+08:00", "score": 3.0},
        ]
    )


def _select(frame, cutoff="2024-01-02T17:00:00+08:00"):
    return select_asof_revision(
        frame,
        signal_date="2024-01-02",
        decision_cutoff=cutoff,
        keys=("date", "code"),
    )


def test_future_revision_cannot_change_earlier_snapshot():
    first = _select(_features().iloc[:1])
    with_future = _select(_features())
    pd.testing.assert_frame_equal(first, with_future)
    assert with_future.loc[0, "score"] == 1.0
    assert with_future.loc[0, "code"] == "000001"


def test_later_cutoff_can_use_mature_revision():
    result = _select(_features(), "2024-01-03T12:00:00+08:00")
    assert result.loc[0, "score"] == 2.0


def test_network_effective_interval_and_publication_both_apply():
    edges = pd.DataFrame(
        [
            {"source_code": "000001", "target_code": "000002", "available_at": "2024-01-01T12:00:00+08:00", "effective_from": "2024-01-01", "effective_to": "2024-01-02", "weight": 1.0},
            {"source_code": "000003", "target_code": "000002", "available_at": "2024-01-04T12:00:00+08:00", "effective_from": "2024-01-03", "effective_to": None, "weight": 1.0},
        ]
    )
    earlier = select_asof_revision(
        edges, signal_date="2024-01-02", decision_cutoff="2024-01-02T17:00:00+08:00",
        keys=("source_code", "target_code"), date_column=None,
        effective_from_column="effective_from", effective_to_column="effective_to",
    )
    later = select_asof_revision(
        edges, signal_date="2024-01-03", decision_cutoff="2024-01-03T17:00:00+08:00",
        keys=("source_code", "target_code"), date_column=None,
        effective_from_column="effective_from", effective_to_column="effective_to",
    )
    assert earlier["source_code"].tolist() == ["000001"]
    assert later.empty


def test_naive_publication_time_fails_closed():
    frame = _features()
    frame.loc[0, "available_at"] = "2024-01-02T16:00:00"
    with pytest.raises(AsOfError, match="timezone"):
        _select(frame)


def test_duplicate_latest_revision_fails_closed():
    frame = pd.concat([_features().iloc[:1], _features().iloc[:1]], ignore_index=True)
    with pytest.raises(AsOfError, match="duplicate latest"):
        _select(frame)
