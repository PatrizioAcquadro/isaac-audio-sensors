"""Isaac-layer occlusion raycasts: material-aware ray/transmission model.

The Isaac layer computes per-source, per-microphone occlusion by walking each
source-to-microphone ray through the PhysX scene query interface, accumulating
transmission loss for every blocking surface hit along the path. Material loss
comes from explicit USD attributes on the hit prim, from a small preset table
matched against bound-material or prim-path tokens, or from a flat default.
The pure core only consumes the resulting ``SourceOcclusion`` records from
``AudioSceneSnapshot.occlusion``.

This is a ray/transmission model, not a wave-acoustic solver: diffraction,
edge effects, and thickness-dependent transmission are not modeled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from isaac_audio_sensors.core.acoustics.materials import (
    LEGACY_MATERIAL_ALIASES,
    MaterialResolution,
    resolve_material,
    resolve_material_coefficients,
)
from isaac_audio_sensors.core.constants import OCCLUSION_BAND_CENTERS_HZ
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.math_utils import Vector3, add, norm, scale, subtract
from isaac_audio_sensors.core.microphone_array import microphone_world_positions
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    SourceOcclusion,
)

DEFAULT_OCCLUSION_MAX_ATTENUATION_DB = 20.0
DEFAULT_OCCLUSION_ATTENUATION_CAP_DB = 60.0
DEFAULT_ENDPOINT_EPSILON_M = 0.01
DEFAULT_MAX_RECASTS = 4
DEFAULT_MAX_HITS_PER_RAY = 8

OCCLUSION_MODEL_RAYCAST_TRANSMISSION = "raycast_transmission_v1"

TRANSMISSION_LOSS_ATTR = "ias:transmission_loss_db"
TRANSMISSION_LOSS_BANDS_ATTR = "ias:transmission_loss_db_bands"
ACOUSTIC_MATERIAL_ID_ATTR = "ias:acoustic_material_id"

# Illustrative octave-band transmission-loss presets (dB per surface hit),
# aligned with OCCLUSION_BAND_CENTERS_HZ. These are documentation-grade
# approximations for simulation plausibility, not measured material truth.
DEFAULT_MATERIAL_TRANSMISSION_DB: dict[str, tuple[float, ...]] = {
    alias: resolve_material_coefficients(target, "transmission_db").values
    for alias, target in LEGACY_MATERIAL_ALIASES.items()
}


@dataclass(slots=True)
class LiveOcclusionState:
    """Own live pair comparison, refresh reasons, and diagnostics."""

    enabled: bool = False
    max_attenuation_db: float = DEFAULT_OCCLUSION_MAX_ATTENUATION_DB
    attenuation_cap_db: float = DEFAULT_OCCLUSION_ATTENUATION_CAP_DB
    raycaster: Any | None = None
    transmission_resolver: Any | None = None
    _previous_pairs: dict[tuple[str, str], tuple[Any, ...]] = field(
        default_factory=dict
    )
    _has_previous_capture: bool = False
    _pending_pairs: dict[tuple[str, str], tuple[Any, ...]] | None = None
    _frame_state: dict[str, Any] | None = None

    def begin_capture(self) -> None:
        self._pending_pairs = None
        self._frame_state = None

    def reset(self) -> None:
        self._previous_pairs.clear()
        self._has_previous_capture = False
        self.begin_capture()

    def apply(
        self,
        scene: AudioSceneSnapshot,
        *,
        stage: Any,
        cache: Any | None,
        stage_diagnostics: dict[str, Any],
    ) -> AudioSceneSnapshot:
        if not self.enabled:
            return scene
        try:
            if self.raycaster is None:
                self.raycaster = IsaacPhysxRaycaster()
            if self.transmission_resolver is None:
                self.transmission_resolver = UsdTransmissionLossResolver(
                    stage,
                    default_db=self.max_attenuation_db,
                )
            records = compute_scene_occlusion(
                scene,
                self.raycaster,
                max_attenuation_db=self.max_attenuation_db,
                transmission_resolver=self.transmission_resolver,
                attenuation_cap_db=self.attenuation_cap_db,
            )
        except IsaacIntegrationUnavailable as exc:
            stage_diagnostics["occlusion"] = {
                "status": "unavailable",
                "error": str(exc),
            }
            self._frame_state = {"occlusion_recompute_count": 0}
            return scene

        current_pairs = {
            (record.array_id, record.source_id): _canonical_pair(record)
            for record in records
        }
        changed_pairs = [
            f"{array.array_id}:{source.source_id}"
            for array in scene.arrays
            for source in scene.sources
            if self._has_previous_capture
            and self._previous_pairs.get((array.array_id, source.source_id))
            != current_pairs.get((array.array_id, source.source_id))
        ]
        if cache is not None and cache.pending_non_audio_pose_paths and changed_pairs:
            cache.record_acoustic_refresh("occluder_moved")
        self._pending_pairs = current_pairs
        state: dict[str, Any] = {"occlusion_recompute_count": 1}
        if self._has_previous_capture:
            state["changed_occlusion_pairs"] = changed_pairs
        material_evidence = getattr(self.transmission_resolver, "material_evidence", {})
        if isinstance(material_evidence, dict) and material_evidence:
            state["material_evidence"] = {
                key: dict(material_evidence[key]) for key in sorted(material_evidence)
            }
        self._frame_state = state
        stage_diagnostics["occlusion"] = {
            "status": "computed",
            "record_count": len(records),
            "max_attenuation_db": float(self.max_attenuation_db),
            "attenuation_cap_db": float(self.attenuation_cap_db),
            "occlusion_model": OCCLUSION_MODEL_RAYCAST_TRANSMISSION,
        }
        return replace(scene, occlusion=records)

    def merge_frame(
        self,
        frame: AudioSensorFrame,
        *,
        cache: Any | None,
        stage_diagnostics: dict[str, Any] | None,
    ) -> AudioSensorFrame:
        diagnostics = dict(frame.diagnostics)
        backend_state = diagnostics.get("acoustics_state")
        state = dict(backend_state) if isinstance(backend_state, dict) else {}
        if self._frame_state is not None:
            live_materials = self._frame_state.get("material_evidence")
            room_materials = state.get("material_evidence")
            merged_materials: dict[str, Any] = {}
            if isinstance(room_materials, dict) and "room" in room_materials:
                merged_materials["room"] = room_materials["room"]
            for mapping in (room_materials, live_materials):
                if isinstance(mapping, dict):
                    for key in sorted(mapping):
                        if key != "room":
                            merged_materials[key] = mapping[key]
            if merged_materials:
                state["material_evidence"] = merged_materials
            state.update(
                (key, value)
                for key, value in self._frame_state.items()
                if key != "material_evidence"
            )
        reasons = () if cache is None else cache.consume_acoustic_refresh_reasons()
        if state or self.enabled:
            state["refresh_reasons"] = list(reasons)
            diagnostics["acoustics_state"] = state
        if cache is not None:
            if self._pending_pairs is not None:
                self._previous_pairs = self._pending_pairs
                self._has_previous_capture = True
                cache.clear_pending_non_audio_pose_paths()
            if isinstance(stage_diagnostics, dict):
                cache_diagnostics = stage_diagnostics.get("discovery_cache")
                if isinstance(cache_diagnostics, dict):
                    cache_diagnostics["acoustic_refresh_reasons"] = tuple(
                        cache.acoustic_refresh_reasons
                    )
        self._pending_pairs = None
        return replace(frame, diagnostics=diagnostics)


def _canonical_pair(record: SourceOcclusion) -> tuple[Any, ...]:
    return (
        record.array_id,
        record.source_id,
        tuple(record.per_mic_blocked.items()),
        record.occlusion_factor,
        record.attenuation_db,
        tuple(record.per_mic_attenuation_db.items()),
        tuple(record.band_centers_hz),
        tuple(
            (mic_id, tuple(values))
            for mic_id, values in record.per_mic_band_attenuation_db.items()
        ),
        tuple(record.hit_prim_paths),
        tuple(
            (mic_id, tuple(paths))
            for mic_id, paths in record.per_mic_hit_prim_paths.items()
        ),
        tuple(sorted(record.hit_materials.items())),
        record.occlusion_model,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class OcclusionHit:
    """One blocking-candidate hit returned by an occlusion raycaster."""

    prim_path: str
    distance_m: float


@dataclass(frozen=True, slots=True, kw_only=True)
class TransmissionLoss:
    """Transmission loss attributed to one blocking surface hit."""

    broadband_db: float
    band_db: tuple[float, ...] | None = None
    material: str | None = None
    expanded_band_db: tuple[float, ...] | None = None
    material_id: str | None = None
    evidence: str = "nominal"
    citation: str | None = None


class TransmissionLossResolver(Protocol):
    """Maps a blocking hit's prim path to its transmission loss."""

    def loss_for(self, prim_path: str) -> TransmissionLoss:
        """Return the per-hit loss for one blocking prim path."""


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


