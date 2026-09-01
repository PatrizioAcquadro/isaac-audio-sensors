"""Isaac-layer occlusion raycasts: material-aware ray/transmission model.

The Isaac layer computes per-source, per-microphone occlusion by walking each
source-to-microphone ray through the PhysX scene query interface, accumulating
transmission loss for every distinct acoustic partition along the path. Material loss
comes from explicit USD attributes on the hit prim, from a small preset table
matched against bound-material or prim-path tokens, or from an explicit nominal
unknown-material fallback.
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

DEFAULT_UNKNOWN_MATERIAL_LOSS_DB = 20.0
DEFAULT_ENDPOINT_EPSILON_M = 0.01
DEFAULT_MAX_RECASTS = 4
DEFAULT_MAX_HITS_PER_RAY = 8

OCCLUSION_MODEL_RAYCAST_TRANSMISSION = "raycast_transmission_v1"

TRANSMISSION_LOSS_ATTR = "ias:transmission_loss_db"
TRANSMISSION_LOSS_BANDS_ATTR = "ias:transmission_loss_db_bands"
ACOUSTIC_MATERIAL_ID_ATTR = "ias:acoustic_material_id"
ACOUSTIC_PARTITION_ID_ATTR = "ias:acoustic_partition_id"

# Illustrative octave-band whole-partition transmission-loss presets (dB),
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
    unknown_material_loss_db: float = DEFAULT_UNKNOWN_MATERIAL_LOSS_DB
    trace_enabled: bool = False
    raycaster: Any | None = None
    transmission_resolver: Any | None = None
    latest_trace: tuple[_OcclusionRayTrace, ...] = field(
        default_factory=tuple,
        init=False,
    )
    _previous_pairs: dict[tuple[str, str], tuple[Any, ...]] = field(
        default_factory=dict
    )
    _has_previous_capture: bool = False
    _pending_pairs: dict[tuple[str, str], tuple[Any, ...]] | None = None
    _frame_state: dict[str, Any] | None = None

    def begin_capture(self) -> None:
        self._pending_pairs = None
        self._frame_state = None
        self.latest_trace = ()

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
                    unknown_material_loss_db=self.unknown_material_loss_db,
                )
            trace: list[_OcclusionRayTrace] | None = [] if self.trace_enabled else None
            occlusion_diagnostics: dict[str, Any] = {}
            records = compute_scene_occlusion(
                scene,
                self.raycaster,
                unknown_material_loss_db=self.unknown_material_loss_db,
                transmission_resolver=self.transmission_resolver,
                diagnostics_out=occlusion_diagnostics,
                trace_out=trace,
            )
        except IsaacIntegrationUnavailable as exc:
            stage_diagnostics["occlusion"] = {
                "status": "unavailable",
                "error": str(exc),
            }
            self._frame_state = {"occlusion_recompute_count": 0}
            return scene

        self.latest_trace = () if trace is None else tuple(trace)

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
        state: dict[str, Any] = {
            "occlusion_recompute_count": 1,
            "occlusion": occlusion_diagnostics,
        }
        if self._has_previous_capture:
            state["changed_occlusion_pairs"] = changed_pairs
        self._frame_state = state
        stage_diagnostics["occlusion"] = {
            "status": "computed",
            "record_count": len(records),
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
            state.update(self._frame_state)
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
        tuple(record.per_mic_attenuation_db.items()),
        tuple(record.band_centers_hz),
        tuple(
            (mic_id, tuple(values))
            for mic_id, values in record.per_mic_band_attenuation_db.items()
        ),
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
    unknown_material_fallback: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class _RayHit:
    prim_path: str
    point_world: Vector3


@dataclass(frozen=True, slots=True, kw_only=True)
class _OcclusionTraceHit:
    prim_path: str
    point_world: Vector3
    partition_id: str
    material_id: str | None
    broadband_db: float
    band_db: tuple[float, ...] | None
    unknown_material_fallback: bool
    applied: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class _OcclusionRayTrace:
    array_id: str
    source_id: str
    mic_id: str
    source_world: Vector3
    microphone_world: Vector3
    hits: tuple[_OcclusionTraceHit, ...]


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
    """Default per-hit loss lookup: USD attrs, presets, then nominal fallback.

    Precedence per blocking prim: explicit ``ias:transmission_loss_db`` /
    ``ias:transmission_loss_db_bands`` attributes on the hit prim (when a
    stage is available), then a preset matched case-insensitively against the
    bound-material name or prim-path tokens, then ``unknown_material_loss_db``.
    """

    def __init__(
        self,
        stage: Any | None = None,
        *,
        presets: dict[str, tuple[float, ...]] | None = None,
        unknown_material_loss_db: float = DEFAULT_UNKNOWN_MATERIAL_LOSS_DB,
    ) -> None:
        self.stage = stage
        self.presets = (
            DEFAULT_MATERIAL_TRANSMISSION_DB if presets is None else dict(presets)
        )
        self.unknown_material_loss_db = float(unknown_material_loss_db)
        if (
            not math.isfinite(self.unknown_material_loss_db)
            or self.unknown_material_loss_db < 0.0
        ):
            raise ValueError(
                "unknown_material_loss_db must be finite and non-negative."
            )
        for name, bands in self.presets.items():
            _validated_transmission_vector(
                bands,
                application=f"transmission preset {name!r}",
            )
    def loss_for(self, prim_path: str) -> TransmissionLoss:
        """Return the transmission loss for one blocking prim path."""

        prim = self._prim(prim_path)
        explicit = self._explicit_loss(prim, prim_path=prim_path)
        if explicit is not None:
            return explicit
        bound_path, bound_prim = _bound_material(prim)
        if bound_prim is not None:
            bound_explicit = self._explicit_loss(
                bound_prim,
                prim_path=bound_path or prim_path,
            )
            if bound_explicit is not None:
                return bound_explicit
        referenced = self._referenced_material_loss(prim, prim_path=prim_path)
        if referenced is not None:
            return referenced
        preset = self._preset_loss(prim, prim_path)
        if preset is not None:
            return preset
        fallback = TransmissionLoss(
            broadband_db=self.unknown_material_loss_db,
            material_id=(
                f"configured_unknown_material:{self.unknown_material_loss_db:g}-db"
            ),
            unknown_material_fallback=True,
        )
        return fallback

    def partition_id_for(self, prim_path: str) -> str:
        """Resolve one authored acoustic partition or use the collider path."""

        prim = self._prim(prim_path)
        value = None if prim is None else _prim_attr(prim, ACOUSTIC_PARTITION_ID_ATTR)
        if value is None:
            return prim_path
        partition_id = str(value).strip()
        if not partition_id:
            raise ValueError(
                f"{ACOUSTIC_PARTITION_ID_ATTR} on {prim_path!r} must be non-empty."
            )
        return partition_id

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
                material_id="usd_attribute",
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
                material_id="usd_attribute",
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

def compute_scene_occlusion(
    scene: AudioSceneSnapshot,
    raycaster: Any,
    *,
    unknown_material_loss_db: float = DEFAULT_UNKNOWN_MATERIAL_LOSS_DB,
    endpoint_epsilon_m: float = DEFAULT_ENDPOINT_EPSILON_M,
    max_recasts: int = DEFAULT_MAX_RECASTS,
    transmission_resolver: TransmissionLossResolver | None = None,
    max_hits_per_ray: int = DEFAULT_MAX_HITS_PER_RAY,
    diagnostics_out: dict[str, Any] | None = None,
    trace_out: list[_OcclusionRayTrace] | None = None,
) -> tuple[SourceOcclusion, ...]:
    """Raycast every source toward every microphone of every array.

    Multiple colliders assigned to one acoustic partition contribute one
    whole-assembly transmission curve. Distinct sequential partitions add in
    dB without a total-loss clamp. ``max_hits_per_ray`` bounds traversal and
    fails closed rather than returning a truncated attenuation.
    """

    if (
        not math.isfinite(unknown_material_loss_db)
        or unknown_material_loss_db < 0.0
    ):
        raise ValueError("unknown_material_loss_db must be finite and non-negative.")
    if not math.isfinite(endpoint_epsilon_m) or endpoint_epsilon_m <= 0.0:
        raise ValueError("endpoint_epsilon_m must be finite and positive.")
    for value, name, minimum in (
        (max_recasts, "max_recasts", 0),
        (max_hits_per_ray, "max_hits_per_ray", 1),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            qualifier = "non-negative" if minimum == 0 else "positive"
            raise ValueError(f"{name} must be a {qualifier} integer.")
    band_count = len(OCCLUSION_BAND_CENTERS_HZ)
    records: list[SourceOcclusion] = []
    partition_signatures: dict[str, tuple[Any, ...]] = {}
    material_resolution: dict[str, dict[str, Any]] | None = (
        {} if diagnostics_out is not None else None
    )
    fallback_applications: list[dict[str, Any]] | None = (
        [] if diagnostics_out is not None else None
    )
    for array in scene.arrays:
        mic_positions = microphone_world_positions(array)
        for source in scene.sources:
            excluded_prefixes = tuple(
                prefix for prefix in (source.prim_path, array.prim_path) if prefix
            )
            per_mic_blocked: dict[str, bool] = {}
            per_mic_attenuation_db: dict[str, float] = {}
            per_mic_band_attenuation_db: dict[str, tuple[float, ...]] = {}
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
                resolved_partitions: dict[
                    str,
                    tuple[TransmissionLoss, float, tuple[float, ...] | None],
                ] = {}
                trace_hits: list[_OcclusionTraceHit] | None = (
                    [] if trace_out is not None else None
                )
                broadband = 0.0
                bands = [0.0] * band_count
                mic_has_band_data = False
                for hit in hits:
                    partition_id = _partition_id_for(
                        transmission_resolver,
                        hit.prim_path,
                    )
                    loss = (
                        transmission_resolver.loss_for(hit.prim_path)
                        if transmission_resolver is not None
                        else TransmissionLoss(
                            broadband_db=float(unknown_material_loss_db),
                            material_id=(
                                "configured_unknown_material:"
                                f"{unknown_material_loss_db:g}-db"
                            ),
                            unknown_material_fallback=True,
                        )
                    )
                    broadband_loss = _validated_nonnegative_float(
                        loss.broadband_db,
                        application=f"transmission loss for {hit.prim_path!r}",
                    )
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
                            application=f"transmission loss for {hit.prim_path!r}",
                        )
                    )
                    signature = _loss_signature(
                        loss,
                        broadband_db=broadband_loss,
                        band_db=hit_bands,
                    )
                    previous_signature = partition_signatures.get(partition_id)
                    if (
                        previous_signature is not None
                        and previous_signature != signature
                    ):
                        raise ValueError(
                            f"Acoustic partition {partition_id!r} resolves conflicting "
                            "transmission curves or provenance."
                        )
                    partition_signatures.setdefault(partition_id, signature)
                    applied = partition_id not in resolved_partitions
                    if applied:
                        resolved_partitions[partition_id] = (
                            loss,
                            broadband_loss,
                            hit_bands,
                        )
                        broadband += broadband_loss
                        if hit_bands is not None:
                            mic_has_band_data = True
                        for index in range(band_count):
                            bands[index] += float(
                                hit_bands[index]
                                if hit_bands is not None
                                else broadband_loss
                            )
                        if material_resolution is not None:
                            material_resolution.setdefault(
                                partition_id,
                                _loss_evidence_record(
                                    loss,
                                    broadband_db=broadband_loss,
                                    band_db=hit_bands,
                                ),
                            )
                        if (
                            loss.unknown_material_fallback
                            and fallback_applications is not None
                        ):
                            fallback_applications.append(
                                {
                                    "array_id": array.array_id,
                                    "source_id": source.source_id,
                                    "mic_id": mic_id,
                                    "partition_id": partition_id,
                                    "attenuation_db": broadband_loss,
                                }
                            )
                    if trace_hits is not None:
                        trace_hits.append(
                            _OcclusionTraceHit(
                                prim_path=hit.prim_path,
                                point_world=hit.point_world,
                                partition_id=partition_id,
                                material_id=loss.material_id,
                                broadband_db=broadband_loss,
                                band_db=hit_bands,
                                unknown_material_fallback=(
                                    loss.unknown_material_fallback
                                ),
                                applied=applied,
                            )
                        )
                per_mic_blocked[mic_id] = bool(resolved_partitions)
                per_mic_attenuation_db[mic_id] = broadband
                if mic_has_band_data:
                    any_band_data = True
                per_mic_band_attenuation_db[mic_id] = tuple(bands)
                if trace_out is not None:
                    assert trace_hits is not None
                    trace_out.append(
                        _OcclusionRayTrace(
                            array_id=array.array_id,
                            source_id=source.source_id,
                            mic_id=mic_id,
                            source_world=source.position_world,
                            microphone_world=mic_position,
                            hits=tuple(trace_hits),
                        )
                    )
            if not any_band_data:
                per_mic_band_attenuation_db = {}
            records.append(
                SourceOcclusion(
                    array_id=array.array_id,
                    source_id=source.source_id,
                    per_mic_blocked=per_mic_blocked,
                    per_mic_attenuation_db=per_mic_attenuation_db,
                    per_mic_band_attenuation_db=per_mic_band_attenuation_db,
                    band_centers_hz=(
                        OCCLUSION_BAND_CENTERS_HZ if per_mic_band_attenuation_db else ()
                    ),
                )
            )
    if diagnostics_out is not None:
        assert material_resolution is not None
        assert fallback_applications is not None
        diagnostics_out.clear()
        diagnostics_out.update(
            {
                "model": OCCLUSION_MODEL_RAYCAST_TRANSMISSION,
                "unknown_material_loss_db": float(unknown_material_loss_db),
                "material_resolution": {
                    partition_id: material_resolution[partition_id]
                    for partition_id in sorted(material_resolution)
                },
                "unknown_material_fallbacks": fallback_applications,
            }
        )
    return tuple(records)


def _partition_id_for(
    transmission_resolver: TransmissionLossResolver | None,
    prim_path: str,
) -> str:
    resolver = getattr(transmission_resolver, "partition_id_for", None)
    partition_id = prim_path if not callable(resolver) else str(resolver(prim_path))
    partition_id = partition_id.strip()
    if not partition_id:
        raise ValueError(
            f"Acoustic partition id resolved from {prim_path!r} must be non-empty."
        )
    return partition_id


def _loss_signature(
    loss: TransmissionLoss,
    *,
    broadband_db: float,
    band_db: tuple[float, ...] | None,
) -> tuple[Any, ...]:
    return (
        broadband_db,
        band_db,
        loss.material,
        loss.material_id,
        loss.evidence,
        loss.citation,
        loss.unknown_material_fallback,
    )


def _loss_evidence_record(
    loss: TransmissionLoss,
    *,
    broadband_db: float,
    band_db: tuple[float, ...] | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "material_id": loss.material_id,
        "coefficient": "transmission_db",
        "evidence": loss.evidence,
        "broadband_db": broadband_db,
        "unknown_material_fallback": loss.unknown_material_fallback,
    }
    if band_db is not None:
        record["band_centers_hz"] = list(OCCLUSION_BAND_CENTERS_HZ)
        record["band_db"] = list(band_db)
    if loss.citation is not None:
        record["citation"] = loss.citation
    return record


def occlusion_trace_debug_primitives(
    traces: tuple[_OcclusionRayTrace, ...],
) -> tuple[Any, ...]:
    """Convert transient Isaac occlusion traces to the shared debug surface."""

    from isaac_audio_sensors.isaac.viz.overlays import DebugPrimitive

    primitives: list[DebugPrimitive] = []
    for trace in traces:
        applied_hits = tuple(hit for hit in trace.hits if hit.applied)
        color = (
            (0.95, 0.15, 0.1, 0.85)
            if applied_hits
            else (0.05, 0.9, 0.35, 0.55)
        )
        primitives.append(
            DebugPrimitive(
                kind="occlusion_ray",
                label=(
                    f"occlusion:{trace.array_id}:{trace.source_id}:{trace.mic_id}"
                ),
                points_world=(
                    trace.source_world,
                    *(hit.point_world for hit in trace.hits),
                    trace.microphone_world,
                ),
                color_rgba=color,
                radius_m=0.01,
                metadata={
                    "array_id": trace.array_id,
                    "source_id": trace.source_id,
                    "mic_id": trace.mic_id,
                    "partitions": [
                        {
                            "partition_id": hit.partition_id,
                            "prim_path": hit.prim_path,
                            "material_id": hit.material_id,
                            "broadband_db": hit.broadband_db,
                            "band_db": (
                                None if hit.band_db is None else list(hit.band_db)
                            ),
                            "unknown_material_fallback": (
                                hit.unknown_material_fallback
                            ),
                            "applied": hit.applied,
                        }
                        for hit in trace.hits
                    ],
                },
            )
        )
        for index, hit in enumerate(trace.hits):
            primitives.append(
                DebugPrimitive(
                    kind="occlusion_hit",
                    label=(
                        f"occlusion-hit:{trace.array_id}:{trace.source_id}:"
                        f"{trace.mic_id}:{index}"
                    ),
                    points_world=(hit.point_world,),
                    color_rgba=(0.95, 0.15, 0.1, 1.0),
                    radius_m=0.025,
                    metadata={
                        "partition_id": hit.partition_id,
                        "prim_path": hit.prim_path,
                        "applied": hit.applied,
                    },
                )
            )
    return tuple(primitives)


def _ray_hits(
    raycaster: Any,
    *,
    origin: Vector3,
    target: Vector3,
    excluded_prefixes: tuple[str, ...],
    endpoint_epsilon_m: float,
    max_recasts: int,
    max_hits: int,
) -> tuple[_RayHit, ...]:
    """Ordered distinct collider hits along one source-to-microphone ray.

    Repeated hits on the same prim (e.g. the entry and exit faces of one
    thick collider, or zero-distance re-hits from inside it) are recast past.
    Acoustic-partition deduplication happens after material resolution.
    """

    delta = subtract(target, origin)
    total_distance = norm(delta)
    if total_distance <= 2.0 * endpoint_epsilon_m:
        return ()
    direction = scale(delta, 1.0 / total_distance)
    start = add(origin, scale(direction, endpoint_epsilon_m))
    remaining = total_distance - 2.0 * endpoint_epsilon_m
    blocking_hits: list[_RayHit] = []
    blocking_paths: set[str] = set()
    ignored_recasts = 0
    while remaining > 0.0:
        hit = raycaster.raycast_closest(start, direction, remaining)
        if hit is None:
            break
        prim_path = str(hit.prim_path).strip()
        if not prim_path:
            raise ValueError("Occlusion raycast returned an empty prim path.")
        distance_m = _validated_nonnegative_float(
            hit.distance_m,
            application=f"occlusion hit distance for {prim_path!r}",
        )
        point_world = add(start, scale(direction, distance_m))
        if _path_excluded(prim_path, excluded_prefixes) or prim_path in blocking_paths:
            ignored_recasts += 1
            if ignored_recasts > max_recasts:
                raise ValueError(
                    "Occlusion ray exceeded max_recasts while skipping endpoint "
                    "or repeated collider hits."
                )
        else:
            if len(blocking_hits) >= max_hits:
                raise ValueError(
                    "Occlusion ray exceeded max_hits_per_ray; refusing truncated "
                    "transmission loss."
                )
            blocking_paths.add(prim_path)
            blocking_hits.append(
                _RayHit(prim_path=prim_path, point_world=point_world)
            )
        advance = distance_m + endpoint_epsilon_m
        start = add(start, scale(direction, advance))
        remaining -= advance
    return tuple(blocking_hits)


def _path_excluded(path: str, excluded_prefixes: tuple[str, ...]) -> bool:
    return any(
        path == prefix or path.startswith(f"{prefix.rstrip('/')}/")
        for prefix in excluded_prefixes
    )


def _prim_attr(prim: Any, name: str) -> Any | None:
    """Read one attribute from a USD-compatible prim."""

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
