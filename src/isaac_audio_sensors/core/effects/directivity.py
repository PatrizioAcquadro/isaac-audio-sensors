"""Signed first-order source and microphone waveform directivity."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from isaac_audio_sensors.core.effects.channel_response import (
    design_frequency_response_fir,
)
from isaac_audio_sensors.core.effects.config import (
    DirectivityConfig,
    DirectivityFrequencyPointConfig,
    DirectivityPatternConfig,
    FrequencyResponsePointConfig,
)
from isaac_audio_sensors.core.effects.config.directivity import (
    DIRECTIVITY_MODE,
    PATTERN_COEFFICIENTS,
    pattern_is_noop,
    resolve_pattern,
)
from isaac_audio_sensors.core.effects.config.directivity import (
    validate_directivity as validate_directivity_config,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    clamp,
    dot,
    norm,
    normalize_quaternion,
    quaternion_multiply,
    rotate_vector_by_quaternion,
    subtract,
)

_IDENTITY_QUATERNION: Quaternion = (0.0, 0.0, 0.0, 1.0)


def pattern_coefficient(family: str) -> float:
    """Return the frozen first-order coefficient for one exact family id."""

    try:
        return PATTERN_COEFFICIENTS[family]
    except KeyError as exc:
        raise ConfigValidationError(
            "directivity family must be one of "
            f"{tuple(PATTERN_COEFFICIENTS)!r}; received {family!r}."
        ) from exc


def evaluate_polar_pattern(
    family: str,
    *,
    orientation_xyzw: Quaternion | None,
    direction: Vector3,
) -> float:
    """Evaluate ``a + (1-a)*cos(theta)`` using local ``+X`` as the axis.

    A zero direction has no defined angle and therefore returns exact unity,
    matching the metadata-backend policy. Omni is independent of orientation.
    """

    coefficient = pattern_coefficient(family)
    direction_norm = norm(direction)
    if direction_norm == 0.0 or family == "omni":
        return 1.0
    if orientation_xyzw is None:
        raise ConfigValidationError(
            f"non-omni directivity family {family!r} requires an orientation."
        )
    axis = rotate_vector_by_quaternion(
        (1.0, 0.0, 0.0),
        normalize_quaternion(orientation_xyzw),
    )
    cosine = clamp(dot(axis, direction) / direction_norm, -1.0, 1.0)
    return coefficient + (1.0 - coefficient) * cosine


def source_polar_gain(
    family: str,
    *,
    source_position_world: Vector3,
    source_orientation_world_xyzw: Quaternion | None,
    microphone_position_world: Vector3,
) -> float:
    """Evaluate a source pattern toward one microphone."""

    return evaluate_polar_pattern(
        family,
        orientation_xyzw=source_orientation_world_xyzw,
        direction=subtract(microphone_position_world, source_position_world),
    )


def microphone_world_orientation(
    array_orientation_world_xyzw: Quaternion,
    microphone_relative_orientation_xyzw: Quaternion | None,
) -> Quaternion:
    """Compose normalized ``q_array_world * q_mic_relative``."""

    relative = (
        _IDENTITY_QUATERNION
        if microphone_relative_orientation_xyzw is None
        else normalize_quaternion(microphone_relative_orientation_xyzw)
    )
    return normalize_quaternion(
        quaternion_multiply(
            normalize_quaternion(array_orientation_world_xyzw),
            relative,
        )
    )


def microphone_polar_gain(
    family: str,
    *,
    microphone_position_world: Vector3,
    microphone_orientation_world_xyzw: Quaternion | None,
    source_position_world: Vector3,
) -> float:
    """Evaluate a microphone pattern for incidence from one source."""

    return evaluate_polar_pattern(
        family,
        orientation_xyzw=microphone_orientation_world_xyzw,
        direction=subtract(source_position_world, microphone_position_world),
    )


def apply_pair_directivity(
    samples: np.ndarray,
    *,
    source_pattern: DirectivityPatternConfig,
    microphone_pattern: DirectivityPatternConfig,
    source_position_world: Vector3,
    source_orientation_world_xyzw: Quaternion | None,
    microphone_position_world: Vector3,
    microphone_orientation_world_xyzw: Quaternion | None,
    sample_rate_hz: int,
) -> np.ndarray:
    """Apply signed polar factors and source-then-microphone FIRs to one stem."""

    if pattern_is_noop(source_pattern) and pattern_is_noop(microphone_pattern):
        return samples
    source_gain = source_polar_gain(
        str(source_pattern.family),
        source_position_world=source_position_world,
        source_orientation_world_xyzw=source_orientation_world_xyzw,
        microphone_position_world=microphone_position_world,
    )
    microphone_gain = microphone_polar_gain(
        str(microphone_pattern.family),
        microphone_position_world=microphone_position_world,
        microphone_orientation_world_xyzw=microphone_orientation_world_xyzw,
        source_position_world=source_position_world,
    )
    waveform = samples
    if source_pattern.frequency_points is not None:
        waveform = _apply_frequency_response(
            waveform,
            source_pattern.frequency_points,
            sample_rate_hz=sample_rate_hz,
        )
    if microphone_pattern.frequency_points is not None:
        waveform = _apply_frequency_response(
            waveform,
            microphone_pattern.frequency_points,
            sample_rate_hz=sample_rate_hz,
        )
    return np.asarray(waveform * (source_gain * microphone_gain), dtype=np.float64)


def directivity_diagnostics(
    config: DirectivityConfig,
    *,
    active_source_ids: Sequence[str],
    microphone_ids: Sequence[str],
) -> dict[str, Any]:
    """Build the exact resolved directivity diagnostic or omit an omni no-op."""

    source_patterns = {
        source_id: resolve_pattern(config.source_patterns, source_id)
        for source_id in active_source_ids
    }
    microphone_patterns = {
        mic_id: resolve_pattern(config.mic_patterns, mic_id)
        for mic_id in microphone_ids
    }
    if not any(
        not pattern_is_noop(pattern)
        for pattern in (*source_patterns.values(), *microphone_patterns.values())
    ):
        return {}
    return {
        "source_pattern": {
            source_id: _diagnostic_pattern(pattern)
            for source_id, pattern in source_patterns.items()
        },
        "mic_pattern": {
            mic_id: _diagnostic_pattern(pattern)
            for mic_id, pattern in microphone_patterns.items()
        },
        "mode": DIRECTIVITY_MODE,
    }


def _apply_frequency_response(
    samples: np.ndarray,
    points: Sequence[DirectivityFrequencyPointConfig],
    *,
    sample_rate_hz: int,
) -> np.ndarray:
    response_points = tuple(
        FrequencyResponsePointConfig(
            frequency_hz=point.freq_hz,
            magnitude_db=point.gain_db,
        )
        for point in points
    )
    taps = design_frequency_response_fir(response_points, sample_rate_hz=sample_rate_hz)
    full_size = samples.size + taps.size - 1
    transform_size = 1 if full_size <= 1 else 1 << (full_size - 1).bit_length()
    convolution = np.fft.irfft(
        np.fft.rfft(samples, n=transform_size) * np.fft.rfft(taps, n=transform_size),
        n=transform_size,
    )[:full_size]
    group_delay = taps.size // 2
    return np.asarray(
        convolution[group_delay : group_delay + samples.size],
        dtype=np.float64,
    )


def _diagnostic_pattern(pattern: DirectivityPatternConfig) -> dict[str, Any]:
    return {
        "family": pattern.family,
        "frequency_points": (
            None
            if pattern.frequency_points is None
            else tuple(
                {"freq_hz": point.freq_hz, "gain_db": point.gain_db}
                for point in pattern.frequency_points
            )
        ),
    }


__all__ = [
    "DIRECTIVITY_MODE",
    "PATTERN_COEFFICIENTS",
    "apply_pair_directivity",
    "directivity_diagnostics",
    "evaluate_polar_pattern",
    "microphone_polar_gain",
    "microphone_world_orientation",
    "pattern_coefficient",
    "pattern_is_noop",
    "resolve_pattern",
    "source_polar_gain",
    "validate_directivity_config",
]
