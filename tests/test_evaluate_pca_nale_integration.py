# -*- coding: utf-8 -*-
"""tests/test_evaluate_pca_nale_integration.py —— M4 走步评测 CLI 回归。

覆盖：run_id 隔离与拒绝覆盖、口径复核点时冻结、IC 手算、区块 bootstrap 确定性与区块敏感性、
Holm 单调性、显式计费、无年化字段守卫、同数据同切分、α=0 恒等、NOT_EVALUABLE 并列、
动态门控的可识别性记录、合成面板端到端跑通（产物落在 tmp 根下，不碰真实数据目录）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.evaluate_pca_nale_integration import (
    EVAL_VERSION,
    EvaluationConfig,
    EvaluationError,
    block_bootstrap_interval,
    build_parser,
    config_from_args,
    cross_sectional_ic,
    directory_inventory_sha256,
    frozen_verification,
    guard_field_names,
    holm_adjust,
    ic_summary,
    leg_turnover,
    long_short_period_returns,
    normal_two_sided_p,
    permuted_network,
    resolve_output_dirs,
    run_evaluation,
    trading_days_to_signal_blocks,
    validate_run_id,
)
from src.graph.pca_nale_networks import NOT_EVALUABLE_NETWORKS

CALENDAR = tuple(pd.bdate_range("2024-01-01", periods=60).strftime("%Y-%m-%d"))
FEATURES = (
    "mom_5d", "mom_20d", "mom_60d", "vol_20d", "vol_60d", "turnover_20d",
    "amihud", "price_pos", "amplitude", "gap", "hit_limit", "abnormal_trd",
)


# ---------------------------------------------------------------------------
# 合成输入（端到端用；完全不碰真实数据目录）
# ---------------------------------------------------------------------------

def _synthetic_inputs(root: Path, codes: int = 24, seed: int = 3) -> dict[str, Path]:
    """造一套最小可跑的输入：面板 / 分组 / 行业 / 口径声明 / 语料。"""
    rng = np.random.default_rng(seed)
    code_list = [f"{index:06d}" for index in range(1, codes + 1)]
    rows = []
    for position, code in enumerate(code_list):
        price = 10.0 + position
        for step, date in enumerate(CALENDAR):
            price *= 1.0 + float(rng.normal(0.0004, 0.012))
            rows.append(
                {
                    "stock_code": code,
                    "trade_date": date,
                    "close": round(price, 4),
                    "volume": float(1e6 * (1.0 + 0.01 * step)),
                    "turnover_rate": float(0.01 + 0.0001 * step),
                    "market_value": 1e9 * (1.0 + 0.1 * position) * (1.0 + 0.002 * step),
                    "ret": float(rng.normal(0.0004, 0.012)),
                }
            )
    panel = pd.DataFrame(rows)
    feature_base = {code: rng.normal(0.0, 1.0, size=len(FEATURES)) for code in code_list}
    for column_index, column in enumerate(FEATURES):
        panel[column] = [
            feature_base[code][column_index] + 0.01 * (int(date[-2:]) % 13)
            for code, date in zip(panel["stock_code"], panel["trade_date"])
        ]
    # 前 10 天让部分技术因子缺失（预热），验证可用性过滤确实生效
    warmup = panel["trade_date"] < CALENDAR[10]
    panel.loc[warmup, "mom_60d"] = np.nan

    factors_path = root / "factors.csv"
    pd.DataFrame(
        {"code": code_list, "cohort_key": ["student_A"] * len(code_list)}
    ).to_csv(factors_path, index=False)
    universe_path = root / "universe.csv"
    pd.DataFrame(
        {
            "code": code_list,
            "sub_industry": ["银行" if index % 2 == 0 else "白酒" for index in range(len(code_list))],
        }
    ).to_csv(universe_path, index=False)
    panel_path = root / "panel.csv"
    panel.to_csv(panel_path, index=False)

    caliber_path = root / "caliber.json"
    caliber_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "panel": "panel.csv",
                "cohorts": {
                    "student_A": {
                        "close_basis": "unadjusted",
                        "source_table": "synthetic",
                        "adjustment": "none_price_is_Clsprc_unadjusted",
                        "provenance": "tests/test_evaluate_pca_nale_integration.py",
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
        records = [
            {"item_type": "announcement", "title": "t", "content": "c",
             "publish_time": f"{CALENDAR[20 + index]} 10:00:00"}
            for index in range(3)
        ]
        (corpus / f"{code}.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in records), encoding="utf-8"
        )
    return {
        "panel": panel_path,
        "factors": factors_path,
        "universe": universe_path,
        "caliber": caliber_path,
        "corpus": corpus,
    }


def _smoke_config(run_id: str, **overrides) -> EvaluationConfig:
    params = dict(
        run_id=run_id,
        domain="A",
        feature_family="price_technical_v1",
        networks=("W-ind",),
        labels=(5,),
        alpha_grid=(0.05, 0.40),
        signal_step=5,
        train_window_days=10,
        min_train_rows=50,
        min_cross_section=15,
        start_index=20,
        first_apply_index=45,
        max_signal_dates=2,
        bootstrap_reps=50,
        block_trading_days=(10,),
        gate_versions=("V1",),
        gate_min_train_dates=2,
        placebo_networks=("W-ind",),
    )
    params.update(overrides)
    return EvaluationConfig(**params)


# ---------------------------------------------------------------------------
# 1. run_id 隔离与字段守卫
# ---------------------------------------------------------------------------

def test_run_id_is_required_and_validated() -> None:
    assert validate_run_id("m4-run_1.0") == "m4-run_1.0"
    for bad in ("", "   ", "../escape", "a/b", "a\\b", ".."):
        with pytest.raises(EvaluationError):
            validate_run_id(bad)


def test_output_dirs_are_run_scoped_and_refuse_overwrite(tmp_path: Path) -> None:
    dirs = resolve_output_dirs("m4-test", root=tmp_path)

    assert set(dirs) == {"processed", "tables", "figures"}
    for path in dirs.values():
        assert path.name == "m4-test"
        assert tmp_path in path.parents
        assert path.parent.name == "pca_nale_integration"
    dirs["tables"].mkdir(parents=True)
    with pytest.raises(EvaluationError, match="拒绝就地覆盖"):
        resolve_output_dirs("m4-test", root=tmp_path)


def test_empty_run_id_is_rejected_by_config() -> None:
    with pytest.raises(EvaluationError, match="run-id"):
        _smoke_config("")


def test_field_name_guard_rejects_annualised_metrics() -> None:
    guard_field_names(["mean_ic", "t_stat", "mean_period_return"])
    with pytest.raises(EvaluationError, match="年化"):
        guard_field_names(["annualised_sharpe"])
    with pytest.raises(EvaluationError, match="年化"):
        guard_field_names(["icir_ANNUALIZED"])


def test_directory_inventory_hash_is_stable_and_order_independent(tmp_path: Path) -> None:
    (tmp_path / "b.jsonl").write_text("bb", encoding="utf-8")
    (tmp_path / "a.jsonl").write_text("a", encoding="utf-8")
    first = directory_inventory_sha256(tmp_path)

    assert first is not None
    (tmp_path / "c.jsonl").write_text("c", encoding="utf-8")
    assert directory_inventory_sha256(tmp_path) != first
    assert directory_inventory_sha256(tmp_path / "missing") is None


# ---------------------------------------------------------------------------
# 2. 口径复核点时冻结
# ---------------------------------------------------------------------------

def test_frozen_verification_ignores_future_data(tmp_path: Path) -> None:
    paths = _synthetic_inputs(tmp_path)
    from scripts.audit_return_basis import build_declarations

    panel = pd.read_csv(paths["panel"], dtype={"stock_code": str})
    declarations = build_declarations(paths["caliber"], paths["factors"])
    freeze = CALENDAR[24]
    baseline = frozen_verification(panel, declarations, freeze)

    mutated = panel.copy()
    future = mutated["trade_date"] > freeze
    mutated.loc[future, "close"] *= 1.5
    mutated.loc[future, "market_value"] *= 2.0
    after = frozen_verification(mutated, declarations, freeze)

    assert baseline["verification_window_end"].unique().tolist() == [freeze]
    assert baseline["verdict"].tolist() == after["verdict"].tolist()
    assert np.allclose(
        baseline["n_beyond_limit"].to_numpy(), after["n_beyond_limit"].to_numpy()
    )


def test_frozen_verification_rejects_empty_window(tmp_path: Path) -> None:
    paths = _synthetic_inputs(tmp_path)
    from scripts.audit_return_basis import build_declarations

    panel = pd.read_csv(paths["panel"], dtype={"stock_code": str})
    declarations = build_declarations(paths["caliber"], paths["factors"])
    with pytest.raises(EvaluationError, match="没有任何数据"):
        frozen_verification(panel, declarations, "2000-01-01")


# ---------------------------------------------------------------------------
# 3. IC 与汇总（手算）
# ---------------------------------------------------------------------------

def test_cross_sectional_ic_hand_computed() -> None:
    scores = pd.Series([1.0, 2.0, 3.0, 4.0])
    labels = pd.Series([0.01, 0.02, 0.03, 0.04])
    perfect = cross_sectional_ic(scores, labels, min_stocks=4)

    assert perfect["pearson"] == pytest.approx(1.0)
    assert perfect["spearman"] == pytest.approx(1.0)
    assert perfect["n_stocks"] == 4
    assert perfect["excluded"] is False

    inverse = cross_sectional_ic(scores, -labels, min_stocks=4)
    assert inverse["pearson"] == pytest.approx(-1.0)
    assert inverse["spearman"] == pytest.approx(-1.0)


def test_cross_sectional_ic_excludes_small_or_incomplete_cross_sections() -> None:
    scores = pd.Series([1.0, 2.0, 3.0])
    labels = pd.Series([0.01, np.nan, 0.03])
    stats = cross_sectional_ic(scores, labels, min_stocks=20)

    assert stats["excluded"] is True
    assert stats["n_stocks"] == 2
    assert math.isnan(stats["pearson"])
    assert math.isnan(stats["spearman"])


def test_ic_summary_is_not_annualised_and_hand_computed() -> None:
    summary = ic_summary([0.1, 0.2, 0.3, 0.4])

    mean = 0.25
    std = float(pd.Series([0.1, 0.2, 0.3, 0.4]).std(ddof=1))
    assert summary["n_days"] == 4
    assert summary["mean_ic"] == pytest.approx(mean)
    assert summary["std_ic"] == pytest.approx(std)
    assert summary["icir"] == pytest.approx(mean / std)
    assert summary["t_stat"] == pytest.approx(mean / (std / np.sqrt(4)))
    # ICIR 就是把均值除以标准差，不含任何 252/√252 之类的年化因子
    assert summary["icir"] * std == pytest.approx(summary["mean_ic"])


def test_ic_summary_handles_degenerate_inputs() -> None:
    empty = ic_summary([])

    assert empty["n_days"] == 0
    assert math.isnan(empty["mean_ic"])
    constant = ic_summary([0.5, 0.5, 0.5])
    assert constant["mean_ic"] == pytest.approx(0.5)
    assert constant["std_ic"] == pytest.approx(0.0)
    assert math.isnan(constant["icir"])
    assert math.isnan(constant["t_stat"])


# ---------------------------------------------------------------------------
# 4. 区块 bootstrap
# ---------------------------------------------------------------------------

def test_block_bootstrap_is_deterministic_and_block_sensitive() -> None:
    values = np.sin(np.arange(40) / 3.0) * 0.01 + 0.02
    first = block_bootstrap_interval(values, block_length=2, reps=500, seed=42)
    second = block_bootstrap_interval(values, block_length=2, reps=500, seed=42)
    other_block = block_bootstrap_interval(values, block_length=8, reps=500, seed=42)

    assert first == second
    assert first["point_mean"] == pytest.approx(float(np.mean(values)))
    assert first["ci_low"] < first["point_mean"] < first["ci_high"]
    assert first["block_length_signal_dates"] == 2
    # 区块越长，重采样均值的方差越大（区块内相关性被保留）
    assert other_block["bootstrap_std"] > first["bootstrap_std"]
    assert other_block["block_length_signal_dates"] == 8


def test_block_bootstrap_rejects_bad_inputs() -> None:
    with pytest.raises(EvaluationError, match="为空"):
        block_bootstrap_interval([np.nan], block_length=1)
    with pytest.raises(EvaluationError, match="block_length"):
        block_bootstrap_interval([0.1, 0.2], block_length=0)
    with pytest.raises(EvaluationError, match="次数"):
        block_bootstrap_interval([0.1, 0.2], block_length=1, reps=0)
    with pytest.raises(EvaluationError, match="confidence"):
        block_bootstrap_interval([0.1, 0.2], block_length=1, confidence=1.0)


def test_trading_days_to_signal_blocks_conversion() -> None:
    assert trading_days_to_signal_blocks(10, 5) == 2
    assert trading_days_to_signal_blocks(10, 3) == 4
    assert trading_days_to_signal_blocks(10, 20) == 1
    assert trading_days_to_signal_blocks(40, 5) == 8
    with pytest.raises(EvaluationError, match="signal step"):
        trading_days_to_signal_blocks(10, 0)


# ---------------------------------------------------------------------------
# 5. Holm 校正与 p 值
# ---------------------------------------------------------------------------

def test_holm_adjust_hand_computed_and_monotone() -> None:
    adjusted = holm_adjust([0.01, 0.04, 0.03, 0.5])

    assert adjusted == pytest.approx([0.04, 0.09, 0.09, 0.5])
    raw = [0.01, 0.04, 0.03, 0.5]
    assert all(adj >= value - 1e-12 for adj, value in zip(adjusted, raw))
    assert all(adj <= 1.0 for adj in adjusted)
    assert holm_adjust([np.nan, 0.02]) == pytest.approx([np.nan, 0.02], nan_ok=True)


def test_normal_two_sided_p_hand_computed() -> None:
    assert normal_two_sided_p(0.0) == pytest.approx(1.0)
    assert normal_two_sided_p(1.959964) == pytest.approx(0.05, abs=1e-5)
    assert math.isnan(normal_two_sided_p(float("nan")))


# ---------------------------------------------------------------------------
# 6. 组合口径与计费
# ---------------------------------------------------------------------------

def test_leg_turnover_hand_computed() -> None:
    assert leg_turnover([], ["a", "b"]) == pytest.approx(1.0)
    assert leg_turnover(["a", "b"], ["a", "b"]) == pytest.approx(0.0)
    assert leg_turnover(["a", "b"], ["a", "c"]) == pytest.approx(0.5)
    assert leg_turnover(["a", "b"], ["c", "d"]) == pytest.approx(1.0)


def test_long_short_returns_hand_computed_with_explicit_cost() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": [CALENDAR[0]] * 20 + [CALENDAR[1]] * 20,
            "stock_code": [f"{index:06d}" for index in range(1, 21)] * 2,
            "score": list(range(20, 0, -1)) + list(range(20, 0, -1)),
            "label": [0.01 * index for index in range(20, 0, -1)] * 2,
        }
    )
    free = long_short_period_returns(
        frame, score_column="score", label_column="label", cost_bps=0.0, min_leg=10, quantile=0.45
    )
    charged = long_short_period_returns(
        frame, score_column="score", label_column="label", cost_bps=15.0, min_leg=10, quantile=0.45
    )

    # 得分与标签同向 ⇒ 多头（最高 10 名）收益高于空头（最低 10 名）
    # 手算：多头均值 0.155、空头均值 0.055 ⇒ 毛收益 +0.100
    assert free["gross_return"].iloc[0] == pytest.approx(0.10, abs=1e-12)
    assert free["net_return"].iloc[0] == pytest.approx(free["gross_return"].iloc[0])
    assert charged["turnover"].iloc[1] == pytest.approx(0.0)  # 名单不变 ⇒ 无换手
    assert charged["net_return"].iloc[1] == pytest.approx(charged["gross_return"].iloc[1])
    assert charged.loc[0, "turnover"] == pytest.approx(1.0)  # 首期建仓
    assert charged["net_return"].iloc[0] == pytest.approx(
        charged["gross_return"].iloc[0] - 2.0 * 15.0 / 10000.0
    )


def test_long_short_excludes_thin_cross_sections() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": [CALENDAR[0]] * 12,
            "stock_code": [f"{index:06d}" for index in range(1, 13)],
            "score": np.arange(12, dtype=float),
            "label": np.arange(12, dtype=float) / 100.0,
        }
    )
    table = long_short_period_returns(
        frame, score_column="score", label_column="label", cost_bps=15.0, min_leg=10
    )

    assert bool(table["excluded"].iloc[0]) is True
    assert math.isnan(table["net_return"].iloc[0])


def test_long_short_rejects_illegal_quantile() -> None:
    frame = pd.DataFrame({"signal_date": [], "stock_code": [], "score": [], "label": []})
    with pytest.raises(EvaluationError, match="quantile"):
        long_short_period_returns(frame, score_column="score", label_column="label", cost_bps=0.0, quantile=0.6)


# ---------------------------------------------------------------------------
# 7. 安慰剂置换
# ---------------------------------------------------------------------------

def test_permuted_network_preserves_structure_statistics() -> None:
    rng = np.random.default_rng(7)
    weights = rng.random((8, 8))
    weights = np.triu(weights, 1)
    weights = weights + weights.T
    permuted = permuted_network(weights, seed=42)

    assert permuted.shape == weights.shape
    assert np.array_equal(np.diag(permuted), np.zeros(8))
    assert np.allclose(permuted, permuted.T)
    assert np.allclose(np.sort(permuted.reshape(-1)), np.sort(weights.reshape(-1)))
    assert np.array_equal(
        np.sort((permuted > 0).sum(axis=1)), np.sort((weights > 0).sum(axis=1))
    )
    assert not np.array_equal(permuted, weights)  # 置换确实改变了身份对应


def test_permuted_network_rejects_self_loops() -> None:
    with pytest.raises(EvaluationError, match="对角线"):
        permuted_network(np.eye(3), seed=1)
    with pytest.raises(EvaluationError, match="方阵"):
        permuted_network(np.ones((2, 3)), seed=1)


# ---------------------------------------------------------------------------
# 8. 配置校验
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"domain": "D"}, "domain"),
        ({"feature_family": "static_embedding_768_jina_v2"}, "feature_family"),
        ({"networks": ("W-supply",)}, "未知或不存在的网络"),
        ({"networks": ()}, "未知或不存在的网络"),
        ({"labels": (0,)}, "labels"),
        ({"alpha_grid": (1.5,)}, "alpha"),
        ({"quantile": 0.5}, "quantile"),
        ({"max_signal_dates": 0}, "max_signal_dates"),
        ({"first_apply_index": 10}, "first_apply_index"),
        ({"signal_step": 0}, "signal_step"),
        ({"cost_bps": -1.0}, "cost_bps"),
        ({"bootstrap_reps": 0}, "bootstrap_reps"),
        ({"gate_versions": ("V9",)}, "门控版本"),
    ],
)
def test_config_validation(overrides: dict, fragment: str) -> None:
    with pytest.raises(EvaluationError, match=fragment):
        _smoke_config("cfg-test", **overrides)


def test_config_manifest_serialises_tuples() -> None:
    payload = _smoke_config("cfg-test").to_manifest()

    assert isinstance(payload["networks"], list)
    assert isinstance(payload["alpha_grid"], list)
    assert payload["run_id"] == "cfg-test"


def test_cli_parser_requires_run_id() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(["--run-id", "cli-test", "--domain", "A", "--labels", "5"])
    config = config_from_args(args)

    assert config.run_id == "cli-test"
    assert config.labels == (5,)


# ---------------------------------------------------------------------------
# 9. 端到端（合成面板；产物只落在 tmp 根下）
# ---------------------------------------------------------------------------

def test_end_to_end_run_writes_isolated_artifacts(tmp_path: Path) -> None:
    paths = _synthetic_inputs(tmp_path)
    summary = run_evaluation(_smoke_config("m4-e2e"), paths=paths, root=tmp_path, verbose=False)
    tables = tmp_path / "reports/tables/pca_nale_integration/m4-e2e"
    processed = tmp_path / "data/processed/pca_nale_integration/m4-e2e"
    manifest = json.loads((tables / "manifest.json").read_text(encoding="utf-8"))

    for name in (
        "manifest.json", "report.md", "metrics_by_variant.csv", "ic_series.csv",
        "bootstrap.csv", "portfolio.csv", "variant_index.csv", "network_diagnostics.csv",
    ):
        assert (tables / name).is_file(), name
    for name in ("asof_panel.csv.gz", "variant_scores.csv.gz"):
        assert (processed / name).is_file(), name
    assert (tmp_path / "reports/figures/pca_nale_integration/m4-e2e").is_dir()

    assert manifest["eval_version"] == EVAL_VERSION
    assert manifest["verification_frozen_at"] == CALENDAR[44]
    assert "panel" in manifest["input_sha256"] and len(manifest["input_sha256"]["panel"]) == 64
    assert manifest["corpus_inventory_sha256"] is not None
    assert manifest["versions"]["asof_panel"].startswith("pca_nale_asof_panel")
    assert set(manifest["not_evaluable_networks"]) == set(NOT_EVALUABLE_NETWORKS)
    assert manifest["run_id"] == "m4-e2e"
    assert summary["n_signal_dates_applied"] == 2


def test_end_to_end_run_refuses_second_run_with_same_id(tmp_path: Path) -> None:
    paths = _synthetic_inputs(tmp_path)
    run_evaluation(_smoke_config("m4-dup"), paths=paths, root=tmp_path, verbose=False)

    with pytest.raises(EvaluationError, match="拒绝就地覆盖"):
        run_evaluation(_smoke_config("m4-dup"), paths=paths, root=tmp_path, verbose=False)


def test_end_to_end_variants_share_one_dataset_and_alpha_zero_is_identity(tmp_path: Path) -> None:
    paths = _synthetic_inputs(tmp_path)
    run_evaluation(_smoke_config("m4-shared"), paths=paths, root=tmp_path, verbose=False)
    processed = tmp_path / "data/processed/pca_nale_integration/m4-shared"
    scores = pd.read_csv(processed / "variant_scores.csv.gz", dtype={"stock_code": str})
    asof = pd.read_csv(processed / "asof_panel.csv.gz", dtype={"stock_code": str})

    keys = scores.groupby("variant").apply(
        lambda group: tuple(sorted(zip(group["stock_code"], group["signal_date"]))),
        include_groups=False,
    )
    assert keys.nunique() == 1  # 所有变体同一批 (股票, 信号日)

    zero = scores[scores["variant"] == "alpha_0.00"].set_index(["stock_code", "signal_date"])["score"]
    reference = asof[asof["is_available"]].set_index(["stock_code", "signal_date"])["S0"]
    aligned = reference.reindex(zero.index)
    assert np.allclose(zero.to_numpy(), aligned.to_numpy(), rtol=0, atol=1e-12)

    for column in scores.columns:
        assert "annual" not in column.lower()
    metrics = pd.read_csv(tmp_path / "reports/tables/pca_nale_integration/m4-shared/metrics_by_variant.csv")
    for column in metrics.columns:
        assert "annual" not in column.lower()
    portfolio = pd.read_csv(tmp_path / "reports/tables/pca_nale_integration/m4-shared/portfolio.csv")
    assert set(portfolio["cost_bps"]) == {0.0, 15.0}


def test_end_to_end_report_lists_not_evaluable_networks_and_placebo(tmp_path: Path) -> None:
    paths = _synthetic_inputs(tmp_path)
    run_evaluation(_smoke_config("m4-report"), paths=paths, root=tmp_path, verbose=False)
    tables = tmp_path / "reports/tables/pca_nale_integration/m4-report"
    report = (tables / "report.md").read_text(encoding="utf-8")
    variants = pd.read_csv(tables / "variant_index.csv")

    for name in NOT_EVALUABLE_NETWORKS:
        assert name in report
    assert "NOT_ASOF" in report or "NOT_EVALUABLE" in report
    assert "placebo_node_permutation" in variants["variant"].tolist()
    assert "冻结" in report
    assert "年化" in report  # 明确声明不做年化
    assert "gate_V1" in variants["variant"].tolist()


def test_end_to_end_gate_fallback_is_recorded_not_hidden(tmp_path: Path) -> None:
    """门控若因校准斜率退化而回落，必须在 manifest 里留痕（不得静默当成动态 α）。"""
    paths = _synthetic_inputs(tmp_path)
    run_evaluation(_smoke_config("m4-gate"), paths=paths, root=tmp_path, verbose=False)
    manifest = json.loads(
        (tmp_path / "reports/tables/pca_nale_integration/m4-gate/manifest.json").read_text(encoding="utf-8")
    )
    fits = manifest["gate_fits"]["W-ind"]["V1"]

    assert "fallback_reason" in fits
    assert fits["fit_cutoff"].endswith("+08:00")
    variants = pd.read_csv(tmp_path / "reports/tables/pca_nale_integration/m4-gate/variant_index.csv")
    gate = variants[variants["variant"] == "gate_V1"].iloc[0]
    # 回落时 α 必须等于 0.4（B0），且这一点由 alpha_min/max 显式可见
    if fits["fallback_reason"] is not None:
        assert gate["alpha_min"] == pytest.approx(0.4)
        assert gate["alpha_max"] == pytest.approx(0.4)


def test_end_to_end_attention_network_requires_corpus(tmp_path: Path) -> None:
    paths = _synthetic_inputs(tmp_path)
    config = _smoke_config("m4-attn", networks=("W-attn",), feature_family="price_technical_v1")

    summary = run_evaluation(config, paths=paths, root=tmp_path, verbose=False)

    assert summary["corpus_records"] == 24 * 3  # 合成语料：24 支 × 3 条
    diagnostics = pd.read_csv(tmp_path / "reports/tables/pca_nale_integration/m4-attn/network_diagnostics.csv")
    assert diagnostics["network"].unique().tolist() == ["W-attn"]
    assert diagnostics["node_coverage"].between(0.0, 1.0).all()
    assert diagnostics["n_edges"].notna().all()