"""Point-in-time and PCA fixtures only; no simulated performance claim."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.data.nale_alpha_panel import (
    PC_COLUMNS,
    fit_frozen_pca,
    make_split_manifest,
    validate_nale_panel,
)


def _fixture():
    dates = pd.bdate_range("2024-06-03", periods=7).strftime("%Y-%m-%d")
    codes = ("000001", "000002", "000003")
    columns = tuple(f"dim_{index:03d}" for index in range(12))
    raw = np.random.default_rng(42).normal(size=(len(dates) * len(codes), len(columns)))
    rows = []
    for index, (day, code) in enumerate((day, code) for day in dates for code in codes):
        next_day = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        row = {
            "date": day, "code": code, "s0": float(index) / 100,
            "signal_at": day + "T15:10:00+08:00",
            "source_published_at": day + "T10:00:00+08:00",
            "feature_available_at": day + "T14:00:00+08:00",
            "network_available_at": day + "T14:30:00+08:00",
            "available_at": day + "T14:40:00+08:00",
            "feature_source_id": "doc-version-1", "network_evidence_id": "edge-version-1",
            "feature_version": "features-v1", "embedding_version": "embed-v1",
            "price_source_id": "math-fixture-only",
            "label_available_at": next_day + "T18:00:00+08:00", "y_excess": 0.001,
        }
        row.update(dict(zip(columns, raw[index])))
        rows.append(row)
    return pd.DataFrame(rows), columns, tuple(dates)


def test_validate_keeps_leading_zero_and_rejects_future_information():
    frame, columns, _ = _fixture()
    valid = validate_nale_panel(frame, columns, require_labels=True)
    assert valid.loc[0, "code"] == "000001"
    assert valid.loc[0, "available_at"] < valid.loc[0, "signal_at"]

    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        validate_nale_panel(duplicate, columns)
    bad_code = frame.copy()
    bad_code.loc[0, "code"] = 1
    with pytest.raises(ValueError, match="six-digit"):
        validate_nale_panel(bad_code, columns)
    future = frame.copy()
    future.loc[0, "feature_available_at"] = "2024-06-03T15:30:00+08:00"
    with pytest.raises(ValueError, match="feature availability"):
        validate_nale_panel(future, columns)
    future = frame.copy()
    future.loc[0, "network_available_at"] = "2024-06-03T15:30:00+08:00"
    with pytest.raises(ValueError, match="network availability"):
        validate_nale_panel(future, columns)
    missing_source = frame.copy()
    missing_source.loc[0, "feature_source_id"] = ""
    with pytest.raises(ValueError, match="feature_source_id"):
        validate_nale_panel(missing_source, columns)
    bad_timestamp = frame.copy()
    bad_timestamp.loc[0, "source_published_at"] = "2024-06-03T10:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_nale_panel(bad_timestamp, columns)


def test_labels_are_required_for_splits_but_not_for_prediction_pca():
    frame, columns, _ = _fixture()
    future = frame.drop(columns=["label_available_at", "y_excess", "price_source_id"])
    assert len(validate_nale_panel(future, columns)) == len(future)
    with pytest.raises(ValueError, match="missing panel columns"):
        make_split_manifest(future, columns, train_days=2, validation_days=1, test_days=1, purge_days=1)
    bad = frame.copy()
    bad.loc[0, "label_available_at"] = "2024-06-03T15:00:00+08:00"
    with pytest.raises(ValueError, match="follow"):
        validate_nale_panel(bad, columns, require_labels=True)


def test_purged_date_split_checks_label_maturity():
    frame, columns, _ = _fixture()
    split = make_split_manifest(frame, columns, train_days=2, validation_days=1, test_days=1, purge_days=1)
    assert len(split.train_dates) == 2
    assert len(split.validation_dates) == 1
    assert len(split.test_dates) == 1
    assert len(split.purged_after_train) == 1
    assert set(split.train_dates).isdisjoint(split.validation_dates)
    assert set(split.validation_dates).isdisjoint(split.test_dates)
    assert split.to_dict()["validation_dates"] == list(split.validation_dates)
    late = frame.copy()
    late.loc[late["date"] == split.train_dates[-1], "label_available_at"] = split.validation_fit_cutoff
    with pytest.raises(ValueError, match="cross"):
        make_split_manifest(late, columns, train_days=2, validation_days=1, test_days=1, purge_days=1)
    with pytest.raises(ValueError, match="insufficient"):
        make_split_manifest(frame, columns)


def test_full_svd_frozen_pca_ignores_future_and_input_order():
    frame, columns, dates = _fixture()
    pca = fit_frozen_pca(frame, dates[:4], columns)
    assert pca.components.shape == (10, 12)
    assert pca.to_manifest()["method"].startswith("StandardScaler")
    transformed = pca.transform(frame)
    assert all(column in transformed for column in PC_COLUMNS)
    assert transformed["pca_version"].nunique() == 1
    assert transformed["code"].iloc[0] == "000001"
    assert np.isfinite(transformed.loc[:, PC_COLUMNS].to_numpy()).all()
    assert np.max(np.abs(transformed.loc[frame["date"].isin(dates[:4]), PC_COLUMNS].mean().to_numpy())) < 1e-12

    changed_future = frame.copy()
    changed_future.loc[changed_future["date"] == dates[-1], columns[0]] += 10000
    refit = fit_frozen_pca(changed_future, dates[:4], columns)
    assert refit.pca_version == pca.pca_version
    np.testing.assert_allclose(
        refit.transform(changed_future).loc[frame["date"].isin(dates[:4]), PC_COLUMNS],
        transformed.loc[frame["date"].isin(dates[:4]), PC_COLUMNS],
    )
    reordered = frame.sample(frac=1, random_state=9)
    assert fit_frozen_pca(reordered, dates[:4], columns).pca_version == pca.pca_version


def test_rank_version_and_nonfinite_inputs_fail_closed():
    frame, columns, dates = _fixture()
    low_rank = frame.copy()
    for column in columns[9:]:
        low_rank[column] = low_rank[columns[0]]
    with pytest.raises(ValueError, match="rank"):
        fit_frozen_pca(low_rank, dates[:4], columns)
    mixed = frame.copy()
    mixed.loc[0, "embedding_version"] = "embed-v2"
    with pytest.raises(ValueError, match="single embedding"):
        fit_frozen_pca(mixed, dates[:4], columns)
    pca = fit_frozen_pca(frame, dates[:4], columns)
    changed_version = frame.copy()
    changed_version.loc[0, "embedding_version"] = "embed-v2"
    with pytest.raises(ValueError, match="version differs"):
        pca.transform(changed_version)
    nonfinite = frame.copy()
    nonfinite.loc[0, columns[0]] = np.inf
    with pytest.raises(ValueError, match="NaN or Inf"):
        validate_nale_panel(nonfinite, columns)
