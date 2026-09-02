"""Acoustic environment contracts and geometric validation."""

from __future__ import annotations

from dataclasses import dataclass, field

from isaac_audio_sensors.core.constants import (
    ACOUSTIC_ENVIRONMENT_KINDS,
    ACOUSTIC_SURFACE_ROLES,
)
from isaac_audio_sensors.core.math_utils import (
    Vector3,
    as_vector3,
    cross,
    dot,
    norm,
    subtract,
)
from isaac_audio_sensors.core.types._scene import Pose3D
from isaac_audio_sensors.core.types._validation import (
    require_non_empty,
    require_probability,
    require_unique_ids,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class AcousticSurfaceSpec:
    """One acoustically meaningful surface in environment-local coordinates."""

    surface_id: str
    role: str
    vertices_local_m: tuple[Vector3, ...] = field(default_factory=tuple)
    absorption: float | dict[str, float] | str = 0.35
    infinite: bool = False

    def __post_init__(self) -> None:
        require_non_empty(self.surface_id, "AcousticSurfaceSpec.surface_id")
        if not isinstance(self.role, str):
            raise ValueError("AcousticSurfaceSpec.role must be a string.")
        if self.role not in ACOUSTIC_SURFACE_ROLES:
            raise ValueError(
                "AcousticSurfaceSpec.role must be one of "
                f"{sorted(ACOUSTIC_SURFACE_ROLES)}."
            )
        vertices = tuple(
            as_vector3(vertex, "AcousticSurfaceSpec.vertices_local_m")
            for vertex in self.vertices_local_m
        )
        object.__setattr__(self, "vertices_local_m", vertices)
        if not isinstance(self.infinite, bool):
            raise ValueError("AcousticSurfaceSpec.infinite must be a boolean.")
        if self.infinite:
            if self.role != "floor" or vertices:
                raise ValueError(
                    "An infinite acoustic surface must be the canonical local "
                    "z=0 floor and must not define bounded vertices."
                )
        else:
            _validate_surface_vertices(vertices, surface_id=self.surface_id)
        _validate_absorption(
            self.absorption,
            field_name="AcousticSurfaceSpec.absorption",
            application=f"surface {self.surface_id!r}",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AcousticEnvironmentSpec:
    """Unified analytic environment with local surfaces and one world pose."""

    environment_id: str
    kind: str
    world_pose: Pose3D
    surfaces: tuple[AcousticSurfaceSpec, ...] = field(default_factory=tuple)
    dimensions_m: Vector3 | None = None

    def __post_init__(self) -> None:
        require_non_empty(
            self.environment_id,
            "AcousticEnvironmentSpec.environment_id",
        )
        if not isinstance(self.kind, str):
            raise ValueError("AcousticEnvironmentSpec.kind must be a string.")
        if self.kind not in ACOUSTIC_ENVIRONMENT_KINDS:
            raise ValueError(
                "AcousticEnvironmentSpec.kind must be one of "
                f"{sorted(ACOUSTIC_ENVIRONMENT_KINDS)}."
            )
        if not isinstance(self.world_pose, Pose3D):
            raise ValueError("AcousticEnvironmentSpec.world_pose must be a Pose3D.")
        if self.world_pose.frame != "world":
            raise ValueError(
                "AcousticEnvironmentSpec.world_pose.frame must be 'world'."
            )
        if self.world_pose.orientation_xyzw is None:
            raise ValueError(
                "AcousticEnvironmentSpec.world_pose.orientation_xyzw is required."
            )
        surfaces = tuple(self.surfaces)
        if any(not isinstance(surface, AcousticSurfaceSpec) for surface in surfaces):
            raise ValueError(
                "AcousticEnvironmentSpec.surfaces must contain "
                "AcousticSurfaceSpec values."
            )
        require_unique_ids(
            [surface.surface_id for surface in surfaces],
            "acoustic surface id",
        )
        object.__setattr__(self, "surfaces", surfaces)
        dimensions = self.dimensions_m
        if dimensions is not None:
            dimensions = as_vector3(
                dimensions,
                "AcousticEnvironmentSpec.dimensions_m",
            )
            if any(component <= 0.0 for component in dimensions):
                raise ValueError(
                    "AcousticEnvironmentSpec.dimensions_m values must be positive."
                )
            object.__setattr__(self, "dimensions_m", dimensions)
        self._validate_topology()

    def _validate_topology(self) -> None:
        surfaces = self.surfaces
        bounded = tuple(surface for surface in surfaces if not surface.infinite)
        infinite = tuple(surface for surface in surfaces if surface.infinite)
        if self.kind == "free_field":
            if surfaces or self.dimensions_m is not None:
                raise ValueError("free_field must not define surfaces or dimensions_m.")
            return
        if self.kind == "half_space":
            if (
                len(surfaces) != 1
                or len(infinite) != 1
                or surfaces[0].role != "floor"
                or self.dimensions_m is not None
            ):
                raise ValueError(
                    "half_space must define exactly one infinite local z=0 floor."
                )
            return
        if infinite:
            raise ValueError(f"{self.kind} surfaces must all be bounded.")
        if self.kind == "shoebox":
            if self.dimensions_m is None:
                raise ValueError("shoebox requires dimensions_m.")
            role_counts = {
                role: sum(surface.role == role for surface in bounded)
                for role in ACOUSTIC_SURFACE_ROLES
            }
            if len(bounded) != 6 or role_counts != {
                "floor": 1,
                "wall": 4,
                "ceiling": 1,
            }:
                raise ValueError(
                    "shoebox requires one floor, four walls, and one ceiling."
                )
            _validate_shoebox_surfaces(bounded, self.dimensions_m)
            return
        if self.dimensions_m is not None:
            raise ValueError(f"{self.kind} must not define dimensions_m.")
        if self.kind == "polygon_prism":
            role_counts = {
                role: sum(surface.role == role for surface in bounded)
                for role in ACOUSTIC_SURFACE_ROLES
            }
            if (
                role_counts["floor"] != 1
                or role_counts["ceiling"] != 1
                or role_counts["wall"] < 3
            ):
                raise ValueError(
                    "polygon_prism requires one floor, one ceiling, and at "
                    "least three walls."
                )
            return
        if not bounded:
            raise ValueError("surface_set must contain at least one bounded surface.")


def _validate_surface_vertices(
    vertices: tuple[Vector3, ...],
    *,
    surface_id: str,
) -> None:
    if len(vertices) < 3:
        raise ValueError(
            f"Bounded acoustic surface {surface_id!r} requires at least three vertices."
        )
    if len(set(vertices)) != len(vertices):
        raise ValueError(
            f"Bounded acoustic surface {surface_id!r} has duplicate vertices."
        )
    origin = vertices[0]
    normal: Vector3 | None = None
    for index in range(1, len(vertices) - 1):
        candidate = cross(
            subtract(vertices[index], origin),
            subtract(vertices[index + 1], origin),
        )
        if norm(candidate) > 1e-9:
            normal = candidate
            break
    if normal is None:
        raise ValueError(f"Bounded acoustic surface {surface_id!r} has zero area.")
    tolerance = 1e-8 * max(1.0, norm(normal))
    if any(
        abs(dot(subtract(vertex, origin), normal)) > tolerance for vertex in vertices
    ):
        raise ValueError(
            f"Bounded acoustic surface {surface_id!r} vertices must be coplanar."
        )
    projected = _project_surface_vertices(vertices, normal)
    for left_index in range(len(projected)):
        a = projected[left_index]
        b = projected[(left_index + 1) % len(projected)]
        for right_index in range(left_index + 1, len(projected)):
            if right_index in {
                left_index,
                (left_index + 1) % len(projected),
                (left_index - 1) % len(projected),
            }:
                continue
            c = projected[right_index]
            d = projected[(right_index + 1) % len(projected)]
            if _segments_intersect_2d(a, b, c, d):
                raise ValueError(
                    f"Bounded acoustic surface {surface_id!r} must be a simple polygon."
                )


def _validate_shoebox_surfaces(
    surfaces: tuple[AcousticSurfaceSpec, ...],
    dimensions: Vector3,
) -> None:
    dx, dy, dz = dimensions
    expected = {
        "floor": (
            "floor",
            frozenset(((0.0, 0.0, 0.0), (dx, 0.0, 0.0), (dx, dy, 0.0), (0.0, dy, 0.0))),
        ),
        "ceiling": (
            "ceiling",
            frozenset(((0.0, 0.0, dz), (0.0, dy, dz), (dx, dy, dz), (dx, 0.0, dz))),
        ),
        "wall_x_min": (
            "wall",
            frozenset(((0.0, 0.0, 0.0), (0.0, dy, 0.0), (0.0, dy, dz), (0.0, 0.0, dz))),
        ),
        "wall_x_max": (
            "wall",
            frozenset(((dx, 0.0, 0.0), (dx, 0.0, dz), (dx, dy, dz), (dx, dy, 0.0))),
        ),
        "wall_y_min": (
            "wall",
            frozenset(((0.0, 0.0, 0.0), (0.0, 0.0, dz), (dx, 0.0, dz), (dx, 0.0, 0.0))),
        ),
        "wall_y_max": (
            "wall",
            frozenset(((0.0, dy, 0.0), (dx, dy, 0.0), (dx, dy, dz), (0.0, dy, dz))),
        ),
    }
    actual = {
        surface.surface_id: (surface.role, frozenset(surface.vertices_local_m))
        for surface in surfaces
    }
    if actual != expected:
        raise ValueError(
            "shoebox surfaces must use the canonical six local faces for dimensions_m."
        )


def _project_surface_vertices(
    vertices: tuple[Vector3, ...],
    normal: Vector3,
) -> tuple[tuple[float, float], ...]:
    drop_axis = max(range(3), key=lambda axis: abs(normal[axis]))
    axes = tuple(axis for axis in range(3) if axis != drop_axis)
    return tuple((vertex[axes[0]], vertex[axes[1]]) for vertex in vertices)


def _segments_intersect_2d(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    def orientation(
        left: tuple[float, float],
        middle: tuple[float, float],
        right: tuple[float, float],
    ) -> float:
        return (middle[0] - left[0]) * (right[1] - left[1]) - (middle[1] - left[1]) * (
            right[0] - left[0]
        )

    def on_segment(
        left: tuple[float, float],
        middle: tuple[float, float],
        right: tuple[float, float],
    ) -> bool:
        return (
            min(left[0], right[0]) - 1e-9 <= middle[0] <= max(left[0], right[0]) + 1e-9
            and min(left[1], right[1]) - 1e-9
            <= middle[1]
            <= max(left[1], right[1]) + 1e-9
        )

    values = (
        orientation(a, b, c),
        orientation(a, b, d),
        orientation(c, d, a),
        orientation(c, d, b),
    )
    if values[0] * values[1] < 0.0 and values[2] * values[3] < 0.0:
        return True
    return any(
        abs(value) <= 1e-9 and on_segment(left, middle, right)
        for value, left, middle, right in (
            (values[0], a, c, b),
            (values[1], a, d, b),
            (values[2], c, a, d),
            (values[3], c, b, d),
        )
    )


def _validate_absorption(
    absorption: float | dict[str, float] | str,
    *,
    field_name: str,
    application: str,
) -> None:
    if isinstance(absorption, bool):
        raise ValueError(f"{field_name} must not be a boolean.")
    if isinstance(absorption, str):
        from isaac_audio_sensors.core.acoustics.materials import (
            resolve_material_coefficients,
        )

        resolve_material_coefficients(
            absorption,
            "absorption",
            application=application,
        )
        return
    if isinstance(absorption, dict):
        if not absorption:
            raise ValueError(f"{field_name} mapping must not be empty.")
        for key, value in absorption.items():
            require_non_empty(key, f"{field_name} key")
            if isinstance(value, bool):
                raise ValueError(f"{field_name} values must not be booleans.")
            require_probability(value, f"{field_name} value")
        return
    require_probability(absorption, field_name)
