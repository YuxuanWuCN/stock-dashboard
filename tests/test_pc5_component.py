"""Independent algebra, regression and failure tests for the PC5 assignment."""

from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from scripts.day2_pca_extraction import run_pca_pipeline
from scripts.extract_pc5 import ROOT, prepare_dataset, run_extraction, source_info
from src.pricing.pc5_component import (
    fit_pc5_basis,
    load_pc5_basis,
    save_pc5_basis,
    select_pc5,
    transform_pc5_basis,
)


def known_covariance_sample():
    # Five independent correlated pairs have eigenvalues
    # (1.9, 1.8, 1.7, 1.6, 1.5, .5, .4, .3, .2, .1).
    hadamard = np.ones((1, 1))
    for _ in range(4):
        hadamard = np.block([[hadamard, hadamard], [hadamard, -hadamard]])
    orthogonal = hadamard[:, 1:11]
    columns = []
    for i, rho in enumerate((0.9, 0.8, 0.7, 0.6, 0.5)):
        columns.extend(
            [
                orthogonal[:, 2 * i],
                rho * orthogonal[:, 2 * i]
                + np.sqrt(1 - rho**2) * orthogonal[:, 2 * i + 1],
            ]
        )
    return pd.DataFrame(
        np.column_stack(columns), columns=[f"f{i:02d}" for i in range(10)]
    )


def test_pc5_matches_hand_calculation_not_last_component():
    features = known_covariance_sample()
    basis = fit_pc5_basis(features, 10)
    raw, z = transform_pc5_basis(features, basis)
    expected = (features["f08"] + features["f09"]) / np.sqrt(2)
    np.testing.assert_allclose(select_pc5(raw), expected, atol=1e-12)
    assert basis["explained_variance_ratio"][4] == pytest.approx(0.15)
    assert raw["PC05"].var(ddof=0) == pytest.approx(1.5)
    assert z["PC05"].std(ddof=0) == pytest.approx(1)
    assert not np.allclose(raw["PC05"], raw["PC10"])
    np.testing.assert_allclose(
        np.asarray(basis["components"])[4, 8:], np.ones(2) / np.sqrt(2), atol=1e-12
    )


def test_pc5_agrees_with_independent_covariance_eigendecomposition():
    features = pd.DataFrame(
        np.random.default_rng(10).normal(size=(80, 14)),
        columns=[f"f{i:02d}" for i in range(14)],
    )
    basis = fit_pc5_basis(features, 10)
    raw, _ = transform_pc5_basis(features, basis)
    scaled = (features - features.mean()) / features.std(ddof=0)
    values, vectors = np.linalg.eigh(np.cov(scaled, rowvar=False))
    vector = vectors[:, np.argsort(values)[-5]]
    if vector[np.argmax(np.abs(vector))] < 0:
        vector = -vector
    np.testing.assert_allclose(raw["PC05"], scaled @ vector, atol=1e-11)


@pytest.mark.parametrize("count", [0, 4, 11, 5.0, True])
def test_invalid_component_count_fails_instead_of_fallback(count):
    with pytest.raises(ValueError):
        fit_pc5_basis(known_covariance_sample(), count)


def test_rank_deficiency_missing_values_duplicate_keys_and_absent_pc5_fail():
    source = known_covariance_sample()
    for malformed in (
        source.assign(f09=source["f08"]),
        source.iloc[:5],
        source.iloc[:, :4],
    ):
        with pytest.raises(ValueError):
            fit_pc5_basis(malformed, 10)
    for value in (np.nan, np.inf, -np.inf):
        malformed = source.copy()
        malformed.iloc[0, 0] = value
        with pytest.raises(ValueError, match="NaN or Inf"):
            fit_pc5_basis(malformed, 5)
    malformed = source.copy()
    malformed.index = [0] * len(malformed)
    with pytest.raises(ValueError, match="unique"):
        fit_pc5_basis(malformed, 5)
    with pytest.raises(ValueError, match="PC05"):
        select_pc5(pd.DataFrame({"PC04": [1.0], "PC06": [2.0]}))


def test_floating_point_constant_column_cannot_inflate_centered_rank():
    features = pd.DataFrame(
        np.random.default_rng(42).normal(size=(20, 5)), columns=list("abcde")
    )
    features["constant"] = 0.1
    with pytest.raises(ValueError, match="rank 5"):
        fit_pc5_basis(features, 6)
    basis = fit_pc5_basis(features, 5)
    assert basis["centered_rank"] == 5
    constant_index = basis["feature_columns"].index("constant")
    np.testing.assert_allclose(
        np.asarray(basis["components"])[:, constant_index], 0.0, atol=1e-12
    )


def test_order_invariance_frozen_basis_roundtrip_and_tamper_rejection(tmp_path):
    features = known_covariance_sample()
    basis = fit_pc5_basis(features, 10)
    shuffled = features.sample(frac=1, random_state=4).iloc[:, ::-1]
    assert fit_pc5_basis(shuffled, 10)["pca_version"] == basis["pca_version"]
    expected, _ = transform_pc5_basis(features, basis)
    actual, _ = transform_pc5_basis(shuffled, basis)
    pd.testing.assert_frame_equal(actual.sort_index(), expected)
    path = tmp_path / "basis.json"
    save_pc5_basis(basis, path)
    pd.testing.assert_frame_equal(
        transform_pc5_basis(features, load_pc5_basis(path))[0], expected
    )
    with pytest.raises(FileExistsError):
        save_pc5_basis(basis, path)
    changed = deepcopy(basis)
    changed["components"][4][0] += 0.1
    with pytest.raises(ValueError, match="hash mismatch"):
        transform_pc5_basis(features, changed)
    with pytest.raises(ValueError, match="columns"):
        transform_pc5_basis(features.drop(columns="f09"), basis)