class UsdTransmissionLossResolver:
    """Default per-hit loss lookup: USD attrs, then presets, then default.

    Precedence per blocking prim: explicit ``ias:transmission_loss_db`` /
    ``ias:transmission_loss_db_bands`` attributes on the hit prim (when a
    stage is available), then a preset matched case-insensitively against the
    bound-material name or prim-path tokens, then a flat ``default_db``.
    """

    def __init__(
        self,
        stage: Any | None = None,
        *,
        presets: dict[str, tuple[float, ...]] | None = None,
        default_db: float = DEFAULT_OCCLUSION_MAX_ATTENUATION_DB,
    ) -> None:
        self.stage = stage
        self.presets = (
            DEFAULT_MATERIAL_TRANSMISSION_DB if presets is None else dict(presets)
        )
        self.default_db = float(default_db)
        if not math.isfinite(self.default_db) or self.default_db < 0.0:
            raise ValueError("default_db must be finite and non-negative.")
        for name, bands in self.presets.items():
            _validated_transmission_vector(
                bands,
                application=f"transmission preset {name!r}",
            )
        self.material_evidence: dict[str, dict[str, str]] = {}

    def begin_capture(self) -> None:
        """Clear per-capture material applications before fresh raycasts."""

        self.material_evidence.clear()

    def loss_for(self, prim_path: str) -> TransmissionLoss:
        """Return the transmission loss for one blocking prim path."""

        prim = self._prim(prim_path)
        explicit = self._explicit_loss(prim, prim_path=prim_path)
        if explicit is not None:
            self._record_evidence(prim_path, explicit)
            return explicit
        bound_path, bound_prim = _bound_material(prim)
        if bound_prim is not None:
            bound_explicit = self._explicit_loss(
                bound_prim,
                prim_path=bound_path or prim_path,
            )
            if bound_explicit is not None:
                self._record_evidence(prim_path, bound_explicit)
                return bound_explicit
        referenced = self._referenced_material_loss(prim, prim_path=prim_path)
        if referenced is not None:
            self._record_evidence(prim_path, referenced)
            return referenced
        preset = self._preset_loss(prim, prim_path)
        if preset is not None:
            self._record_evidence(prim_path, preset)
            return preset
        fallback = TransmissionLoss(
            broadband_db=self.default_db,
            material_id=f"configured_fallback:{self.default_db:g}-db",
        )
        self._record_evidence(prim_path, fallback)
        return fallback

    def _prim(self, prim_path: str) -> Any | None:
        if self.stage is None or not prim_path:
            return None
        get_prim = getattr(self.stage, "GetPrimAtPath", None)
        if not callable(get_prim):
            return None
        prim = get_prim(prim_path)
        if prim is None or (hasattr(prim, "IsValid") and not prim.IsValid()):
            return None
        return prim

    def _explicit_loss(
        self,
        prim: Any | None,
        *,
        prim_path: str,
    ) -> TransmissionLoss | None:
        if prim is None:
            return None
        bands_value = _prim_attr(prim, TRANSMISSION_LOSS_BANDS_ATTR)
        if bands_value is not None:
            bands = _validated_transmission_vector(
                bands_value,
                application=f"USD attribute on {prim_path}",
            )
            return TransmissionLoss(
                broadband_db=sum(bands) / len(bands),
                band_db=bands,
                material="usd_attribute",
                material_id=f"usd_attribute:{prim_path}",
            )
        broadband_value = _prim_attr(prim, TRANSMISSION_LOSS_ATTR)
        if broadband_value is not None:
            broadband = _validated_nonnegative_float(
                broadband_value,
                application=f"USD attribute on {prim_path}",
            )
            return TransmissionLoss(
                broadband_db=broadband,
                material="usd_attribute",
                expanded_band_db=(broadband,) * len(OCCLUSION_BAND_CENTERS_HZ),
                material_id=f"usd_attribute:{prim_path}",
            )
        return None

    def _referenced_material_loss(
        self,
        prim: Any | None,
        *,
        prim_path: str,
    ) -> TransmissionLoss | None:
        if prim is None:
            return None
        for attr_name in (ACOUSTIC_MATERIAL_ID_ATTR, "ias:material"):
            value = _prim_attr(prim, attr_name)
            if value is None or not str(value).strip():
                continue
            resolution = resolve_material_coefficients(
                str(value),
                "transmission_db",
                application=f"occluder {prim_path!r} attribute {attr_name}",
            )
            return _loss_from_resolution(resolution, legacy_material=False)
        bound_path, bound_prim = _bound_material(prim)
        if bound_prim is None:
            return None
        for attr_name in (ACOUSTIC_MATERIAL_ID_ATTR, "ias:material"):
            value = _prim_attr(bound_prim, attr_name)
            if value is None or not str(value).strip():
                continue
            resolution = resolve_material_coefficients(
                str(value),
                "transmission_db",
                application=(
                    f"bound material {bound_path!r} for occluder {prim_path!r}"
                ),
            )
            return _loss_from_resolution(resolution, legacy_material=False)
        return None

    def _preset_loss(
        self,
        prim: Any | None,
        prim_path: str,
    ) -> TransmissionLoss | None:
        candidates = [prim_path.lower()]
        material_name = _bound_material_name(prim)
        if material_name:
            candidates.insert(0, material_name.lower())
        for candidate in candidates:
            for token, bands in self.presets.items():
                if token.lower() in candidate:
                    try:
                        material_id = resolve_material(token).material_id
                    except ValueError:
                        material_id = f"nominal.custom:{token}"
                    return TransmissionLoss(
                        broadband_db=sum(bands) / len(bands),
                        band_db=tuple(float(value) for value in bands),
                        material=token,
                        material_id=material_id,
                    )
        return None

    def _record_evidence(self, prim_path: str, loss: TransmissionLoss) -> None:
        if loss.material_id is None:
            return
        record = {
            "material_id": loss.material_id,
            "coefficient": "transmission_db",
            "evidence": loss.evidence,
        }
        if loss.evidence == "measured":
            assert loss.citation is not None
            record["citation"] = loss.citation
        self.material_evidence[f"occluder:{prim_path}"] = record


