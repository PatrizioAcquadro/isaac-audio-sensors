"""Structured debug-visualization records for Isaac review."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.core.acoustics.environments import (
    environment_to_world_point,
)
from isaac_audio_sensors.core.math_utils import add, basis_from_quaternion, scale
from isaac_audio_sensors.core.microphone_array import microphone_world_positions
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AudioObservation,
    AudioSceneSnapshot,
    AudioSensorFrame,
    MicrophoneArraySpec,
)

BEARING_RAY_COLOR = (0.05, 0.9, 0.35, 1.0)
ENVIRONMENT_OUTLINE_COLOR = (0.95, 0.85, 0.1, 1.0)


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugPrimitive:
    """Backend-neutral debug primitive that can be drawn in Isaac or serialized."""

    kind: str
    label: str
    points_world: tuple[tuple[float, float, float], ...]
    color_rgba: tuple[float, float, float, float]
    radius_m: float | None = None
    metadata: dict[str, Any] | None = None


def build_debug_primitives(
    *,
    frame: AudioSensorFrame,
    scene: AudioSceneSnapshot,
    sensor: MicrophoneArraySpec,
    bearing_length_m: float = 2.0,
) -> tuple[DebugPrimitive, ...]:
    """Build deterministic debug primitives for a frame without Isaac imports."""

    primitives: list[DebugPrimitive] = []
    if scene.environment is not None:
        primitives.extend(_environment_primitives(scene.environment))
    for mic_id, position in microphone_world_positions(sensor).items():
        primitives.append(
            DebugPrimitive(
                kind="microphone",
                label=f"mic:{mic_id}",
                points_world=(position,),
                color_rgba=(0.1, 0.45, 1.0, 1.0),
                radius_m=0.035,
                metadata={"array_id": sensor.array_id},
            )
        )

    for observation in frame.observations:
        if observation.doa is None:
            continue
        bearing = observation.doa.estimated_bearing_deg
        if bearing is None:
            continue
        ray_start = sensor.position_world
        ray_end = _bearing_endpoint(sensor, bearing, bearing_length_m)
        primitives.append(
            DebugPrimitive(
                kind="bearing_ray",
                label=f"bearing:{observation.observation_id}",
                points_world=(ray_start, ray_end),
                color_rgba=bearing_ray_color(observation),
                radius_m=0.015,
                metadata={
                    "bearing_deg": bearing,
                    "confidence": observation.doa.bearing_confidence,
                    "sector": observation.doa.bearing_sector,
                    "origin": observation.origin.value,
                    "detector_id": observation.detector_id,
                },
            )
        )
        primitives.append(
            DebugPrimitive(
                kind="sector_wedge",
                label=f"sector:{observation.doa.bearing_sector or 'unknown'}",
                points_world=(
                    ray_start,
                    _bearing_endpoint(sensor, bearing - 22.5, bearing_length_m),
                    _bearing_endpoint(sensor, bearing + 22.5, bearing_length_m),
                ),
                color_rgba=(0.05, 0.9, 0.35, 0.3),
                radius_m=0.01,
                metadata={
                    "bearing_deg": bearing,
                    "sector": observation.doa.bearing_sector,
                },
            )
        )
    return tuple(primitives)


def environment_outline_points(
    environment: AcousticEnvironmentSpec,
) -> tuple[tuple[float, float, float], ...]:
    """Trace all 12 edges of one shoebox environment in world coordinates.

    A box has eight odd-degree corners, so a single stroke must retrace
    three edges; retraced segments overdraw invisibly.
    """

    if environment.kind != "shoebox" or environment.dimensions_m is None:
        raise ValueError("environment_outline_points requires a shoebox environment.")
    dimensions_m = environment.dimensions_m

    def corner(x_max: bool, y_max: bool, z_max: bool) -> tuple[float, float, float]:
        return environment_to_world_point(
            environment,
            (
                dimensions_m[0] if x_max else 0.0,
                dimensions_m[1] if y_max else 0.0,
                dimensions_m[2] if z_max else 0.0,
            ),
        )

    a = corner(False, False, False)
    b = corner(True, False, False)
    c = corner(True, True, False)
    d = corner(False, True, False)
    a_top = corner(False, False, True)
    b_top = corner(True, False, True)
    c_top = corner(True, True, True)
    d_top = corner(False, True, True)
    return (
        a,
        b,
        c,
        d,
        a,
        a_top,
        b_top,
        c_top,
        d_top,
        a_top,
        b_top,
        b,
        c,
        c_top,
        d_top,
        d,
    )


def _environment_primitives(
    environment: AcousticEnvironmentSpec,
) -> tuple[DebugPrimitive, ...]:
    metadata = {
        "environment_id": environment.environment_id,
        "kind": environment.kind,
        "dimensions_m": environment.dimensions_m,
        "position_world": environment.world_pose.position_m,
        "orientation_world_quat": environment.world_pose.orientation_xyzw,
    }
    if environment.kind == "shoebox":
        return (
            DebugPrimitive(
                kind="environment_outline",
                label=f"environment:{environment.environment_id}",
                points_world=environment_outline_points(environment),
                color_rgba=ENVIRONMENT_OUTLINE_COLOR,
                radius_m=0.02,
                metadata=metadata,
            ),
        )
    primitives = []
    for surface in environment.surfaces:
        local_vertices = surface.vertices_local_m
        if surface.infinite:
            local_vertices = (
                (-2.0, -2.0, 0.0),
                (2.0, -2.0, 0.0),
                (2.0, 2.0, 0.0),
                (-2.0, 2.0, 0.0),
            )
        points = tuple(
            environment_to_world_point(environment, vertex) for vertex in local_vertices
        )
        if points:
            points = (*points, points[0])
        primitives.append(
            DebugPrimitive(
                kind="environment_surface",
                label=f"environment:{environment.environment_id}:{surface.surface_id}",
                points_world=points,
                color_rgba=ENVIRONMENT_OUTLINE_COLOR,
                radius_m=0.02,
                metadata={
                    **metadata,
                    "surface_id": surface.surface_id,
                    "role": surface.role,
                    "infinite": surface.infinite,
                },
            )
        )
    return tuple(primitives)


def debug_primitives_to_dicts(
    primitives: tuple[DebugPrimitive, ...],
) -> list[dict[str, Any]]:
    """Return JSON-ready debug primitive dictionaries."""

    return [
        {
            "kind": primitive.kind,
            "label": primitive.label,
            "points_world": [list(point) for point in primitive.points_world],
            "color_rgba": list(primitive.color_rgba),
            "radius_m": primitive.radius_m,
            "metadata": primitive.metadata or {},
        }
        for primitive in primitives
    ]


def bearing_ray_color(
    observation: AudioObservation,
) -> tuple[float, float, float, float]:
    """Return the neutral observed-bearing color."""

    del observation
    return BEARING_RAY_COLOR


def _bearing_endpoint(
    sensor: MicrophoneArraySpec,
    bearing_deg: float,
    length_m: float,
) -> tuple[float, float, float]:
    radians = math.radians(bearing_deg)
    forward, right, _ = basis_from_quaternion(sensor.orientation_world_quat)
    direction = add(
        scale(forward, math.cos(radians)),
        scale(right, math.sin(radians)),
    )
    return add(sensor.position_world, scale(direction, length_m))
