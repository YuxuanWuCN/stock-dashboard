"""Point-in-time NALE input contract, purged date splits, and frozen ten-PC PCA.

This module validates declared evidence times. It does not certify that an
external source is genuine; the data audit must independently establish that.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


PC_COLUMNS = tuple(f"PC{index:02d}" for index in range(1, 11))
EVIDENCE_TIME_COLUMNS = (
    "signal_at", "source_published_at", "feature_available_at",
    "network_available_at", "available_at",
)
EVIDENCE_ID_COLUMNS = (
    "feature_source_id", "network_evidence_id", "feature_version", "embedding_version",
)


def _timestamp(value: object, column: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{column} must contain an ISO timestamp") from exc
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError(f"{column} must contain a timezone-aware timestamp")
    return stamp.tz_convert("UTC")


def validate_nale_panel(
    frame: pd.DataFrame,
    embedding_columns: Sequence[str],
    *,
    require_labels: bool = False,
) -> pd.DataFrame:
    """Validate one stock/date row per signal and its declared availability."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("panel must be a nonempty DataFrame")
    features = tuple(embedding_columns)
    if len(features) < 10 or len(set(features)) != len(features) or any(not isinstance(name, str) for name in features):
        raise ValueError("at least ten distinct embedding columns are required")
    required = {"date", "code", "s0", *features, *EVIDENCE_TIME_COLUMNS, *EVIDENCE_ID_COLUMNS}
    if require_labels:
        required.update({"label_available_at", "y_excess", "price_source_id"})
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing panel columns: {sorted(missing)}")
    result = frame.copy()
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}", value) for value in result["code"]):
        raise ValueError("code must remain a six-digit string")
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) for value in result["date"]):
        raise ValueError("date must be an ISO calendar date")
    try:
        parsed_dates = [date.fromisoformat(value) for value in result["date"]]
    except ValueError as exc:
        raise ValueError("date is not a valid calendar date") from exc
    if result.duplicated(["date", "code"]).any():
        raise ValueError("duplicate date/code key")
    for column in EVIDENCE_ID_COLUMNS:
        if any(not isinstance(value, str) or not value.strip() for value in result[column]):
            raise ValueError(f"{column} must identify a nonempty source or version")
    if "price_source_id" in result.columns and any(
        value is not None and not pd.isna(value) and (not isinstance(value, str) or not value.strip())
        for value in result["price_source_id"]
    ):
        raise ValueError("price_source_id must be a nonempty string when supplied")
    if require_labels and result["price_source_id"].isna().any():
        raise ValueError("price_source_id is required for labeled rows")

    for column in EVIDENCE_TIME_COLUMNS:
        result[column] = pd.DatetimeIndex([_timestamp(value, column) for value in result[column]])
    local_signal = result["signal_at"].dt.tz_convert("Asia/Shanghai")
    if any(stamp.date() != day or stamp.time() < time(15, 0) for stamp, day in zip(local_signal, parsed_dates)):
        raise ValueError("signal_at must be on the signal date after the A-share close")
    if (result["source_published_at"] > result["feature_available_at"]).any():
        raise ValueError("source publication is after feature availability")
    if (result["feature_available_at"] > result["available_at"]).any():
        raise ValueError("feature availability is after aggregate availability")
    if (result["network_available_at"] > result["available_at"]).any():
        raise ValueError("network availability is after aggregate availability")
    if (result["available_at"] > result["signal_at"]).any():
        raise ValueError("a signal uses information not yet available")

    numeric_columns = ("s0", *features)
    if "y_excess" in result.columns:
        if require_labels and result["y_excess"].isna().any():
            raise ValueError("y_excess is required for labeled rows")
        numeric_columns = (*numeric_columns, "y_excess")
    for column in numeric_columns:
        try:
            result[column] = pd.to_numeric(result[column], errors="raise").astype(np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{column} must be numeric") from exc
        if not np.isfinite(result[column].dropna().to_numpy()).all():
            raise ValueError(f"{column} contains NaN or Inf")
        if require_labels and result[column].isna().any():
            raise ValueError(f"{column} contains missing values")
        if column != "y_excess" and result[column].isna().any():
            raise ValueError(f"{column} contains missing values")

    if "label_available_at" in result.columns:
        if require_labels and result["label_available_at"].isna().any():
            raise ValueError("label_available_at is required for labeled rows")
        label_times = [
            pd.NaT if pd.isna(value) else _timestamp(value, "label_available_at")
            for value in result["label_available_at"]
        ]
        result["label_available_at"] = pd.DatetimeIndex(label_times, tz="UTC")
        known = result["label_available_at"].notna()
        if (result.loc[known, "label_available_at"] <= result.loc[known, "signal_at"]).any():
            raise ValueError("label availability must follow its signal")
    return result


@dataclass(frozen=True)
class SplitManifest:
    train_dates: tuple[str, ...]
    validation_dates: tuple[str, ...]
    test_dates: tuple[str, ...]
    purged_after_train: tuple[str, ...]
    purged_after_validation: tuple[str, ...]
    validation_fit_cutoff: str
    test_fit_cutoff: str

    def to_dict(self) -> dict:
        return {
            "train_dates": list(self.train_dates),
            "validation_dates": list(self.validation_dates),
            "test_dates": list(self.test_dates),
            "purged_after_train": list(self.purged_after_train),
            "purged_after_validation": list(self.purged_after_validation),
            "validation_fit_cutoff": self.validation_fit_cutoff,
            "test_fit_cutoff": self.test_fit_cutoff,
        }


def make_split_manifest(
    frame: pd.DataFrame,
    embedding_columns: Sequence[str],
    *,
    train_days: int = 126,
    validation_days: int = 42,
    test_days: int = 42,
    purge_days: int = 6,
) -> SplitManifest:
    """Partition whole signal dates and reject labels crossing the next fit."""
    panel = validate_nale_panel(frame, embedding_columns, require_labels=True)
    if min(train_days, validation_days, test_days) < 1 or purge_days < 0:
        raise ValueError("split sizes must be positive and purge_days nonnegative")
    days = sorted(panel["date"].unique())
    needed = train_days + validation_days + test_days + 2 * purge_days
    if len(days) < needed:
        raise ValueError(f"insufficient dates for split: need {needed}, have {len(days)}")
    train = tuple(days[:train_days])
    train_gap_start = train_days
    train_gap_end = train_gap_start + purge_days
    first_validation = train_gap_end
    last_validation = first_validation + validation_days
    second_gap_end = last_validation + purge_days
    validation = tuple(days[first_validation:last_validation])
    test = tuple(days[second_gap_end:second_gap_end + test_days])
    cutoff_validation = pd.Timestamp(datetime.combine(date.fromisoformat(validation[0]), time(9, 30)), tz="Asia/Shanghai")
    cutoff_test = pd.Timestamp(datetime.combine(date.fromisoformat(test[0]), time(9, 30)), tz="Asia/Shanghai")
    for part_dates, cutoff in ((train, cutoff_validation), (validation, cutoff_test)):
        part = panel[panel["date"].isin(part_dates)]
        if (part["label_available_at"] >= cutoff.tz_convert("UTC")).any():
            raise ValueError("labels cross the next partition's fit cutoff")
    return SplitManifest(
        train, validation, test,
        tuple(days[train_gap_start:train_gap_end]),
        tuple(days[last_validation:second_gap_end]),
        cutoff_validation.isoformat(), cutoff_test.isoformat(),
    )


@dataclass(frozen=True)
class FrozenPCA:
    embedding_columns: tuple[str, ...]
    embedding_version: str
    feature_version: str
    pca_version: str
    train_start: str
    train_end: str
    input_mean: np.ndarray
    input_scale: np.ndarray
    components: np.ndarray
    score_mean: np.ndarray
    score_scale: np.ndarray
    explained_variance_ratio: np.ndarray

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        panel = validate_nale_panel(frame, self.embedding_columns)
        if set(panel["embedding_version"]) != {self.embedding_version} or set(panel["feature_version"]) != {self.feature_version}:
            raise ValueError("feature or embedding version differs from frozen PCA fit")
        raw = panel.loc[:, self.embedding_columns].to_numpy(dtype=np.float64)
        standardized = (raw - self.input_mean) / self.input_scale
        scores = ((standardized @ self.components.T) - self.score_mean) / self.score_scale
        if not np.isfinite(scores).all():
            raise ValueError("PCA transform produced non-finite scores")
        result = pd.DataFrame(scores, columns=PC_COLUMNS, index=panel.index)
        result.insert(0, "pca_version", self.pca_version)
        result.insert(0, "code", panel["code"])
        result.insert(0, "date", panel["date"])
        return result

    def to_manifest(self) -> dict:
        return {
            "embedding_columns": list(self.embedding_columns),
            "embedding_version": self.embedding_version,
            "feature_version": self.feature_version,
            "pca_version": self.pca_version,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "method": "StandardScaler then sklearn PCA(full SVD), frozen ten scores standardized on training rows",
            "input_mean": self.input_mean.tolist(),
            "input_scale": self.input_scale.tolist(),
            "components": self.components.tolist(),
            "score_mean": self.score_mean.tolist(),
            "score_scale": self.score_scale.tolist(),
            "explained_variance_ratio": self.explained_variance_ratio.tolist(),
        }


def fit_frozen_pca(
    frame: pd.DataFrame,
    train_dates: Sequence[str],
    embedding_columns: Sequence[str],
) -> FrozenPCA:
    """Fit only the initial training rows; later dates cannot change the basis."""
    panel = validate_nale_panel(frame, embedding_columns)
    selected_dates = tuple(sorted(set(train_dates)))
    if not selected_dates or len(selected_dates) != len(tuple(train_dates)):
        raise ValueError("train_dates must be nonempty and distinct")
    if not set(selected_dates).issubset(set(panel["date"])):
        raise ValueError("some training dates are missing from the panel")
    training = panel.loc[panel["date"].isin(selected_dates)].sort_values(["date", "code"])
    if training["embedding_version"].nunique() != 1 or training["feature_version"].nunique() != 1:
        raise ValueError("initial PCA requires a single embedding and feature version")
    data = training.loc[:, embedding_columns].to_numpy(dtype=np.float64)
    scaler = StandardScaler().fit(data)
    centered = scaler.transform(data)
    if min(centered.shape) < 10 or np.linalg.matrix_rank(centered) < 10:
        raise ValueError("centered embedding rank is below ten")
    pca = PCA(n_components=10, svd_solver="full").fit(centered)
    components = np.asarray(pca.components_, dtype=np.float64).copy()
    pivot = np.argmax(np.abs(components), axis=1)
    orientation = np.sign(components[np.arange(10), pivot])
    components *= orientation[:, None]
    raw_scores = centered @ components.T
    score_mean = raw_scores.mean(axis=0)
    score_scale = raw_scores.std(axis=0, ddof=0)
    if (score_scale <= 1e-12).any():
        raise ValueError("a principal component has zero training variance")
    columns = tuple(embedding_columns)
    digest = hashlib.sha256()
    digest.update(json.dumps({
        "columns": columns,
        "embedding_version": training["embedding_version"].iloc[0],
        "feature_version": training["feature_version"].iloc[0],
        "train_dates": selected_dates,
    }, sort_keys=True).encode("utf-8"))
    for matrix in (scaler.mean_, scaler.scale_, components, score_mean, score_scale):
        digest.update(np.asarray(matrix, dtype="<f8").tobytes())
    return FrozenPCA(
        embedding_columns=columns,
        embedding_version=training["embedding_version"].iloc[0],
        feature_version=training["feature_version"].iloc[0],
        pca_version="pca10-" + digest.hexdigest()[:16],
        train_start=selected_dates[0], train_end=selected_dates[-1],
        input_mean=np.asarray(scaler.mean_, dtype=np.float64),
        input_scale=np.asarray(scaler.scale_, dtype=np.float64),
        components=components, score_mean=score_mean, score_scale=score_scale,
        explained_variance_ratio=np.asarray(pca.explained_variance_ratio_, dtype=np.float64),
    )
