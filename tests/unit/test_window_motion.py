from __future__ import annotations

import json
import math

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.effects import EffectsConfig, MotionEffectsConfig
from isaac_audio_sensors.core.effects.validation import (
    UnsupportedEffectError,
    validate_effects_config,
    validate_motion_effects_config,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.motion import (
    EntityMotionInput,
    PoseHistory,
    build_window_motion,
    segment_boundaries,
)
from tests.helpers import (
    MOTION_SEGMENTS,
    SAMPLE_RATE_HZ,
    WINDOW_SAMPLE_COUNT,
    CaptureSink,
    install_fake_pyroom,
    motion_plan,
    motion_room_fixture,
)

WINDOW_DURATION_S = WINDOW_SAMPLE_COUNT / SAMPLE_RATE_HZ


def _motion_effects(segments: int) -> EffectsConfig:
    return EffectsConfig(
        motion=MotionEffectsConfig(
            derive_velocity_from_poses=True,
            segments_per_window=segments,
        )
    )


def _position_errors(position, plan):
    interpolation_error = 0.0
    for time_s in np.linspace(0.0, WINDOW_DURATION_S, 1_001):
        observed = _interpolate_endpoints(
            position(0.0),
            position(WINDOW_DURATION_S),
            float(time_s / WINDOW_DURATION_S),
        )
        interpolation_error = max(
            interpolation_error,
            _distance(observed, position(float(time_s))),
        )
    held_error = 0.0
    for segment in plan.segments:
        held = segment.entities["source"].midpoint_position_world_m
        for sample in range(segment.start_sample, segment.end_sample):
            held_error = max(
                held_error,
                _distance(held, position(sample / SAMPLE_RATE_HZ)),
            )
    return interpolation_error, held_error


def _interpolate_endpoints(start, end, weight):
    return tuple(
        start[index] + weight * (end[index] - start[index]) for index in range(3)
    )


def _distance(left, right):
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def test_segment_division_longer_remainders_first_and_accounts_every_sample():
    assert segment_boundaries(10, 4) == (0, 3, 6, 8, 10)
    assert segment_boundaries(WINDOW_SAMPLE_COUNT, MOTION_SEGMENTS) == tuple(
        range(0, WINDOW_SAMPLE_COUNT + 1, 300)
    )
    assert segment_boundaries(64, 64) == tuple(range(65))
    with pytest.raises(ValueError, match="segments_per_window"):
        segment_boundaries(4, 5)


@pytest.mark.parametrize("value", [0, 65, -1, True, 1.5])
def test_segments_configuration_range_is_exact_and_rejects_bool(value):
    with pytest.raises(ConfigValidationError, match="segments_per_window"):
        validate_motion_effects_config(MotionEffectsConfig(segments_per_window=value))


def test_segments_greater_than_window_reject_before_backend_output():
    with pytest.raises(UnsupportedEffectError, match="window_sample_count"):
        validate_effects_config(
            _motion_effects(8),
            microphone_orders=(("left", "right"),),
            sample_rate_hz=SAMPLE_RATE_HZ,
            backend_id="room_acoustics",
            runtime_profile="waveform_fidelity",
            sample_count=7,
        )


def test_linear_interpolation_and_midpoint_hold_obey_frozen_bound():
    def position(time_s):
        return (1.0 + 20.0 * time_s, -2.0, 0.5)

    _history, plan = motion_plan(position, (20.0, 0.0, 0.0))
    interpolation, held = _position_errors(position, plan)
    assert interpolation <= 1e-9
    assert held <= 0.062500001


def test_constant_acceleration_interpolation_obeys_frozen_inequalities():
    def position(time_s):
        return (12.0 * time_s + 4.0 * time_s**2, 0.0, 0.0)

    _history, plan = motion_plan(position, (12.4, 0.0, 0.0))
    interpolation, held = _position_errors(position, plan)
    assert interpolation <= 0.002500001
    assert held <= 0.0412890635


def test_circular_speed_dependent_error_obeys_frozen_bound():
    def position(time_s):
        return (
            10.0 * math.cos(2.0 * time_s),
            10.0 * math.sin(2.0 * time_s),
            0.0,
        )

    _history, plan = motion_plan(position, (0.0, 20.0, 0.0))
    interpolation, held = _position_errors(position, plan)
    assert interpolation <= 40.0 * WINDOW_DURATION_S**2 / 8.0 + 1e-9
    assert held <= 0.0751953135


@pytest.mark.parametrize("backend", [GeometryBackend, TdoaSyntheticBackend])
def test_l0_l1_explicitly_reject_multiple_segments_before_output(backend):
    scene, array, window = motion_room_fixture()
    with pytest.raises(UnsupportedEffectError, match="segments_per_window"):
        backend(effects=_motion_effects(2)).simulate(scene, array.array_id, window)


def test_segments_one_is_byte_identical_to_default_motion_config(monkeypatch):
    install_fake_pyroom(monkeypatch)
    scene, array, window = motion_room_fixture()
    absent = RoomAcousticsBackend(
        effects=EffectsConfig(
            motion=MotionEffectsConfig(derive_velocity_from_poses=True)
        )
    ).simulate(scene, array.array_id, window)
    explicit = RoomAcousticsBackend(effects=_motion_effects(1)).simulate(
        scene, array.array_id, window
    )
    absent_bytes = json.dumps(
        frame_to_trace_dict(absent), sort_keys=True, separators=(",", ":")
    ).encode()
    explicit_bytes = json.dumps(
        frame_to_trace_dict(explicit), sort_keys=True, separators=(",", ":")
    ).encode()
    assert absent_bytes == explicit_bytes
    assert "motion" not in absent.diagnostics


def test_piecewise_room_assembles_exact_window_and_segment_diagnostics(monkeypatch):
    fake = install_fake_pyroom(monkeypatch)
    scene, array, window = motion_room_fixture()
    _history, plan = motion_plan(
        lambda time_s: (1.0 + 20.0 * time_s, 2.0, 1.0),
        (20.0, 0.0, 0.0),
    )
    sink = CaptureSink()
    frame = RoomAcousticsBackend(
        effects=_motion_effects(MOTION_SEGMENTS),
        window_motion=plan,
        waveform_writer=sink,
    ).simulate(scene, array.array_id, window)
    mixture = sink.calls[0]["mixture"]
    assert mixture.shape[1] >= WINDOW_SAMPLE_COUNT
    assert np.isfinite(mixture).all()
    assert frame.diagnostics["motion"]["segments_per_window"] == MOTION_SEGMENTS
    rows = frame.diagnostics["motion"]["segments"]
    assert len(rows) == MOTION_SEGMENTS
    assert [row["start_sample"] for row in rows] == list(
        range(0, WINDOW_SAMPLE_COUNT, 300)
    )
    assert all(set(row["doppler_factor_by_source"]) == {"source"} for row in rows)
    assert len(fake.ShoeBox.instances) == MOTION_SEGMENTS


def test_policy_absent_segments_hold_current_pose_and_use_exact_unity(monkeypatch):
    install_fake_pyroom(monkeypatch)
    scene, array, window = motion_room_fixture()
    history = PoseHistory()
    history.observe("source", WINDOW_DURATION_S, scene.sources[0].position_world)
    history.observe("array", WINDOW_DURATION_S, array.position_world)
    plan = build_window_motion(
        history,
        entities={
            "source": EntityMotionInput(
                position_world_m=scene.sources[0].position_world,
                velocity_world_mps=None,
                velocity_source="none:teleport",
            ),
            "array": EntityMotionInput(
                position_world_m=array.position_world,
                velocity_world_mps=None,
                velocity_source="none:stale_pose",
            ),
        },
        start_time_s=0.0,
        sample_rate_hz=SAMPLE_RATE_HZ,
        window_sample_count=WINDOW_SAMPLE_COUNT,
        segments_per_window=MOTION_SEGMENTS,
    )
    frame = RoomAcousticsBackend(
        effects=_motion_effects(MOTION_SEGMENTS), window_motion=plan
    ).simulate(scene, array.array_id, window)
    for row in frame.diagnostics["motion"]["segments"]:
        assert row["doppler_factor_by_source"]["source"] == 1.0
        entity = row["entities"]["source"]
        assert entity["start_position_world_m"] == scene.sources[0].position_world
        assert entity["mid_position_world_m"] == scene.sources[0].position_world
