"""Shared synthetic source-amplitude physics for the L0/L1 backends.

The reference convention is amplitude-relative: the analytical asset reference
is multiplied by source gain, entity directivity magnitude, propagation, then
the microphone and documented per-channel deltas.
"""

from __future__ import annotations

import math

from isaac_audio_sensors.core.directivity import (
    microphone_world_orientation,
    pair_directivity_gain,
)
from isaac_audio_sensors.core.gain import db_to_amplitude_gain
from isaac_audio_sensors.core.math_utils import Quaternion, Vector3, norm, subtract
from isaac_audio_sensors.core.types import AudioSourceSpec, MicrophoneSpec

DISTANCE_FLOOR_M = 0.1


def directivity_factor(
    source: AudioSourceSpec,
    microphone: MicrophoneSpec,
    mic_position_world: Vector3,
    array_orientation_world_xyzw: Quaternion,
) -> float:
    """Signed canonical source-times-microphone direct-path gain."""

    return pair_directivity_gain(
        source_pattern=source.directivity,
        microphone_pattern=microphone.directivity,
        source_position_world=source.position_world,
        source_orientation_world_xyzw=source.orientation_world_quat,
        microphone_position_world=mic_position_world,
        microphone_orientation_world_xyzw=microphone_world_orientation(
            array_orientation_world_xyzw,
            microphone.relative_orientation_quat,
        ),
    )


def source_amplitude_at(
    source: AudioSourceSpec,
    microphone: MicrophoneSpec,
    mic_position_world: Vector3,
    array_orientation_world_xyzw: Quaternion,
    *,
    occlusion_gain_delta_db: float = 0.0,
    tdoa_gain_mismatch_delta_db: float = 0.0,
    channel_response_gain_delta_db: float = 0.0,
    air_absorption_db_per_m: float = 0.0,
) -> float:
    """Synthetic RMS amplitude of one source at one microphone position."""

    distance = norm(subtract(source.position_world, mic_position_world))
    amplitude = (
        db_to_amplitude_gain(source.gain_db, "AudioSourceSpec.gain_db")
        * abs(
            directivity_factor(
                source,
                microphone,
                mic_position_world,
                array_orientation_world_xyzw,
            )
        )
        / max(distance, DISTANCE_FLOOR_M)
    )
    if air_absorption_db_per_m > 0.0:
        amplitude *= 10.0 ** (-air_absorption_db_per_m * distance / 20.0)
    amplitude *= db_to_amplitude_gain(
        occlusion_gain_delta_db,
        "occlusion_gain_delta_db",
    )
    amplitude *= db_to_amplitude_gain(microphone.gain_db, "MicrophoneSpec.gain_db")
    amplitude *= db_to_amplitude_gain(
        tdoa_gain_mismatch_delta_db,
        "tdoa_gain_mismatch_delta_db",
    )
    amplitude *= db_to_amplitude_gain(
        channel_response_gain_delta_db,
        "channel_response_gain_delta_db",
    )
    return amplitude


def self_noise_floor(microphone: MicrophoneSpec) -> float:
    """Linear RMS noise floor for one microphone (0.0 when unconfigured)."""

    if microphone.self_noise_db is None:
        return 0.0
    return 10.0 ** (microphone.self_noise_db / 20.0)


def aggregate_rms_power_sum(
    per_mic_rms_power: dict[str, float],
    microphones: tuple[MicrophoneSpec, ...],
    *,
    include_self_noise: bool = True,
) -> dict[str, float]:
    """Combine accumulated per-mic RMS powers into aggregate RMS amplitudes."""

    aggregate: dict[str, float] = {}
    for microphone in microphones:
        power = per_mic_rms_power[microphone.mic_id]
        if include_self_noise:
            power += self_noise_floor(microphone) ** 2
        aggregate[microphone.mic_id] = math.sqrt(power)
    return aggregate
