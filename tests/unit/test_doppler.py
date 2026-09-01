from __future__ import annotations

from dataclasses import replace

import pytest

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.motion.doppler import (
    doppler_factor,
    source_doppler_factor,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)

SPEED_OF_SOUND_MPS = 343.0


def _moving_source(
    source_id: str,
    position: tuple[float, float, float],
    velocity: tuple[float, float, float] | None,
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/Sources/{source_id}",
        class_label="Vehicle",
        audio_asset_path="generated://deterministic_pulse",
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=None,
        gain_db=0.0,
        velocity_world_mps=velocity,
    )


def _window() -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=0,
        sample_rate_hz=48_000,
    )


def test_doppler_factor_matches_closed_form():
    closing = doppler_factor(
        source_position=(10.0, 0.0, 0.0),
        listener_position=(0.0, 0.0, 0.0),
        source_velocity=(-20.0, 0.0, 0.0),
        listener_velocity=None,
        speed_of_sound_mps=SPEED_OF_SOUND_MPS,
    )
    assert closing == pytest.approx(SPEED_OF_SOUND_MPS / (SPEED_OF_SOUND_MPS - 20.0))

    receding = doppler_factor(
        source_position=(10.0, 0.0, 0.0),
        listener_position=(0.0, 0.0, 0.0),
        source_velocity=(20.0, 0.0, 0.0),
        listener_velocity=None,
        speed_of_sound_mps=SPEED_OF_SOUND_MPS,
    )
    assert receding == pytest.approx(SPEED_OF_SOUND_MPS / (SPEED_OF_SOUND_MPS + 20.0))

    listener_closing = doppler_factor(
        source_position=(10.0, 0.0, 0.0),
        listener_position=(0.0, 0.0, 0.0),
        source_velocity=None,
        listener_velocity=(15.0, 0.0, 0.0),
        speed_of_sound_mps=SPEED_OF_SOUND_MPS,
    )
    assert listener_closing == pytest.approx(
        (SPEED_OF_SOUND_MPS + 15.0) / SPEED_OF_SOUND_MPS
    )

    perpendicular = doppler_factor(
        source_position=(10.0, 0.0, 0.0),
        listener_position=(0.0, 0.0, 0.0),
        source_velocity=(0.0, 25.0, 0.0),
        listener_velocity=None,
        speed_of_sound_mps=SPEED_OF_SOUND_MPS,
    )
    assert perpendicular == pytest.approx(1.0)

    coincident = doppler_factor(
        source_position=(0.0, 0.0, 0.0),
        listener_position=(0.0, 0.0, 0.0),
        source_velocity=(50.0, 0.0, 0.0),
        listener_velocity=None,
        speed_of_sound_mps=SPEED_OF_SOUND_MPS,
    )
    assert coincident == 1.0

    supersonic = doppler_factor(
        source_position=(10.0, 0.0, 0.0),
        listener_position=(0.0, 0.0, 0.0),
        source_velocity=(-400.0, 0.0, 0.0),
        listener_velocity=None,
        speed_of_sound_mps=SPEED_OF_SOUND_MPS,
    )
    assert supersonic == 8.0


def test_source_doppler_factor_is_none_without_velocities():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
    )
    static = _moving_source("static", (5.0, 0.0, 0.0), None)
    assert (
        source_doppler_factor(static, array, speed_of_sound_mps=SPEED_OF_SOUND_MPS)
        is None
    )

    moving_array = replace(array, velocity_world_mps=(10.0, 0.0, 0.0))
    factor = source_doppler_factor(
        static, moving_array, speed_of_sound_mps=SPEED_OF_SOUND_MPS
    )
    assert factor == pytest.approx((SPEED_OF_SOUND_MPS + 10.0) / SPEED_OF_SOUND_MPS)


def test_tdoa_backend_emits_doppler_metadata_only_with_velocity():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    moving = _moving_source("mover", (10.0, 0.0, 0.0), (-20.0, 0.0, 0.0))
    static = _moving_source("static", (0.0, 5.0, 0.0), None)
    scene = AudioSceneSnapshot(
        stage_id="doppler_l1",
        timestamp_ms=0,
        sources=(moving, static),
        arrays=(array,),
        environment=free_field_environment(environment_id="doppler_free_field"),
    )
    frame = TdoaSyntheticBackend().simulate(scene, array.array_id, _window())

    by_source = {detection.source_id: detection for detection in frame.detections}
    mover = by_source["mover"].diagnostics
    expected = SPEED_OF_SOUND_MPS / (SPEED_OF_SOUND_MPS - 20.0)
    assert mover["doppler_factor"] == pytest.approx(expected, rel=1e-9)
    assert mover["doppler_waveform_rendered"] is False
    assert set(mover["per_mic_doppler_factor"]) == {
        "front",
        "right",
        "rear",
        "left",
    }
    for value in mover["per_mic_doppler_factor"].values():
        assert value == pytest.approx(expected, rel=1e-2)

    assert "doppler_factor" not in by_source["static"].diagnostics
    assert "per_mic_doppler_factor" not in by_source["static"].diagnostics
