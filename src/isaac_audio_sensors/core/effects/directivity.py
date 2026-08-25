"""Signed first-order source and microphone waveform directivity."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any

import numpy as np

from isaac_audio_sensors.core.constants import DIRECTIVITY_COEFFICIENTS
from isaac_audio_sensors.core.effects.channel_response import (
    design_frequency_response_fir,
)
from isaac_audio_sensors.core.effects.config import (
    DirectivityConfig,
    DirectivityFrequencyPointConfig,
    DirectivityPatternConfig,
    DirectivityPatternSetConfig,
    FrequencyResponsePointConfig,
)
from isaac_audio_sensors.core.effects.validation import UnsupportedEffectError
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

PATTERN_COEFFICIENTS: Mapping[str, float] = DIRECTIVITY_COEFFICIENTS
DIRECTIVITY_MODE = "per_pair_direct_path"
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


def resolve_pattern(
    pattern_set: DirectivityPatternSetConfig | None,
    entity_id: str,
) -> DirectivityPatternConfig:
    """Resolve exact override, then default, then flat omni."""

    if pattern_set is not None:
        overrides = pattern_set.overrides or {}
        if entity_id in overrides:
            return overrides[entity_id]
        if pattern_set.default is not None:
            return pattern_set.default
    return DirectivityPatternConfig(family="omni")


def pattern_is_noop(pattern: DirectivityPatternConfig) -> bool:
    """Return whether a resolved pattern is exactly flat omni."""

    return pattern.family == "omni" and pattern.frequency_points is None


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


def validate_directivity_config(
    config: DirectivityConfig,
    *,
    microphone_orders: Sequence[Sequence[str]],
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    source_ids: Sequence[str] | None = None,
    source_orientations: Mapping[str, Quaternion | None] | None = None,
    microphone_orientations: Mapping[str, Quaternion | None] | None = None,
) -> None:
    """Validate the frozen directivity contract without synthesis side effects."""

    table = "audio.effects.directivity"
    if not isinstance(config, DirectivityConfig):
        raise ConfigValidationError(
            f"{table} must normalize to DirectivityConfig; received "
            f"{type(config).__name__}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if type(config.enabled) is not bool:
        raise ConfigValidationError(
            f"{table}.enabled must be a bool; received {config.enabled!r}."
        )
    if not config.enabled:
        return
    if config.mode is not None and config.mode != DIRECTIVITY_MODE:
        raise UnsupportedEffectError(
            f"{table}.mode={config.mode!r} is unsupported; the supported "
            f"backend/profile envelope provides only {DIRECTIVITY_MODE!r}."
        )

    orders = tuple(tuple(order) for order in microphone_orders)
    normalized_source_ids = None if source_ids is None else tuple(source_ids)
    _validate_pattern_set(
        config.source_patterns,
        table=f"{table}.source_patterns",
        entity_ids=normalized_source_ids,
        entity_label="AudioSourceSpec.source_id",
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
    )
    mic_ids = tuple(dict.fromkeys(mic_id for order in orders for mic_id in order))
    _validate_pattern_set(
        config.mic_patterns,
        table=f"{table}.mic_patterns",
        entity_ids=mic_ids,
        entity_orders=orders,
        entity_label="MicrophoneSpec.mic_id",
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
    )

    if (
        config.enabled
        and config.source_patterns is None
        and config.mic_patterns is None
    ):
        raise UnsupportedEffectError(
            f"{table}.enabled=true requires source_patterns or mic_patterns; "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    if config.enabled and (
        backend_id not in {"room_acoustics", "room_acoustics_srp"}
        or runtime_profile != "waveform_fidelity"
    ):
        raise UnsupportedEffectError(
            f"{table}.enabled=true is waveform-only; supported envelope is "
            "room_acoustics or room_acoustics_srp with profile "
            f"'waveform_fidelity', received backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )

    if normalized_source_ids is not None:
        for source_id in normalized_source_ids:
            pattern = resolve_pattern(config.source_patterns, source_id)
            if pattern.family != "omni" and (
                source_orientations is None
                or source_orientations.get(source_id) is None
            ):
                raise ConfigValidationError(
                    f"{table}.source_patterns resolved non-omni family "
                    f"{pattern.family!r} for {source_id!r}, but "
                    "AudioSourceSpec.orientation_world_quat is missing; "
                    f"backend={backend_id!r}, profile={runtime_profile!r}."
                )
    if microphone_orientations is not None:
        for mic_id in mic_ids:
            pattern = resolve_pattern(config.mic_patterns, mic_id)
            if pattern.family != "omni" and microphone_orientations.get(mic_id) is None:
                raise ConfigValidationError(
                    f"{table}.mic_patterns resolved non-omni family "
                    f"{pattern.family!r} for {mic_id!r}, but the composed "
                    "microphone world orientation is missing; "
                    f"backend={backend_id!r}, profile={runtime_profile!r}."
                )


def _validate_pattern_set(
    pattern_set: DirectivityPatternSetConfig | None,
    *,
    table: str,
    entity_ids: tuple[str, ...] | None,
    entity_label: str,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    entity_orders: tuple[tuple[str, ...], ...] | None = None,
) -> None:
    if pattern_set is None:
        return
    if not isinstance(pattern_set, DirectivityPatternSetConfig):
        raise ConfigValidationError(
            f"{table} must be DirectivityPatternSetConfig; received "
            f"{type(pattern_set).__name__}."
        )
    if pattern_set.default is None and pattern_set.overrides is None:
        raise ConfigValidationError(
            f"{table} must contain a default or non-empty overrides mapping; "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    if pattern_set.default is not None:
        _validate_pattern(
            pattern_set.default,
            table=f"{table}.default",
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
    overrides = pattern_set.overrides
    if overrides is None:
        return
    if not isinstance(overrides, Mapping) or not overrides:
        raise ConfigValidationError(
            f"{table}.overrides must be a non-empty mapping; received "
            f"{overrides!r}, backend={backend_id!r}, profile={runtime_profile!r}."
        )
    configured_ids = tuple(overrides)
    if any(
        not isinstance(entity_id, str) or not entity_id for entity_id in configured_ids
    ):
        raise ConfigValidationError(
            f"{table}.overrides ids must be exact non-empty {entity_label} strings; "
            f"received {configured_ids!r}."
        )
    if entity_ids is not None:
        unknown = tuple(
            entity_id for entity_id in configured_ids if entity_id not in entity_ids
        )
        if unknown:
            raise ConfigValidationError(
                f"{table}.overrides contains unknown exact {entity_label} values "
                f"{unknown!r}; available ids {entity_ids!r}, "
                f"backend={backend_id!r}, profile={runtime_profile!r}."
            )
        orders = entity_orders or (entity_ids,)
        if configured_ids and not any(
            configured_ids
            == tuple(entity_id for entity_id in order if entity_id in configured_ids)
            and set(configured_ids).issubset(order)
            for order in orders
        ):
            raise ConfigValidationError(
                f"{table}.overrides order mismatch: configured {configured_ids!r}, "
                f"available orders {orders!r}, backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )
    for entity_id, pattern in overrides.items():
        _validate_pattern(
            pattern,
            table=f"{table}.overrides.{entity_id}",
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )


def _validate_pattern(
    pattern: DirectivityPatternConfig,
    *,
    table: str,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
) -> None:
    if not isinstance(pattern, DirectivityPatternConfig):
        raise ConfigValidationError(
            f"{table} must be DirectivityPatternConfig; received "
            f"{type(pattern).__name__}."
        )
    if (
        not isinstance(pattern.family, str)
        or pattern.family not in PATTERN_COEFFICIENTS
    ):
        raise ConfigValidationError(
            f"{table}.family must be one of {tuple(PATTERN_COEFFICIENTS)!r}; "
            f"received {pattern.family!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    points = pattern.frequency_points
    if points is None:
        return
    if len(points) < 2:
        raise ConfigValidationError(
            f"{table}.frequency_points requires at least two points; received "
            f"{len(points)}, backend={backend_id!r}, profile={runtime_profile!r}."
        )
    previous = 0.0
    for index, point in enumerate(points):
        prefix = f"{table}.frequency_points[{index}]"
        if not isinstance(point, DirectivityFrequencyPointConfig):
            raise ConfigValidationError(
                f"{prefix} must be DirectivityFrequencyPointConfig; received "
                f"{type(point).__name__}."
            )
        for field_name, value in (
            ("freq_hz", point.freq_hz),
            ("gain_db", point.gain_db),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, Real)
                or not math.isfinite(float(value))
            ):
                raise ConfigValidationError(
                    f"{prefix}.{field_name} must be finite; received {value!r}, "
                    f"backend={backend_id!r}, profile={runtime_profile!r}."
                )
        frequency = float(point.freq_hz)
        if frequency <= 0.0 or frequency <= previous:
            raise ConfigValidationError(
                f"{prefix}.freq_hz={frequency!r} must be positive and strictly "
                f"increasing; backend={backend_id!r}, profile={runtime_profile!r}."
            )
        previous = frequency
    nyquist = sample_rate_hz / 2.0
    if previous > nyquist:
        raise ConfigValidationError(
            f"{table}.frequency_points highest frequency {previous!r} exceeds "
            f"Nyquist {nyquist!r}; backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )


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
