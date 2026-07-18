"""Fixed-seed regression tests for noise-aware SRP confidence."""

from __future__ import annotations

import math
from dataclasses import astuple

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsSrpBackend
from isaac_audio_sensors.core.doa.srp_phat import (
    SrpPhatResult,
    srp_phat_confidence,
    srp_phat_direction,
)
from isaac_audio_sensors.core.effects.channel_response import fractional_delay
from isaac_audio_sensors.core.effects.directivity import source_polar_gain
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    microphone_layout,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneSpec,
    RoomAcousticsSpec,
)

SAMPLE_RATE_HZ = 48_000
SAMPLE_COUNT = 65_536
SOURCE_POSITION = (2.0, 4.0, 1.5)
ARRAY_CENTER = (6.0, 4.0, 1.5)
LADDER_QUATERNIONS = (
    (0.0, 0.0, 0.0, 1.0),
    (0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5)),
    (0.0, 0.0, math.sqrt(3.0) / 2.0, 0.5),
    (0.0, 0.0, 1.0, 0.0),
)
FRONT_FLOOR = 0.050
REAR_CEILING = 0.005


def _frozen_ladder_inputs() -> tuple[
    tuple[MicrophoneSpec, ...],
    dict[str, tuple[float, float, float]],
    tuple[np.ndarray, ...],
]:
    microphones = microphone_layout("tetrahedral", spacing_m=0.16)
    relative_positions = {
        microphone.mic_id: microphone.relative_position_m
        for microphone in microphones
    }
    world_positions = {
        mic_id: np.asarray(ARRAY_CENTER) + np.asarray(position)
        for mic_id, position in relative_positions.items()
    }
    probe = np.random.default_rng(20260718).standard_normal(SAMPLE_COUNT)
    frequencies = np.fft.rfftfreq(SAMPLE_COUNT, 1.0 / SAMPLE_RATE_HZ)
    spectrum = np.fft.rfft(probe)
    spectrum[(frequencies < 200.0) | (frequencies > 12_000.0)] = 0.0
    probe = np.fft.irfft(spectrum, n=SAMPLE_COUNT)
    distances = {
        mic_id: float(np.linalg.norm(position - np.asarray(SOURCE_POSITION)))
        for mic_id, position in world_positions.items()
    }
    minimum_distance = min(distances.values())
    delayed = {
        mic_id: fractional_delay(
            probe,
            delay_s=(distance - minimum_distance) / 343.0,
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
        for mic_id, distance in distances.items()
    }
    clean_rungs = tuple(
        np.asarray(
            [
                delayed[microphone.mic_id]
                * source_polar_gain(
                    "cardioid",
                    source_position_world=SOURCE_POSITION,
                    source_orientation_world_xyzw=quaternion,
                    microphone_position_world=tuple(
                        world_positions[microphone.mic_id]
                    ),
                )
                for microphone in microphones
            ]
        )
        for quaternion in LADDER_QUATERNIONS
    )
    raw_noise = np.random.default_rng(20260718).standard_normal(
        (len(microphones), SAMPLE_COUNT)
    )
    front_rms = float(np.sqrt(np.mean(clean_rungs[0] ** 2)))
    noise_rms = float(np.sqrt(np.mean(raw_noise**2)))
    noise = raw_noise * front_rms / noise_rms / 10.0 ** (18.0 / 20.0)
    mixtures = tuple(clean + noise for clean in clean_rungs)
    return microphones, relative_positions, mixtures


def _estimate_ladder() -> tuple[SrpPhatResult, ...]:
    microphones, positions, mixtures = _frozen_ladder_inputs()
    return tuple(
        srp_phat_direction(
            {
                microphone.mic_id: mixture[index]
                for index, microphone in enumerate(microphones)
            },
            mic_positions_m=positions,
            sample_rate_hz=SAMPLE_RATE_HZ,
            interp=8,
        )
        for mixture in mixtures
    )


@pytest.fixture(scope="module")
def ladder_results() -> tuple[SrpPhatResult, ...]:
    return _estimate_ladder()


def test_nominal_front_confidence_exceeds_frozen_floor(
    ladder_results: tuple[SrpPhatResult, ...],
) -> None:
    assert srp_phat_confidence(ladder_results[0]) >= FRONT_FLOOR


def test_mid_ladder_confidence_degrades_without_reversal(
    ladder_results: tuple[SrpPhatResult, ...],
) -> None:
    confidence = tuple(srp_phat_confidence(result) for result in ladder_results)

    assert REAR_CEILING < confidence[2] < confidence[0]
    assert all(
        left >= right
        for left, right in zip(confidence, confidence[1:], strict=False)
    )


def test_rear_null_confidence_is_abstention_grade(
    ladder_results: tuple[SrpPhatResult, ...],
) -> None:
    assert srp_phat_confidence(ladder_results[-1]) <= REAR_CEILING


def test_noise_only_grid_does_not_reproduce_legacy_high_confidence() -> None:
    microphones = microphone_layout("tetrahedral", spacing_m=0.16)
    rng = np.random.default_rng(20260718)
    result = srp_phat_direction(
        {
            microphone.mic_id: rng.standard_normal(SAMPLE_COUNT)
            for microphone in microphones
        },
        mic_positions_m={
            microphone.mic_id: microphone.relative_position_m
            for microphone in microphones
        },
        sample_rate_hz=SAMPLE_RATE_HZ,
        interp=8,
    )
    legacy_contrast = max(
        0.0,
        min(1.0, (result.peak_power - result.mean_power) / result.peak_power),
    )

    assert legacy_contrast > REAR_CEILING
    assert srp_phat_confidence(result) <= REAR_CEILING


def test_fixed_seed_srp_confidence_is_byte_stable() -> None:
    first = _estimate_ladder()
    second = _estimate_ladder()

    first_bytes = np.asarray(
        [value for result in first for value in astuple(result)], dtype="<f8"
    ).tobytes()
    second_bytes = np.asarray(
        [value for result in second for value in astuple(result)], dtype="<f8"
    ).tobytes()
    assert first_bytes == second_bytes


def test_room_acoustics_srp_exports_noise_aware_bearing_confidence() -> None:
    pytest.importorskip(
        "pyroomacoustics",
        reason="pyroomacoustics is required to exercise room_acoustics_srp export",
    )
    sensor = create_microphone_array(
        array_id="confidence_rig",
        prim_path="/World/ConfidenceRig/AudioArray",
        layout_name="tetrahedral",
        spacing_m=0.16,
        position_world=(3.0, 2.0, 1.5),
    )
    source = AudioSourceSpec(
        source_id="front_source",
        prim_path="/World/FrontSource",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=(1.0, 2.0, 1.5),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=0.08,
        gain_db=0.0,
    )
    scene = AudioSceneSnapshot(
        stage_id="srp_confidence_export",
        timestamp_ms=0,
        sources=(source,),
        arrays=(sensor,),
        room=RoomAcousticsSpec(
            room_id="near_anechoic",
            dimensions_m=(6.0, 4.0, 3.0),
            absorption=0.9,
            max_order=0,
        ),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=0.08,
        timestamp_ms=0,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    frame = RoomAcousticsSrpBackend().simulate(scene, sensor, window)
    detection = frame.detections[0]
    diagnostics = detection.diagnostics["srp_phat"]
    peak_power = diagnostics["peak_power"]
    mean_power = diagnostics["mean_power"]
    coherence = max(0.0, min(1.0, peak_power / diagnostics["pair_count"]))
    contrast = max(0.0, min(1.0, (peak_power - mean_power) / peak_power))

    assert frame.backend_id == "room_acoustics_srp"
    assert detection.diagnostics["doa_estimator"] == "srp_phat"
    assert detection.doa.bearing_confidence == contrast * coherence
    assert detection.doa.bearing_confidence >= FRONT_FLOOR
