"""Rotation must change microphone arrivals, not the reported DOA alone."""

from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core.acoustics import (
    free_field_environment,
    shoebox_environment,
)
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.motion import (
    SegmentEntityMotion,
    WindowMotionPlan,
    WindowMotionSegment,
)
from isaac_audio_sensors.core.motion.orientation import interpolate_orientation
from tests.integration.test_analytic_acoustics import _array, _scene, _source
from tests.integration.test_propagation_continuity import window


def yaw(angle):
    return (0.0, 0.0, float(np.sin(angle / 2)), float(np.cos(angle / 2)))


def plan(scene, start, end, rate, source_rate=0.0):
    entities = {}
    for entity in (*scene.sources, *scene.arrays):
        key = getattr(entity, "array_id", None) or entity.source_id
        speed = rate if key == "rig" else source_rate
        entities[key] = SegmentEntityMotion(
            start_position_world_m=entity.position_world,
            end_position_world_m=entity.position_world,
            midpoint_position_world_m=entity.position_world,
            velocity_world_mps=(0.0, 0.0, 0.0),
            velocity_source="derived",
            start_orientation_world_xyzw=yaw(speed * start),
            end_orientation_world_xyzw=yaw(speed * end),
        )
    return WindowMotionPlan(
        sample_rate_hz=scene.arrays[0].sample_rate_hz,
        window_sample_count=round((end - start) * scene.arrays[0].sample_rate_hz),
        segments=(
            WindowMotionSegment(
                index=0,
                start_sample=0,
                end_sample=round((end - start) * scene.arrays[0].sample_rate_hz),
                start_time_s=start,
                end_time_s=end,
                entities=entities,
            ),
        ),
    )


@pytest.mark.parametrize("room", [False, True])
def test_rotation_partition_and_reset(room):
    if room:
        pytest.importorskip("pyroomacoustics")
    environment = (
        shoebox_environment(environment_id="room", dimensions_m=(6.0, 5.0, 3.0))
        if room
        else free_field_environment(environment_id="free")
    )
    scene = _scene(
        environment,
        array=_array(position_world=(2.0, 2.0, 1.0)),
        source=replace(_source((4.0, 2.5, 1.0)), duration_s=1.0),
    )
    backend = AnalyticAcoustics(max_order=int(room))
    backend.window_motion = plan(scene, 0.0, 0.4, 1.5)
    whole = backend.propagate(scene, "rig", window(0.0, 0.4)).samples
    backend.reset()
    pieces = []
    for i in range(8):
        start = i * 0.05
        backend.window_motion = plan(scene, start, start + 0.05, 1.5)
        pieces.append(
            backend.propagate(scene, "rig", window(start, start + 0.05, i)).samples
        )
    np.testing.assert_allclose(
        np.concatenate(pieces, axis=1), whole, atol=2e-7, rtol=2e-4
    )
    static = (
        AnalyticAcoustics(max_order=int(room))
        .propagate(scene, "rig", window(0.0, 0.4))
        .samples
    )
    assert np.linalg.norm(whole - static) / np.linalg.norm(whole) > 0.05


def test_rotating_microphone_and_source_follow_closed_form(tmp_path, monkeypatch):
    sf = pytest.importorskip("soundfile")
    monkeypatch.chdir(tmp_path)
    fs = 48000
    sf.write(
        "tone.wav",
        0.5 * np.sin(2 * np.pi * 800 * np.arange(fs) / fs),
        fs,
        subtype="FLOAT",
    )
    array = _array()
    source = replace(
        _source((3.0, 1.0, 1.0)),
        audio_asset_path="tone.wav",
        duration_s=1.0,
        directivity="cardioid",
        orientation_world_quat=yaw(0),
    )
    scene = _scene(
        free_field_environment(environment_id="free"), array=array, source=source
    )
    backend = AnalyticAcoustics()
    backend.window_motion = plan(scene, 0.0, 0.4, 2.0, source_rate=3.0)
    actual = backend.propagate(scene, "rig", window(0.0, 0.4)).samples[0]
    t = np.arange(len(actual)) / fs
    offset = np.asarray(array.microphones[0].relative_position_m)
    receiver = np.array(array.position_world) + np.column_stack(
        [
            offset[0] * np.cos(2 * t) - offset[1] * np.sin(2 * t),
            offset[0] * np.sin(2 * t) + offset[1] * np.cos(2 * t),
            np.full(len(t), offset[2]),
        ]
    )
    direction = receiver - np.array(source.position_world)
    distance = np.linalg.norm(direction, axis=1)
    te = t - distance / 343
    cosine = (
        direction[:, 0] * np.cos(3 * np.maximum(te, 0))
        + direction[:, 1] * np.sin(3 * np.maximum(te, 0))
    ) / distance
    expected = (
        0.5
        * np.sin(2 * np.pi * 800 * te)
        / (4 * np.pi * distance)
        * (0.5 + 0.5 * cosine)
    )
    np.testing.assert_allclose(actual[2000:], expected[2000:], atol=2e-5, rtol=0.003)


def test_shortest_arc_and_angular_extrapolation():
    from isaac_audio_sensors.core.backends._analytic.arrival import Trajectory

    q = interpolate_orientation(yaw(np.radians(170)), yaw(np.radians(-170)), 0.5)
    assert abs(q[2]) == pytest.approx(1.0)
    np.testing.assert_allclose(interpolate_orientation(q, -q, 0.5), q)
    trajectory = Trajectory()
    trajectory.observe(0.0, (0, 0, 0), None, yaw(0.0))
    trajectory.observe(0.1, (0, 0, 0), None, yaw(0.1))
    np.testing.assert_allclose(
        trajectory.orientation_at(np.array([-0.1, 0.05, 0.2])),
        [yaw(0), yaw(0.05), yaw(0.2)],
        atol=1e-12,
    )


@pytest.mark.parametrize("speed", [-342.999, 0.0, 342.999])
def test_affine_arrival_equation_near_sound_speed(speed):
    from isaac_audio_sensors.core.backends._analytic.arrival import (
        Trajectory,
        retarded_path,
    )

    trajectory = Trajectory()
    trajectory.observe(0.0, (100.0, 1.0, 0.0), (speed, 0.0, 0.0))
    times = np.array([0.01, 0.05, 0.1])
    receiver = np.zeros((3, 3))
    emission, distance, _ = retarded_path(times, receiver, trajectory, 343.0, 16000)
    assert np.all(emission <= times)
    np.testing.assert_allclose(
        np.linalg.norm(receiver - trajectory.at(emission), axis=1),
        distance,
        rtol=1e-11,
        atol=1e-8,
    )
    np.testing.assert_allclose(emission + distance / 343.0, times, rtol=0, atol=1e-9)
