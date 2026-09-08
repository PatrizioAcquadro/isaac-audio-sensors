"""Numerical and event-selection invariants of the maintained spatial solver."""

import numpy as np
import pytest

pytest.importorskip("pyroomacoustics")
pytest.importorskip("nara_wpe")

from isaac_audio_sensors.core.plugins._multisource_sparse import GroupSparseCovariance


@pytest.mark.parametrize("three_d", [False, True])
def test_silence_geometry_and_unbounded_event_selection(three_d):
    positions = np.array(
        [[0, 0, 0], [0.06, 0, 0], [0, 0.06, 0], [0, 0, 0.06 if three_d else 0]]
    )
    estimator = GroupSparseCovariance()
    samples = np.zeros((4, 12000))
    samples.setflags(write=False)
    found, diagnostic = estimator.localize(samples, positions, 16000)
    assert found.shape == (0, 3)
    assert diagnostic["status"] == "no_events"
    with pytest.raises(ValueError, match="non-collinear"):
        estimator.localize(samples[:2], positions[:2], 16000)
    _, (vectors, _, near) = estimator.prepare(samples, positions, 16000)
    truth = np.array([[1, 0, 0], [-1, 0, 0], [0, 0, 1] if three_d else [0, 1, 0]])
    histogram = np.zeros(len(vectors))
    histogram[np.argmax(vectors @ truth.T, axis=0)] = 1 / 3
    found, _ = estimator.events(vectors, histogram, near, {})
    assert len(found) == 3
    assert len(set(np.argmax(found @ truth.T, axis=1))) == 3
    assert np.all(np.max(found @ truth.T, axis=1) > np.cos(np.radians(10)))


@pytest.mark.parametrize("rho", [0.2, 1.0, 3.0])
def test_group_solver_matches_nonnegative_orthogonal_closed_form(rho):
    from isaac_audio_sensors.core.plugins._multisource_sparse import fit_groups

    observed = np.array([[2, -1, 0.02, 3, -2], [1, 3, 0.01, -1, 4]], dtype=float)
    dictionary = np.broadcast_to(np.eye(5), (2, 5, 5))
    expected = np.maximum(observed, 0)
    expected[:, :-2] *= np.maximum(
        1 - 0.5 / np.linalg.norm(expected[:, :-2], axis=0), 0
    )
    fitted, diagnostic = fit_groups(dictionary, observed, 0.5, rho=rho, iterations=500)
    np.testing.assert_allclose(fitted, expected, atol=5e-5)
    assert diagnostic["solver_converged"]
