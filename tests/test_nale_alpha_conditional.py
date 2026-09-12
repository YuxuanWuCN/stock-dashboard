"""Independent engineering fixtures for conditional gates; not market evidence."""

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from src.pricing.nale_alpha_conditional import (
    ConditionalPanel, ReliabilityObservation, fit_conditional_gate,
    market_state_from_history, predict_conditional_gate,
    reliability_from_frozen_history,
)


def _panel(n=80):
    rng = np.random.default_rng(42)
    z = rng.normal(size=(n, 10))
    g = np.linspace(-1, 1, n)
    q = np.linspace(1, -1, n) + 0.1 * rng.normal(size=n)
    d = rng.uniform(0.1, 0.3, size=n)
    s0 = rng.normal(size=n)
    return ConditionalPanel(
        dates=np.repeat(np.arange(n // 4), 4), age_days=np.repeat(np.arange(n // 4)[::-1], 4),
        z=z, g=g, q=q, q_available=np.ones(n, dtype=bool), s0=s0, d=d,
        y=s0 + 0.4 * d + 0.02 * z[:, 0] * d,
    )


@pytest.mark.parametrize("version,n_params", [("V4", 22), ("V5", 33)])
def test_fit_has_expected_parameters_gradient_and_bounded_predictions(version, n_params):
    panel = _panel()
    fit = fit_conditional_gate(panel, version=version, a=0, c=1, ridge=0.01, half_life=20)
    assert fit.status == "fitted"
    assert fit.theta.shape == (n_params,)
    assert fit.gradient_max_abs_error < 1e-5
    assert fit.n_dates == 20
    predicted = predict_conditional_gate(
        fit, z=panel.z, g=panel.g, q=panel.q, q_available=panel.q_available,
        s0=panel.s0, d=panel.d, a=0, c=1,
    )
    assert np.all((predicted["alpha_nale"] >= 0.05) & (predicted["alpha_nale"] <= 0.75))
    assert np.allclose(predicted["score"], panel.s0 + predicted["alpha_nale"] * panel.d)


def test_unidentifiable_gate_falls_back_to_b0():
    panel = _panel()
    fit = fit_conditional_gate(panel, version="V4", a=0, c=0, ridge=0.01, half_life=20)
    assert fit.status == "fallback_b0"
    pred = predict_conditional_gate(fit, z=panel.z, g=panel.g, q=None, q_available=None,
                                    s0=panel.s0, d=panel.d, a=0, c=0)
    assert np.all(pred["alpha_nale"] == 0.4)


def test_v5_missing_reliability_is_zero_after_scaling_and_marked():
    panel = _panel()
    fit = fit_conditional_gate(panel, version="V5", a=0, c=1, ridge=0.01, half_life=20)
    available = np.ones(len(panel.z), dtype=bool)
    available[0] = False
    pred = predict_conditional_gate(fit, z=panel.z, g=panel.g, q=panel.q,
                                    q_available=available, s0=panel.s0, d=panel.d, a=0, c=1)
    assert pred["q_scaled"][0] == 0
    assert pred["q_missing"][0]


def test_market_state_needs_60_visible_prices():
    assert market_state_from_history(np.arange(1.0, 61.0)) == pytest.approx(
        np.mean(np.arange(41.0, 61.0)) / np.mean(np.arange(1.0, 61.0)) - 1
    )
    with pytest.raises(ValueError, match="60 observed"):
        market_state_from_history([1.0] * 59)


def test_reliability_uses_only_mature_frozen_forecasts():
    start = date(2026, 1, 1)
    rows = []
    for j in range(21):
        day = start + timedelta(days=j)
        rows.append(ReliabilityObservation(
            "000001", day, datetime.combine(day, datetime.min.time()),
            datetime.combine(day + timedelta(days=5), datetime.min.time()),
            0.1, 0.0, 0.1,
        ))
    early = reliability_from_frozen_history(rows, code="000001", decision_cutoff=datetime(2026, 1, 20))
    assert not early.available and early.q == 0
    mature = reliability_from_frozen_history(rows, code="000001", decision_cutoff=datetime(2026, 2, 1))
    assert mature.available and mature.mature_days == 21 and mature.q == pytest.approx(0.01)
