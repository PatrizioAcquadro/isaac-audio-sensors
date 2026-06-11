"""Isaac-layer occlusion raycasts: the first shipped L3 capability.

The Isaac layer computes per-source occlusion by casting one ray from each
active source toward each microphone of each array through the PhysX scene
query interface. The pure core only consumes the resulting
``SourceOcclusion`` records from ``AudioSceneSnapshot.occlusion``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.math_utils import Vector3, add, norm, scale, subtract
from isaac_audio_sensors.core.microphone_array import microphone_world_positions
from isaac_audio_sensors.core.types import AudioSceneSnapshot, SourceOcclusion

DEFAULT_OCCLUSION_MAX_ATTENUATION_DB = 20.0
DEFAULT_ENDPOINT_EPSILON_M = 0.01
DEFAULT_MAX_RECASTS = 4


@dataclass(frozen=True, slots=True, kw_only=True)
class OcclusionHit:
    """One blocking-candidate hit returned by an occlusion raycaster."""

    prim_path: str
    distance_m: float


class IsaacPhysxRaycaster:
    """Closest-hit raycaster backed by the PhysX scene-query interface.

    The interface is acquired lazily on the first cast so that constructing
    sensors outside an Isaac Sim Python environment stays import-safe.
    """

    def __init__(self) -> None:
        self._interface: Any | None = None

    def raycast_closest(
        self,
        origin: Vector3,
        direction: Vector3,
        max_distance_m: float,
    ) -> OcclusionHit | None:
        """Return the closest collider hit along a ray, or ``None``."""

        interface = self._acquire()
        hit = interface.raycast_closest(
            _carb_vec3(origin),
            _carb_vec3(direction),
            float(max_distance_m),
        )
        if not hit or not hit.get("hit"):
            return None
        return OcclusionHit(
            prim_path=str(hit.get("collision", "")),
            distance_m=float(hit.get("distance", 0.0)),
        )

    def _acquire(self) -> Any:
        if self._interface is None:
            try:
                from omni.physx import (  # type: ignore
                    get_physx_scene_query_interface,
                )
            except ImportError as exc:
                raise IsaacIntegrationUnavailable(
                    "PhysX occlusion raycasts require omni.physx inside an "
                    "Isaac Sim Python environment."
                ) from exc
            self._interface = get_physx_scene_query_interface()
        if self._interface is None:
            raise IsaacIntegrationUnavailable(
                "omni.physx is importable, but no PhysX scene-query interface "
                "was acquired."
            )
        return self._interface


def compute_scene_occlusion(
    scene: AudioSceneSnapshot,
    raycaster: Any,
    *,
    max_attenuation_db: float = DEFAULT_OCCLUSION_MAX_ATTENUATION_DB,
    endpoint_epsilon_m: float = DEFAULT_ENDPOINT_EPSILON_M,
    max_recasts: int = DEFAULT_MAX_RECASTS,
) -> tuple[SourceOcclusion, ...]:
    """Raycast every source toward every microphone of every array.

    Hits on the source prim or the array prim themselves are skipped by
    re-casting just past them (bounded by ``max_recasts``), so self-geometry
    never counts as occlusion. The per-source ``occlusion_factor`` is the
    fraction of blocked source-to-microphone rays and ``attenuation_db`` is
    ``occlusion_factor * max_attenuation_db``.
    """

    if max_attenuation_db < 0.0:
        raise ValueError("max_attenuation_db must be non-negative.")
    records: list[SourceOcclusion] = []
    for array in scene.arrays:
        mic_positions = microphone_world_positions(array)
        for source in scene.sources:
            excluded_prefixes = tuple(
                prefix for prefix in (source.prim_path, array.prim_path) if prefix
            )
            per_mic_blocked: dict[str, bool] = {}
            hit_prim_paths: list[str] = []
            for mic_id, mic_position in mic_positions.items():
                blocked, hits = _ray_blocked(
                    raycaster,
                    origin=source.position_world,
                    target=mic_position,
                    excluded_prefixes=excluded_prefixes,
                    endpoint_epsilon_m=endpoint_epsilon_m,
                    max_recasts=max_recasts,
                )
                per_mic_blocked[mic_id] = blocked
                for hit_path in hits:
                    if hit_path not in hit_prim_paths:
                        hit_prim_paths.append(hit_path)
            blocked_count = sum(per_mic_blocked.values())
            factor = blocked_count / len(per_mic_blocked) if per_mic_blocked else 0.0
            records.append(
                SourceOcclusion(
                    array_id=array.array_id,
                    source_id=source.source_id,
                    per_mic_blocked=per_mic_blocked,
                    occlusion_factor=factor,
                    attenuation_db=factor * float(max_attenuation_db),
                    hit_prim_paths=tuple(hit_prim_paths),
                )
            )
    return tuple(records)


def _ray_blocked(
    raycaster: Any,
    *,
    origin: Vector3,
    target: Vector3,
    excluded_prefixes: tuple[str, ...],
    endpoint_epsilon_m: float,
    max_recasts: int,
) -> tuple[bool, tuple[str, ...]]:
    delta = subtract(target, origin)
    total_distance = norm(delta)
    if total_distance <= 2.0 * endpoint_epsilon_m:
        return False, ()
    direction = scale(delta, 1.0 / total_distance)
    start = add(origin, scale(direction, endpoint_epsilon_m))
    remaining = total_distance - 2.0 * endpoint_epsilon_m
    blocking_paths: list[str] = []
    for _ in range(max_recasts + 1):
        hit = raycaster.raycast_closest(start, direction, remaining)
        if hit is None:
            return False, tuple(blocking_paths)
        if _path_excluded(hit.prim_path, excluded_prefixes):
            advance = max(float(hit.distance_m), 0.0) + endpoint_epsilon_m
            start = add(start, scale(direction, advance))
            remaining -= advance
            if remaining <= 0.0:
                return False, tuple(blocking_paths)
            continue
        blocking_paths.append(hit.prim_path)
        return True, tuple(blocking_paths)
    return False, tuple(blocking_paths)


def _path_excluded(path: str, excluded_prefixes: tuple[str, ...]) -> bool:
    return any(
        path == prefix or path.startswith(f"{prefix.rstrip('/')}/")
        for prefix in excluded_prefixes
    )


def _carb_vec3(value: Vector3) -> Any:
    try:
        import carb  # type: ignore
    except ImportError:
        return (float(value[0]), float(value[1]), float(value[2]))
    return carb.Float3(float(value[0]), float(value[1]), float(value[2]))
