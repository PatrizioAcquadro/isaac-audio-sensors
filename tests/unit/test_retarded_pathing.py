"""Retarded routing semantics with independent segment/time oracles."""

import numpy as np
import pytest

from isaac_audio_sensors.core.backends._analytic.arrival import Trajectory
from tools.native.pathing import Route
from tools.native.retarded_pathing import (
    GeometryHistory,
    RetardedRouteStream,
    routed_emission,
)


def trajectory(position, velocity=(0, 0, 0)):
    t = Trajectory()
    t.observe(0, position, velocity)
    return t


def plane(starts, ends):
    # Infinite screen x=0. Half-open end matches geometry epoch ownership.
    return (starts[:, 0] >= 0) & (ends[:, 0] < 0)


def test_interception_depends_on_flight_time_not_emission_or_reception():
    points = np.array([[[2, 0, 0], [1, 1, 0], [-1, 1, 0], [-2, 0, 0]]], float)
    crossing = (np.sqrt(2) + 1) / 343

    def visible(changes):
        history = GeometryHistory()
        for time, blocked in changes:
            history.append(
                time, plane if blocked else lambda a, b: np.zeros(len(a), bool)
            )
        return bool(history.visible(points, np.array([0.0]))[0])

    assert not visible([(0, False), (crossing - 0.001, True)])
    assert visible([(0, False), (crossing + 0.001, True)])
    assert visible([(0, False), (crossing - 0.002, True), (crossing - 0.001, False)])
    assert not visible([(0, True), (crossing + 0.001, False)])
    assert visible([(0, True), (crossing - 0.001, False)])


def test_moving_endpoints_retarded_equation_and_partitioned_stream():
    pytest.importorskip("scipy")
    fs = 16000
    nodes = np.array([[2, 0, 0], [1, 1, 0], [-1, 1, 0], [-2, 0, 0]], float)
    route = Route(
        (-1, 0, 1, -2),
        nodes,
        float(np.linalg.norm(np.diff(nodes, axis=0), axis=1).sum()),
        1.0,
        (1.0, 1.0, 1.0),
    )
    source = trajectory(nodes[0], (0.4, 0.1, 0))
    mic = trajectory(nodes[-1], (-0.2, 0.05, 0))
    times = np.arange(8000) / fs
    te, dist, _ = routed_emission(times, mic.at(times), source, route, 343, fs)
    np.testing.assert_allclose(te + dist / 343, times, atol=1e-10)
    x = np.sin(2 * np.pi * 400 * times).astype(np.float32)
    x[4000:] = 0
    history = GeometryHistory()
    history.append(0, lambda a, b: np.zeros(len(a), bool))

    def render(sizes):
        stream = RetardedRouteStream(fs, 1, 0.1, lambda eq: np.array([1.0]))
        stream.append(0, x, [[route]])
        return np.concatenate(
            [stream.read(n, source, [mic], history) for n in sizes], axis=1
        )[0]

    received = render([8000])
    split = render([97, 1303, 2511, 4089])
    np.testing.assert_allclose(received, split, atol=1e-7)
    physical = np.sin(2 * np.pi * 400 * te) / (4 * np.pi * dist)
    mask = (te > 0.01) & (te < 0.24)
    np.testing.assert_allclose(received[mask], physical[mask], atol=6e-5)
    assert np.max(abs(received[4000:4200])) > 0.01
    np.testing.assert_allclose(received[4500:], 0, atol=1e-7)


def test_epoch_retirement_preserves_valid_flight_and_reset_discards_it():
    pytest.importorskip("scipy")
    nodes = np.array([[2, 0, 0], [1, 1, 0], [-1, 1, 0], [-2, 0, 0]], float)
    length = np.linalg.norm(np.diff(nodes, axis=0), axis=1).sum()
    route = Route((-1, 0, 1, -2), nodes, float(length), 1.0, (1.0, 1.0, 1.0))
    stream = RetardedRouteStream(16000, 1, 0.1, lambda eq: np.array([1.0, 0.2]))
    stream.append(0, np.r_[1.0, np.zeros(79)], [[route]])
    stream.append(80, np.zeros(720), [[]])
    history = GeometryHistory()
    history.append(0, lambda a, b: np.zeros(len(a), bool))
    output = stream.read(800, trajectory(nodes[0]), [trajectory(nodes[-1])], history)
    assert abs(np.argmax(abs(output)) - length / 343 * 16000) <= 1
    stream.reset()
    assert not stream.epochs and not stream.filters
    assert not stream.tail.pending.any()
    with pytest.raises(ValueError, match="available"):
        stream.read(1, trajectory(nodes[0]), [trajectory(nodes[-1])], history)


def test_geometry_history_releases_drained_snapshots_and_isolates_environments():
    released = []
    first, second = GeometryHistory(), GeometryHistory()
    first.append(0, plane, lambda: released.append(0))
    first.append(0.01, lambda a, b: np.zeros(len(a), bool), lambda: released.append(1))
    second.append(0, plane)
    points = np.array([[[0.1, 0, 0], [-0.1, 0, 0]]])
    assert first.visible(points, np.array([0.02]))[0]
    assert not second.visible(points, np.array([0.02]))[0]
    first.prune(0.005)
    assert not released
    first.prune(0.02)
    assert released == [0]
    with pytest.raises(ValueError, match="cover"):
        first.visible(points, np.array([0.0]))
    first.close()
    first.close()
    assert released == [0, 1]
    assert len(second.epochs) == 1
