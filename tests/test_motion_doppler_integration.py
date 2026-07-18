"""S3.1 end-to-end teleport no-spike and off-state backend tests."""

from __future__ import annotations

import json

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.effects import EffectsConfig, MotionEffectsConfig
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.motion import PoseHistory
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
)
from isaac_audio_sensors.isaac.stage_snapshot import enrich_snapshot_motion


def _effects(enabled: bool = True) -> EffectsConfig:
    return EffectsConfig(
        motion=MotionEffectsConfig(derive_velocity_from_poses=enabled)
    )


def _array(position=(1.0, 1.0, 1.0)):
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
        position_world=position,
        sample_rate_hz=8_000,
    )


def _source(position):
    return AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Speaker",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=10.0,
        gain_db=0.0,
    )


def _scene(position, *, room=False):
    array = _array()
    return AudioSceneSnapshot(
        stage_id="motion_teleport",
        timestamp_ms=0,
        sources=(_source(position),),
        arrays=(array,),
        room=(
            RoomAcousticsSpec(
                room_id="motion_room",
                dimensions_m=(8.0, 5.0, 3.0),
                absorption=0.35,
                max_order=0,
            )
            if room
            else None
        ),
    )


def _teleport_snapshot(*, room=False):
    history = PoseHistory()
    config = _effects().motion
    first, _ = enrich_snapshot_motion(
        _scene((2.0, 1.0, 1.0), room=room),
        selected_array_id="rig",
        time_s=1.0,
        pose_history=history,
        motion_config=config,
    )
    second, _ = enrich_snapshot_motion(
        _scene((2.0, 1.0, 1.0), room=room),
        selected_array_id="rig",
        time_s=1.05,
        pose_history=history,
        motion_config=config,
    )
    teleport, diagnostics = enrich_snapshot_motion(
        _scene((5.0, 1.0, 1.0), room=room),
        selected_array_id="rig",
        time_s=1.10,
        pose_history=history,
        motion_config=config,
    )
    assert first.sources[0].velocity_world_mps is None
    assert second.sources[0].velocity_world_mps == (0.0, 0.0, 0.0)
    assert teleport.sources[0].velocity_world_mps is None
    assert diagnostics["speaker"] == "none:teleport"
    assert diagnostics["rig"] == "derived"
    return teleport, diagnostics


def _window() -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=1.10,
        end_time_s=1.12,
        timestamp_ms=1_100,
        sample_rate_hz=8_000,
        frame_index=2,
    )


def _frame_bytes(frame) -> bytes:
    return (
        json.dumps(
            frame_to_trace_dict(frame),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def test_tdoa_teleport_frame_has_exact_unity_central_and_per_mic_factors():
    scene, diagnostics = _teleport_snapshot()
    sensor = scene.array_by_id("rig")
    frame = TdoaSyntheticBackend(effects=_effects()).simulate(
        scene, sensor, _window()
    )
    detection = frame.detections[0]
    assert diagnostics["speaker"] == "none:teleport"
    assert detection.diagnostics["doppler_factor"] == 1.0
    assert detection.diagnostics["per_mic_doppler_factor"] == dict.fromkeys(
        (mic.mic_id for mic in sensor.microphones), 1.0
    )
    assert detection.diagnostics["doppler_waveform_rendered"] is False


def test_enabled_first_sample_with_both_velocities_absent_records_unity():
    history = PoseHistory()
    scene, diagnostics = enrich_snapshot_motion(
        _scene((2.0, 1.0, 1.0)),
        selected_array_id="rig",
        time_s=1.0,
        pose_history=history,
        motion_config=_effects().motion,
    )
    frame = TdoaSyntheticBackend(effects=_effects()).simulate(
        scene, scene.array_by_id("rig"), _window()
    )
    detection = frame.detections[0]
    assert diagnostics == {
        "speaker": "none:first_sample",
        "rig": "none:first_sample",
    }
    assert detection.diagnostics["doppler_factor"] == 1.0
    assert set(detection.diagnostics["per_mic_doppler_factor"].values()) == {1.0}
    assert detection.diagnostics["doppler_waveform_rendered"] is False


def test_tdoa_motion_off_state_is_byte_identical_and_omits_doppler():
    scene = _scene((2.0, 1.0, 1.0))
    sensor = scene.array_by_id("rig")
    baseline = TdoaSyntheticBackend().simulate(scene, sensor, _window())
    explicit_disabled = TdoaSyntheticBackend(effects=_effects(False)).simulate(
        scene, sensor, _window()
    )
    assert _frame_bytes(baseline) == _frame_bytes(explicit_disabled)
    assert "doppler_factor" not in baseline.detections[0].diagnostics
    assert "doppler_factor" not in explicit_disabled.detections[0].diagnostics
    assert "motion" not in baseline.diagnostics
    assert "motion" not in explicit_disabled.diagnostics


class _CaptureSink:
    def __init__(self):
        self.mixture = None

    def write_frame_mixture(
        self,
        *,
        frame_id,
        mixture,
        sample_rate_hz,
        mic_ids,
        window_sample_count,
    ):
        del sample_rate_hz, mic_ids, window_sample_count
        self.mixture = np.array(mixture, copy=True)
        return WaveformWriteResult(
            paths=(f"capture://{frame_id}.wav",),
            diagnostics={"mode": "capture"},
        )


def test_room_teleport_frame_has_unity_factor_and_never_resamples(monkeypatch):
    pytest.importorskip("pyroomacoustics")
    import isaac_audio_sensors.core.backends.room_acoustics as room_module

    scene, diagnostics = _teleport_snapshot(room=True)
    sensor = scene.array_by_id("rig")

    def _unexpected_resample(*args, **kwargs):
        del args, kwargs
        raise AssertionError("teleport frame must not Doppler-resample")

    monkeypatch.setattr(room_module, "_doppler_resampled_signal", _unexpected_resample)
    sink = _CaptureSink()
    frame = RoomAcousticsBackend(
        effects=_effects(),
        waveform_writer=sink,
    ).simulate(scene, sensor, _window())
    detection = frame.detections[0]
    assert diagnostics["speaker"] == "none:teleport"
    assert detection.diagnostics["doppler_factor"] == 1.0
    assert detection.diagnostics["doppler_waveform_rendered"] is False
    assert sink.mixture is not None


def test_room_motion_off_state_frame_and_waveform_are_byte_identical():
    pytest.importorskip("pyroomacoustics")
    scene = _scene((2.0, 1.0, 1.0), room=True)
    sensor = scene.array_by_id("rig")
    baseline_sink = _CaptureSink()
    disabled_sink = _CaptureSink()
    baseline = RoomAcousticsBackend(waveform_writer=baseline_sink).simulate(
        scene, sensor, _window()
    )
    disabled = RoomAcousticsBackend(
        waveform_writer=disabled_sink,
        effects=_effects(False),
    ).simulate(scene, sensor, _window())
    assert _frame_bytes(baseline) == _frame_bytes(disabled)
    assert baseline_sink.mixture.tobytes() == disabled_sink.mixture.tobytes()
    assert "motion" not in baseline.diagnostics
    assert "motion" not in disabled.diagnostics
