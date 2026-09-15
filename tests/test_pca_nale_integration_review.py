# -*- coding: utf-8 -*-
"""tests/test_pca_nale_integration_review.py —— M5 独立复核（跨模块一致性 + 时间往返 + 手算 + 梯度校验）。

本文件刻意**不复用** M2/M3/M4 测试的夹具，独立重建最小数据，避免"同一份夹具证明同一件事"。
覆盖：
  1. 跨模块一致性：M4 CLI 的 `alpha_0.00` 得分 ≡ M2 面板 `S0` ≡ 直接调用 M1 权威传播核在 α=0 的结果；
  2. CLI 级时间往返：改动首个应用信号日之后的数据，此前的 S0/网络诊断/变体得分必须逐位不变；
     并证明"标签"确实随未来数据变化（标签是目标，不是信号）；
  3. 口径复核点时冻结：用 spy 截获 `compute_return_basis` 收到的 verification，确认窗口止于冻结日；
  4. 手算传播与去边敏感性（独立于 M3 用例的数值）；
  5. 门控目标函数与解析梯度的中心差分校验 + theta=0 时的闭式损失值；
  6. 产物隔离：同 run_id 二次运行在任何文件写出之前就被拒绝。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import evaluate_pca_nale_integration as cli
from scripts.evaluate_pca_nale_integration import (
    EvaluationConfig,
    EvaluationError,
    run_evaluation,
)
from src.graph.nale_alpha_adapter import propagate_nale_vectorized
from src.graph.pca_nale_networks import (
    CORRELATION_RELATION,
    NetworkConfig,
    build_network,
    edge_removal_sensitivity,
)
from src.pricing.nale_alpha_models import B0Calibration, gate_loss_and_gradient

CALENDAR = tuple(pd.bdate_range("2024-01-01", periods=70).strftime("%Y-%m-%d"))
FEATURES = (
    "mom_5d", "mom_20d", "mom_60d", "vol_20d", "vol_60d", "turnover_20d",
    "amihud", "price_pos", "amplitude", "gap", "hit_limit", "abnormal_trd",
)


def _independent_inputs(root: Path, codes: int = 22, seed: int = 99) -> dict[str, Path]:
    """独立重建最小输入（与其它测试文件不共享夹具）。"""
    rng = np.random.default_rng(seed)
    code_list = [f"{index:06d}" for index in range(10, 10 + codes)]
    rows = []
    for position, code in enumerate(code_list):
        price = 5.0 + 0.5 * position
        for step, date in enumerate(CALENDAR):
            price *= 1.0 + float(rng.normal(0.0002, 0.011))
            rows.append(
                {
                    "stock_code": code,
                    "trade_date": date,
                    "close": round(price, 4),
                    "volume": float(2e6 + 1000 * step),
                    "turnover_rate": float(0.012 + 0.00005 * step),
                    "market_value": 2e9 * (1.0 + 0.05 * position) * (1.0 + 0.0015 * step),
                    "ret": float(rng.normal(0.0002, 0.011)),
                }
            )
    panel = pd.DataFrame(rows)
    for column_index, column in enumerate(FEATURES):
        panel[column] = [
            rng.normal(0.0, 1.0) if False else float(
                np.sin((int(code) % 7) + step / 5.0) + 0.02 * column_index
            )
            for code, step in zip(panel["stock_code"], panel.groupby("stock_code").cumcount())
        ]
    panel.loc[panel["trade_date"] < CALENDAR[8], "mom_60d"] = np.nan

    factors = root / "factors.csv"
    pd.DataFrame({"code": code_list, "cohort_key": ["student_A"] * len(code_list)}).to_csv(factors, index=False)
    universe = root / "universe.csv"
    pd.DataFrame(
        {
            "code": code_list,
            "sub_industry": ["有色" if index < len(code_list) // 2 else "医药" for index in range(len(code_list))],
        }
    ).to_csv(universe, index=False)
    panel_path = root / "panel.csv"
    panel.to_csv(panel_path, index=False)
    caliber = root / "caliber.json"
    caliber.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cohorts": {
                    "student_A": {
                        "close_basis": "unadjusted",
                        "source_table": "synthetic-review",
                        "adjustment": "none_price_is_Clsprc_unadjusted",
                        "provenance": "tests/test_pca_nale_integration_review.py",
                        "total_return_available": True,
                        "total_return_column": "ret",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    corpus = root / "corpus"
    corpus.mkdir(exist_ok=True)
    for code in code_list:
        (corpus / f"{code}.jsonl").write_text(
            json.dumps(
                {"item_type": "announcement", "title": "t", "content": "c",
                 "publish_time": f"{CALENDAR[30]} 09:30:00"},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    return {"panel": panel_path, "factors": factors, "universe": universe, "caliber": caliber, "corpus": corpus}


def _review_config(run_id: str, **overrides) -> EvaluationConfig:
    params = dict(
        run_id=run_id,
        domain="A",
        networks=("W-ind",),
        labels=(5,),
        alpha_grid=(0.05,),
        signal_step=5,
        train_window_days=10,
        min_train_rows=40,
        min_cross_section=12,
        start_index=20,
        first_apply_index=45,
        max_signal_dates=2,
        bootstrap_reps=30,
        block_trading_days=(10,),
        gate_versions=("V1",),
        gate_min_train_dates=2,
    )
    params.update(overrides)
    return EvaluationConfig(**params)


# ---------------------------------------------------------------------------
# 1. 跨模块一致性
# ---------------------------------------------------------------------------

def _aligned_scores(processed: Path, variant: str, column: str = "S0") -> pd.DataFrame:
    """把某变体得分与面板列按 (stock_code, signal_date) 对齐（与行序无关）。"""
    scores = pd.read_csv(processed / "variant_scores.csv.gz", dtype={"stock_code": str})
    asof = pd.read_csv(processed / "asof_panel.csv.gz", dtype={"stock_code": str})
    left = (
        scores[scores["variant"] == variant]
        .loc[:, ["stock_code", "signal_date", "score"]]
        .drop_duplicates(["stock_code", "signal_date"])
    )
    right = (
        asof[asof["is_available"]]
        .loc[:, ["stock_code", "signal_date", column]]
        .drop_duplicates(["stock_code", "signal_date"])
    )
    merged = left.merge(right, on=["stock_code", "signal_date"], how="inner", validate="one_to_one")
    return merged.sort_values(["signal_date", "stock_code"]).reset_index(drop=True)


def test_alpha_zero_equals_panel_s0_and_direct_kernel_call(tmp_path: Path) -> None:
    paths = _independent_inputs(tmp_path)
    run_evaluation(_review_config("review-identity"), paths=paths, root=tmp_path, verbose=False)
    processed = tmp_path / "data/processed/pca_nale_integration/review-identity"
    merged = _aligned_scores(processed, "alpha_0.00")

    assert len(merged) == merged[["stock_code", "signal_date"]].drop_duplicates().shape[0]
    assert merged["S0"].notna().all()
    assert np.array_equal(merged["score"].to_numpy(), merged["S0"].to_numpy())

    # 第三条独立路径：α=0 时权威核必须给出 S ≡ S0（单位阵图）
    kernel_scores, _, _ = propagate_nale_vectorized(
        merged["S0"].to_numpy(), np.eye(len(merged)), 0.0
    )
    assert np.array_equal(kernel_scores, merged["S0"].to_numpy())


def test_b0_variant_equals_kernel_with_the_same_industry_network(tmp_path: Path) -> None:
    """跨模块一致性：M4 的 b0 得分 ≡ 用 M3 重建同一 W-ind 网络 + M1 权威核传播面板 S0。"""
    paths = _independent_inputs(tmp_path)
    run_evaluation(_review_config("review-kernel"), paths=paths, root=tmp_path, verbose=False)
    processed = tmp_path / "data/processed/pca_nale_integration/review-kernel"
    merged = _aligned_scores(processed, "b0_alpha_0.40")
    signal_date = str(merged["signal_date"].max())
    rows = merged[merged["signal_date"] == signal_date].sort_values("stock_code").reset_index(drop=True)
    codes = tuple(rows["stock_code"].tolist())
    industries = dict(zip(
        pd.read_csv(paths["universe"], dtype=str)["code"],
        pd.read_csv(paths["universe"], dtype=str)["sub_industry"],
    ))
    returns = pd.DataFrame(
        [
            {"stock_code": code, "trade_date": date, "basis_return": value}
            for code, phase in zip(codes, np.linspace(0.0, 1.0, len(codes)))
            for date, value in zip(CALENDAR, np.sin(np.arange(len(CALENDAR)) + phase) * 0.01)
        ]
    )
    build = build_network(
        codes,
        CALENDAR.index(signal_date),
        CALENDAR,
        NetworkConfig(relation_type="industry_cooccurrence"),
        industries=industries,
        returns=returns,
    )
    expected, _, _ = propagate_nale_vectorized(rows["S0"].to_numpy(), build.normalized, 0.4)

    # 跨模块一致性到机器精度：M4 走的是"诱导子图 + 重新归一化"的矩阵（内存布局不同），
    # BLAS 的求和顺序会带来 ~1e-16 级差异，属浮点非确定性而非语义差异。
    difference = np.abs(rows["score"].to_numpy() - expected)
    assert float(difference.max()) < 1e-12
    assert np.allclose(rows["score"].to_numpy(), expected, rtol=0, atol=1e-12)


# ---------------------------------------------------------------------------
# 2. CLI 级时间往返
# ---------------------------------------------------------------------------

def _run_pair(tmp_path: Path, mutate_after_index: int, run_suffix: str) -> tuple[Path, Path]:
    """跑两次（原始 / 未来被改），返回两次的 tables 目录。"""
    base = tmp_path / f"base-{run_suffix}"
    mutated = tmp_path / f"mut-{run_suffix}"
    base.mkdir()
    mutated.mkdir()
    base_paths = _independent_inputs(base)
    mut_paths = _independent_inputs(mutated)
    panel = pd.read_csv(mut_paths["panel"], dtype={"stock_code": str})
    future = panel["trade_date"] > CALENDAR[mutate_after_index]
    panel.loc[future, "close"] *= 3.0
    panel.loc[future, "market_value"] *= 4.0
    panel.loc[future, "ret"] += 0.05
    for column in FEATURES:
        panel.loc[future, column] += 7.0
    panel.to_csv(mut_paths["panel"], index=False)
    run_evaluation(_review_config(f"rt-{run_suffix}"), paths=base_paths, root=base, verbose=False)
    run_evaluation(_review_config(f"rt-{run_suffix}"), paths=mut_paths, root=mutated, verbose=False)
    return (
        base / "reports/tables/pca_nale_integration" / f"rt-{run_suffix}",
        mutated / "reports/tables/pca_nale_integration" / f"rt-{run_suffix}",
    )


def _compare_frames(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> list[str]:
    """按 keys 对齐后逐列比较，返回不一致的列名（keys 必须唯一标识行）。"""
    assert not left.duplicated(keys).any(), f"left 的比对键不唯一：{keys}"
    assert not right.duplicated(keys).any(), f"right 的比对键不唯一：{keys}"
    merged = left.merge(right, on=keys, how="inner", suffixes=("_a", "_b"))
    mismatched: list[str] = []
    for column in left.columns:
        if column in keys:
            continue
        a, b = merged[f"{column}_a"], merged[f"{column}_b"]
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            if not np.array_equal(a.to_numpy(), b.to_numpy(), equal_nan=True):
                mismatched.append(column)
        elif not a.astype(str).equals(b.astype(str)):
            mismatched.append(column)
    return mismatched


def test_products_are_bit_identical_when_only_distant_future_changes(tmp_path: Path) -> None:
    """改动远处未来（index>60）⇒ 边界 55 及以前的所有信号日产物逐位不变（含标签）。"""
    boundary = CALENDAR[55]
    base_tables, mutated_tables = _run_pair(tmp_path, mutate_after_index=60, run_suffix="far")
    base_processed = base_tables.parents[3] / "data/processed/pca_nale_integration/rt-far"
    mutated_processed = mutated_tables.parents[3] / "data/processed/pca_nale_integration/rt-far"

    keys = ["stock_code", "signal_date"]
    for name in ("asof_panel.csv.gz", "variant_scores.csv.gz"):
        left = pd.read_csv(base_processed / name, dtype={"stock_code": str})
        right = pd.read_csv(mutated_processed / name, dtype={"stock_code": str})
        compare_keys = list(keys)
        if "variant" in left.columns:
            compare_keys = ["network", "variant", *keys]
        left = left[left["signal_date"] <= boundary].reset_index(drop=True)
        right = right[right["signal_date"] <= boundary].reset_index(drop=True)
        assert left.shape == right.shape
        assert len(left) > 0
        assert _compare_frames(left, right, compare_keys) == []
    for name in ("metrics_by_variant.csv", "network_diagnostics.csv"):
        left = pd.read_csv(base_tables / name)
        right = pd.read_csv(mutated_tables / name)
        compare_keys = (
            ["signal_date", "network"] if "signal_date" in left.columns else ["network", "variant", "horizon"]
        )
        left = left.sort_values(compare_keys).reset_index(drop=True)
        right = right.sort_values(compare_keys).reset_index(drop=True)
        assert _compare_frames(left, right, compare_keys) == []


def test_mutation_does_reach_the_panel_after_the_boundary(tmp_path: Path) -> None:
    """反向守卫：同一改动**必须**改变边界之后的信号日，否则上面的"逐位不变"是假绿灯。"""
    boundary = CALENDAR[55]
    base_tables, mutated_tables = _run_pair(tmp_path, mutate_after_index=60, run_suffix="guard")
    base_processed = base_tables.parents[3] / "data/processed/pca_nale_integration/rt-guard"
    mutated_processed = mutated_tables.parents[3] / "data/processed/pca_nale_integration/rt-guard"
    left = pd.read_csv(base_processed / "asof_panel.csv.gz", dtype={"stock_code": str})
    right = pd.read_csv(mutated_processed / "asof_panel.csv.gz", dtype={"stock_code": str})
    keys = ["stock_code", "signal_date"]
    far_left = left[left["signal_date"] > boundary].reset_index(drop=True)
    far_right = right[right["signal_date"] > boundary].reset_index(drop=True)

    assert len(far_left) > 0
    assert "S0" in _compare_frames(far_left, far_right, keys)


def test_future_change_leaves_signals_untouched_but_labels_move(tmp_path: Path) -> None:
    """改动 index>50 ⇒ 边界 45 及以前的全部列逐位不变；而 index 50 的标签横跨被改区间 ⇒ 必须变。"""
    boundary = CALENDAR[45]
    mutated_from = CALENDAR[50]
    base_tables, mutated_tables = _run_pair(tmp_path, mutate_after_index=50, run_suffix="near")
    base_processed = base_tables.parents[3] / "data/processed/pca_nale_integration/rt-near"
    mutated_processed = mutated_tables.parents[3] / "data/processed/pca_nale_integration/rt-near"
    keys = ["stock_code", "signal_date"]
    left = pd.read_csv(base_processed / "asof_panel.csv.gz", dtype={"stock_code": str})
    right = pd.read_csv(mutated_processed / "asof_panel.csv.gz", dtype={"stock_code": str})
    assert _compare_frames(
        left[left["signal_date"] <= boundary].reset_index(drop=True),
        right[right["signal_date"] <= boundary].reset_index(drop=True),
        keys,
    ) == []
    # 下一个信号日：特征未变（该日不被改），但其标签落在被改区间内 ⇒ 标签必须变化
    later_left = left[left["signal_date"] == mutated_from].reset_index(drop=True)
    later_right = right[right["signal_date"] == mutated_from].reset_index(drop=True)
    assert len(later_left) > 0
    differences = _compare_frames(later_left, later_right, keys)
    assert "label_5" in differences
    assert "S0" not in differences  # 该日自身的特征与训练窗都未被改
    left_diag = pd.read_csv(base_tables / "network_diagnostics.csv")
    right_diag = pd.read_csv(mutated_tables / "network_diagnostics.csv")
    assert np.array_equal(left_diag["n_edges"].to_numpy(), right_diag["n_edges"].to_numpy())


# ---------------------------------------------------------------------------
# 3. 口径复核窗冻结（spy 截获实际传入的 verification）
# ---------------------------------------------------------------------------

def test_return_basis_receives_frozen_verification_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _independent_inputs(tmp_path)
    captured: dict[str, object] = {}
    real = cli.compute_return_basis

    def spy(panel, declarations, config=None, verification=None):
        captured["window_end"] = sorted(set(verification["verification_window_end"].tolist()))
        captured["max_panel_date"] = str(panel["trade_date"].max())
        return real(panel, declarations, config, verification)

    monkeypatch.setattr(cli, "compute_return_basis", spy)
    run_evaluation(_review_config("review-frozen"), paths=paths, root=tmp_path, verbose=False)

    assert captured["window_end"] == [CALENDAR[44]]
    assert captured["max_panel_date"] == CALENDAR[-1]  # 面板本身含未来数据，但复核结论只用冻结窗
    manifest = json.loads(
        (tmp_path / "reports/tables/pca_nale_integration/review-frozen/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["verification_frozen_at"] == CALENDAR[44]
    assert "PIT" in manifest["verification_window_rule"]


# ---------------------------------------------------------------------------
# 4. 手算传播与去边敏感性（独立数值）
# ---------------------------------------------------------------------------

def test_hand_computed_two_node_propagation() -> None:
    s0 = np.array([0.5, -0.5])
    normalized = np.array([[0.0, 1.0], [1.0, 0.0]])
    scores, neighbor, difference = propagate_nale_vectorized(s0, normalized, 0.25)

    assert neighbor.tolist() == [-0.5, 0.5]
    assert difference.tolist() == [-1.0, 1.0]
    assert scores.tolist() == [0.25, -0.25]


def test_hand_computed_edge_removal_sensitivity_on_three_nodes() -> None:
    """3 节点等权图、S0=[0,1,2]、α=0.4：手算移除一条边后的 |ΔS|。"""
    codes = ("000001", "000002", "000003")
    returns = pd.DataFrame(
        [
            {"stock_code": code, "trade_date": date, "basis_return": value}
            for code, phase in zip(codes, (0.0, 0.1, 0.7))
            for date, value in zip(CALENDAR, np.sin(np.arange(len(CALENDAR)) + phase) * 0.01)
        ]
    )
    build = build_network(
        codes, 40, CALENDAR,
        NetworkConfig(relation_type=CORRELATION_RELATION, window=30, corr_threshold=0.0, min_overlap=10),
        returns=returns,
    )
    weights = np.ones((3, 3)) - np.eye(3)
    normalized = weights / weights.sum(axis=1, keepdims=True)
    s0 = np.array([0.0, 1.0, 2.0])
    baseline, _, _ = propagate_nale_vectorized(s0, normalized, 0.4)

    manual_pruned = weights.copy()
    manual_pruned[0, 1] = manual_pruned[1, 0] = 0.0
    manual_norm = manual_pruned / manual_pruned.sum(axis=1, keepdims=True)
    manual, _, _ = propagate_nale_vectorized(s0, manual_norm, 0.4)

    table = edge_removal_sensitivity(
        type(build)(
            relation_type=build.relation_type, codes=build.codes, signal_index=40,
            signal_date=CALENDAR[40], weights=weights, normalized=normalized,
            diagnostics={}, config=build.config, spec=build.spec,
        ),
        s0, alpha=0.4, fractions=(0.34,),
    )
    assert int(table.loc[0, "edges_removed"]) == 1
    assert float(table.loc[0, "max_abs_delta"]) == pytest.approx(float(np.abs(manual - baseline).max()), abs=1e-15)
    assert float(table.loc[0, "max_abs_delta"]) > 0.0


# ---------------------------------------------------------------------------
# 5. 门控目标函数：闭式损失 + 中心差分梯度
# ---------------------------------------------------------------------------

def _gate_inputs(seed: int = 5, size: int = 40):
    rng = np.random.default_rng(seed)
    z = rng.normal(size=(size, 10))
    s0 = rng.normal(scale=0.2, size=size)
    difference = rng.normal(scale=0.1, size=size)
    y = rng.normal(scale=0.02, size=size)
    weights = np.full(size, 1.0 / size)
    calibration = B0Calibration(
        intercept=0.0005, slope=0.6, fit_cutoff="2025-04-01T00:00:00+08:00",
        n_signal_dates=3, n_rows=size,
    )
    return z, s0, difference, y, weights, calibration


def test_gate_loss_at_zero_theta_matches_closed_form() -> None:
    z, s0, difference, y, weights, calibration = _gate_inputs()
    theta = np.zeros(11)
    loss, gradient = gate_loss_and_gradient(
        theta, z=z, s0=s0, difference=difference, y=y,
        calibration=calibration, sample_weights=weights, ridge_lambda=0.5,
    )

    # 手算：θ=0 ⇒ α ≡ 0.05 + 0.70·sigmoid(0) = 0.40；无 ridge 惩罚（θ[1:] 全 0）
    alpha = 0.05 + 0.70 * 0.5
    prediction = calibration.intercept + calibration.slope * (s0 + alpha * difference)
    residual = prediction - y
    expected = float(np.sum(weights * residual**2))
    assert loss == pytest.approx(expected, rel=1e-12)
    assert gradient.shape == (11,)


def test_gate_gradient_matches_central_differences() -> None:
    z, s0, difference, y, weights, calibration = _gate_inputs(seed=17)
    rng = np.random.default_rng(23)
    theta = rng.normal(scale=0.05, size=11)

    def objective(candidate: np.ndarray) -> float:
        value, _ = gate_loss_and_gradient(
            candidate, z=z, s0=s0, difference=difference, y=y,
            calibration=calibration, sample_weights=weights, ridge_lambda=0.8,
        )
        return float(value)

    _, analytic = gate_loss_and_gradient(
        theta, z=z, s0=s0, difference=difference, y=y,
        calibration=calibration, sample_weights=weights, ridge_lambda=0.8,
    )
    step = 1e-6
    numeric = np.empty(11)
    for index in range(11):
        bump = np.zeros(11)
        bump[index] = step
        numeric[index] = (objective(theta + bump) - objective(theta - bump)) / (2 * step)

    assert np.allclose(analytic, numeric, rtol=1e-5, atol=1e-7)


# ---------------------------------------------------------------------------
# 6. 产物隔离：拒绝发生在任何写出之前
# ---------------------------------------------------------------------------

def test_refusal_happens_before_any_file_is_written(tmp_path: Path) -> None:
    paths = _independent_inputs(tmp_path)
    run_evaluation(_review_config("review-isolation"), paths=paths, root=tmp_path, verbose=False)
    tables = tmp_path / "reports/tables/pca_nale_integration/review-isolation"
    before = sorted(path.name for path in tables.iterdir())

    with pytest.raises(EvaluationError, match="拒绝就地覆盖"):
        run_evaluation(_review_config("review-isolation"), paths=paths, root=tmp_path, verbose=False)
    after = sorted(path.name for path in tables.iterdir())
    assert before == after
    assert "manifest.json" in after


def test_report_never_hides_isolated_nodes(tmp_path: Path) -> None:
    """覆盖率与孤立点必须落在产物里（W-attn 实测会孤立，不得只报平均 IC）。"""
    paths = _independent_inputs(tmp_path)
    run_evaluation(
        _review_config("review-coverage", networks=("W-attn",)), paths=paths, root=tmp_path, verbose=False
    )
    tables = tmp_path / "reports/tables/pca_nale_integration/review-coverage"
    diagnostics = pd.read_csv(tables / "network_diagnostics.csv")
    manifest = json.loads((tables / "manifest.json").read_text(encoding="utf-8"))
    report = (tables / "report.md").read_text(encoding="utf-8")

    assert {"node_coverage", "isolated_nodes"} <= set(diagnostics.columns)
    assert "W-attn" in manifest["network_coverage"]
    assert "孤立点" in report
    assert diagnostics["isolated_nodes"].notna().all()