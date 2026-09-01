"""Builders and transforms for the unified analytic environment contract."""

from __future__ import annotations

import math
from collections.abc import Iterable

from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    as_vector3,
    quaternion_conjugate,
    rotate_vector_by_quaternion,
)
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AcousticSurfaceSpec,
    Pose3D,
)

Absorption = float | dict[str, float] | str
IDENTITY_QUATERNION: Quaternion = (0.0, 0.0, 0.0, 1.0)


def free_field_environment(
    *,
    environment_id: str,
    position_world: Vector3 = (0.0, 0.0, 0.0),
    orientation_world_quat: Quaternion = IDENTITY_QUATERNION,
) -> AcousticEnvironmentSpec:
    """Build an explicit environment with no acoustic surfaces."""

    return AcousticEnvironmentSpec(
        environment_id=environment_id,
        kind="free_field",
        world_pose=_world_pose(position_world, orientation_world_quat),
    )


def half_space_environment(
    *,
    environment_id: str,
    absorption: Absorption = 0.35,
    position_world: Vector3 = (0.0, 0.0, 0.0),
    orientation_world_quat: Quaternion = IDENTITY_QUATERNION,
) -> AcousticEnvironmentSpec:
    """Build one infinite local z=0 floor with acoustic space above it."""

    return AcousticEnvironmentSpec(
        environment_id=environment_id,
        kind="half_space",
        world_pose=_world_pose(position_world, orientation_world_quat),
        surfaces=(
            AcousticSurfaceSpec(
                surface_id="floor",
                role="floor",
                absorption=absorption,
                infinite=True,
            ),
        ),
    )


def shoebox_environment(
    *,
    environment_id: str,
    dimensions_m: Vector3,
    absorption: Absorption = 0.35,
    position_world: Vector3 = (0.0, 0.0, 0.0),
    orientation_world_quat: Quaternion = IDENTITY_QUATERNION,
) -> AcousticEnvironmentSpec:
    """Build a closed box spanning local ``[0, dimensions_m]``."""

    dimensions = as_vector3(dimensions_m, "shoebox_environment.dimensions_m")
    if any(extent <= 0.0 for extent in dimensions):
        raise ValueError("shoebox_environment dimensions must be positive.")
    dx, dy, dz = dimensions
    surfaces = (
        _surface(
            "floor",
            "floor",
            ((0, 0, 0), (dx, 0, 0), (dx, dy, 0), (0, dy, 0)),
            absorption,
        ),
        _surface(
            "ceiling",
            "ceiling",
            ((0, 0, dz), (0, dy, dz), (dx, dy, dz), (dx, 0, dz)),
            absorption,
        ),
        _surface(
            "wall_x_min",
            "wall",
            ((0, 0, 0), (0, dy, 0), (0, dy, dz), (0, 0, dz)),
            absorption,
        ),
        _surface(
            "wall_x_max",
            "wall",
            ((dx, 0, 0), (dx, 0, dz), (dx, dy, dz), (dx, dy, 0)),
            absorption,
        ),
        _surface(
            "wall_y_min",
            "wall",
            ((0, 0, 0), (0, 0, dz), (dx, 0, dz), (dx, 0, 0)),
            absorption,
        ),
        _surface(
            "wall_y_max",
            "wall",
            ((0, dy, 0), (dx, dy, 0), (dx, dy, dz), (0, dy, dz)),
            absorption,
        ),
    )
    return AcousticEnvironmentSpec(
        environment_id=environment_id,
        kind="shoebox",
        world_pose=_world_pose(position_world, orientation_world_quat),
        surfaces=surfaces,
        dimensions_m=dimensions,
    )


def polygon_prism_environment(
    *,
    environment_id: str,
    floor_vertices_local_m: Iterable[Vector3],
    height_m: float,
    absorption: Absorption = 0.35,
    position_world: Vector3 = (0.0, 0.0, 0.0),
    orientation_world_quat: Quaternion = IDENTITY_QUATERNION,
) -> AcousticEnvironmentSpec:
    """Build a closed prism by extruding a simple local z=0 floor polygon."""

    floor = tuple(
        as_vector3(vertex, "polygon_prism_environment.floor_vertices_local_m")
        for vertex in floor_vertices_local_m
    )
    _validate_floor_polygon(floor)
    height = float(height_m)
    if not math.isfinite(height) or height <= 0.0:
        raise ValueError("polygon_prism_environment.height_m must be positive.")
    ceiling = tuple((x, y, height) for x, y, _ in reversed(floor))
    walls = tuple(
        _surface(
            f"wall_{index}",
            "wall",
            (
                left,
                right,
                (right[0], right[1], height),
                (left[0], left[1], height),
            ),
            absorption,
        )
        for index, (left, right) in enumerate(
            zip(floor, floor[1:] + floor[:1], strict=True)
        )
    )
    return AcousticEnvironmentSpec(
        environment_id=environment_id,
        kind="polygon_prism",
        world_pose=_world_pose(position_world, orientation_world_quat),
        surfaces=(
            _surface("floor", "floor", floor, absorption),
            _surface("ceiling", "ceiling", ceiling, absorption),
            *walls,
        ),
    )


