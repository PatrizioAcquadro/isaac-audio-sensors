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

from dataclasses import dataclass
from typing import Any, Protocol

from isaac_audio_sensors.core.constants import OCCLUSION_BAND_CENTERS_HZ
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.math_utils import Vector3, add, norm, scale, subtract
from isaac_audio_sensors.core.microphone_array import microphone_world_positions
from isaac_audio_sensors.core.types import AudioSceneSnapshot, SourceOcclusion

DEFAULT_OCCLUSION_MAX_ATTENUATION_DB = 20.0
DEFAULT_OCCLUSION_ATTENUATION_CAP_DB = 60.0
DEFAULT_ENDPOINT_EPSILON_M = 0.01
DEFAULT_MAX_RECASTS = 4
DEFAULT_MAX_HITS_PER_RAY = 8

OCCLUSION_MODEL_RAYCAST_TRANSMISSION = "raycast_transmission_v1"

TRANSMISSION_LOSS_ATTR = "ias:transmission_loss_db"
TRANSMISSION_LOSS_BANDS_ATTR = "ias:transmission_loss_db_bands"

# Illustrative octave-band transmission-loss presets (dB per surface hit),
# aligned with OCCLUSION_BAND_CENTERS_HZ. These are documentation-grade
# approximations for simulation plausibility, not measured material truth.
DEFAULT_MATERIAL_TRANSMISSION_DB: dict[str, tuple[float, ...]] = {
    "concrete": (33.0, 36.0, 40.0, 44.0, 50.0, 55.0),
    "brick": (30.0, 33.0, 37.0, 42.0, 48.0, 52.0),
    "metal": (20.0, 25.0, 30.0, 35.0, 39.0, 42.0),
    "drywall": (15.0, 22.0, 29.0, 34.0, 39.0, 44.0),
    "plaster": (15.0, 22.0, 29.0, 34.0, 39.0, 44.0),
    "glass": (18.0, 22.0, 26.0, 30.0, 33.0, 36.0),
    "wood": (15.0, 19.0, 23.0, 26.0, 29.0, 32.0),
    "fabric": (3.0, 4.0, 6.0, 9.0, 12.0, 15.0),
    "curtain": (3.0, 4.0, 6.0, 9.0, 12.0, 15.0),
}


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

    def loss_for(self, prim_path: str) -> TransmissionLoss:
        """Return the transmission loss for one blocking prim path."""

        prim = self._prim(prim_path)
        explicit = self._explicit_loss(prim)
        if explicit is not None:
            return explicit
        preset = self._preset_loss(prim, prim_path)
        if preset is not None:
            return preset
        return TransmissionLoss(broadband_db=self.default_db)

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

    def _explicit_loss(self, prim: Any | None) -> TransmissionLoss | None:
        if prim is None:
            return None
        bands_value = _prim_attr(prim, TRANSMISSION_LOSS_BANDS_ATTR)
        if bands_value is not None:
            bands = tuple(float(value) for value in bands_value)
            if len(bands) == len(OCCLUSION_BAND_CENTERS_HZ):
                return TransmissionLoss(
                    broadband_db=sum(bands) / len(bands),
                    band_db=bands,
                    material="usd_attribute",
                )
        broadband_value = _prim_attr(prim, TRANSMISSION_LOSS_ATTR)
        if broadband_value is not None:
            return TransmissionLoss(
                broadband_db=float(broadband_value),
                material="usd_attribute",
            )
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
                    return TransmissionLoss(
                        broadband_db=sum(bands) / len(bands),
                        band_db=tuple(float(value) for value in bands),
                        material=token,
                    )
        return None


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

    if max_attenuation_db < 0.0:
        raise ValueError("max_attenuation_db must be non-negative.")
    if attenuation_cap_db < 0.0:
        raise ValueError("attenuation_cap_db must be non-negative.")
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
                    broadband += max(0.0, float(loss.broadband_db))
                    hit_bands = (
                        loss.band_db
                        if loss.band_db is not None
                        and len(loss.band_db) == band_count
                        else None
                    )
                    if hit_bands is not None:
                        mic_has_band_data = True
                    for index in range(band_count):
                        bands[index] += max(
                            0.0,
                            float(
                                hit_bands[index]
                                if hit_bands is not None
                                else loss.broadband_db
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
                        OCCLUSION_BAND_CENTERS_HZ
                        if per_mic_band_attenuation_db
                        else ()
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

    if prim is None:
        return None
    try:
        from pxr import UsdShade  # type: ignore
    except ImportError:
        return None
    try:
        binding = UsdShade.MaterialBindingAPI(prim)
        material, _ = binding.ComputeBoundMaterial()
        if material and material.GetPrim().IsValid():
            return str(material.GetPath())
    except Exception:  # noqa: BLE001 - material lookup is best-effort.
        return None
    return None


def _carb_vec3(value: Vector3) -> Any:
    try:
        import carb  # type: ignore
    except ImportError:
        return (float(value[0]), float(value[1]), float(value[2]))
    return carb.Float3(float(value[0]), float(value[1]), float(value[2]))
