#!/usr/bin/env python
"""Reproduce the assigned fifth principal component from pinned GitHub inputs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pricing.pc5_component import (  # noqa: E402
    fit_pc5_basis,
    save_pc5_basis,
    select_pc5,
    transform_pc5_basis,
)


def source_info(path: Path, expected_blob: str | None = None) -> dict[str, str]:
    content = path.read_bytes()
    blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    if expected_blob is not None and blob != expected_blob:
        raise ValueError(f"Input differs from the pinned GitHub blob: {path}")
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "git_blob": blob,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def prepare_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    """Validate the input and compute outputs before creating any run directory."""
    path = ROOT / dataset["input"]
    sources = [source_info(path, dataset.get("input_git_blob"))]
    frame = pd.read_csv(path, dtype={"code": "string"})
    kind = dataset["kind"]
    if kind == "embedding_snapshot":
        if dataset.get("fit_end") is not None:
            raise ValueError("A current-only snapshot has no chronological fit_end")
        if dataset["n_components"] != 10:
            raise ValueError("The 768D handoff requires exactly ten retained PCs")
        dimensions = [f"dim_{i:03d}" for i in range(768)]
        if set(frame.filter(regex=r"^dim_").columns) != set(dimensions):
            raise ValueError("Expected exactly dim_000 through dim_767")
        if (
            "code" not in frame
            or not frame["code"].str.fullmatch(r"[0-9]{6}", na=False).all()
        ):
            raise ValueError("Every code must be a six-digit string")
        if frame["code"].duplicated().any():
            raise ValueError("Duplicate stock code in the snapshot")
        frame = frame.set_index("code").sort_index()
        metadata_columns = [
            c for c in ("name", "sector", "cohort_key", "feature_source") if c in frame
        ]
        identities = frame[metadata_columns].copy()
        features = frame[dimensions]
        if dataset.get("name_mapping"):
            mapping_path = ROOT / dataset["name_mapping"]
            sources.append(
                source_info(mapping_path, dataset.get("name_mapping_git_blob"))
            )
            mapping = (
                pd.read_csv(mapping_path, dtype={"code": "string"})
                .set_index("code")
                .sort_index()
            )
            if mapping.index.has_duplicates or not frame["name"].equals(
                mapping["name"]
            ):
                raise ValueError(
                    "Code/name mapping differs from the repository assignment table"
                )
        sources_counts = (
            frame["feature_source"].value_counts().to_dict()
            if "feature_source" in frame
            else {}
        )
        provenance = {
            "feature_sources": sources_counts,
            "historical_panel_available": False,
        }
    elif kind == "dated_factors":
        if "date" not in frame:
            raise ValueError("Dated factors require an explicit date column")
        dates = pd.to_datetime(frame.pop("date"), errors="raise")
        if dates.isna().any() or dates.duplicated().any() or dates.dt.tz is not None:
            raise ValueError("Dates must be valid, unique, timezone-naive signal dates")
        if not dates.equals(dates.dt.normalize()):
            raise ValueError("Dated factors must use whole calendar dates")
        frame.index = pd.DatetimeIndex(dates, name="date")
        features = frame.sort_index()
        identities = pd.DataFrame(index=features.index)
        provenance = {
            "historical_panel_available": False,
            "point_in_time_availability_verified": False,
        }
    else:
        raise ValueError(f"Unsupported input kind: {kind}")
    training = features
    if dataset.get("fit_end") is not None:
        cutoff = pd.Timestamp(dataset["fit_end"])
        training = features.loc[features.index <= cutoff]
    basis = fit_pc5_basis(training, n_components=dataset["n_components"])
    raw, standardized = transform_pc5_basis(features, basis)
    selected = select_pc5(raw)
    training_scores = raw.loc[training.index].to_numpy()
    covariance = np.atleast_2d(np.cov(training_scores, rowvar=False, ddof=1))
    components = np.asarray(basis["components"])
    diagnostics = {
        "selected_component": "PC05",
        "selected_column_equals_fifth": bool(
            np.array_equal(selected.to_numpy(), raw.iloc[:, 4].to_numpy())
        ),
        "loading_orthogonality_max_error": float(
            np.max(np.abs(components @ components.T - np.eye(len(components))))
        ),
        "training_covariance_off_diagonal_max": float(
            np.max(np.abs(covariance - np.diag(np.diag(covariance))))
        ),
        "pc5_training_mean": float(raw.loc[training.index, "PC05"].mean()),
        "pc5_training_std_population": float(
            raw.loc[training.index, "PC05"].std(ddof=0)
        ),
        "pc5_z_training_std_population": float(
            standardized.loc[training.index, "PC05"].std(ddof=0)
        ),
        "pc5_explained_variance_ratio": basis["explained_variance_ratio"][4],
        "retained_explained_variance_ratio": float(
            sum(basis["explained_variance_ratio"])
        ),
        "pc5_near_degenerate": basis["pc5_near_degenerate"],
    }
    if dataset.get("previous_pc5"):
        previous_path = ROOT / dataset["previous_pc5"]
        sources.append(source_info(previous_path, dataset.get("previous_pc5_git_blob")))
        previous = pd.read_csv(previous_path, index_col="date", parse_dates=True)[
            "PC5_raw"
        ]
        if previous.index.has_duplicates or set(previous.index) != set(selected.index):
            raise ValueError("Legacy PC5 keys differ from the extracted series")
        old = previous.reindex(selected.index).to_numpy(dtype=np.float64)
        if not np.isfinite(old).all():
            raise ValueError("Legacy PC5 contains nonfinite values")
        sign = 1 if np.dot(old, selected) >= 0 else -1
        diagnostics["legacy_sign_alignment"] = sign
        diagnostics["legacy_pc5_max_abs_error_after_sign_alignment"] = float(
            np.max(np.abs(sign * selected - old))
        )
    if dataset.get("previous_variance"):
        previous_path = ROOT / dataset["previous_variance"]
        sources.append(
            source_info(previous_path, dataset.get("previous_variance_git_blob"))
        )
        previous = pd.read_csv(previous_path)
        old = float(
            previous.set_index("Component").loc["PC5", "Explained_Variance_Ratio"]
        )
        diagnostics["previous_report_pc5_explained_variance_ratio"] = old
        diagnostics["variance_ratio_difference_from_previous_report"] = (
            basis["explained_variance_ratio"][4] - old
        )
    return {
        "config": dataset,
        "basis": basis,
        "raw": raw,
        "standardized": standardized,
        "selected": selected,
        "identities": identities,
        "sources": sources,
        "provenance": provenance,
        "diagnostics": diagnostics,
    }


def write_dataset(prepared: dict[str, Any], output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    basis, raw = prepared["basis"], prepared["raw"]
    identities = prepared["identities"]
    identities.join(prepared["selected"]).to_csv(
        output / "pc5_raw.csv", float_format="%.17g", lineterminator="\n"
    )
    selected = identities.join(raw[["PC05"]])
    selected["PC05_z"] = prepared["standardized"]["PC05"]
    selected["pca_version"] = basis["pca_version"]
    selected.to_csv(
        output / "pc5_scores.csv", float_format="%.17g", lineterminator="\n"
    )
    identities.join(raw).to_csv(
        output / "all_pcs.csv", float_format="%.17g", lineterminator="\n"
    )
    loadings = pd.DataFrame(
        np.asarray(basis["components"]).T,
        index=pd.Index(basis["feature_columns"], name="feature"),
        columns=raw.columns,
    )
    loadings.to_csv(
        output / "pca_loadings.csv", float_format="%.17g", lineterminator="\n"
    )
    pc5_loadings = loadings[["PC05"]].rename(columns={"PC05": "loading"})
    pc5_loadings["absolute_loading"] = pc5_loadings["loading"].abs()
    pc5_loadings.sort_values("absolute_loading", ascending=False, kind="stable").to_csv(
        output / "pc5_loadings.csv", float_format="%.17g", lineterminator="\n"
    )
    variance = pd.DataFrame(
        {
            "component": raw.columns,
            "eigenvalue": basis["explained_variance"],
            "explained_variance_ratio": basis["explained_variance_ratio"],
            "cumulative_variance_ratio": np.cumsum(basis["explained_variance_ratio"]),
        }
    )
    variance.to_csv(
        output / "explained_variance.csv",
        index=False,
        float_format="%.17g",
        lineterminator="\n",
    )
    save_pc5_basis(basis, output / "pca_basis.json")
    write_json(output / "checks.json", prepared["diagnostics"])
    return {
        "id": prepared["config"]["id"],
        "rows": len(raw),
        "features": len(basis["feature_columns"]),
        "retained_components": basis["n_components"],
        "pca_version": basis["pca_version"],
        "fit_end": prepared["config"].get("fit_end"),
        "training_rows": basis["n_training_rows"],
        "sources": prepared["sources"],
        "provenance": prepared["provenance"],
        "diagnostics": prepared["diagnostics"],
        "limitations": prepared["config"].get("limitations", []),
    }


def write_figure(prepared: dict[str, Any], output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    basis = prepared["basis"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    ratios = np.asarray(basis["explained_variance_ratio"]) * 100
    colors = ["#2b667b"] * len(ratios)
    colors[4] = "#cc7139"
    axes[0].bar(np.arange(1, len(ratios) + 1), ratios, color=colors)
    axes[0].set(
        xlabel="Principal component",
        ylabel="Explained variance (%)",
        title="Fifth component selected",
    )
    axes[0].set_xticks(np.arange(1, len(ratios) + 1))
    axes[1].hist(prepared["selected"], bins=24, color="#2b667b", edgecolor="white")
    axes[1].set(
        xlabel="PC05 raw score (PCA units)",
        ylabel="Observations",
        title="PC05 score distribution",
    )
    vector = np.asarray(basis["components"])[4]
    top = np.argsort(np.abs(vector), kind="stable")[-10:]
    axes[2].barh(
        [basis["feature_columns"][i] for i in top], vector[top], color="#cc7139"
    )
    axes[2].set(
        xlabel="Loading (unit-length direction)", title="Largest absolute PC05 loadings"
    )
    fig.suptitle(
        prepared["config"]["id"] + " | descriptive extraction, no return estimate"
    )
    fig.tight_layout()
    fig.savefig(output, dpi=220)
    plt.close(fig)


def run_extraction(config_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("selected_component") != 5:
        raise ValueError("This assignment selects component 5")
    datasets = config["datasets"]
    ids = [item["id"] for item in datasets]
    if (
        not ids
        or len(ids) != len(set(ids))
        or any(not re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in ids)
    ):
        raise ValueError("Dataset IDs must be unique and path-safe")
    prepared = [prepare_dataset(dataset) for dataset in datasets]
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for result in prepared:
        directory = output / result["config"]["id"]
        results.append(write_dataset(result, directory))
        write_figure(result, directory / "pc5_summary.png")
    write_json(output / "config_snapshot.json", config)
    manifest = {
        "schema_version": 1,
        "status": "PC5_EXTRACTION_COMPLETE_DESCRIPTIVE_ONLY",
        "source_repository": config["source_repository"],
        "source_commit": config["source_commit"],
        "selected_component": 5,
        "datasets": results,
        "config_sha256": source_info(config_path)["sha256"],
        "implementation": [
            source_info(ROOT / path)
            for path in (
                "src/pricing/pc5_component.py",
                "scripts/extract_pc5.py",
                "scripts/day2_pca_extraction.py",
            )
        ],
        "versions": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "performance_evaluation": "NOT_RUN_NO_POINT_IN_TIME_PANEL",
        "stable_output_replacement": False,
        "system_did_not_order": True,
    }
    lines = [
        "# PC5（第五主成分）交付结果",
        "",
        "状态：提取完成；描述性结果，不代表策略有效或真实历史回测。",
        "",
        "按负责人指定选择第5主成分，统一列名 PC05。PC5_raw 为原始得分别名，PC05_z 为拟合样本尺度标准化得分。",
        "",
        "| 输入 | 行数 | 因子数 | 保留PC数 | PC5解释率 |",
        "|---|---:|---:|---:|---:|",
    ]
    for result in results:
        lines.append(
            f"| {result['id']} | {result['rows']} | {result['features']} | {result['retained_components']} | {result['diagnostics']['pc5_explained_variance_ratio']:.6%} |"
        )
    lines += [
        "",
        "## 方法和交付",
        "",
        "对原始特征做拟合样本中心化和总体标准差缩放，执行完整 SVD，按特征值从大到小取第5维。最大绝对载荷固定为正，保存完整基底和尺度。方差解释率是特征空间的解释比例，不是收益率或预测准确率。",
        "",
        "每个子目录包含 pc5_raw.csv、pc5_scores.csv、all_pcs.csv、pc5_loadings.csv、pca_loadings.csv、explained_variance.csv、pca_basis.json、checks.json 和 220dpi 图。",
        "",
        "PC5 的原始标准差不必等于1；只有 PC05_z 在拟合样本上按总体标准差归一。符号反转不改变主成分含义，跨版本使用必须同时匹配基底、得分及系数。近重根时PC编号可能不稳定，检查checks与basis中的标记。",
        "",
    ]
    for result in results:
        lines += [f"## {result['id']} 的限制与核对", ""]
        lines += ["- " + item for item in result["limitations"]]
        diagnostic = result["diagnostics"]
        if "legacy_pc5_max_abs_error_after_sign_alignment" in diagnostic:
            lines += [
                f"- 与 GitHub 旧 PC5 的符号对齐后最大绝对误差：{diagnostic['legacy_pc5_max_abs_error_after_sign_alignment']:.3e}。"
            ]
        if "variance_ratio_difference_from_previous_report" in diagnostic:
            lines += [
                f"- 与旧768维报告PC5解释率的差值：{diagnostic['variance_ratio_difference_from_previous_report']:.3e}；旧脚本采用auto求解器并在尺度中加1e-8，本次固定full SVD及标准缩放。"
            ]
        lines += [""]
    (output / "README.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    manifest["artifacts_sha256"] = {
        str(path.relative_to(output)).replace("\\", "/"): source_info(path)["sha256"]
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    write_json(output / "run_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "config/experiments/pc5_component.json"
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir or ROOT / "data/processed/pc5_component" / datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        manifest = run_extraction(args.config.resolve(), output.resolve())
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"PC5_EXTRACTION_FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"status={manifest['status']}\noutput={output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
