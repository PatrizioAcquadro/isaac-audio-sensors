"""Microphone-array layout and transform helpers."""

from __future__ import annotations

import math
from collections.abc import Iterable

from isaac_audio_sensors.core.constants import COORDINATE_CONVENTION
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    add,
    as_quaternion_xyzw,
    basis_from_quaternion,
    dot,
    norm,
    scale,
)
from isaac_audio_sensors.core.types import MicrophoneArraySpec, MicrophoneSpec


def create_microphone_array(
    *,
    array_id: str,
    prim_path: str,
    layout_name: str,
    position_world: Vector3 = (0.0, 0.0, 0.0),
    orientation_world_quat: Quaternion = (0.0, 0.0, 0.0, 1.0),
    sample_rate_hz: int = 48_000,
    spacing_m: float = 0.16,
) -> MicrophoneArraySpec:
    """Build a named microphone-array layout in the public coordinate frame."""

    microphones = microphone_layout(layout_name, spacing_m=spacing_m)
    orientation = as_quaternion_xyzw(
        orientation_world_quat,
        "orientation_world_quat",
    )
    forward, right, up = basis_from_quaternion(orientation)
    return MicrophoneArraySpec(
        array_id=array_id,
        prim_path=prim_path,
        position_world=position_world,
        orientation_world_quat=orientation,
        forward_vec_world=forward,
        right_vec_world=right,
        up_vec_world=up,
        microphones=microphones,
        sample_rate_hz=sample_rate_hz,
        coordinate_convention=COORDINATE_CONVENTION,
    )


def microphone_layout(
    layout_name: str,
    *,
    spacing_m: float = 0.16,
) -> tuple[MicrophoneSpec, ...]:
    """Return one of the built-in layouts used by tests and examples."""

    if not math.isfinite(spacing_m) or spacing_m <= 0.0:
        raise ValueError("spacing_m must be positive and finite.")

    half = spacing_m / 2.0
    if layout_name == "mono":
        return (MicrophoneSpec(mic_id="center", relative_position_m=(0.0, 0.0, 0.0)),)
    if layout_name in {"stereo_y", "two_mic_y"}:
        return (
            MicrophoneSpec(mic_id="left", relative_position_m=(0.0, -half, 0.0)),
            MicrophoneSpec(mic_id="right", relative_position_m=(0.0, half, 0.0)),
        )
    if layout_name in {"quad_front", "quad_cross"}:
        return (
            MicrophoneSpec(mic_id="front", relative_position_m=(half, 0.0, 0.0)),
            MicrophoneSpec(mic_id="right", relative_position_m=(0.0, half, 0.0)),
            MicrophoneSpec(mic_id="rear", relative_position_m=(-half, 0.0, 0.0)),
            MicrophoneSpec(mic_id="left", relative_position_m=(0.0, -half, 0.0)),
        )
    raise ValueError(f"Unknown microphone layout {layout_name!r}.")


def arbitrary_microphone_array(
    *,
    array_id: str,
    prim_path: str,
    relative_positions_m: Iterable[tuple[str, Vector3]],
    position_world: Vector3 = (0.0, 0.0, 0.0),
    orientation_world_quat: Quaternion = (0.0, 0.0, 0.0, 1.0),
    sample_rate_hz: int = 48_000,
) -> MicrophoneArraySpec:
    """Create an array from arbitrary microphone ids and local positions."""

    orientation = as_quaternion_xyzw(
        orientation_world_quat,
        "orientation_world_quat",
    )
    forward, right, up = basis_from_quaternion(orientation)
    return MicrophoneArraySpec(
        array_id=array_id,
        prim_path=prim_path,
        position_world=position_world,
        orientation_world_quat=orientation,
        forward_vec_world=forward,
        right_vec_world=right,
        up_vec_world=up,
        microphones=tuple(
            MicrophoneSpec(mic_id=mic_id, relative_position_m=position)
            for mic_id, position in relative_positions_m
        ),
        sample_rate_hz=sample_rate_hz,
        coordinate_convention=COORDINATE_CONVENTION,
    )


def microphone_world_positions(
    array: MicrophoneArraySpec,
) -> dict[str, Vector3]:
    """Compute world-space microphone positions from local array coordinates."""

    world_positions: dict[str, Vector3] = {}
    for microphone in array.microphones:
        local = microphone.relative_position_m
        world_offset = add(
            add(
                scale(array.forward_vec_world, local[0]),
                scale(array.right_vec_world, local[1]),
            ),
            scale(array.up_vec_world, local[2]),
        )
        world_positions[microphone.mic_id] = add(array.position_world, world_offset)
    return world_positions


def validate_tdoa_array(array: MicrophoneArraySpec) -> None:
    """Validate minimum geometry for the synthetic TDOA backend."""

    if len(array.microphones) < 2:
        raise ValueError("tdoa_synthetic requires at least two microphones.")
    if _layout_rank_xy(array) < 1:
        raise ValueError("tdoa_synthetic microphone layout is degenerate.")


def layout_rank_xy(array: MicrophoneArraySpec) -> int:
    """Return a simple local-XY layout rank used in diagnostics."""

    return _layout_rank_xy(array)


def _layout_rank_xy(array: MicrophoneArraySpec) -> int:
    positions = [microphone.relative_position_m for microphone in array.microphones]
    if len(positions) <= 1:
        return 0

    origin = positions[0]
    vectors = [
        (position[0] - origin[0], position[1] - origin[1]) for position in positions[1:]
    ]
    if all(math.hypot(vector[0], vector[1]) <= 1e-9 for vector in vectors):
        return 0

    first = next(
        vector for vector in vectors if math.hypot(vector[0], vector[1]) > 1e-9
    )
    for vector in vectors[1:]:
        cross_z = first[0] * vector[1] - first[1] * vector[0]
        if abs(cross_z) > 1e-9:
            return 2
    return 1


def basis_is_orthogonal(array: MicrophoneArraySpec, *, tolerance: float = 1e-6) -> bool:
    """Return whether the public basis vectors are approximately orthonormal."""

    vectors = (array.forward_vec_world, array.right_vec_world, array.up_vec_world)
    unit_lengths = all(abs(norm(vector) - 1.0) <= tolerance for vector in vectors)
    orthogonal = (
        abs(dot(vectors[0], vectors[1])) <= tolerance
        and abs(dot(vectors[0], vectors[2])) <= tolerance
        and abs(dot(vectors[1], vectors[2])) <= tolerance
    )
    return unit_lengths and orthogonal