def surface_set_environment(
    *,
    environment_id: str,
    surfaces: Iterable[AcousticSurfaceSpec],
    position_world: Vector3 = (0.0, 0.0, 0.0),
    orientation_world_quat: Quaternion = IDENTITY_QUATERNION,
) -> AcousticEnvironmentSpec:
    """Build a simple open environment from bounded local surfaces."""

    bounded = tuple(surfaces)
    if any(surface.infinite for surface in bounded):
        raise ValueError("surface_set_environment accepts only bounded surfaces.")
    return AcousticEnvironmentSpec(
        environment_id=environment_id,
        kind="surface_set",
        world_pose=_world_pose(position_world, orientation_world_quat),
        surfaces=bounded,
    )


def shoebox_environment_from_bounds(
    *,
    min_world: Vector3,
    max_world: Vector3,
    environment_id: str,
    absorption: Absorption = 0.35,
) -> AcousticEnvironmentSpec:
    """Build an identity-oriented shoebox from world-aligned bounds."""

    minimum = as_vector3(min_world, "shoebox_environment_from_bounds.min_world")
    maximum = as_vector3(max_world, "shoebox_environment_from_bounds.max_world")
    dimensions = tuple(maximum[axis] - minimum[axis] for axis in range(3))
    if any(extent <= 0.0 for extent in dimensions):
        raise ValueError(
            f"Environment {environment_id!r} has degenerate world-aligned bounds: "
            f"extents {dimensions} must be positive."
        )
    return shoebox_environment(
        environment_id=environment_id,
        dimensions_m=dimensions,
        absorption=absorption,
        position_world=minimum,
    )


def world_to_environment_point(
    environment: AcousticEnvironmentSpec,
    position_world: Vector3,
) -> Vector3:
    """Transform one world-frame point into environment-local coordinates."""

    point = as_vector3(position_world, "world_to_environment_point.position_world")
    origin = environment.world_pose.position_m
    orientation = environment.world_pose.orientation_xyzw
    assert orientation is not None
    relative = tuple(point[axis] - origin[axis] for axis in range(3))
    return rotate_vector_by_quaternion(relative, quaternion_conjugate(orientation))


def environment_to_world_point(
    environment: AcousticEnvironmentSpec,
    position_local_m: Vector3,
) -> Vector3:
    """Transform one environment-local point into world coordinates."""

    point = as_vector3(
        position_local_m,
        "environment_to_world_point.position_local_m",
    )
    orientation = environment.world_pose.orientation_xyzw
    assert orientation is not None
    rotated = rotate_vector_by_quaternion(point, orientation)
    origin = environment.world_pose.position_m
    return tuple(rotated[axis] + origin[axis] for axis in range(3))


def _world_pose(position: Vector3, orientation: Quaternion) -> Pose3D:
    return Pose3D(position_m=position, orientation_xyzw=orientation)


def _surface(
    surface_id: str,
    role: str,
    vertices: Iterable[Vector3],
    absorption: Absorption,
) -> AcousticSurfaceSpec:
    return AcousticSurfaceSpec(
        surface_id=surface_id,
        role=role,
        vertices_local_m=tuple(vertices),
        absorption=absorption,
    )


def _validate_floor_polygon(vertices: tuple[Vector3, ...]) -> None:
    if len(vertices) < 3 or len(set(vertices)) != len(vertices):
        raise ValueError(
            "polygon_prism_environment floor polygon requires at least three "
            "distinct vertices."
        )
    if any(abs(vertex[2]) > 1e-9 for vertex in vertices):
        raise ValueError(
            "polygon_prism_environment floor vertices must lie on local z=0."
        )
    edge_count = len(vertices)
    for left_index in range(edge_count):
        a = vertices[left_index]
        b = vertices[(left_index + 1) % edge_count]
        for right_index in range(left_index + 1, edge_count):
            if right_index in {
                left_index,
                (left_index + 1) % edge_count,
                (left_index - 1) % edge_count,
            }:
                continue
            c = vertices[right_index]
            d = vertices[(right_index + 1) % edge_count]
            if _segments_intersect(a, b, c, d):
                raise ValueError(
                    "polygon_prism_environment floor polygon must not self-intersect."
                )
    area_twice = sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(vertices, vertices[1:] + vertices[:1], strict=True)
    )
    if abs(area_twice) <= 1e-9:
        raise ValueError("polygon_prism_environment floor polygon has zero area.")


def _segments_intersect(a: Vector3, b: Vector3, c: Vector3, d: Vector3) -> bool:
    def orientation(left: Vector3, middle: Vector3, right: Vector3) -> float:
        return (middle[1] - left[1]) * (right[0] - middle[0]) - (
            middle[0] - left[0]
        ) * (right[1] - middle[1])

    first = orientation(a, b, c)
    second = orientation(a, b, d)
    third = orientation(c, d, a)
    fourth = orientation(c, d, b)
    return first * second < 0.0 and third * fourth < 0.0


__all__ = [
    "environment_to_world_point",
    "free_field_environment",
    "half_space_environment",
    "polygon_prism_environment",
    "shoebox_environment",
    "shoebox_environment_from_bounds",
    "surface_set_environment",
    "world_to_environment_point",
]
