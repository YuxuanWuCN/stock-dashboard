"""Arithmetic-only fixtures; these are not historical market observations."""

from dataclasses import replace

import numpy as np
import pytest

from src.pricing.nale_alpha_models import (
    B0Calibration,
    TrainingPanel,
    date_sample_weights,
    fit_b0_calibration,
    fit_gate,
    gate_loss_and_gradient,
)


def _panel() -> TrainingPanel:
    days = ["2024-06-01", "2024-06-02", "2024-06-03", "2024-06-04"]
    signal_dates = [day for day in days for _ in range(3)]
    label_available_at = [f"2024-06-{day:02d}T18:00:00+08:00" for day in (6, 7, 8, 9) for _ in range(3)]
    s0 = np.tile([-0.2, 0.0, 0.2], 4)
    difference = np.tile([0.3, -0.2, 0.1], 4)
    z = np.zeros((12, 10))
    z[:, 0] = np.linspace(-1, 1, 12)
    y = 0.01 + 0.4 * (s0 + (0.4 + 0.05 * z[:, 0]) * difference)
    return TrainingPanel(
        signal_dates=signal_dates, label_available_at=label_available_at,
        s0=s0, difference=difference, z=z, excess_return=y,
        age_trading_days=np.repeat([3, 2, 1, 0], 3),
    )


def test_date_weights_equalize_stocks_and_decay_only_training_dates():
    dates = np.array(["2024-06-01", "2024-06-01", "2024-06-02"], dtype="datetime64[D]")
    np.testing.assert_allclose(date_sample_weights(dates), [0.25, 0.25, 0.5])
    np.testing.assert_allclose(
        date_sample_weights(dates, age_trading_days=[20, 20, 0], half_life_days=20),
        [1 / 6, 1 / 6, 2 / 3],
    )
    with pytest.raises(ValueError):
        date_sample_weights(dates, age_trading_days=[0, 0, 0], half_life_days=20)
    with pytest.raises(ValueError):
        date_sample_weights(dates, age_trading_days=[20, 19, 0], half_life_days=20)


def test_public_b0_calibrator_has_nonnegative_slope():
    panel = _panel()
    calibration = fit_b0_calibration(panel, fit_cutoff="2024-06-15T09:00:00+08:00", min_train_dates=4)
    assert calibration.slope > 0
    baseline = np.asarray(panel.s0) + 0.4 * np.asarray(panel.difference)
    assert np.mean((calibration.predict(baseline) - panel.excess_return) ** 2) < 1e-3

    reversed_y = replace(panel, excess_return=-baseline)
    constrained = fit_b0_calibration(reversed_y, fit_cutoff="2024-06-15T09:00:00+08:00", min_train_dates=4)
    assert constrained.slope == 0.0


def test_gate_gradient_matches_independent_finite_difference():
    panel = _panel()
    calibration = B0Calibration(intercept=0.01, slope=0.4, fit_cutoff="2024-06-15T09:00:00+08:00", n_signal_dates=4, n_rows=12)
    theta = np.linspace(-0.1, 0.1, 11)
    inputs = dict(
        z=panel.z, s0=np.asarray(panel.s0), difference=np.asarray(panel.difference),
        y=np.asarray(panel.excess_return), calibration=calibration,
        sample_weights=date_sample_weights(np.asarray(panel.signal_dates, dtype="datetime64[D]")),
        ridge_lambda=0.01,
    )
    _, analytical = gate_loss_and_gradient(theta, **inputs)
    numerical = np.empty(11)
    step = 1e-6
    for index in range(11):
        before = theta.copy()
        after = theta.copy()
        before[index] -= step
        after[index] += step
        numerical[index] = (
            gate_loss_and_gradient(after, **inputs)[0] - gate_loss_and_gradient(before, **inputs)[0]
        ) / (2 * step)
    np.testing.assert_allclose(analytical, numerical, atol=1e-8, rtol=1e-5)


@pytest.mark.parametrize("version,half_life", [("V1", None), ("V2", None), ("V3", 20)])
def test_fit_versions_share_b0_calibration_and_record_fit(version, half_life):
    panel = _panel()
    result = fit_gate(
        panel, version=version, fit_cutoff="2024-06-15T09:00:00+08:00",
        ridge_lambda=0.01, half_life_days=half_life, min_train_dates=4,
    )
    assert result.calibration.slope > 0
    assert result.n_signal_dates == 4
    assert result.n_rows == 12
    assert result.initial_parameters == (0.0,) * 11
    assert result.gradient_check_error is not None and result.gradient_check_error < 1e-4
    assert result.converged and result.fallback_reason is None
    assert np.isfinite(result.objective)
    assert np.isfinite(result.gradient_norm)
    assert np.isfinite(result.predict(panel.s0, panel.difference, panel.z)).all()
    assert ((result.alpha(panel.z) >= 0.05) & (result.alpha(panel.z) <= 0.75)).all()


def test_label_maturity_and_missing_v3_ages_fail_closed():
    panel = _panel()
    immature = replace(panel, label_available_at=["2024-06-15T09:00:00+08:00"] + list(panel.label_available_at[1:]))
    with pytest.raises(ValueError, match="mature"):
        fit_gate(immature, version="V1", fit_cutoff="2024-06-15T09:00:00+08:00", ridge_lambda=0.01, min_train_dates=4)
    with pytest.raises(ValueError, match="timezone"):
        fit_gate(panel, version="V1", fit_cutoff="2024-06-15", ridge_lambda=0.01, min_train_dates=4)
    with pytest.raises(ValueError, match="age"):
        fit_gate(replace(panel, age_trading_days=None), version="V3", fit_cutoff="2024-06-15T09:00:00+08:00", ridge_lambda=0.01, half_life_days=20, min_train_dates=4)
    with pytest.raises(ValueError, match="insufficient"):
        fit_gate(panel, version="V1", fit_cutoff="2024-06-15T09:00:00+08:00", ridge_lambda=0.01)


def test_unidentifiable_gate_falls_back_to_b0():
    panel = _panel()
    baseline = np.asarray(panel.s0) + 0.4 * np.asarray(panel.difference)
    negative_slope = fit_gate(
        replace(panel, excess_return=-baseline), version="V1",
        fit_cutoff="2024-06-15T09:00:00+08:00", ridge_lambda=0.01, min_train_dates=4,
    )
    assert negative_slope.fallback_reason == "calibration_slope_zero"
    np.testing.assert_allclose(negative_slope.alpha(panel.z), 0.4)

    sparse_difference = np.asarray(panel.difference).copy()
    sparse_difference[:7] = 0
    no_network = fit_gate(
        replace(panel, difference=sparse_difference), version="V2",
        fit_cutoff="2024-06-15T09:00:00+08:00", ridge_lambda=0.01, min_train_dates=4,
    )
    assert no_network.fallback_reason == "network_difference_unidentifiable"


def test_optimizer_failure_falls_back(monkeypatch):
    panel = _panel()

    class FailedResult:
        success = False
        message = "fixture optimizer stopped"
        x = np.zeros(11)
        fun = 1.0

    monkeypatch.setattr("src.pricing.nale_alpha_models.minimize", lambda *args, **kwargs: FailedResult())
    result = fit_gate(
        panel, version="V1", fit_cutoff="2024-06-15T09:00:00+08:00",
        ridge_lambda=0.01, min_train_dates=4,
    )
    assert result.fallback_reason == "optimizer_failed"
    np.testing.assert_allclose(result.alpha(panel.z), 0.4)
