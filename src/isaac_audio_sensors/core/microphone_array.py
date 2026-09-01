"""Microphone-array layout and transform helpers."""

from __future__ import annotations

import math

from isaac_audio_sensors.core.constants import COORDINATE_CONVENTION
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    add,
    as_quaternion_xyzw,
    basis_from_quaternion,
    cross,
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
    return MicrophoneArraySpec(
        array_id=array_id,
        prim_path=prim_path,
        position_world=position_world,
        orientation_world_quat=orientation,
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
    if layout_name == "tetrahedral":
        # Centered regular tetrahedron with edge length spacing_m; the only
        # built-in rank-3 layout, enabling elevation estimation.
        reach = spacing_m / (2.0 * math.sqrt(2.0))
        return (
            MicrophoneSpec(
                mic_id="front_right_up",
                relative_position_m=(reach, reach, reach),
            ),
            MicrophoneSpec(
                mic_id="front_left_down",
                relative_position_m=(reach, -reach, -reach),
            ),
            MicrophoneSpec(
                mic_id="rear_right_down",
                relative_position_m=(-reach, reach, -reach),
            ),
            MicrophoneSpec(
                mic_id="rear_left_up",
                relative_position_m=(-reach, -reach, reach),
            ),
        )
    raise ValueError(f"Unknown microphone layout {layout_name!r}.")


def microphone_world_positions(
    array: MicrophoneArraySpec,
) -> dict[str, Vector3]:
    """Compute world-space microphone positions from local array coordinates."""

    forward, right, up = basis_from_quaternion(array.orientation_world_quat)
    world_positions: dict[str, Vector3] = {}
    for microphone in array.microphones:
        local = microphone.relative_position_m
        world_offset = add(
            add(
                scale(forward, local[0]),
                scale(right, local[1]),
            ),
            scale(up, local[2]),
        )
        world_positions[microphone.mic_id] = add(array.position_world, world_offset)
    return world_positions


def validate_tdoa_array(array: MicrophoneArraySpec) -> None:
    """Validate minimum geometry for the synthetic TDOA backend."""

    if len(array.microphones) < 2:
        raise ValueError("TDOA localization requires at least two microphones.")
    if _layout_rank_xy(array) < 1:
        raise ValueError("TDOA microphone layout is degenerate.")


def layout_rank_xy(array: MicrophoneArraySpec) -> int:
    """Return a simple local-XY layout rank used in diagnostics."""

    return _layout_rank_xy(array)


def layout_rank_xyz(array: MicrophoneArraySpec) -> int:
    """Return the full local-3D layout rank (0-3) used for elevation gating."""

    return microphone_positions_rank_xyz(
        [microphone.relative_position_m for microphone in array.microphones]
    )


def microphone_positions_rank_xyz(positions: list[Vector3]) -> int:
    """Return the affine rank (0-3) of microphone positions in 3D."""

    if len(positions) <= 1:
        return 0

    origin = positions[0]
    vectors = [
        (
            position[0] - origin[0],
            position[1] - origin[1],
            position[2] - origin[2],
        )
        for position in positions[1:]
    ]
    vectors = [vector for vector in vectors if norm(vector) > 1e-9]
    if not vectors:
        return 0

    first = vectors[0]
    second = None
    for vector in vectors[1:]:
        if norm(cross(first, vector)) > 1e-9:
            second = vector
            break
    if second is None:
        return 1

    plane_normal = cross(first, second)
    for vector in vectors:
        if abs(dot(plane_normal, vector)) > 1e-9:
            return 3
    return 2


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
