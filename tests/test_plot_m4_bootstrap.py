# -*- coding: utf-8 -*-
"""tests/test_plot_m4_bootstrap.py —— Bootstrap 图集脚本回归（可手算 + 确定性重放）。

覆盖：重放与评测器 block_bootstrap_interval 逐位一致、一致性断言拒绝被篡改的参照、
年化字样守卫、Holm 热图与森林图在小合成帧上出图成功。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.evaluate_pca_nale_integration import block_bootstrap_interval
from scripts.plot_m4_bootstrap_significance import (
    PlotError,
    _assert_consistent,
    _guard_text,
    plot_holm_heatmap,
    plot_ic_forest,
    replay_block_bootstrap_means,
)


def test_replay_matches_evaluator_interval_exactly() -> None:
    rng = np.random.default_rng(7)
    values = rng.normal(0.01, 0.05, size=80).tolist()
    interval = block_bootstrap_interval(values, block_length=4, reps=300, seed=42)
    means = replay_block_bootstrap_means(values, block_length=4, reps=300, seed=42)
    # point_mean 是原始序列均值（评测器定义），逐位相等
    assert interval["point_mean"] == pytest.approx(float(np.mean(values)), abs=0, rel=0)
    # 同算法同种子 ⇒ 重放分位数与评测器区间逐位一致
    assert np.quantile(means, 0.025) == pytest.approx(interval["ci_low"], abs=1e-12, rel=0)
    assert np.quantile(means, 0.975) == pytest.approx(interval["ci_high"], abs=1e-12, rel=0)
    # 确定性：同 seed 两次重放逐位一致
    again = replay_block_bootstrap_means(values, block_length=4, reps=300, seed=42)
    assert np.array_equal(means, again)


def test_replay_is_block_sensitive() -> None:
    rng = np.random.default_rng(11)
    values = rng.normal(0.0, 1.0, size=120).tolist()
    short = replay_block_bootstrap_means(values, block_length=2, reps=500, seed=42)
    long = replay_block_bootstrap_means(values, block_length=24, reps=500, seed=42)
    assert float(short.std(ddof=1)) != pytest.approx(float(long.std(ddof=1)))
    assert short.size == 500 and long.size == 500


def test_assert_consistent_rejects_tampered_reference() -> None:
    raw = np.asarray([0.01, -0.02, 0.03, 0.04])
    means = replay_block_bootstrap_means(raw.tolist(), block_length=1, reps=50, seed=1)
    reference = pd.Series({"point_mean": float(raw.mean()),
                           "ci_low": float(np.quantile(means, 0.025)),
                           "ci_high": float(np.quantile(means, 0.975))})
    _assert_consistent(means, raw, reference, label="ok")
    tampered = reference.copy()
    tampered["ci_high"] = tampered["ci_high"] + 1e-3
    with pytest.raises(PlotError, match="图与表脱节"):
        _assert_consistent(means, raw, tampered, label="tampered")
    wrong_mean = reference.copy()
    wrong_mean["point_mean"] = wrong_mean["point_mean"] + 1e-9
    with pytest.raises(PlotError, match="point_mean"):
        _assert_consistent(means, raw, wrong_mean, label="wrong-mean")


def test_guard_text_rejects_annualised_wording() -> None:
    assert _guard_text("mean IC per holding period") == "mean IC per holding period"
    for bad in ("Annualized return", "annual-mean IC", "年化 annual"):
        with pytest.raises(PlotError, match="年化字样"):
            _guard_text(bad)


def _ic_series_frame() -> pd.DataFrame:
    rng = np.random.default_rng(5)
    rows = []
    for network in ("W-ind", "W-corr"):
        for variant in ("alpha_0.00", "b0_alpha_0.40", "alpha_0.75"):
            for index, day in enumerate(range(1, 25)):
                rows.append(
                    {
                        "network": network,
                        "variant": variant,
                        "signal_date": f"2025-01-{day:02d}" if day < 29 else f"2025-02-{day - 28:02d}",
                        "horizon": 5,
                        "n_stocks": 100,
                        "excluded": False,
                        "pearson_ic": float(rng.normal(0.01, 0.05)),
                        "spearman_ic": float(rng.normal(0.01, 0.05)),
                    }
                )
    return pd.DataFrame(rows)


def test_plot_ic_forest_writes_files(tmp_path) -> None:
    ic = _ic_series_frame()
    bootstrap = pd.DataFrame(
        [
            {
                "network": network,
                "variant": variant,
                "horizon": 5,
                "metric": "pearson_ic",
                "block_trading_days": 10,
                "is_sensitivity": False,
                "point_mean": 0.01,
                "ci_low": -0.01,
                "ci_high": 0.03,
            }
            for network in ("W-ind", "W-corr")
            for variant in ("alpha_0.00", "b0_alpha_0.40", "alpha_0.75")
        ]
    )
    outputs = plot_ic_forest(bootstrap, ["alpha_0.00", "b0_alpha_0.40", "alpha_0.75"], tmp_path)
    assert outputs and all(path.exists() for path in outputs)
    assert {path.suffix for path in outputs} == {".png", ".pdf"}


def test_plot_holm_heatmap_writes_files(tmp_path) -> None:
    metrics = pd.DataFrame(
        [
            {
                "network": network,
                "variant": variant,
                "horizon": 5,
                "holm_adjusted_p": 0.5,
            }
            for network in ("W-ind",)
            for variant in ("alpha_0.00", "b0_alpha_0.40")
        ]
    )
    outputs = plot_holm_heatmap(metrics, tmp_path)
    assert outputs and outputs[0].exists()