def compute_scene_occlusion(
    scene: AudioSceneSnapshot,
    raycaster: Any,
    *,
    max_attenuation_db: float = DEFAULT_OCCLUSION_MAX_ATTENUATION_DB,
    endpoint_epsilon_m: float = DEFAULT_ENDPOINT_EPSILON_M,
    max_recasts: int = DEFAULT_MAX_RECASTS,
    transmission_resolver: TransmissionLossResolver | None = None,
    attenuation_cap_db: float = DEFAULT_OCCLUSION_ATTENUATION_CAP_DB,
    max_hits_per_ray: int = DEFAULT_MAX_HITS_PER_RAY,
) -> tuple[SourceOcclusion, ...]:
    """Raycast every source toward every microphone of every array.

    Each ray is walked past every blocking surface (bounded by
    ``max_hits_per_ray``); hits on the source prim or the array prim are
    skipped by re-casting just past them. Per-microphone attenuation is the
    capped sum of per-hit transmission losses (flat ``max_attenuation_db``
    when no resolver is configured). The per-source ``attenuation_db`` is the
    mean of the per-microphone values, which for single-hit defaults equals
    the legacy ``occlusion_factor * max_attenuation_db``.
    """

    if not math.isfinite(max_attenuation_db) or max_attenuation_db < 0.0:
        raise ValueError("max_attenuation_db must be finite and non-negative.")
    if not math.isfinite(attenuation_cap_db) or attenuation_cap_db < 0.0:
        raise ValueError("attenuation_cap_db must be finite and non-negative.")
    begin_capture = getattr(transmission_resolver, "begin_capture", None)
    if callable(begin_capture):
        begin_capture()
    band_count = len(OCCLUSION_BAND_CENTERS_HZ)
    records: list[SourceOcclusion] = []
    for array in scene.arrays:
        mic_positions = microphone_world_positions(array)
        for source in scene.sources:
            excluded_prefixes = tuple(
                prefix for prefix in (source.prim_path, array.prim_path) if prefix
            )
            per_mic_blocked: dict[str, bool] = {}
            per_mic_attenuation_db: dict[str, float] = {}
            per_mic_band_attenuation_db: dict[str, tuple[float, ...]] = {}
            per_mic_hit_prim_paths: dict[str, tuple[str, ...]] = {}
            hit_prim_paths: list[str] = []
            hit_materials: dict[str, str] = {}
            any_band_data = False
            for mic_id, mic_position in mic_positions.items():
                hits = _ray_hits(
                    raycaster,
                    origin=source.position_world,
                    target=mic_position,
                    excluded_prefixes=excluded_prefixes,
                    endpoint_epsilon_m=endpoint_epsilon_m,
                    max_recasts=max_recasts,
                    max_hits=max_hits_per_ray,
                )
                per_mic_blocked[mic_id] = bool(hits)
                per_mic_hit_prim_paths[mic_id] = hits
                for hit_path in hits:
                    if hit_path not in hit_prim_paths:
                        hit_prim_paths.append(hit_path)
                broadband = 0.0
                bands = [0.0] * band_count
                mic_has_band_data = False
                for hit_path in hits:
                    loss = (
                        transmission_resolver.loss_for(hit_path)
                        if transmission_resolver is not None
                        else TransmissionLoss(broadband_db=float(max_attenuation_db))
                    )
                    broadband_loss = _validated_nonnegative_float(
                        loss.broadband_db,
                        application=f"transmission loss for {hit_path!r}",
                    )
                    broadband += broadband_loss
                    raw_hit_bands = (
                        loss.band_db
                        if loss.band_db is not None
                        else loss.expanded_band_db
                    )
                    hit_bands = (
                        None
                        if raw_hit_bands is None
                        else _validated_transmission_vector(
                            raw_hit_bands,
                            application=f"transmission loss for {hit_path!r}",
                        )
                    )
                    if hit_bands is not None:
                        mic_has_band_data = True
                    for index in range(band_count):
                        bands[index] += max(
                            0.0,
                            float(
                                hit_bands[index]
                                if hit_bands is not None
                                else broadband_loss
                            ),
                        )
                    if loss.material is not None:
                        hit_materials.setdefault(hit_path, loss.material)
                per_mic_attenuation_db[mic_id] = min(
                    broadband, float(attenuation_cap_db)
                )
                if mic_has_band_data:
                    any_band_data = True
                per_mic_band_attenuation_db[mic_id] = tuple(
                    min(value, float(attenuation_cap_db)) for value in bands
                )
            if not any_band_data:
                per_mic_band_attenuation_db = {}
            blocked_count = sum(per_mic_blocked.values())
            factor = blocked_count / len(per_mic_blocked) if per_mic_blocked else 0.0
            attenuation_db = (
                sum(per_mic_attenuation_db.values()) / len(per_mic_attenuation_db)
                if per_mic_attenuation_db
                else 0.0
            )
            records.append(
                SourceOcclusion(
                    array_id=array.array_id,
                    source_id=source.source_id,
                    per_mic_blocked=per_mic_blocked,
                    occlusion_factor=factor,
                    attenuation_db=attenuation_db,
                    hit_prim_paths=tuple(hit_prim_paths),
                    per_mic_attenuation_db=per_mic_attenuation_db,
                    per_mic_band_attenuation_db=per_mic_band_attenuation_db,
                    band_centers_hz=(
                        OCCLUSION_BAND_CENTERS_HZ if per_mic_band_attenuation_db else ()
                    ),
                    per_mic_hit_prim_paths=per_mic_hit_prim_paths,
                    hit_materials=hit_materials,
                    occlusion_model=OCCLUSION_MODEL_RAYCAST_TRANSMISSION,
                )
            )
    return tuple(records)


