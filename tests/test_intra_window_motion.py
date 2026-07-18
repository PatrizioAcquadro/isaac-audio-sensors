"""Frozen S3.2 intra-window interpolation and room-assembly tests."""

from __future__ import annotations

import json
import math
import types
from dataclasses import replace

import numpy as np
import pytest

import isaac_audio_sensors.core.backends.room_acoustics as room_module
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.effects import EffectsConfig, MotionEffectsConfig
from isaac_audio_sensors.core.effects.config import (
    UnsupportedEffectError,
    validate_effects_config,
    validate_motion_effects_config,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.motion import (
    EntityMotionInput,
    PoseHistory,
    build_window_motion,
    segment_boundaries,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
)
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor

R = 48_000
W = 2_400
P = 8
T = W / R


def _motion_effects(segments: int) -> EffectsConfig:
    return EffectsConfig(
        motion=MotionEffectsConfig(
            derive_velocity_from_poses=True,
            segments_per_window=segments,
        )
    )


def _plan_for_trajectory(position, velocity, *, segments: int = P):
    history = PoseHistory(teleport_speed_threshold_mps=100.0)
    history.observe("source", 0.0, position(0.0))
    result = history.observe("source", T, position(T))
    assert result.velocity_world_mps is not None
    history.observe("array", 0.0, (4.0, 2.0, 1.0))
    array_result = history.observe("array", T, (4.0, 2.0, 1.0))
    assert array_result.velocity_world_mps == (0.0, 0.0, 0.0)
    plan = build_window_motion(
        history,
        entities={
            "source": EntityMotionInput(
                position_world_m=position(T),
                velocity_world_mps=velocity,
                velocity_source="derived",
            ),
            "array": EntityMotionInput(
                position_world_m=(4.0, 2.0, 1.0),
                velocity_world_mps=(0.0, 0.0, 0.0),
                velocity_source="derived",
            ),
        },
        start_time_s=0.0,
        sample_rate_hz=R,
        window_sample_count=W,
        segments_per_window=segments,
    )
    return history, plan


def _position_errors(position, plan):
    interpolation_error = 0.0
    for time_s in np.linspace(0.0, T, 1_001):
        observed = _interpolate_endpoints(
            position(0.0), position(T), float(time_s / T)
        )
        interpolation_error = max(
            interpolation_error,
            _distance(observed, position(float(time_s))),
        )
    held_error = 0.0
    for segment in plan.segments:
        held = segment.entities["source"].midpoint_position_world_m
        for sample in range(segment.start_sample, segment.end_sample):
            held_error = max(held_error, _distance(held, position(sample / R)))
    return interpolation_error, held_error


def _interpolate_endpoints(start, end, weight):
    return tuple(
        start[index] + weight * (end[index] - start[index])
        for index in range(3)
    )


def _distance(left, right):
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def test_segment_division_longer_remainders_first_and_accounts_every_sample():
    assert segment_boundaries(10, 4) == (0, 3, 6, 8, 10)
    assert segment_boundaries(W, P) == tuple(range(0, W + 1, 300))
    assert segment_boundaries(64, 64) == tuple(range(65))
    with pytest.raises(ValueError, match="segments_per_window"):
        segment_boundaries(4, 5)


@pytest.mark.parametrize("value", [0, 65, -1, True, 1.5])
def test_segments_configuration_range_is_exact_and_rejects_bool(value):
    with pytest.raises(ConfigValidationError, match="segments_per_window"):
        validate_motion_effects_config(
            MotionEffectsConfig(segments_per_window=value)
        )


def test_segments_greater_than_window_reject_before_backend_output():
    with pytest.raises(UnsupportedEffectError, match="window_sample_count"):
        validate_effects_config(
            _motion_effects(8),
            microphone_orders=(("left", "right"),),
            sample_rate_hz=R,
            backend_id="room_acoustics",
            runtime_profile="waveform_fidelity",
            sample_count=7,
        )


def test_linear_interpolation_and_midpoint_hold_obey_frozen_bound():
    def position(time_s):
        return (1.0 + 20.0 * time_s, -2.0, 0.5)

    _history, plan = _plan_for_trajectory(position, (20.0, 0.0, 0.0))
    interpolation, held = _position_errors(position, plan)
    assert interpolation <= 1e-9
    assert held <= 0.062500001


def test_constant_acceleration_interpolation_obeys_frozen_inequalities():
    def position(time_s):
        return (12.0 * time_s + 4.0 * time_s**2, 0.0, 0.0)

    _history, plan = _plan_for_trajectory(position, (12.4, 0.0, 0.0))
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

    _history, plan = _plan_for_trajectory(position, (0.0, 20.0, 0.0))
    interpolation, held = _position_errors(position, plan)
    assert interpolation <= 40.0 * T**2 / 8.0 + 1e-9
    assert held <= 0.0751953135


def test_phase_cursor_continuity_residual_is_below_two_e_minus_six():
    factors = (0.95, 0.97, 0.99, 1.00, 1.01, 1.03, 1.04, 1.05)
    lengths = (300,) * 8
    samples = np.arange(W, dtype=float)
    source = (
        np.sin(2.0 * math.pi * 700.0 * samples / R)
        + 0.6 * np.sin(2.0 * math.pi * 1132.6238 * samples / R)
    ) / 1.6
    observed = room_module._piecewise_phase_signal(
        source,
        factors=factors,
        segment_lengths=lengths,
    )
    reference = np.zeros(W, dtype=float)
    cursor = 0.0
    for index in range(W):
        segment = index // 300
        lower = math.floor(cursor)
        fraction = cursor - lower
        first = source[lower] if lower < W else 0.0
        second = source[lower + 1] if lower + 1 < W else 0.0
        reference[index] = first + fraction * (second - first)
        cursor += factors[segment]
    signal_pairs = [(observed, reference)]
    for delay, decay in ((0, 0.7), (3, 0.5), (7, 0.35), (11, 0.2)):
        response = np.zeros(delay + 3, dtype=float)
        response[delay:] = (1.0, decay, decay * decay)
        signal_pairs.append(
            (
                np.convolve(observed, response)[:W],
                np.convolve(reference, response)[:W],
            )
        )
    residuals = []
    for observed_signal, reference_signal in signal_pairs:
        peak = max(
            float(np.max(np.abs(observed_signal))),
            float(np.max(np.abs(reference_signal))),
        )
        observed_signal = observed_signal / peak
        reference_signal = reference_signal / peak
        residuals.extend(
            abs(
                (
                    observed_signal[boundary]
                    - observed_signal[boundary - 1]
                )
                - (
                    reference_signal[boundary]
                    - reference_signal[boundary - 1]
                )
            )
            for boundary in range(300, W, 300)
        )
    assert max(residuals) <= 2e-6
    assert observed.shape == (W,)
    assert np.isfinite(observed).all()


@pytest.mark.parametrize("backend", [GeometryBackend, TdoaSyntheticBackend])
def test_l0_l1_explicitly_reject_multiple_segments_before_output(backend):
    scene, array, window = _room_fixture()
    with pytest.raises(UnsupportedEffectError, match="segments_per_window"):
        backend(effects=_motion_effects(2)).simulate(scene, array, window)


def test_segments_one_selects_literal_room_branch_and_is_byte_identical(
    monkeypatch
):
    _install_fake_pyroom(monkeypatch)
    scene, array, window = _room_fixture()
    calls = {"scheduled": 0}
    original_scheduled = room_module._scheduled_window_signal

    def scheduled_spy(*args, **kwargs):
        calls["scheduled"] += 1
        return original_scheduled(*args, **kwargs)

    def forbidden_piecewise(**_kwargs):
        raise AssertionError("segments=1 entered the piecewise branch")

    monkeypatch.setattr(room_module, "_scheduled_window_signal", scheduled_spy)
    monkeypatch.setattr(room_module, "_simulate_piecewise_room", forbidden_piecewise)
    absent = RoomAcousticsBackend(
        effects=EffectsConfig(
            motion=MotionEffectsConfig(derive_velocity_from_poses=True)
        )
    ).simulate(scene, array, window)
    explicit = RoomAcousticsBackend(
        effects=_motion_effects(1)
    ).simulate(scene, array, window)
    absent_bytes = json.dumps(
        frame_to_trace_dict(absent), sort_keys=True, separators=(",", ":")
    ).encode()
    explicit_bytes = json.dumps(
        frame_to_trace_dict(explicit), sort_keys=True, separators=(",", ":")
    ).encode()
    assert absent_bytes == explicit_bytes
    assert calls["scheduled"] == 2
    assert "motion" not in absent.diagnostics


def test_piecewise_room_assembles_exact_window_and_segment_diagnostics(monkeypatch):
    fake = _install_fake_pyroom(monkeypatch)
    scene, array, window = _room_fixture()
    _history, plan = _plan_for_trajectory(
        lambda time_s: (1.0 + 20.0 * time_s, 2.0, 1.0),
        (20.0, 0.0, 0.0),
    )
    sink = _CaptureSink()
    frame = RoomAcousticsBackend(
        effects=_motion_effects(P),
        window_motion=plan,
        waveform_writer=sink,
    ).simulate(scene, array, window)
    assert sink.mixture is not None
    assert sink.mixture.shape[1] >= W
    assert np.isfinite(sink.mixture).all()
    assert frame.diagnostics["motion"]["segments_per_window"] == P
    rows = frame.diagnostics["motion"]["segments"]
    assert len(rows) == P
    assert [row["start_sample"] for row in rows] == list(range(0, W, 300))
    assert all(set(row["doppler_factor_by_source"]) == {"source"} for row in rows)
    assert len(fake.ShoeBox.instances) == P


def test_policy_absent_segments_hold_current_pose_and_use_exact_unity(monkeypatch):
    _install_fake_pyroom(monkeypatch)
    scene, array, window = _room_fixture()
    history = PoseHistory()
    history.observe("source", T, scene.sources[0].position_world)
    history.observe("array", T, array.position_world)
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
        sample_rate_hz=R,
        window_sample_count=W,
        segments_per_window=P,
    )
    frame = RoomAcousticsBackend(
        effects=_motion_effects(P), window_motion=plan
    ).simulate(scene, array, window)
    for row in frame.diagnostics["motion"]["segments"]:
        assert row["doppler_factor_by_source"]["source"] == 1.0
        entity = row["entities"]["source"]
        assert entity["start_position_world_m"] == scene.sources[0].position_world
        assert entity["mid_position_world_m"] == scene.sources[0].position_world


