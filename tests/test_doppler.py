"""Doppler tests: factor math, L1 metadata, and L2 resampled waveforms."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    _doppler_resampled_signal,
)
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.doppler import doppler_factor, source_doppler_factor
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
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
    )
    frame = TdoaSyntheticBackend().simulate(scene, array, _window())

    by_source = {
        detection.source_id: detection for detection in frame.detections
    }
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


def test_doppler_resampled_signal_scales_length_and_pitch():
    sample_rate_hz = 48_000
    factor = 343.0 / (343.0 - 30.0)
    time_s = np.arange(sample_rate_hz, dtype=float) / sample_rate_hz
    tone = np.sin(2.0 * math.pi * 440.0 * time_s)

    shifted = _doppler_resampled_signal(tone, factor=factor)

    assert shifted.size == pytest.approx(tone.size / factor, rel=1e-3)
    spectrum = np.abs(np.fft.rfft(shifted))
    frequencies = np.fft.rfftfreq(shifted.size, d=1.0 / sample_rate_hz)
    peak_hz = float(frequencies[int(np.argmax(spectrum))])
    assert peak_hz == pytest.approx(440.0 * factor, abs=2.0)


class _CaptureSink:
    """In-memory waveform sink capturing per-frame mixtures."""

    def __init__(self) -> None:
        self.mixtures: list[np.ndarray] = []

    def write_frame_mixture(
        self,
        *,
        frame_id: str,
        mixture: np.ndarray,
        sample_rate_hz: int,
        mic_ids: tuple[str, ...],
        window_sample_count: int,
    ) -> WaveformWriteResult:
        self.mixtures.append(np.asarray(mixture, dtype=float))
        return WaveformWriteResult(paths=())

    def close(self) -> None:
        pass


def _anechoic_scene(source: AudioSourceSpec, array) -> AudioSceneSnapshot:
    return AudioSceneSnapshot(
        stage_id="doppler_l2",
        timestamp_ms=0,
        sources=(source,),
        arrays=(array,),
        room=RoomAcousticsSpec(
            room_id="anechoic_room",
            dimensions_m=(8.0, 6.0, 3.0),
            absorption=0.9,
            max_order=0,
            origin_m=(-2.0, -3.0, -1.5),
        ),
    )


def _dominant_frequency_hz(mixture: np.ndarray, *, sample_rate_hz: int) -> float:
    spectrum = np.abs(np.fft.rfft(mixture[0]))
    frequencies = np.fft.rfftfreq(mixture.shape[1], d=1.0 / sample_rate_hz)
    band = (frequencies > 100.0) & (frequencies < 3000.0)
    band_index = int(np.argmax(spectrum[band]))
    return float(frequencies[band][band_index])


@pytest.mark.skipif(
    not RoomAcousticsBackend.is_available(),
    reason="pyroomacoustics is not installed in this environment.",
)
def test_room_backend_renders_doppler_shifted_waveforms():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    position = (3.0, 0.0, 0.0)
    velocity = (-30.0, 0.0, 0.0)
    expected_factor = SPEED_OF_SOUND_MPS / (SPEED_OF_SOUND_MPS - 30.0)

    static_sink = _CaptureSink()
    static_frame = RoomAcousticsBackend(waveform_writer=static_sink).simulate(
        _anechoic_scene(_moving_source("tone", position, None), array),
        array,
        _window(),
    )
    moving_sink = _CaptureSink()
    moving_frame = RoomAcousticsBackend(waveform_writer=moving_sink).simulate(
        _anechoic_scene(_moving_source("tone", position, velocity), array),
        array,
        _window(),
    )

    static_hz = _dominant_frequency_hz(static_sink.mixtures[0], sample_rate_hz=48_000)
    moving_hz = _dominant_frequency_hz(moving_sink.mixtures[0], sample_rate_hz=48_000)
    assert moving_hz / static_hz == pytest.approx(expected_factor, rel=0.02)

    moving_detection = moving_frame.detections[0]
    assert moving_detection.diagnostics["doppler_factor"] == pytest.approx(
        expected_factor, rel=1e-6
    )
    assert moving_detection.diagnostics["doppler_waveform_rendered"] is True
    assert "doppler_factor" not in static_frame.detections[0].diagnostics


@pytest.mark.skipif(
    not RoomAcousticsBackend.is_available(),
    reason="pyroomacoustics is not installed in this environment.",
)
def test_room_backend_zero_velocity_matches_static_signals():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    position = (3.0, 0.0, 0.0)

    static_frame = RoomAcousticsBackend().simulate(
        _anechoic_scene(_moving_source("tone", position, None), array),
        array,
        _window(),
    )
    zero_velocity_frame = RoomAcousticsBackend().simulate(
        _anechoic_scene(_moving_source("tone", position, (0.0, 0.0, 0.0)), array),
        array,
        _window(),
    )

    static_detection = static_frame.detections[0]
    zero_detection = zero_velocity_frame.detections[0]
    assert zero_detection.diagnostics["doppler_factor"] == 1.0
    assert zero_detection.diagnostics["doppler_waveform_rendered"] is False
    assert zero_detection.per_mic_rms == static_detection.per_mic_rms
    assert zero_detection.per_mic_delay_s == static_detection.per_mic_delay_s
    assert zero_detection.doa == static_detection.doa
