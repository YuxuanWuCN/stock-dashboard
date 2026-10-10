"""Empirical Stress Tests and Adversarial Invariance Verification for Challenger 2.

Mission: Challenger 2 (teamwork_preview_challenger) - Milestone 5 Final Verification.
Validates:
1. Percentile Ranking Engine:
   - Uniform distribution mapping to [0, 100] across diverse universe sizes (5, 10, 50, 205).
   - Average rank tie-handling and symmetry.
   - Outlier invariance: massive outlier (+1000%) does not distort cross-sectional ranks of remaining assets.
   - Zero-volatility floor anti-overflow clamping at sigma_floor = 0.08 (inv_vol = 12.5).
   - Noise perturbation stability.
2. Rollover Gap Adjustment & Lookahead Bias Audit:
   - Elimination of artificial overnight jump on contract switch; replacement with true intraday holding return.
   - Strict lookahead audit: signals and weights at t_eval are identical whether future data exists or not.
3. Diversification Ratio (DR) across varied correlation structures:
   - DR == 1.0 for perfect correlation (rho = 1.0).
   - DR == sqrt(N) for uncorrelated equal-volatility assets (rho = 0.0).
   - Strict monotonicity: d(DR)/d(rho) < 0 across all correlation levels.
   - Cross-asset stock-futures correlation reduction strictly amplifies DR.
4. Production Artifacts & Report Cross-Consistency:
   - JSON artifact validity and schema conformity.
   - Markdown report metrics matching JSON values.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.assets.cross_asset_mix.contracts import get_contract_spec
from src.assets.cross_asset_mix.data_loader import AlignedDataset, DataLoader
from src.assets.cross_asset_mix.ranking import (
    CrossAssetRanker,
    calculate_compounded_20d_momentum,
    calculate_ctsi,
    calculate_inverse_volatility,
    compute_cross_asset_percentile_rank,
    select_top_k,
)
from src.assets.cross_asset_mix.backtest_engine import (
    BacktestConfig,
    BacktestResult,
    CrossAssetBacktestEngine,
    calculate_diversification_ratio,
    calculate_mpt_metrics,
    run_cross_asset_pipeline,
)


class TestPercentileRankingStability:
    """Adversarial challenge tests for the non-parametric percentile ranking engine."""

    @pytest.mark.parametrize("universe_size", [5, 10, 50, 205])
    def test_uniform_distribution_properties(self, universe_size: int):
        """Percentile rank of strictly distinct values must map uniformly onto [0, 100]."""
        scores = pd.Series(
            np.linspace(-50.0, 100.0, universe_size),
            index=[f"A_{i}" for i in range(universe_size)],
        )
        pct = compute_cross_asset_percentile_rank(scores)

        assert np.isclose(pct.min(), 0.0)
        assert np.isclose(pct.max(), 100.0)
        assert np.isclose(pct.mean(), 50.0)
        step = 100.0 / (universe_size - 1)
        diffs = np.diff(pct.values)
        assert np.allclose(diffs, step, atol=1e-8)

    def test_tied_scores_average_rank_assignment(self):
        """Tied factor scores must receive identical percentile rankings via average ranking."""
        tied = pd.Series([10.0, 10.0, 10.0, 50.0, 50.0], index=["a", "b", "c", "d", "e"])
        pct = compute_cross_asset_percentile_rank(tied)
        assert np.isclose(pct["a"], 25.0)
        assert np.isclose(pct["b"], 25.0)
        assert np.isclose(pct["c"], 25.0)
        assert np.isclose(pct["d"], 87.5)
        assert np.isclose(pct["e"], 87.5)

    def test_outlier_insensitivity_preserves_cross_sectional_order(self):
        """A +1000% extreme momentum outlier must not distort the relative rankings of remaining assets."""
        np.random.seed(123)
        n_stk = 202
        stock_scores = np.random.normal(0.02, 0.05, n_stk)
        names = [f"STK_{i:03d}" for i in range(n_stk)] + ["SA", "FG", "AU"]
        raw_scores = np.concatenate([stock_scores, [0.03, -0.01, 10.0]])  # AU has massive outlier
        s1 = pd.Series(raw_scores, index=names)

        # Moderate AU score
        s2 = s1.copy()
        s2["AU"] = 0.10

        pct1 = compute_cross_asset_percentile_rank(s1)
        pct2 = compute_cross_asset_percentile_rank(s2)

        assert pct1["AU"] == 100.0
        # Other 204 assets' relative ranks must be identical
        order1 = pct1.drop("AU").rank().values
        order2 = pct2.drop("AU").rank().values
        assert np.array_equal(order1, order2)

    def test_zero_volatility_floor_anti_overflow(self):
        """Zero variance price path must clamp annualized volatility at floor=0.08 (inv_vol = 12.5)."""
        zero_ret = pd.Series(np.zeros(30))
        iv = calculate_inverse_volatility(zero_ret, window=20, floor=0.08)
        assert np.isclose(iv.iloc[-1], 12.5)

    def test_noise_perturbation_rank_stability(self):
        """Micro-noise (1e-7) must not trigger catastrophic rank inversions."""
        scores = pd.Series(np.linspace(10.0, 50.0, 50), index=[f"S_{i}" for i in range(50)])
        pct_base = compute_cross_asset_percentile_rank(scores)
        noise = np.random.normal(0, 1e-7, 50)
        pct_noisy = compute_cross_asset_percentile_rank(scores + noise)
        max_shift = np.max(np.abs(pct_base.values - pct_noisy.values))
        assert max_shift < 1e-4


class TestRolloverGapAndLookaheadBias:
    """Adversarial verification of rollover jump elimination and zero lookahead bias."""

    def test_rollover_gap_jump_eliminated(self):
        """A +9.4% overnight rollover price jump is replaced with the true intraday return (+0.45%)."""
        dates = pd.bdate_range("2024-01-01", periods=40)
        open_px = np.full(40, 2000.0)
        close_px = np.full(40, 2000.0)
        settle_px = np.full(40, 2000.0)
        oi = np.full(40, 500000.0)

        # Day 20 roll: overnight shift from 2000 to 2200, intraday close at 2210
        close_px[19] = 2000.0
        open_px[20] = 2200.0
        close_px[20] = 2210.0
        settle_px[20] = 2210.0
        open_px[21:] = 2210.0
        close_px[21:] = 2210.0
        settle_px[21:] = 2210.0

        df = pd.DataFrame(
            {
                "open": open_px,
                "high": np.maximum(open_px, close_px) + 5.0,
                "low": np.minimum(open_px, close_px) - 5.0,
                "close": close_px,
                "settle": settle_px,
                "open_interest": oi,
                "volume": np.full(40, 10000.0),
            },
            index=dates,
        )

        adj_ret, adj_close, adj_settle, is_roll = DataLoader.adjust_rollover_gap(
            df, gap_threshold=0.035
        )
        assert is_roll.iloc[20] is True or is_roll.iloc[20] == 1
        expected_ret = (2210.0 - 2200.0) / 2200.0
        assert np.isclose(adj_ret.iloc[20], expected_ret, atol=1e-6)

        # Synthetic returns match adj_ret
        ret_diff = np.max(np.abs(adj_close.pct_change().iloc[1:] - adj_ret.iloc[1:]))
        assert ret_diff < 1e-10

    def test_strict_lookahead_invariance_on_market_data(self):
        """CrossAssetRanker Top-K selection and target weights at t_eval must be identical
        whether future data beyond t_eval is present or truncated.
        """
        dl = DataLoader()
        full_ds = dl.load_aligned_market_data()
        assert len(full_ds.dates) >= 40

        t_eval = full_ds.dates[35].strftime("%Y-%m-%d")
        ranker_full = CrossAssetRanker(dataset=full_ds)
        res_full = ranker_full.rank_universe(as_of_date=t_eval, top_k=10)

        # Truncate dataset strictly up to t_eval
        trunc_dates = full_ds.dates[:36]
        trunc_ds = AlignedDataset(
            dates=trunc_dates,
            prices=full_ds.prices.loc[trunc_dates].copy(),
            returns=full_ds.returns.loc[trunc_dates].copy(),
            settle_prices=full_ds.settle_prices.loc[trunc_dates].copy(),
            asset_types=full_ds.asset_types.copy(),
            metadata=full_ds.metadata.copy(),
        )
        ranker_trunc = CrossAssetRanker(dataset=trunc_ds)
        res_trunc = ranker_trunc.rank_universe(as_of_date=t_eval, top_k=10)

        syms_full = [it.symbol for it in res_full.selected_top_k]
        syms_trunc = [it.symbol for it in res_trunc.selected_top_k]
        assert syms_full == syms_trunc

        w_full = [it.target_weight for it in res_full.selected_top_k]
        w_trunc = [it.target_weight for it in res_trunc.selected_top_k]
        assert np.allclose(w_full, w_trunc, atol=1e-6)


class TestDiversificationRatioDynamics:
    """Adversarial verification of Diversification Ratio (DR >= 1.0) under various correlation regimes."""

    def test_dr_perfect_correlation_boundary(self):
        """Under perfect correlation (rho = 1.0), DR must equal 1.000000 exactly."""
        N = 8
        w = np.ones(N) / N
        vols = np.array([0.10 + 0.02 * i for i in range(N)])
        cov = np.outer(vols, vols) * 1.0
        dr = calculate_diversification_ratio(w, vols, cov)
        assert np.isclose(dr, 1.0, atol=1e-5)

    def test_dr_uncorrelated_equal_vol_equals_sqrt_n(self):
        """Under zero correlation (rho = 0.0) with equal volatilities, DR must equal sqrt(N)."""
        N = 16
        w = np.ones(N) / N
        vols = np.full(N, 0.20)
        cov = np.diag(vols ** 2)
        dr = calculate_diversification_ratio(w, vols, cov)
        assert np.isclose(dr, np.sqrt(N), atol=1e-4)

    def test_dr_strict_monotonicity_wrt_correlation(self):
        """DR must be strictly monotonically decreasing with respect to cross-asset correlation rho."""
        N = 6
        w = np.ones(N) / N
        vols = np.array([0.15, 0.18, 0.20, 0.22, 0.25, 0.28])
        rhos = [0.95, 0.70, 0.40, 0.10, -0.10]
        dr_list = []
        for rho in rhos:
            corr = np.full((N, N), rho)
            np.fill_diagonal(corr, 1.0)
            cov = np.outer(vols, vols) * corr
            dr = calculate_diversification_ratio(w, vols, cov)
            dr_list.append(dr)

        for i in range(len(dr_list) - 1):
            assert dr_list[i] < dr_list[i + 1]

    def test_dr_stock_futures_correlation_reduction_enhances_gain(self):
        """Reducing cross-asset correlation between equities and commodities strictly increases DR."""
        n_stk, n_fut = 10, 3
        n_tot = n_stk + n_fut
        w = np.ones(n_tot) / n_tot
        vols = np.concatenate([np.full(n_stk, 0.22), np.full(n_fut, 0.18)])

        rho_cross_list = [0.50, 0.25, 0.00, -0.25]
        dr_results = []
        for rho_cross in rho_cross_list:
            corr = np.zeros((n_tot, n_tot))
            corr[:n_stk, :n_stk] = 0.40
            corr[n_stk:, n_stk:] = 0.30
            corr[:n_stk, n_stk:] = rho_cross
            corr[n_stk:, :n_stk] = rho_cross
            np.fill_diagonal(corr, 1.0)
            cov = np.outer(vols, vols) * corr
            dr_results.append(calculate_diversification_ratio(w, vols, cov))

        for i in range(len(dr_results) - 1):
            assert dr_results[i] < dr_results[i + 1]


class TestArtifactGenerationAndConsistency:
    """Verifies that runner outputs valid JSON and Markdown reports with matching metrics."""

    def test_production_artifacts_schema_and_cross_match(self):
        """Runner must produce backtest_cross_asset_mix.json and backtest_cross_asset_mix_report.md
        with consistent numerical values.
        """
        rainbow_root = Path(__file__).resolve().parents[2]
        json_path = rainbow_root / "docs" / "data" / "paper" / "backtest_cross_asset_mix.json"
        report_path = rainbow_root / "reports" / "tables" / "backtest_cross_asset_mix_report.md"

        assert json_path.exists()
        assert report_path.exists()

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "metadata" in data
        assert "metrics" in data
        assert "nav_summary" in data
        assert "accounting_trajectories" in data

        dr_val = data["metrics"]["diversification_ratio"]
        assert dr_val >= 1.0

        with open(report_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        assert f"{dr_val:.4f}" in md_content or f"{round(dr_val, 4)}" in md_content
        mixed_sharpe = data["metrics"]["mixed_portfolio"]["sharpe_ratio"]
        assert f"{mixed_sharpe:.2f}" in md_content
