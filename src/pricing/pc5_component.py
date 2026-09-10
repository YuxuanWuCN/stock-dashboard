"""Extract the fifth principal component from a frozen, full-SVD PCA basis.

PC05 is a statistical component, not the P1-P5 fusion operator. No returns,
labels, financial interpretation, or NALE coefficients are inferred here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TARGET_COMPONENT = 5


def _matrix(features: pd.DataFrame) -> np.ndarray:
    if not isinstance(features, pd.DataFrame) or features.empty:
        raise ValueError("PCA requires a nonempty feature DataFrame")
    if features.columns.has_duplicates or features.index.has_duplicates:
        raise ValueError("PCA requires unique feature names and sample keys")
    if not all(isinstance(column, str) for column in features.columns):
        raise ValueError("PCA feature names must be strings")
    matrix = features.apply(pd.to_numeric, errors="raise").to_numpy(dtype=np.float64)
    if not np.isfinite(matrix).all():
        raise ValueError("PCA input contains NaN or Inf; no filling is performed")
    return matrix


def basis_version(basis: dict[str, Any]) -> str:
    payload = {key: value for key, value in basis.items() if key != "pca_version"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "pc5-full-svd-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fit_pc5_basis(features: pd.DataFrame, n_components: int = 10) -> dict[str, Any]:
    """Fit only the supplied training rows; retain exactly n_components >= 5.

    Raw features use population-standard-deviation scaling. Component signs
    put the largest absolute loading on the positive side. Raw PC variance is
    the corresponding eigenvalue, so it is not assumed to equal one.
    """
    if isinstance(n_components, bool) or not isinstance(n_components, int):
        raise ValueError("n_components must be an integer")
    if n_components < TARGET_COMPONENT:
        raise ValueError("PC5 requires at least 5 retained components")
    ordered = features.sort_index().sort_index(axis=1)
    matrix = _matrix(ordered)
    if min(matrix.shape[0] - 1, matrix.shape[1]) < n_components:
        raise ValueError(f"Centered data cannot support {n_components} components")
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0, ddof=0)
    # An exactly constant float column can acquire a tiny nonzero std through
    # rounding in its computed mean. It must not add a spurious PCA direction.
    constant = np.ptp(matrix, axis=0) == 0.0
    mean[constant] = matrix[0, constant]
    scale = np.where(constant | (scale == 0.0), 1.0, scale)
    standardized = (matrix - mean) / scale
    _, singular, vectors = np.linalg.svd(standardized, full_matrices=False)
    tolerance = max(standardized.shape) * np.finfo(np.float64).eps * singular[0]
    rank = int(np.count_nonzero(singular > tolerance))
    if rank < n_components:
        raise ValueError(f"Centered rank {rank} is below required {n_components}")
    components = vectors[:n_components].copy()
    for row in components:
        if row[np.argmax(np.abs(row))] < 0.0:
            row *= -1.0
    scores = standardized @ components.T
    eigenvalues = singular**2 / (len(matrix) - 1)
    ratios = singular**2 / np.dot(singular, singular)
    target = TARGET_COMPONENT - 1
    gaps = [
        float((eigenvalues[target - 1] - eigenvalues[target]) / eigenvalues[target])
    ]
    if target + 1 < len(eigenvalues):
        gaps.append(
            float((eigenvalues[target] - eigenvalues[target + 1]) / eigenvalues[target])
        )
    basis = {
        "schema_version": 1,
        "selected_component": TARGET_COMPONENT,
        "n_components": n_components,
        "n_training_rows": len(matrix),
        "centered_rank": rank,
        "solver": "numpy.linalg.svd(full_matrices=False)",
        "sign_convention": "largest_absolute_loading_positive",
        "feature_columns": ordered.columns.tolist(),
        "feature_mean": mean.tolist(),
        "feature_scale": scale.tolist(),
        "components": components.tolist(),
        "pc_mean": scores.mean(axis=0).tolist(),
        "pc_scale": scores.std(axis=0, ddof=0).tolist(),
        "explained_variance": eigenvalues[:n_components].tolist(),
        "explained_variance_ratio": ratios[:n_components].tolist(),
        "pc5_relative_eigenvalue_gaps": gaps,
        "pc5_near_degenerate": min(gaps) < 1e-6,
        "training_matrix_sha256": hashlib.sha256(
            np.ascontiguousarray(matrix, dtype="<f8").tobytes()
        ).hexdigest(),
        "training_keys_sha256": hashlib.sha256(
            json.dumps([str(key) for key in ordered.index]).encode()
        ).hexdigest(),
    }
    basis["pca_version"] = basis_version(basis)
    return basis


def transform_pc5_basis(
    features: pd.DataFrame, basis: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply frozen feature/PC scales and loadings; no fitting occurs here."""
    if basis.get("pca_version") != basis_version(basis):
        raise ValueError("PCA basis hash mismatch")
    columns = basis["feature_columns"]
    if set(features.columns) != set(columns) or len(features.columns) != len(columns):
        raise ValueError("Transform feature columns must match the fitted PCA basis")
    matrix = _matrix(features.loc[:, columns])
    normalized = (matrix - np.asarray(basis["feature_mean"])) / np.asarray(
        basis["feature_scale"]
    )
    raw = normalized @ np.asarray(basis["components"]).T
    standardized = (raw - np.asarray(basis["pc_mean"])) / np.asarray(basis["pc_scale"])
    if not np.isfinite(raw).all() or not np.isfinite(standardized).all():
        raise ValueError("PCA transform produced nonfinite values")
    names = [f"PC{i:02d}" for i in range(1, basis["n_components"] + 1)]
    return (
        pd.DataFrame(raw, index=features.index, columns=names),
        pd.DataFrame(standardized, index=features.index, columns=names),
    )


def select_pc5(scores: pd.DataFrame) -> pd.Series:
    """Select PC05 by name; never relabel the last retained component PC5."""
    if "PC05" not in scores.columns or scores.columns.has_duplicates:
        raise ValueError("Exactly one PC05 column is required")
    result = pd.to_numeric(scores["PC05"], errors="raise")
    if not np.isfinite(result.to_numpy(dtype=np.float64)).all():
        raise ValueError("PC05 contains nonfinite values")
    return result.rename("PC5_raw")


def save_pc5_basis(basis: dict[str, Any], path: Path) -> None:
    if basis.get("pca_version") != basis_version(basis):
        raise ValueError("PCA basis hash mismatch")
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(basis, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def load_pc5_basis(path: Path) -> dict[str, Any]:
    basis = json.loads(Path(path).read_text(encoding="utf-8"))
    if basis.get("pca_version") != basis_version(basis):
        raise ValueError("PCA basis hash mismatch")
    return basis