def test_extension_rejects_decrease_before_backend_mutation():
    scene, array, _window = _room_fixture()
    sensor = IsaacAudioArraySensor(
        array_id=array.array_id,
        backend="geometry_only",
        stage_snapshot=replace(scene, room=None),
        update_period_s=0.05,
    ).start()
    first = sensor.update(sim_time_s=1.0)
    assert sensor._frame_index == 1
    with pytest.raises(ValueError, match="non-monotonic"):
        sensor.update(sim_time_s=0.9)
    sensor.effects = _motion_effects(2)
    with pytest.raises(ValueError, match="duplicates or overlaps"):
        sensor.update(sim_time_s=1.0, force=True)
    assert sensor.latest_frame is first
    assert sensor._frame_index == 1


def _room_fixture():
    array = create_microphone_array(
        array_id="array",
        prim_path="/World/Array",
        layout_name="quad_front",
        position_world=(4.0, 2.0, 1.0),
        sample_rate_hz=R,
    )
    source = AudioSourceSpec(
        source_id="source",
        prim_path="/World/Source",
        class_label="tone",
        audio_asset_path="generated://deterministic_pulse",
        position_world=(2.0, 2.0, 1.0),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )
    scene = AudioSceneSnapshot(
        stage_id="s3_2",
        timestamp_ms=0,
        sources=(source,),
        arrays=(array,),
        room=RoomAcousticsSpec(
            room_id="room",
            dimensions_m=(8.0, 6.0, 3.0),
            absorption=0.35,
            max_order=0,
        ),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=T,
        timestamp_ms=0,
        sample_rate_hz=R,
        frame_index=0,
    )
    return scene, array, window