def test_dated_future_changes_do_not_change_training_basis_or_earlier_scores(tmp_path):
    features = pd.DataFrame(
        np.random.default_rng(42).normal(size=(40, 10)),
        columns=[f"f{i}" for i in range(10)],
    )
    features.insert(0, "date", pd.bdate_range("2025-01-01", periods=40))
    path = tmp_path / "input.csv"
    features.to_csv(path, index=False)
    config = {
        "id": "fixture",
        "input": str(path),
        "kind": "dated_factors",
        "n_components": 10,
        "fit_end": str(features.loc[24, "date"].date()),
    }
    first = prepare_dataset(config)
    features.iloc[25:, 1:] *= -100
    features.to_csv(path, index=False)
    second = prepare_dataset(config)
    assert first["basis"]["pca_version"] == second["basis"]["pca_version"]
    pd.testing.assert_frame_equal(first["raw"].iloc[:25], second["raw"].iloc[:25])
    assert not np.allclose(first["raw"].iloc[25:], second["raw"].iloc[25:])


def test_day2_selects_fifth_even_when_six_are_retained_and_refuses_overwrite(tmp_path):
    features = known_covariance_sample()
    features.insert(0, "date", pd.bdate_range("2025-01-01", periods=len(features)))
    path = tmp_path / "factors.csv"
    features.to_csv(path, index=False)
    output = tmp_path / "result"
    run_pca_pipeline(path, output, n_components=6)
    raw = pd.read_csv(output / "pc5_raw.csv")
    all_pcs = pd.read_csv(output / "all_pcs.csv")
    np.testing.assert_allclose(raw["PC5_raw"], all_pcs["PC05"], atol=1e-12)
    assert not np.allclose(raw["PC5_raw"], all_pcs["PC06"])
    before = (output / "pc5_raw.csv").read_bytes()
    with pytest.raises(FileExistsError):
        run_pca_pipeline(path, output, n_components=5)
    assert (output / "pc5_raw.csv").read_bytes() == before


def test_pinned_repository_inputs_and_legacy_pc5_reproduce():
    config = json.loads(
        (ROOT / "config/experiments/pc5_component.json").read_text(encoding="utf-8")
    )
    snapshot, legacy = [prepare_dataset(dataset) for dataset in config["datasets"]]
    assert snapshot["raw"].shape == (300, 10)
    assert all(len(code) == 6 for code in snapshot["raw"].index)
    assert "000001" in snapshot["raw"].index
    assert snapshot["provenance"]["feature_sources"] == {"local_semantic": 300}
    assert snapshot["diagnostics"]["pc5_explained_variance_ratio"] == pytest.approx(
        0.03726987527943329, abs=1e-12
    )
    assert (
        legacy["diagnostics"]["legacy_pc5_max_abs_error_after_sign_alignment"] < 1e-11
    )
    features = (
        pd.read_csv(ROOT / config["datasets"][0]["input"], dtype={"code": str})
        .set_index("code")
        .sort_index()
        .filter(regex=r"^dim_")
    )
    independent = PCA(n_components=10, svd_solver="full").fit_transform(
        StandardScaler().fit_transform(features)
    )
    sign = np.sign(np.dot(independent[:, 4], snapshot["selected"]))
    np.testing.assert_allclose(
        sign * independent[:, 4], snapshot["selected"], atol=1e-10
    )


def test_source_hash_and_invalid_input_leave_no_output(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("date,a\n2025-01-01,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pinned GitHub"):
        source_info(path, "0" * 40)
    config = {
        "selected_component": 5,
        "datasets": [
            {
                "id": "bad",
                "input": str(path),
                "kind": "dated_factors",
                "n_components": 5,
            }
        ],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError):
        run_extraction(config_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_end_to_end_artifact_hashes_and_descriptive_status(tmp_path):
    config_path = ROOT / "config/experiments/pc5_component.json"
    output = tmp_path / "delivery"
    manifest = run_extraction(config_path, output)
    assert manifest["status"] == "PC5_EXTRACTION_COMPLETE_DESCRIPTIVE_ONLY"
    assert manifest["system_did_not_order"] is True
    assert manifest["stable_output_replacement"] is False
    assert manifest["performance_evaluation"] == "NOT_RUN_NO_POINT_IN_TIME_PANEL"
    for name, expected in manifest["artifacts_sha256"].items():
        assert source_info(output / name)["sha256"] == expected
        if (output / name).suffix in {".csv", ".json", ".md"}:
            assert b"\r\n" not in (output / name).read_bytes()
    score = pd.read_csv(output / "snapshot_768d/pc5_scores.csv", dtype={"code": str})
    assert score.shape[0] == 300
    assert score["PC05_z"].std(ddof=0) == pytest.approx(1)
    with pytest.raises(FileExistsError):
        run_extraction(config_path, output)
