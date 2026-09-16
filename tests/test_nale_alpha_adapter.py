"""Independent arithmetic fixtures for the Week1 propagation contract."""

import numpy as np
import pytest

from src.graph.nale_alpha_adapter import propagate_nale


def test_fixed_baseline_and_per_node_alpha():
    codes = ["000001", "000002"]
    s0 = [0.2, 0.8]
    network = np.array([[0, 1], [1, 0]], dtype=float)
    baseline = propagate_nale(codes, s0, network)
    np.testing.assert_allclose(baseline.neighbor_score, [0.8, 0.2])
    np.testing.assert_allclose(baseline.difference, [0.6, -0.6])
    np.testing.assert_allclose(baseline.alpha_nale, [0.4, 0.4])
    np.testing.assert_allclose(baseline.score, [0.44, 0.56])

    per_node = propagate_nale(codes, s0, network, alpha_override=[0.6, 0.4])
    np.testing.assert_allclose(per_node.score, [0.56, 0.56])


def test_zero_gate_is_fixed_baseline_and_extremes_are_bounded():
    codes = ["000001", "000002"]
    z = np.zeros((2, 10))
    network = np.eye(2)
    result = propagate_nale(codes, [0.2, 0.8], network, z=z, weights=np.zeros(10))
    np.testing.assert_allclose(result.u, [0, 0])
    np.testing.assert_allclose(result.alpha_nale, [0.4, 0.4])
    np.testing.assert_allclose(result.score, [0.2, 0.8])

    z[:, 0] = [-1000, 1000]
    extremes = propagate_nale(codes, [0.2, 0.8], network, z=z, weights=[1] + [0] * 9)
    assert np.isfinite(extremes.alpha_nale).all()
    np.testing.assert_allclose(extremes.alpha_nale, [0.05, 0.75])


def test_isolated_nodes_self_loop_and_row_normalization():
    result = propagate_nale(
        ["000001", "000002"], [0.2, 0.8], np.array([[0.0, 0.0], [2.0, 0.0]])
    )
    np.testing.assert_allclose(result.normalized_network, [[1, 0], [1, 0]])
    np.testing.assert_allclose(result.neighbor_score, [0.2, 0.2])
    np.testing.assert_allclose(result.score, [0.2, 0.56])


def test_permutation_and_pc_sign_flip_invariance():
    codes = ["000001", "000002", "000003"]
    s0 = np.array([0.2, 0.8, -0.1])
    network = np.array([[0, 2, 1], [1, 0, 0], [0, 1, 0]], dtype=float)
    z = np.arange(30, dtype=float).reshape(3, 10) / 100
    weights = np.arange(1, 11, dtype=float) / 10
    first = propagate_nale(codes, s0, network, z=z, weights=weights)
    order = [2, 0, 1]
    shuffled = propagate_nale(
        [codes[i] for i in order], s0[order], network[np.ix_(order, order)],
        z=z[order], weights=weights,
    )
    np.testing.assert_allclose(shuffled.score, first.score[order])
    flipped_z = z.copy()
    flipped_z[:, 3] *= -1
    flipped_weights = weights.copy()
    flipped_weights[3] *= -1
    flipped = propagate_nale(codes, s0, network, z=flipped_z, weights=flipped_weights)
    np.testing.assert_allclose(flipped.score, first.score)


@pytest.mark.parametrize("codes,s0,network,z,weights,override", [
    (["1"], [0.2], [[1]], None, None, None),
    (["000001", "000001"], [0.2, 0.8], [[0, 1], [1, 0]], None, None, None),
    (["000001"], [float("nan")], [[1]], None, None, None),
    (["000001"], [0.2], [[-1]], None, None, None),
    (["000001"], [0.2], [[float("inf")]], None, None, None),
    (["000001"], [0.2], [[1, 0]], None, None, None),
    (["000001"], [0.2], [[1]], np.zeros((1, 9)), [0] * 10, None),
    (["000001"], [0.2], [[1]], np.zeros((1, 10)), [0] * 9, None),
    (["000001"], [0.2], [[1]], None, None, 0.9),
])
def test_invalid_input_fails_closed(codes, s0, network, z, weights, override):
    with pytest.raises(ValueError):
        propagate_nale(codes, s0, np.asarray(network), z=z, weights=weights, alpha_override=override)