class _CaptureSink:
    def __init__(self) -> None:
        self.mixture = None

    def write_frame_mixture(self, **kwargs):
        self.mixture = np.asarray(kwargs["mixture"], dtype=float).copy()
        return WaveformWriteResult(paths=())

    def close(self):
        return None


def _install_fake_pyroom(monkeypatch):
    fake = types.ModuleType("pyroomacoustics")
    fake.__version__ = "s3.2-fake"
    fake.Material = lambda absorption: absorption
    fake.MicrophoneArray = _FakeMicrophoneArray
    fake.ShoeBox = _FakeShoeBox
    _FakeShoeBox.instances = []
    monkeypatch.setitem(__import__("sys").modules, "pyroomacoustics", fake)
    return fake


class _FakeMicrophoneArray:
    def __init__(self, positions, fs):
        self.R = np.asarray(positions, dtype=float)
        self.fs = fs
        self.signals = np.zeros((self.R.shape[1], 0))


class _FakeShoeBox:
    instances = []

    def __init__(self, dimensions, *, fs, max_order=0, c=343.0, **kwargs):
        del dimensions, max_order, kwargs
        self.fs = fs
        self.c = c
        self.sources = []
        self.mic_array = None
        self.rir = []
        type(self).instances.append(self)

    def add_source(self, position, signal):
        self.sources.append((np.asarray(position), np.asarray(signal)))

    def add_microphone_array(self, microphones):
        self.mic_array = microphones

    def compute_rir(self):
        self.rir = []
        for mic_position in self.mic_array.R.T:
            per_source = []
            for source_position, _signal in self.sources:
                delay = round(
                    np.linalg.norm(source_position - mic_position)
                    / self.c
                    * self.fs
                )
                impulse = np.zeros(max(0, delay) + 8)
                impulse[max(0, delay)] = 1.0
                per_source.append(impulse)
            self.rir.append(per_source)

    def simulate(self, return_premix=False):
        convolved = [
            [
                np.convolve(signal, self.rir[mic][source])
                for mic in range(self.mic_array.R.shape[1])
            ]
            for source, (_position, signal) in enumerate(self.sources)
        ]
        length = max(len(signal) for source in convolved for signal in source)
        premix = np.zeros((len(self.sources), self.mic_array.R.shape[1], length))
        for source, per_mic in enumerate(convolved):
            for mic, signal in enumerate(per_mic):
                premix[source, mic, : len(signal)] = signal
        self.mic_array.signals = premix.sum(axis=0)
        return premix if return_premix else None
