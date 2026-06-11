"""Structured debug-visualization records for Isaac review."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.core.math_utils import add, scale
from isaac_audio_sensors.core.microphone_array import microphone_world_positions
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSceneSnapshot,
    AudioSensorFrame,
    MicrophoneArraySpec,
)

CLEAR_BEARING_RAY_COLOR = (0.05, 0.9, 0.35, 1.0)
PARTIAL_OCCLUSION_BEARING_RAY_COLOR = (1.0, 0.65, 0.05, 1.0)
OCCLUDED_BEARING_RAY_COLOR = (0.95, 0.15, 0.1, 1.0)


@dataclass(frozen=True, slots=True, kw_only=True)
class BearingOverlayRecord:
    """Serializable description of a source-to-array or estimated bearing ray."""

    label: str
    start_world: tuple[float, float, float]
    bearing_deg: float | None
    confidence: float
    ambiguity_class: str | None = None


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

    source_by_id = {source.source_id: source for source in scene.sources}
    for detection in frame.detections:
        source_position = None
        if detection.source_pose is not None:
            source_position = detection.source_pose.position_m
        elif detection.source_id in source_by_id:
            source_position = source_by_id[detection.source_id].position_world
        if source_position is not None:
            primitives.append(
                DebugPrimitive(
                    kind="source",
                    label=f"source:{detection.source_id or detection.detection_id}",
                    points_world=(source_position,),
                    color_rgba=(1.0, 0.6, 0.05, 1.0),
                    radius_m=0.06,
                    metadata={"detection_id": detection.detection_id},
                )
            )

        bearing = detection.doa.estimated_bearing_deg
        if bearing is None:
            continue
        ray_start = sensor.position_world
        ray_length = detection.source_distance_m or bearing_length_m
        ray_end = _bearing_endpoint(sensor, bearing, ray_length)
        primitives.append(
            DebugPrimitive(
                kind="bearing_ray",
                label=f"bearing:{detection.detection_id}",
                points_world=(ray_start, ray_end),
                color_rgba=bearing_ray_color(detection),
                radius_m=0.015,
                metadata={
                    "bearing_deg": bearing,
                    "confidence": detection.doa.bearing_confidence,
                    "sector": detection.doa.bearing_sector,
                    "occluded": detection.occluded,
                    "occlusion_factor": _occlusion_factor(detection),
                },
            )
        )
        primitives.append(
            DebugPrimitive(
                kind="sector_wedge",
                label=f"sector:{detection.doa.bearing_sector or 'unknown'}",
                points_world=(
                    ray_start,
                    _bearing_endpoint(sensor, bearing - 22.5, bearing_length_m),
                    _bearing_endpoint(sensor, bearing + 22.5, bearing_length_m),
                ),
                color_rgba=(0.05, 0.9, 0.35, 0.3),
                radius_m=0.01,
                metadata={
                    "bearing_deg": bearing,
                    "sector": detection.doa.bearing_sector,
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
    detection: AudioDetection,
) -> tuple[float, float, float, float]:
    """Bearing-ray color by occlusion state: green, amber, or red."""

    if detection.occluded:
        return OCCLUDED_BEARING_RAY_COLOR
    factor = _occlusion_factor(detection)
    if factor is not None and factor > 0.0:
        return PARTIAL_OCCLUSION_BEARING_RAY_COLOR
    return CLEAR_BEARING_RAY_COLOR


def _occlusion_factor(detection: AudioDetection) -> float | None:
    occlusion = detection.diagnostics.get("occlusion")
    if not isinstance(occlusion, dict):
        return None
    factor = occlusion.get("occlusion_factor")
    return None if factor is None else float(factor)


def _bearing_endpoint(
    sensor: MicrophoneArraySpec,
    bearing_deg: float,
    length_m: float,
) -> tuple[float, float, float]:
    radians = math.radians(bearing_deg)
    direction = add(
        scale(sensor.forward_vec_world, math.cos(radians)),
        scale(sensor.right_vec_world, math.sin(radians)),
    )
    return add(sensor.position_world, scale(direction, length_m))
