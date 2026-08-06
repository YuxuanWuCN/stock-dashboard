"""Deterministic checks for the research-driven fundamental scoring rules."""

from types import SimpleNamespace

from src.analysis.fundamental import score_asset_quality


def test_cycle_exposure_score_is_reproducible_for_fixed_financial_inputs():
    metrics = SimpleNamespace(
        total_assets_yoy=57.7,
        inventory_prepay_ratio=0.60,
        receivable_revenue=0.20,
        goodwill_equity=0.05,
    )

    first = score_asset_quality(metrics, "contraction")
    second = score_asset_quality(metrics, "contraction")

    assert first == second
    assert first["score"] < 50
