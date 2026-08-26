"""Doppler factor helpers for moving sources and listeners.

The factor is the observed-over-emitted frequency ratio of the classic
moving source/listener model: with ``r_hat`` the unit vector from the source
to the listener, ``factor = (c - v_listener . r_hat) / (c - v_source . r_hat)``,
so a source closing on the listener yields a factor above 1. Factors are
clamped to ``[1/8, 8]`` so near- and super-sonic radial velocities cannot
produce unstable or negative ratios.
"""

from __future__ import annotations

from isaac_audio_sensors.core.constants import EPSILON
from isaac_audio_sensors.core.math_utils import Vector3, dot, norm, subtract
from isaac_audio_sensors.core.types import AudioSourceSpec, MicrophoneArraySpec

_MAX_DOPPLER_FACTOR = 8.0


def doppler_factor(
    *,
    source_position: Vector3,
    listener_position: Vector3,
    source_velocity: Vector3 | None,
    listener_velocity: Vector3 | None,
    speed_of_sound_mps: float,
) -> float:
    """Observed/emitted frequency ratio for one source-listener pair."""

    if speed_of_sound_mps <= 0.0:
        raise ValueError("speed_of_sound_mps must be positive.")
    direction = subtract(listener_position, source_position)
    distance = norm(direction)
    if distance <= EPSILON:
        return 1.0
    r_hat = (
        direction[0] / distance,
        direction[1] / distance,
        direction[2] / distance,
    )
    listener_radial = (
        0.0 if listener_velocity is None else dot(listener_velocity, r_hat)
    )
    source_radial = 0.0 if source_velocity is None else dot(source_velocity, r_hat)
    numerator = speed_of_sound_mps - listener_radial
    denominator = speed_of_sound_mps - source_radial
    if denominator <= EPSILON or numerator <= EPSILON:
        if numerator > denominator:
            return _MAX_DOPPLER_FACTOR
        return 1.0 / _MAX_DOPPLER_FACTOR
    factor = numerator / denominator
    return min(_MAX_DOPPLER_FACTOR, max(1.0 / _MAX_DOPPLER_FACTOR, factor))


def source_doppler_factor(
    source: AudioSourceSpec,
    sensor: MicrophoneArraySpec,
    *,
    speed_of_sound_mps: float,
) -> float | None:
    """Doppler factor at the array center, or ``None`` when no velocity is set.

    A single per-source factor is an approximation shared by all microphones
    of the array; per-microphone factors are exposed as L1 metadata only.
    """

    if source.velocity_world_mps is None and sensor.velocity_world_mps is None:
        return None
    return doppler_factor(
        source_position=source.position_world,
        listener_position=sensor.position_world,
        source_velocity=source.velocity_world_mps,
        listener_velocity=sensor.velocity_world_mps,
        speed_of_sound_mps=speed_of_sound_mps,
    )


__all__ = ["doppler_factor", "source_doppler_factor"]