def _ray_hits(
    raycaster: Any,
    *,
    origin: Vector3,
    target: Vector3,
    excluded_prefixes: tuple[str, ...],
    endpoint_epsilon_m: float,
    max_recasts: int,
    max_hits: int,
) -> tuple[str, ...]:
    """Ordered distinct blocking prim paths along one source-to-mic ray.

    Repeated hits on the same prim (e.g. the entry and exit faces of one
    thick collider, or zero-distance re-hits from inside it) count as one
    partition traversal: transmission loss accumulates per blocking prim,
    not per surface face.
    """

    delta = subtract(target, origin)
    total_distance = norm(delta)
    if total_distance <= 2.0 * endpoint_epsilon_m:
        return ()
    direction = scale(delta, 1.0 / total_distance)
    start = add(origin, scale(direction, endpoint_epsilon_m))
    remaining = total_distance - 2.0 * endpoint_epsilon_m
    blocking_paths: list[str] = []
    for _ in range(max_recasts + max_hits):
        hit = raycaster.raycast_closest(start, direction, remaining)
        if hit is None:
            break
        if (
            not _path_excluded(hit.prim_path, excluded_prefixes)
            and hit.prim_path not in blocking_paths
        ):
            blocking_paths.append(hit.prim_path)
            if len(blocking_paths) >= max_hits:
                break
        advance = max(float(hit.distance_m), 0.0) + endpoint_epsilon_m
        start = add(start, scale(direction, advance))
        remaining -= advance
        if remaining <= 0.0:
            break
    return tuple(blocking_paths)


