"""Fail-closed acoustic-environment resolution for USD-compatible stages."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.core.acoustics.environments import (
    half_space_environment,
    shoebox_environment_from_bounds,
    world_to_environment_point,
)
from isaac_audio_sensors.core.acoustics.materials import resolve_material
from isaac_audio_sensors.core.microphone_array import microphone_world_positions
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    MicrophoneArraySpec,
)
from isaac_audio_sensors.isaac.pose_resolver import (
    IsaacStagePoseResolver,
    prim_path,
)
from isaac_audio_sensors.isaac.usd_bounds import (
    ABSORPTION_ATTR,
    DEFAULT_SEMANTIC_ABSORPTION,
    MATERIAL_ATTR,
    resolve_environment_absorption,
    world_aligned_bbox,
)

ENVIRONMENT_KIND_ATTR = "ias:environment_kind"
ENVIRONMENT_ID_ATTR = "ias:environment_id"
ENVIRONMENT_PRIORITY_ATTR = "ias:environment_priority"
ISAAC_ENVIRONMENT_RESOLUTION_MODES = frozenset({"manual", "anchor", "auto"})
USD_ENVIRONMENT_KINDS = frozenset({"shoebox", "half_space"})
DEFAULT_CONTAINMENT_TOLERANCE_M = 0.001
DEFAULT_ENVIRONMENT_ABSORPTION = 0.35


@dataclass(frozen=True, slots=True, kw_only=True)
class IsaacEnvironmentResolutionCfg:
    """Select how Isaac obtains the mandatory Core acoustic environment."""

    mode: str
    anchor_prim_path: str | None = None
    candidate_roots: tuple[str, ...] = ("/World",)
    containment_tolerance_m: float = DEFAULT_CONTAINMENT_TOLERANCE_M

    def __post_init__(self) -> None:
        if self.mode not in ISAAC_ENVIRONMENT_RESOLUTION_MODES:
            raise ValueError(
                "IsaacEnvironmentResolutionCfg.mode must be one of "
                f"{sorted(ISAAC_ENVIRONMENT_RESOLUTION_MODES)}."
            )
        anchor = self.anchor_prim_path
        if anchor is not None:
            anchor = str(anchor).rstrip("/")
            if not anchor.startswith("/"):
                raise ValueError("anchor_prim_path must be an absolute USD path.")
            object.__setattr__(self, "anchor_prim_path", anchor)
        if self.mode == "anchor" and anchor is None:
            raise ValueError("mode='anchor' requires anchor_prim_path.")
        if self.mode != "anchor" and anchor is not None:
            raise ValueError("anchor_prim_path is accepted only when mode='anchor'.")
        roots = tuple(str(root).rstrip("/") or "/" for root in self.candidate_roots)
        if not roots or any(not root.startswith("/") for root in roots):
            raise ValueError("candidate_roots must contain absolute USD paths.")
        if len(set(roots)) != len(roots):
            raise ValueError("candidate_roots must not contain duplicates.")
        object.__setattr__(self, "candidate_roots", roots)
        tolerance = float(self.containment_tolerance_m)
        if not math.isfinite(tolerance) or tolerance < 0.0:
            raise ValueError("containment_tolerance_m must be finite and non-negative.")
        object.__setattr__(self, "containment_tolerance_m", tolerance)


@dataclass(frozen=True, slots=True)
class _Candidate:
    environment: AcousticEnvironmentSpec
    prim_path: str
    priority: int
    volume_m3: float | None
    absorption_provenance: str


def resolve_stage_environment(
    stage: Any,
    array: MicrophoneArraySpec,
    *,
    cfg: IsaacEnvironmentResolutionCfg,
    manual_environment: AcousticEnvironmentSpec | None = None,
    time_code: Any | None = None,
    prims: tuple[Any, ...] | None = None,
    diagnostics_out: dict[str, Any] | None = None,
) -> AcousticEnvironmentSpec:
    """Resolve and validate one environment for the complete microphone array."""

    if not isinstance(cfg, IsaacEnvironmentResolutionCfg):
        raise ValueError("cfg must be an IsaacEnvironmentResolutionCfg.")
    if not isinstance(array, MicrophoneArraySpec):
        raise ValueError("array must be a MicrophoneArraySpec.")
    diagnostics: dict[str, Any] = {
        "mode": cfg.mode,
        "containment_tolerance_m": cfg.containment_tolerance_m,
    }
    if cfg.mode == "manual":
        if not isinstance(manual_environment, AcousticEnvironmentSpec):
            raise ValueError(
                "mode='manual' requires an explicit AcousticEnvironmentSpec."
            )
        _require_array_contained(
            manual_environment,
            array,
            tolerance_m=cfg.containment_tolerance_m,
            context="manual environment",
        )
        diagnostics.update(
            {
                "selected_prim_path": None,
                "environment_id": manual_environment.environment_id,
                "kind": manual_environment.kind,
                "candidate_count": 0,
            }
        )
        _replace_diagnostics(diagnostics_out, diagnostics)
        return manual_environment
    if manual_environment is not None:
        raise ValueError(f"mode={cfg.mode!r} must not receive a manual environment.")

    resolver = IsaacStagePoseResolver(stage, time_code=time_code, prims=prims)
    if cfg.mode == "anchor":
        assert cfg.anchor_prim_path is not None
        try:
            anchor_prim = resolver.prim(cfg.anchor_prim_path)
        except ValueError as exc:
            raise ValueError(
                f"Environment anchor {cfg.anchor_prim_path!r} is missing; the "
                "previous environment cannot be reused."
            ) from exc
        candidate = _candidate_from_prim(
            anchor_prim,
            resolver=resolver,
            explicit_anchor=True,
        )
        _require_array_contained(
            candidate.environment,
            array,
            tolerance_m=cfg.containment_tolerance_m,
            context=f"environment anchor {candidate.prim_path!r}",
        )
        diagnostics.update(_candidate_diagnostics(candidate, candidate_count=1))
        _replace_diagnostics(diagnostics_out, diagnostics)
        return candidate.environment

    candidates = tuple(
        _candidate_from_prim(prim, resolver=resolver, explicit_anchor=False)
        for prim in resolver.prims
        if _is_marked_candidate(prim, resolver=resolver, roots=cfg.candidate_roots)
    )
    volumes = tuple(
        candidate
        for candidate in candidates
        if candidate.environment.kind == "shoebox"
        and _array_is_contained(
            candidate.environment,
            array,
            tolerance_m=cfg.containment_tolerance_m,
        )
    )
    floors = tuple(
        candidate
        for candidate in candidates
        if candidate.environment.kind == "half_space"
        and _array_is_contained(
            candidate.environment,
            array,
            tolerance_m=cfg.containment_tolerance_m,
        )
    )
    selected = _select_volume(volumes) if volumes else _select_floor(floors)
    if selected is None:
        raise ValueError(
            "Automatic acoustic-environment resolution found no marked shoebox "
            "or half_space containing the complete microphone array. Select an "
            "explicit anchor or provide a manual environment."
        )
    diagnostics.update(
        _candidate_diagnostics(selected, candidate_count=len(candidates))
    )
    diagnostics["containing_volume_count"] = len(volumes)
    diagnostics["containing_floor_count"] = len(floors)
    _replace_diagnostics(diagnostics_out, diagnostics)
    return selected.environment


def _candidate_from_prim(
    prim: Any,
    *,
    resolver: IsaacStagePoseResolver,
    explicit_anchor: bool,
) -> _Candidate:
    path = prim_path(prim)
    attrs = resolver.attrs(prim)
    kind_value = attrs.get(ENVIRONMENT_KIND_ATTR)
    kind = "shoebox" if explicit_anchor and kind_value is None else str(kind_value)
    if kind not in USD_ENVIRONMENT_KINDS:
        raise ValueError(
            f"Acoustic environment prim {path!r} has invalid "
            f"{ENVIRONMENT_KIND_ATTR}={kind_value!r}; expected shoebox or half_space."
        )
    identifier = attrs.get(ENVIRONMENT_ID_ATTR)
    if identifier is None and explicit_anchor:
        identifier = path.rsplit("/", 1)[-1] or path
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError(
            f"Marked acoustic environment prim {path!r} requires a non-empty "
            f"{ENVIRONMENT_ID_ATTR}."
        )
    priority = attrs.get(ENVIRONMENT_PRIORITY_ATTR, 0)
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ValueError(
            f"Acoustic environment prim {path!r} requires integer "
            f"{ENVIRONMENT_PRIORITY_ATTR}."
        )
    absorption, provenance = _resolve_absorption(
        prim,
        attrs=attrs,
        time_code=resolver.time_code,
    )
    if kind == "shoebox":
        minimum, maximum = world_aligned_bbox(
            prim,
            prim_path=path,
            time_code=resolver.time_code,
        )
        environment = shoebox_environment_from_bounds(
            min_world=minimum,
            max_world=maximum,
            environment_id=identifier.strip(),
            absorption=absorption,
        )
        assert environment.dimensions_m is not None
        volume = math.prod(environment.dimensions_m)
    else:
        pose = resolver.resolve_world_pose(
            prim,
            field_name=f"half-space environment {path}",
        )
        environment = half_space_environment(
            environment_id=identifier.strip(),
            absorption=absorption,
            position_world=pose.position_world,
            orientation_world_quat=(
                pose.orientation_world_quat or (0.0, 0.0, 0.0, 1.0)
            ),
        )
        volume = None
    return _Candidate(environment, path, priority, volume, provenance)


def _resolve_absorption(
    prim: Any,
    *,
    attrs: dict[str, Any],
    time_code: Any | None,
) -> tuple[float | dict[str, float] | str, str]:
    if attrs.get(ABSORPTION_ATTR) is not None:
        value = attrs[ABSORPTION_ATTR]
        if isinstance(value, dict):
            return {str(key): float(item) for key, item in value.items()}, (
                f"attr:{ABSORPTION_ATTR}"
            )
        return float(value), f"attr:{ABSORPTION_ATTR}"
    acoustic_id = attrs.get("ias:acoustic_material_id")
    if acoustic_id is not None:
        material = resolve_material(
            str(acoustic_id),
            application=f"environment prim {prim_path(prim)!r}",
        )
        return material.material_id, "attr:ias:acoustic_material_id"
    material_id = attrs.get(MATERIAL_ATTR)
    if material_id is not None and str(material_id).strip():
        try:
            material = resolve_material(
                str(material_id),
                application=f"environment prim {prim_path(prim)!r}",
            )
            return material.material_id, f"attr:{MATERIAL_ATTR}"
        except ValueError:
            pass
    return resolve_environment_absorption(
        prim,
        semantic_absorption=dict(DEFAULT_SEMANTIC_ABSORPTION),
        default=DEFAULT_ENVIRONMENT_ABSORPTION,
        time_code=time_code,
    )


def _is_marked_candidate(
    prim: Any,
    *,
    resolver: IsaacStagePoseResolver,
    roots: tuple[str, ...],
) -> bool:
    path = prim_path(prim)
    if not any(_path_in_root(path, root) for root in roots):
        return False
    return ENVIRONMENT_KIND_ATTR in resolver.attrs(prim)


def _path_in_root(path: str, root: str) -> bool:
    return root == "/" or path == root or path.startswith(f"{root}/")


def _select_volume(candidates: tuple[_Candidate, ...]) -> _Candidate | None:
    if not candidates:
        return None
    priority = max(candidate.priority for candidate in candidates)
    preferred = tuple(item for item in candidates if item.priority == priority)
    minimum_volume = min(
        candidate.volume_m3
        for candidate in preferred
        if candidate.volume_m3 is not None
    )
    smallest = tuple(
        candidate
        for candidate in preferred
        if candidate.volume_m3 is not None
        and math.isclose(
            candidate.volume_m3,
            minimum_volume,
            rel_tol=1e-9,
            abs_tol=1e-12,
        )
    )
    if len(smallest) != 1:
        raise ValueError(
            "Automatic acoustic-volume resolution is ambiguous after priority "
            "and smallest-volume selection; choose an explicit anchor. Candidates: "
            f"{[candidate.prim_path for candidate in smallest]!r}."
        )
    return smallest[0]


def _select_floor(candidates: tuple[_Candidate, ...]) -> _Candidate | None:
    if not candidates:
        return None
    priority = max(candidate.priority for candidate in candidates)
    preferred = tuple(item for item in candidates if item.priority == priority)
    if len(preferred) != 1:
        raise ValueError(
            "Automatic half-space resolution is ambiguous at the highest priority; "
            "choose an explicit anchor. Candidates: "
            f"{[candidate.prim_path for candidate in preferred]!r}."
        )
    return preferred[0]


def _require_array_contained(
    environment: AcousticEnvironmentSpec,
    array: MicrophoneArraySpec,
    *,
    tolerance_m: float,
    context: str,
) -> None:
    if _array_is_contained(environment, array, tolerance_m=tolerance_m):
        return
    raise ValueError(
        f"The complete microphone array {array.array_id!r} is not contained by "
        f"{context} {environment.environment_id!r} within tolerance {tolerance_m} m."
    )


def _array_is_contained(
    environment: AcousticEnvironmentSpec,
    array: MicrophoneArraySpec,
    *,
    tolerance_m: float,
) -> bool:
    points = tuple(microphone_world_positions(array).values())
    if environment.kind in {"free_field", "surface_set"}:
        return True
    local_points = tuple(
        world_to_environment_point(environment, point) for point in points
    )
    if environment.kind == "half_space":
        return all(point[2] >= -tolerance_m for point in local_points)
    if environment.kind == "shoebox":
        assert environment.dimensions_m is not None
        return all(
            all(
                -tolerance_m
                <= point[axis]
                <= environment.dimensions_m[axis] + tolerance_m
                for axis in range(3)
            )
            for point in local_points
        )
    if environment.kind == "polygon_prism":
        floor = next(
            surface for surface in environment.surfaces if surface.role == "floor"
        )
        ceiling_z = max(
            vertex[2]
            for surface in environment.surfaces
            for vertex in surface.vertices_local_m
        )
        polygon = tuple((vertex[0], vertex[1]) for vertex in floor.vertices_local_m)
        return all(
            -tolerance_m <= point[2] <= ceiling_z + tolerance_m
            and _point_in_polygon((point[0], point[1]), polygon, tolerance_m)
            for point in local_points
        )
    return False


def _point_in_polygon(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
    tolerance: float,
) -> bool:
    x, y = point
    inside = False
    for start, end in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        x1, y1 = start
        x2, y2 = end
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) <= tolerance and (
            min(x1, x2) - tolerance <= x <= max(x1, x2) + tolerance
            and min(y1, y2) - tolerance <= y <= max(y1, y2) + tolerance
        ):
            return True
        if (y1 > y) != (y2 > y):
            intersection_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection_x:
                inside = not inside
    return inside


def _candidate_diagnostics(
    candidate: _Candidate,
    *,
    candidate_count: int,
) -> dict[str, Any]:
    return {
        "candidate_count": candidate_count,
        "selected_prim_path": candidate.prim_path,
        "environment_id": candidate.environment.environment_id,
        "kind": candidate.environment.kind,
        "priority": candidate.priority,
        "volume_m3": candidate.volume_m3,
        "absorption_provenance": candidate.absorption_provenance,
    }


def _replace_diagnostics(
    destination: dict[str, Any] | None,
    values: dict[str, Any],
) -> None:
    if destination is not None:
        destination.clear()
        destination.update(values)


__all__ = [
    "DEFAULT_CONTAINMENT_TOLERANCE_M",
    "ENVIRONMENT_ID_ATTR",
    "ENVIRONMENT_KIND_ATTR",
    "ENVIRONMENT_PRIORITY_ATTR",
    "ISAAC_ENVIRONMENT_RESOLUTION_MODES",
    "IsaacEnvironmentResolutionCfg",
    "resolve_stage_environment",
]
