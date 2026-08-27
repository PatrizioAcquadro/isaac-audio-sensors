"""Canonical entity-owned first-order directivity."""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType

from isaac_audio_sensors.core.constants import EPSILON
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

DIRECTIVITY_MODE = "per_pair_direct_path"


class DirectivityValidationError(ValueError):
    """Invalid entity-owned directivity or missing required orientation."""


class DirectivityPattern(str, Enum):
    """Supported first-order polar-pattern families."""

    OMNI = "omni"
    CARDIOID = "cardioid"
    SUPERCARDIOID = "supercardioid"
    FIGURE_EIGHT = "figure_eight"


DIRECTIVITY_COEFFICIENTS = MappingProxyType(
    {
        DirectivityPattern.OMNI: 1.0,
        DirectivityPattern.CARDIOID: 0.5,
        DirectivityPattern.SUPERCARDIOID: 0.37,
        DirectivityPattern.FIGURE_EIGHT: 0.0,
    }
)


def resolve_directivity_pattern(
    value: DirectivityPattern | str,
    field_name: str = "directivity",
) -> DirectivityPattern:
    """Resolve one exact supported family or fail explicitly."""

    if isinstance(value, DirectivityPattern):
        return value
    if not isinstance(value, str):
        raise DirectivityValidationError(
            f"{field_name} must be a DirectivityPattern or string."
        )
    try:
        return DirectivityPattern(value)
    except ValueError as exc:
        supported = tuple(pattern.value for pattern in DirectivityPattern)
        raise DirectivityValidationError(
            f"{field_name} must be one of {supported!r}; received {value!r}."
        ) from exc


def pattern_coefficient(pattern: DirectivityPattern | str) -> float:
    """Return the canonical first-order coefficient for one family."""

    return DIRECTIVITY_COEFFICIENTS[resolve_directivity_pattern(pattern)]


def evaluate_polar_pattern(
    pattern: DirectivityPattern | str,
    *,
    orientation_xyzw: Quaternion | None,
    direction: Vector3,
) -> float:
    """Evaluate signed ``a + (1-a)*cos(theta)`` about local ``+X``."""

    resolved = resolve_directivity_pattern(pattern)
    direction_norm = norm(direction)
    if direction_norm <= EPSILON or resolved is DirectivityPattern.OMNI:
        return 1.0
    if orientation_xyzw is None:
        raise DirectivityValidationError(
            f"non-omni directivity {resolved.value!r} requires an orientation."
        )
    axis = rotate_vector_by_quaternion(
        (1.0, 0.0, 0.0),
        normalize_quaternion(orientation_xyzw),
    )
    cosine = clamp(dot(axis, direction) / direction_norm, -1.0, 1.0)
    coefficient = DIRECTIVITY_COEFFICIENTS[resolved]
    return coefficient + (1.0 - coefficient) * cosine


def source_polar_gain(
    pattern: DirectivityPattern | str,
    *,
    source_position_world: Vector3,
    source_orientation_world_xyzw: Quaternion | None,
    microphone_position_world: Vector3,
) -> float:
    """Evaluate one source pattern toward one microphone."""

    return evaluate_polar_pattern(
        pattern,
        orientation_xyzw=source_orientation_world_xyzw,
        direction=subtract(microphone_position_world, source_position_world),
    )


def microphone_world_orientation(
    array_orientation_world_xyzw: Quaternion,
    microphone_relative_orientation_xyzw: Quaternion | None,
) -> Quaternion:
    """Compose normalized array-world and microphone-relative orientations."""

    relative = (
        (0.0, 0.0, 0.0, 1.0)
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
    pattern: DirectivityPattern | str,
    *,
    microphone_position_world: Vector3,
    microphone_orientation_world_xyzw: Quaternion | None,
    source_position_world: Vector3,
) -> float:
    """Evaluate one microphone pattern for incidence from one source."""

    return evaluate_polar_pattern(
        pattern,
        orientation_xyzw=microphone_orientation_world_xyzw,
        direction=subtract(source_position_world, microphone_position_world),
    )


def pair_directivity_gain(
    *,
    source_pattern: DirectivityPattern | str,
    microphone_pattern: DirectivityPattern | str,
    source_position_world: Vector3,
    source_orientation_world_xyzw: Quaternion | None,
    microphone_position_world: Vector3,
    microphone_orientation_world_xyzw: Quaternion | None,
) -> float:
    """Return the signed direct-path source-times-microphone polar gain."""

    return source_polar_gain(
        source_pattern,
        source_position_world=source_position_world,
        source_orientation_world_xyzw=source_orientation_world_xyzw,
        microphone_position_world=microphone_position_world,
    ) * microphone_polar_gain(
        microphone_pattern,
        microphone_position_world=microphone_position_world,
        microphone_orientation_world_xyzw=microphone_orientation_world_xyzw,
        source_position_world=source_position_world,
    )


__all__ = [
    "DIRECTIVITY_COEFFICIENTS",
    "DIRECTIVITY_MODE",
    "DirectivityPattern",
    "evaluate_polar_pattern",
    "microphone_polar_gain",
    "microphone_world_orientation",
    "pair_directivity_gain",
    "pattern_coefficient",
    "resolve_directivity_pattern",
    "source_polar_gain",
]