def _path_excluded(path: str, excluded_prefixes: tuple[str, ...]) -> bool:
    return any(
        path == prefix or path.startswith(f"{prefix.rstrip('/')}/")
        for prefix in excluded_prefixes
    )


def _prim_attr(prim: Any, name: str) -> Any | None:
    """Read one attribute from a real USD prim or a duck-typed fake prim."""

    attributes = getattr(prim, "attributes", None)
    if isinstance(attributes, dict):
        return attributes.get(name)
    get_attribute = getattr(prim, "GetAttribute", None)
    if callable(get_attribute):
        attribute = get_attribute(name)
        if attribute is None:
            return None
        is_valid = getattr(attribute, "IsValid", None)
        if callable(is_valid) and not is_valid():
            return None
        get = getattr(attribute, "Get", None)
        if callable(get):
            return get()
    return None


def _bound_material_name(prim: Any) -> str | None:
    """Best-effort bound-material name for preset matching."""

    path, _material_prim = _bound_material(prim)
    return path


def _bound_material(prim: Any) -> tuple[str | None, Any | None]:
    """Best-effort bound material path and prim for exact-id resolution."""

    if prim is None:
        return None, None
    duck_material = getattr(prim, "bound_material", None)
    if duck_material is not None:
        path = getattr(duck_material, "path", None)
        return (None if path is None else str(path)), duck_material
    try:
        from pxr import UsdShade  # type: ignore
    except ImportError:
        return None, None
    try:
        binding = UsdShade.MaterialBindingAPI(prim)
        material, _ = binding.ComputeBoundMaterial()
        if material and material.GetPrim().IsValid():
            return str(material.GetPath()), material.GetPrim()
    except Exception:  # noqa: BLE001 - material lookup is best-effort.
        return None, None
    return None, None


