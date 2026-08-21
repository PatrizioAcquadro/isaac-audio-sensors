"""Public dataclasses for audio scenes, arrays, detections, and frames."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
    DETECTION_MODES,
    FRAME_PROVENANCE_VALUES,
    FRAME_SCHEMA_VERSION,
    FRAME_UNITS,
    OPTIONAL_FRAME_UNIT_KEYS,
    ROOM_OUT_OF_BOUNDS_POLICIES,
)
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    as_quaternion_xyzw,
    as_vector3,
    normalize_bearing_deg,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Pose3D:
    """World-frame pose used by the public audio sensor frame schema."""

    position_m: Vector3
    orientation_xyzw: Quaternion | None = None
    frame: str = "world"
    coordinate_convention: str = COORDINATE_CONVENTION

    def __post_init__(self) -> None:
        _require_non_empty(self.frame, "Pose3D.frame")
        _require_coordinate_convention(
            self.coordinate_convention,
            "Pose3D.coordinate_convention",
        )
        object.__setattr__(
            self,
            "position_m",
            as_vector3(self.position_m, "Pose3D.position_m"),
        )
        if self.orientation_xyzw is not None:
            object.__setattr__(
                self,
                "orientation_xyzw",
                as_quaternion_xyzw(
                    self.orientation_xyzw,
                    "Pose3D.orientation_xyzw",
                ),
            )

    @classmethod
    def from_array(cls, array: MicrophoneArraySpec) -> Pose3D:
        """Build an array pose from a microphone array spec."""

        return cls(
            position_m=array.position_world,
            orientation_xyzw=array.orientation_world_quat,
            coordinate_convention=array.coordinate_convention,
        )

    @classmethod
    def from_source(cls, source: AudioSourceSpec) -> Pose3D:
        """Build a source pose from a source spec."""

        return cls(
            position_m=source.position_world,
            orientation_xyzw=source.orientation_world_quat,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioSourceSpec:
    """Known sound source in a scene snapshot."""

    source_id: str
    prim_path: str
    class_label: str
    audio_asset_path: str | None
    position_world: Vector3
    orientation_world_quat: Quaternion | None
    start_time_s: float
    duration_s: float | None
    gain_db: float
    directivity: str = "omni"
    velocity_world_mps: Vector3 | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.source_id, "AudioSourceSpec.source_id")
        _require_non_empty(self.prim_path, "AudioSourceSpec.prim_path")
        _require_non_empty(self.class_label, "AudioSourceSpec.class_label")
        _require_non_empty(self.directivity, "AudioSourceSpec.directivity")
        object.__setattr__(
            self,
            "position_world",
            as_vector3(self.position_world, "AudioSourceSpec.position_world"),
        )
        if self.velocity_world_mps is not None:
            object.__setattr__(
                self,
                "velocity_world_mps",
                as_vector3(
                    self.velocity_world_mps,
                    "AudioSourceSpec.velocity_world_mps",
                ),
            )
        if self.orientation_world_quat is not None:
            object.__setattr__(
                self,
                "orientation_world_quat",
                as_quaternion_xyzw(
                    self.orientation_world_quat,
                    "AudioSourceSpec.orientation_world_quat",
                ),
            )
        _require_finite(self.start_time_s, "AudioSourceSpec.start_time_s")
        _require_finite(self.gain_db, "AudioSourceSpec.gain_db")
        if self.duration_s is not None:
            _require_finite(self.duration_s, "AudioSourceSpec.duration_s")
            if self.duration_s <= 0.0:
                raise ValueError("AudioSourceSpec.duration_s must be positive.")

    def is_active_in(self, start_time_s: float, end_time_s: float) -> bool:
        """Return whether the source overlaps a half-open time window."""

        source_end = (
            math.inf if self.duration_s is None else self.start_time_s + self.duration_s
        )
        return self.start_time_s < end_time_s and source_end > start_time_s


@dataclass(frozen=True, slots=True, kw_only=True)
class MicrophoneSpec:
    """One microphone in an array-local frame."""

    mic_id: str
    relative_position_m: Vector3
    relative_orientation_quat: Quaternion | None = None
    gain_db: float = 0.0
    self_noise_db: float | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.mic_id, "MicrophoneSpec.mic_id")
        object.__setattr__(
            self,
            "relative_position_m",
            as_vector3(
                self.relative_position_m,
                "MicrophoneSpec.relative_position_m",
            ),
        )
        if self.relative_orientation_quat is not None:
            object.__setattr__(
                self,
                "relative_orientation_quat",
                as_quaternion_xyzw(
                    self.relative_orientation_quat,
                    "MicrophoneSpec.relative_orientation_quat",
                ),
            )
        _require_finite(self.gain_db, "MicrophoneSpec.gain_db")
        if self.self_noise_db is not None:
            _require_finite(self.self_noise_db, "MicrophoneSpec.self_noise_db")


@dataclass(frozen=True, slots=True, kw_only=True)
class MicrophoneArraySpec:
    """Microphone array pose and layout in the public core convention."""

    array_id: str
    prim_path: str
    position_world: Vector3
    orientation_world_quat: Quaternion
    microphones: tuple[MicrophoneSpec, ...]
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    coordinate_convention: str = COORDINATE_CONVENTION
    velocity_world_mps: Vector3 | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.array_id, "MicrophoneArraySpec.array_id")
        _require_non_empty(self.prim_path, "MicrophoneArraySpec.prim_path")
        _require_coordinate_convention(
            self.coordinate_convention,
            "MicrophoneArraySpec.coordinate_convention",
        )
        object.__setattr__(
            self,
            "position_world",
            as_vector3(self.position_world, "MicrophoneArraySpec.position_world"),
        )
        object.__setattr__(
            self,
            "orientation_world_quat",
            as_quaternion_xyzw(
                self.orientation_world_quat,
                "MicrophoneArraySpec.orientation_world_quat",
            ),
        )
        if self.velocity_world_mps is not None:
            object.__setattr__(
                self,
                "velocity_world_mps",
                as_vector3(
                    self.velocity_world_mps,
                    "MicrophoneArraySpec.velocity_world_mps",
                ),
            )
        microphones = tuple(self.microphones)
        if not microphones:
            raise ValueError("MicrophoneArraySpec.microphones must not be empty.")
        _require_unique_ids(
            [microphone.mic_id for microphone in microphones],
            "microphone id",
        )
        object.__setattr__(self, "microphones", microphones)
        if int(self.sample_rate_hz) <= 0:
            raise ValueError("MicrophoneArraySpec.sample_rate_hz must be positive.")
        object.__setattr__(self, "sample_rate_hz", int(self.sample_rate_hz))


@dataclass(frozen=True, slots=True, kw_only=True)
class RoomAcousticsSpec:
    """Optional shoebox room-acoustics configuration.

    The room occupies the world-frame box ``[origin_m, origin_m +
    dimensions_m]``; ``origin_m`` is the room's minimum corner, so scene
    positions map into room coordinates by subtracting it.
    """

    room_id: str
    dimensions_m: Vector3
    absorption: float | dict[str, float] | str
    max_order: int
    air_absorption: bool = False
    ray_tracing: bool = False
    origin_m: Vector3 = (0.0, 0.0, 0.0)
    out_of_bounds: str = "error"
    anchor_prim_path: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.room_id, "RoomAcousticsSpec.room_id")
        object.__setattr__(
            self,
            "dimensions_m",
            as_vector3(self.dimensions_m, "RoomAcousticsSpec.dimensions_m"),
        )
        if any(component <= 0.0 for component in self.dimensions_m):
            raise ValueError("RoomAcousticsSpec.dimensions_m values must be positive.")
        if isinstance(self.absorption, str):
            from isaac_audio_sensors.core.acoustics.materials import (
                resolve_material_coefficients,
            )

            resolve_material_coefficients(
                self.absorption,
                "absorption",
                application=f"room {self.room_id!r}",
            )
        elif isinstance(self.absorption, dict):
            for key, value in self.absorption.items():
                _require_non_empty(key, "RoomAcousticsSpec.absorption key")
                _require_probability(value, "RoomAcousticsSpec.absorption value")
        else:
            _require_probability(self.absorption, "RoomAcousticsSpec.absorption")
        if int(self.max_order) < 0:
            raise ValueError("RoomAcousticsSpec.max_order must be non-negative.")
        object.__setattr__(self, "max_order", int(self.max_order))
        object.__setattr__(
            self,
            "origin_m",
            as_vector3(self.origin_m, "RoomAcousticsSpec.origin_m"),
        )
        if self.out_of_bounds not in ROOM_OUT_OF_BOUNDS_POLICIES:
            raise ValueError(
                "RoomAcousticsSpec.out_of_bounds must be one of "
                f"{sorted(ROOM_OUT_OF_BOUNDS_POLICIES)}."
            )
        if self.anchor_prim_path is not None:
            _require_non_empty(
                self.anchor_prim_path, "RoomAcousticsSpec.anchor_prim_path"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioTimeWindow:
    """Half-open simulation window ``[start_time_s, end_time_s)``."""

    start_time_s: float
    end_time_s: float
    timestamp_ms: int
    sample_rate_hz: int
    frame_index: int | None = None
    max_events: int | None = None

    def __post_init__(self) -> None:
        _require_finite(self.start_time_s, "AudioTimeWindow.start_time_s")
        _require_finite(self.end_time_s, "AudioTimeWindow.end_time_s")
        if self.end_time_s <= self.start_time_s:
            raise ValueError("AudioTimeWindow end must be after start.")
        if int(self.sample_rate_hz) <= 0:
            raise ValueError("AudioTimeWindow.sample_rate_hz must be positive.")
        object.__setattr__(self, "sample_rate_hz", int(self.sample_rate_hz))
        object.__setattr__(self, "timestamp_ms", int(self.timestamp_ms))
        if self.frame_index is not None and int(self.frame_index) < 0:
            raise ValueError("AudioTimeWindow.frame_index must be non-negative.")
        if self.max_events is not None:
            max_events = int(self.max_events)
            if max_events < 0:
                raise ValueError("AudioTimeWindow.max_events must be non-negative.")
            object.__setattr__(self, "max_events", max_events)


@dataclass(frozen=True, slots=True, kw_only=True)
class DoaEstimate:
    """Direction-of-arrival estimate with explicit ambiguity representation.

    Elevation fields are additive optional v1 fields measured in degrees up
    from the array's forward/right plane (positive toward array-local +Z),
    in ``[-90.0, +90.0]``. They stay ``None``/empty unless the producer can
    resolve elevation (e.g. a rank-3 microphone layout); planar arrays keep
    the azimuth-only behavior. ``bearing_confidence`` covers the full
    estimated direction, including elevation when present.
    """

    estimated_bearing_deg: float | None
    candidate_bearing_deg: tuple[float, ...] = field(default_factory=tuple)
    bearing_sector: str | None = None
    bearing_confidence: float = 0.0
    ambiguity_class: str | None = None
    ambiguity_reason: str | None = None
    estimated_elevation_deg: float | None = None
    candidate_elevation_deg: tuple[float, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        estimated = self.estimated_bearing_deg
        if estimated is not None:
            _require_finite(estimated, "DoaEstimate.estimated_bearing_deg")
            estimated = normalize_bearing_deg(estimated)
            object.__setattr__(self, "estimated_bearing_deg", estimated)
            if self.bearing_sector is None:
                object.__setattr__(
                    self,
                    "bearing_sector",
                    bearing_deg_to_sector_name(estimated),
                )
        candidates = tuple(
            normalize_bearing_deg(value) for value in self.candidate_bearing_deg
        )
        object.__setattr__(self, "candidate_bearing_deg", candidates)
        _require_probability(
            self.bearing_confidence,
            "DoaEstimate.bearing_confidence",
        )
        if self.estimated_elevation_deg is not None:
            _require_elevation_deg(
                self.estimated_elevation_deg,
                "DoaEstimate.estimated_elevation_deg",
            )
            object.__setattr__(
                self,
                "estimated_elevation_deg",
                float(self.estimated_elevation_deg),
            )
        elevation_candidates = tuple(
            float(value) for value in self.candidate_elevation_deg
        )
        for value in elevation_candidates:
            _require_elevation_deg(value, "DoaEstimate.candidate_elevation_deg")
        object.__setattr__(self, "candidate_elevation_deg", elevation_candidates)
        if self.bearing_sector is not None:
            _require_non_empty(self.bearing_sector, "DoaEstimate.bearing_sector")
        if self.ambiguity_class is not None:
            _require_non_empty(self.ambiguity_class, "DoaEstimate.ambiguity_class")
        if self.ambiguity_reason is not None:
            _require_non_empty(self.ambiguity_reason, "DoaEstimate.ambiguity_reason")


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioDetection:
    """One detected, scheduled, or externally described sound event."""

    detection_id: str
    source_id: str | None
    class_label: str | None
    detection_mode: str
    timestamp_ms: int
    ground_truth_bearing_deg: float | None
    source_distance_m: float | None
    doa: DoaEstimate
    ground_truth_elevation_deg: float | None = None
    source_pose: Pose3D | None = None
    per_mic_delay_s: dict[str, float] = field(default_factory=dict)
    per_mic_rms: dict[str, float] = field(default_factory=dict)
    audio_asset_path: str | None = None
    occluded: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.detection_id, "AudioDetection.detection_id")
        if self.source_id is not None:
            _require_non_empty(self.source_id, "AudioDetection.source_id")
        if self.class_label is not None:
            _require_non_empty(self.class_label, "AudioDetection.class_label")
        if self.detection_mode not in DETECTION_MODES:
            raise ValueError(
                "AudioDetection.detection_mode must be one of "
                f"{sorted(DETECTION_MODES)}."
            )
        object.__setattr__(self, "timestamp_ms", int(self.timestamp_ms))
        if self.ground_truth_bearing_deg is not None:
            _require_finite(
                self.ground_truth_bearing_deg,
                "AudioDetection.ground_truth_bearing_deg",
            )
            object.__setattr__(
                self,
                "ground_truth_bearing_deg",
                normalize_bearing_deg(self.ground_truth_bearing_deg),
            )
        if self.ground_truth_elevation_deg is not None:
            _require_elevation_deg(
                self.ground_truth_elevation_deg,
                "AudioDetection.ground_truth_elevation_deg",
            )
            object.__setattr__(
                self,
                "ground_truth_elevation_deg",
                float(self.ground_truth_elevation_deg),
            )
        if self.source_distance_m is not None:
            _require_finite(self.source_distance_m, "AudioDetection.source_distance_m")
            if self.source_distance_m < 0.0:
                raise ValueError(
                    "AudioDetection.source_distance_m must be non-negative."
                )
        object.__setattr__(
            self,
            "per_mic_delay_s",
            _coerce_float_dict(self.per_mic_delay_s, "AudioDetection.per_mic_delay_s"),
        )
        object.__setattr__(
            self,
            "per_mic_rms",
            _coerce_float_dict(
                self.per_mic_rms,
                "AudioDetection.per_mic_rms",
                non_negative=True,
            ),
        )
        object.__setattr__(self, "occluded", bool(self.occluded))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioSensorFrame:
    """One microphone-array observation window."""

    frame_id: str
    timestamp_ms: int
    backend_id: str
    array_id: str
    schema_version: str = FRAME_SCHEMA_VERSION
    frame_name: str | None = None
    array_pose: Pose3D | None = None
    start_time_s: float | None = None
    end_time_s: float | None = None
    sample_rate_hz: int | None = None
    frame_index: int | None = None
    coordinate_convention: str = COORDINATE_CONVENTION
    units: dict[str, str] = field(default_factory=lambda: dict(FRAME_UNITS))
    provenance: str = "synthetic/core"
    max_events: int | None = None
    detections: tuple[AudioDetection, ...] = field(default_factory=tuple)
    aggregate_per_mic_rms: dict[str, float] = field(default_factory=dict)
    waveform_paths: tuple[str, ...] = field(default_factory=tuple)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.frame_id, "AudioSensorFrame.frame_id")
        _require_non_empty(self.backend_id, "AudioSensorFrame.backend_id")
        _require_non_empty(self.array_id, "AudioSensorFrame.array_id")
        _require_non_empty(self.schema_version, "AudioSensorFrame.schema_version")
        if self.frame_name is None:
            object.__setattr__(self, "frame_name", self.frame_id)
        else:
            _require_non_empty(self.frame_name, "AudioSensorFrame.frame_name")
        _require_coordinate_convention(
            self.coordinate_convention,
            "AudioSensorFrame.coordinate_convention",
        )
        _require_non_empty(self.provenance, "AudioSensorFrame.provenance")
        if self.schema_version != FRAME_SCHEMA_VERSION:
            raise ValueError(
                f"AudioSensorFrame.schema_version must be {FRAME_SCHEMA_VERSION!r}."
            )
        if self.provenance not in FRAME_PROVENANCE_VALUES:
            raise ValueError(
                "AudioSensorFrame.provenance must be one of "
                f"{sorted(FRAME_PROVENANCE_VALUES)}."
            )
        object.__setattr__(self, "timestamp_ms", int(self.timestamp_ms))
        if self.start_time_s is not None:
            _require_finite(self.start_time_s, "AudioSensorFrame.start_time_s")
        if self.end_time_s is not None:
            _require_finite(self.end_time_s, "AudioSensorFrame.end_time_s")
        if (
            self.start_time_s is not None
            and self.end_time_s is not None
            and self.end_time_s <= self.start_time_s
        ):
            raise ValueError("AudioSensorFrame end time must be after start time.")
        if self.sample_rate_hz is not None:
            if int(self.sample_rate_hz) <= 0:
                raise ValueError("AudioSensorFrame.sample_rate_hz must be positive.")
            object.__setattr__(self, "sample_rate_hz", int(self.sample_rate_hz))
        if self.frame_index is not None:
            frame_index = int(self.frame_index)
            if frame_index < 0:
                raise ValueError("AudioSensorFrame.frame_index must be non-negative.")
            object.__setattr__(self, "frame_index", frame_index)
        if self.max_events is not None:
            max_events = int(self.max_events)
            if max_events < 0:
                raise ValueError("AudioSensorFrame.max_events must be non-negative.")
            object.__setattr__(self, "max_events", max_events)
        units = {str(key): str(value) for key, value in self.units.items()}
        missing_units = (
            set(FRAME_UNITS) - set(units) - set(OPTIONAL_FRAME_UNIT_KEYS)
        )
        if missing_units:
            raise ValueError(
                "AudioSensorFrame.units is missing required keys "
                f"{sorted(missing_units)}."
            )
        changed_units = {
            key: units[key]
            for key, expected_value in FRAME_UNITS.items()
            if key in units and units[key] != expected_value
        }
        if changed_units:
            raise ValueError(
                f"AudioSensorFrame.units changed stable unit values {changed_units!r}."
            )
        object.__setattr__(self, "units", units)
        detections = tuple(self.detections)
        if self.max_events is not None and len(detections) > self.max_events:
            detections = detections[: self.max_events]
        object.__setattr__(self, "detections", detections)
        object.__setattr__(
            self,
            "aggregate_per_mic_rms",
            _coerce_float_dict(
                self.aggregate_per_mic_rms,
                "AudioSensorFrame.aggregate_per_mic_rms",
                non_negative=True,
            ),
        )
        object.__setattr__(self, "waveform_paths", tuple(self.waveform_paths))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceOcclusion:
    """Per-source occlusion of the direct source-to-array paths.

    Computed outside the pure core (e.g. by Isaac-layer raycasts); backends
    only consume it. ``occlusion_factor`` is the fraction of blocked
    source-to-microphone rays in ``[0, 1]`` and ``attenuation_db`` is the
    non-negative extra attenuation the producer derived from that factor.

    The optional per-microphone fields are additive (1.4.0): when present,
    ``per_mic_attenuation_db`` carries broadband transmission loss per
    microphone and ``per_mic_band_attenuation_db`` carries per-band losses
    aligned with ``band_centers_hz``. Backends fall back to the uniform
    ``attenuation_db`` for microphones missing from those maps.
    """

    array_id: str
    source_id: str
    per_mic_blocked: dict[str, bool] = field(default_factory=dict)
    occlusion_factor: float = 0.0
    attenuation_db: float = 0.0
    hit_prim_paths: tuple[str, ...] = ()
    per_mic_attenuation_db: dict[str, float] = field(default_factory=dict)
    per_mic_band_attenuation_db: dict[str, tuple[float, ...]] = field(
        default_factory=dict
    )
    band_centers_hz: tuple[float, ...] = ()
    per_mic_hit_prim_paths: dict[str, tuple[str, ...]] = field(default_factory=dict)
    hit_materials: dict[str, str] = field(default_factory=dict)
    occlusion_model: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.array_id, "SourceOcclusion.array_id")
        _require_non_empty(self.source_id, "SourceOcclusion.source_id")
        object.__setattr__(
            self,
            "per_mic_blocked",
            {
                str(mic_id): bool(blocked)
                for mic_id, blocked in dict(self.per_mic_blocked).items()
            },
        )
        _require_finite(self.occlusion_factor, "SourceOcclusion.occlusion_factor")
        if not 0.0 <= float(self.occlusion_factor) <= 1.0:
            raise ValueError("SourceOcclusion.occlusion_factor must be in [0, 1].")
        _require_finite(self.attenuation_db, "SourceOcclusion.attenuation_db")
        if float(self.attenuation_db) < 0.0:
            raise ValueError("SourceOcclusion.attenuation_db must be non-negative.")
        object.__setattr__(self, "occlusion_factor", float(self.occlusion_factor))
        object.__setattr__(self, "attenuation_db", float(self.attenuation_db))
        object.__setattr__(
            self,
            "hit_prim_paths",
            tuple(str(path) for path in self.hit_prim_paths),
        )
        object.__setattr__(
            self,
            "per_mic_attenuation_db",
            _coerce_float_dict(
                self.per_mic_attenuation_db,
                "SourceOcclusion.per_mic_attenuation_db",
                non_negative=True,
            ),
        )
        band_centers = tuple(
            float(center) for center in self.band_centers_hz
        )
        for center in band_centers:
            _require_finite(center, "SourceOcclusion.band_centers_hz value")
            if center <= 0.0:
                raise ValueError(
                    "SourceOcclusion.band_centers_hz values must be positive."
                )
        object.__setattr__(self, "band_centers_hz", band_centers)
        per_mic_bands: dict[str, tuple[float, ...]] = {}
        for mic_id, bands in dict(self.per_mic_band_attenuation_db).items():
            values = tuple(float(value) for value in bands)
            if len(values) != len(band_centers):
                raise ValueError(
                    "SourceOcclusion.per_mic_band_attenuation_db rows must "
                    "match band_centers_hz length."
                )
            for value in values:
                _require_finite(
                    value, "SourceOcclusion.per_mic_band_attenuation_db value"
                )
                if value < 0.0:
                    raise ValueError(
                        "SourceOcclusion.per_mic_band_attenuation_db values "
                        "must be non-negative."
                    )
            per_mic_bands[str(mic_id)] = values
        object.__setattr__(self, "per_mic_band_attenuation_db", per_mic_bands)
        object.__setattr__(
            self,
            "per_mic_hit_prim_paths",
            {
                str(mic_id): tuple(str(path) for path in paths)
                for mic_id, paths in dict(self.per_mic_hit_prim_paths).items()
            },
        )
        object.__setattr__(
            self,
            "hit_materials",
            {
                str(path): str(material)
                for path, material in dict(self.hit_materials).items()
            },
        )
        if self.occlusion_model is not None:
            _require_non_empty(
                self.occlusion_model, "SourceOcclusion.occlusion_model"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioSceneSnapshot:
    """Static scene state consumed by simulation backends."""

    stage_id: str
    timestamp_ms: int
    sources: tuple[AudioSourceSpec, ...]
    arrays: tuple[MicrophoneArraySpec, ...]
    room: RoomAcousticsSpec | None = None
    occlusion: tuple[SourceOcclusion, ...] | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.stage_id, "AudioSceneSnapshot.stage_id")
        object.__setattr__(self, "timestamp_ms", int(self.timestamp_ms))
        sources = tuple(self.sources)
        arrays = tuple(self.arrays)
        _require_unique_ids([source.source_id for source in sources], "source id")
        _require_unique_ids([array.array_id for array in arrays], "array id")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "arrays", arrays)
        if self.occlusion is not None:
            occlusion = tuple(self.occlusion)
            _require_unique_ids(
                [f"{record.array_id}:{record.source_id}" for record in occlusion],
                "occlusion record id",
            )
            object.__setattr__(self, "occlusion", occlusion)

    def array_by_id(self, array_id: str) -> MicrophoneArraySpec:
        """Return an array by id or raise a clear error."""

        for array in self.arrays:
            if array.array_id == array_id:
                return array
        raise KeyError(f"AudioSceneSnapshot has no array {array_id!r}.")

    def occlusion_for(
        self,
        array_id: str,
        source_id: str,
    ) -> SourceOcclusion | None:
        """Return the occlusion record for one array/source pair, if any."""

        if self.occlusion is None:
            return None
        for record in self.occlusion:
            if record.array_id == array_id and record.source_id == source_id:
                return record
        return None


def _require_non_empty(value: str, field_name: str) -> None:
    if value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty.")


def _require_coordinate_convention(value: str, field_name: str) -> None:
    _require_non_empty(value, field_name)
    if value != COORDINATE_CONVENTION:
        raise ValueError(f"{field_name} must be {COORDINATE_CONVENTION!r}.")


def _require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite.")


def _require_probability(value: float, field_name: str) -> None:
    _require_finite(value, field_name)
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0.")


def _require_elevation_deg(value: float, field_name: str) -> None:
    _require_finite(value, field_name)
    if not -90.0 <= float(value) <= 90.0:
        raise ValueError(f"{field_name} must be between -90.0 and 90.0.")


def _require_unique_ids(values: list[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"Duplicate {label} {value!r}.")
        seen.add(value)


def _coerce_float_dict(
    value: dict[str, float],
    field_name: str,
    *,
    non_negative: bool = False,
) -> dict[str, float]:
    coerced: dict[str, float] = {}
    for key, raw_value in value.items():
        _require_non_empty(key, f"{field_name} key")
        numeric = float(raw_value)
        _require_finite(numeric, f"{field_name}[{key!r}]")
        if non_negative and numeric < 0.0:
            raise ValueError(f"{field_name}[{key!r}] must be non-negative.")
        coerced[key] = numeric
    return coerced
