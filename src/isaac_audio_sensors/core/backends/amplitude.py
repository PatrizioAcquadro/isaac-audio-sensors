"""Shared synthetic source-amplitude physics for the L0/L1 backends.

The reference convention is pressure-like: ``AudioSourceSpec.gain_db`` is the
source level re 1 m, so an omnidirectional source emits an RMS amplitude of
``10 ** (gain_db / 20)`` at one meter and falls off as ``1 / distance``.
"""

from __future__ import annotations

import math

from isaac_audio_sensors.core.constants import EPSILON
from isaac_audio_sensors.core.math_utils import (
    Vector3,
    clamp,
    dot,
    norm,
    normalize_quaternion,
    rotate_vector_by_quaternion,
    subtract,
)
from isaac_audio_sensors.core.types import AudioSourceSpec, MicrophoneSpec

DISTANCE_FLOOR_M = 0.1


def resolve_directivity(source: AudioSourceSpec) -> str:
    """Return the directivity model the L0/L1 backends actually apply.

    Only ``"cardioid"`` is modeled, and it needs an orientation to point the
    lobe; every other declared directivity behaves as ``"omni"``.
    """

    if (
        source.directivity == "cardioid"
        and source.orientation_world_quat is not None
    ):
        return "cardioid"
    return "omni"


def directivity_factor(
    source: AudioSourceSpec,
    mic_position_world: Vector3,
) -> float:
    """First-order directivity gain toward one microphone, in ``[0, 1]``."""

    if resolve_directivity(source) != "cardioid":
        return 1.0
    forward = rotate_vector_by_quaternion(
        (1.0, 0.0, 0.0),
        normalize_quaternion(source.orientation_world_quat),
    )
    to_mic = subtract(mic_position_world, source.position_world)
    distance = norm(to_mic)
    if distance <= EPSILON:
        return 1.0
    cos_theta = clamp(dot(forward, to_mic) / distance, -1.0, 1.0)
    return (1.0 + cos_theta) / 2.0


def source_amplitude_at(
    source: AudioSourceSpec,
    mic_position_world: Vector3,
    *,
    extra_gain_db: float = 0.0,
    air_absorption_db_per_m: float = 0.0,
) -> float:
    """Synthetic RMS amplitude of one source at one microphone position."""

    distance = norm(subtract(source.position_world, mic_position_world))
    gain_scale = 10.0 ** ((source.gain_db + extra_gain_db) / 20.0)
    amplitude = (
        gain_scale
        * directivity_factor(source, mic_position_world)
        / max(distance, DISTANCE_FLOOR_M)
    )
    if air_absorption_db_per_m > 0.0:
        amplitude *= 10.0 ** (-air_absorption_db_per_m * distance / 20.0)
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