def _validated_nonnegative_float(value: Any, *, application: str) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{application} must be a finite non-negative value.") from exc
    if not math.isfinite(resolved) or resolved < 0.0:
        raise ValueError(f"{application} must be a finite non-negative value.")
    return resolved


def _validated_transmission_vector(
    values: Any,
    *,
    application: str,
) -> tuple[float, ...]:
    try:
        resolved = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{application} transmission vector must contain finite values."
        ) from exc
    expected = len(OCCLUSION_BAND_CENTERS_HZ)
    if len(resolved) != expected:
        raise ValueError(
            f"{application} transmission vector must contain exactly {expected} "
            f"bands, got {len(resolved)}."
        )
    if any(not math.isfinite(value) or value < 0.0 for value in resolved):
        raise ValueError(
            f"{application} transmission values must be finite and non-negative."
        )
    return resolved


def _loss_from_resolution(
    resolution: MaterialResolution,
    *,
    legacy_material: bool,
) -> TransmissionLoss:
    material = (
        resolution.material_id.removeprefix("nominal.")
        if legacy_material
        else resolution.material_id
    )
    return TransmissionLoss(
        broadband_db=sum(resolution.values) / len(resolution.values),
        band_db=resolution.values,
        material=material,
        material_id=resolution.material_id,
        evidence=resolution.evidence,
        citation=resolution.citation,
    )


def _carb_vec3(value: Vector3) -> Any:
    try:
        import carb  # type: ignore
    except ImportError:
        return (float(value[0]), float(value[1]), float(value[2]))
    return carb.Float3(float(value[0]), float(value[1]), float(value[2]))
