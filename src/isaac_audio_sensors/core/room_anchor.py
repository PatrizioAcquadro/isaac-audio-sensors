"""Build scene-anchored room specs from world-aligned bounds."""

from __future__ import annotations

from isaac_audio_sensors.core.constants import MIN_ROOM_EXTENT_M
from isaac_audio_sensors.core.math_utils import Vector3, as_vector3
from isaac_audio_sensors.core.types import RoomAcousticsSpec


def room_spec_from_bounds(
    *,
    min_world: Vector3,
    max_world: Vector3,
    room_id: str,
    absorption: float | dict[str, float] = 0.35,
    max_order: int = 0,
    out_of_bounds: str = "error",
    anchor_prim_path: str | None = None,
    air_absorption: bool = False,
    ray_tracing: bool = False,
) -> RoomAcousticsSpec:
    """Anchor a shoebox room to a world-aligned bounding box.

    The box's minimum corner becomes the room origin and its extents the
    room dimensions, so world positions map into the room without any
    refitting.
    """

    minimum = as_vector3(min_world, "room_spec_from_bounds.min_world")
    maximum = as_vector3(max_world, "room_spec_from_bounds.max_world")
    dimensions = tuple(maximum[axis] - minimum[axis] for axis in range(3))
    if any(extent <= MIN_ROOM_EXTENT_M for extent in dimensions):
        anchor = (
            f" from prim {anchor_prim_path!r}" if anchor_prim_path is not None else ""
        )
        raise ValueError(
            f"Room {room_id!r}{anchor} has a degenerate world-aligned bounding "
            f"box: extents {dimensions} must each exceed {MIN_ROOM_EXTENT_M}m."
        )
    return RoomAcousticsSpec(
        room_id=room_id,
        dimensions_m=dimensions,
        absorption=absorption,
        max_order=max_order,
        air_absorption=air_absorption,
        ray_tracing=ray_tracing,
        origin_m=minimum,
        out_of_bounds=out_of_bounds,
        anchor_prim_path=anchor_prim_path,
    )
