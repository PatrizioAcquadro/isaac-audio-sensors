"""Public dataclasses for audio scenes, arrays, detections, and frames."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from isaac_audio_sensors.core.constants import (
    ACOUSTIC_ENVIRONMENT_KINDS,
    ACOUSTIC_SURFACE_ROLES,
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
    DETECTION_MODES,
    FRAME_PROVENANCE_VALUES,
    FRAME_SCHEMA_VERSION,
    FRAME_UNITS,
    OPTIONAL_FRAME_UNIT_KEYS,
)
from isaac_audio_sensors.core.directivity import (
    DirectivityPattern,
    DirectivityValidationError,
    resolve_directivity_pattern,
)
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.gain import db_to_amplitude_gain
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    as_quaternion_xyzw,
    as_vector3,
    cross,
    dot,
    norm,
    normalize_bearing_deg,
    subtract,
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
    loop_count: int = 0
    directivity: DirectivityPattern = DirectivityPattern.OMNI
    velocity_world_mps: Vector3 | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.source_id, "AudioSourceSpec.source_id")
        _require_non_empty(self.prim_path, "AudioSourceSpec.prim_path")
        _require_non_empty(self.class_label, "AudioSourceSpec.class_label")
        directivity = resolve_directivity_pattern(
            self.directivity,
            "AudioSourceSpec.directivity",
        )
        object.__setattr__(self, "directivity", directivity)
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
        db_to_amplitude_gain(self.gain_db, "AudioSourceSpec.gain_db")
        object.__setattr__(self, "gain_db", float(self.gain_db))
        if (
            directivity is not DirectivityPattern.OMNI
            and self.orientation_world_quat is None
        ):
            raise DirectivityValidationError(
                "AudioSourceSpec.orientation_world_quat is required for "
                f"non-omni directivity {directivity.value!r}."
            )
        if type(self.loop_count) is not int or self.loop_count < -1:
            raise ValueError(
                "AudioSourceSpec.loop_count must be -1 or a non-negative integer."
            )
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
    directivity: DirectivityPattern = DirectivityPattern.OMNI

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
        directivity = resolve_directivity_pattern(
            self.directivity,
            "MicrophoneSpec.directivity",
        )
        object.__setattr__(self, "directivity", directivity)
        db_to_amplitude_gain(self.gain_db, "MicrophoneSpec.gain_db")
        object.__setattr__(self, "gain_db", float(self.gain_db))
        if (
            directivity is not DirectivityPattern.OMNI
            and self.relative_orientation_quat is None
        ):
            raise DirectivityValidationError(
                "MicrophoneSpec.relative_orientation_quat is required for "
                f"non-omni directivity {directivity.value!r}."
            )
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
        if type(self.sample_rate_hz) is not int or self.sample_rate_hz <= 0:
            raise ValueError(
                "MicrophoneArraySpec.sample_rate_hz must be a positive integer."
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
        _require_non_empty(self.surface_id, "AcousticSurfaceSpec.surface_id")
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
        _require_non_empty(
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
        _require_unique_ids(
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


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioTimeWindow:
    """Half-open simulation window ``[start_time_s, end_time_s)``."""

    start_time_s: float
    end_time_s: float
    frame_index: int

    def __post_init__(self) -> None:
        _require_finite(self.start_time_s, "AudioTimeWindow.start_time_s")
        _require_finite(self.end_time_s, "AudioTimeWindow.end_time_s")
        if self.end_time_s <= self.start_time_s:
            raise ValueError("AudioTimeWindow end must be after start.")
        if type(self.frame_index) is not int or self.frame_index < 0:
            raise ValueError(
                "AudioTimeWindow.frame_index must be a non-negative integer."
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DoaEstimate:
    """Direction-of-arrival estimate with explicit ambiguity representation.

    Elevation fields are measured in degrees up
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
    backend_id: str
    array_id: str
    start_time_s: float
    end_time_s: float
    sample_rate_hz: int
    frame_index: int
    timestamp_ms: int = field(init=False)
    schema_version: str = FRAME_SCHEMA_VERSION
    frame_name: str | None = None
    array_pose: Pose3D | None = None
    coordinate_convention: str = COORDINATE_CONVENTION
    units: dict[str, str] = field(default_factory=lambda: dict(FRAME_UNITS))
    provenance: str = "synthetic/core"
    max_detections: int | None = None
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
        _require_finite(self.start_time_s, "AudioSensorFrame.start_time_s")
        _require_finite(self.end_time_s, "AudioSensorFrame.end_time_s")
        if self.end_time_s <= self.start_time_s:
            raise ValueError("AudioSensorFrame end time must be after start time.")
        object.__setattr__(
            self,
            "timestamp_ms",
            int(round(self.start_time_s * 1000.0)),
        )
        if type(self.sample_rate_hz) is not int or self.sample_rate_hz <= 0:
            raise ValueError(
                "AudioSensorFrame.sample_rate_hz must be a positive integer."
            )
        if type(self.frame_index) is not int or self.frame_index < 0:
            raise ValueError(
                "AudioSensorFrame.frame_index must be a non-negative integer."
            )
        if self.max_detections is not None and (
            type(self.max_detections) is not int or self.max_detections < 0
        ):
            raise ValueError(
                "AudioSensorFrame.max_detections must be a non-negative integer."
            )
        units = {str(key): str(value) for key, value in self.units.items()}
        missing_units = set(FRAME_UNITS) - set(units) - set(OPTIONAL_FRAME_UNIT_KEYS)
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
        if self.max_detections is not None and len(detections) > self.max_detections:
            raise ValueError(
                "AudioSensorFrame.detections exceeds max_detections; producers "
                "must apply the output limit after localization."
            )
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
    only consume it. ``per_mic_attenuation_db`` carries broadband
    transmission loss for every microphone. Optional band rows replace the
    broadband value for that microphone and align with ``band_centers_hz``.
    Geometry paths, material resolution, and producing-model provenance stay
    outside this simulator-independent attenuation record.
    """

    array_id: str
    source_id: str
    per_mic_blocked: dict[str, bool]
    per_mic_attenuation_db: dict[str, float]
    per_mic_band_attenuation_db: dict[str, tuple[float, ...]] = field(
        default_factory=dict
    )
    band_centers_hz: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.array_id, "SourceOcclusion.array_id")
        _require_non_empty(self.source_id, "SourceOcclusion.source_id")
        blocked = {
            str(mic_id): bool(value)
            for mic_id, value in dict(self.per_mic_blocked).items()
        }
        if not blocked:
            raise ValueError("SourceOcclusion.per_mic_blocked must not be empty.")
        for mic_id in blocked:
            _require_non_empty(mic_id, "SourceOcclusion microphone id")
        object.__setattr__(
            self,
            "per_mic_blocked",
            blocked,
        )
        attenuation = _coerce_float_dict(
            self.per_mic_attenuation_db,
            "SourceOcclusion.per_mic_attenuation_db",
            non_negative=True,
        )
        if set(attenuation) != set(blocked):
            raise ValueError(
                "SourceOcclusion.per_mic_attenuation_db must contain exactly "
                "the per_mic_blocked microphone ids."
            )
        object.__setattr__(
            self,
            "per_mic_attenuation_db",
            attenuation,
        )
        band_centers = tuple(float(center) for center in self.band_centers_hz)
        for center in band_centers:
            _require_finite(center, "SourceOcclusion.band_centers_hz value")
            if center <= 0.0:
                raise ValueError(
                    "SourceOcclusion.band_centers_hz values must be positive."
                )
        if any(
            right <= left
            for left, right in zip(band_centers, band_centers[1:], strict=False)
        ):
            raise ValueError(
                "SourceOcclusion.band_centers_hz must be strictly increasing."
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
        if bool(per_mic_bands) != bool(band_centers):
            raise ValueError(
                "SourceOcclusion.band_centers_hz and "
                "per_mic_band_attenuation_db must be provided together."
            )
        if per_mic_bands and set(per_mic_bands) != set(blocked):
            raise ValueError(
                "SourceOcclusion.per_mic_band_attenuation_db must contain "
                "exactly the per_mic_blocked microphone ids."
            )
        object.__setattr__(self, "per_mic_band_attenuation_db", per_mic_bands)
        for mic_id, is_blocked in blocked.items():
            if is_blocked:
                continue
            if attenuation[mic_id] != 0.0:
                raise ValueError(
                    "SourceOcclusion unblocked microphones must have zero "
                    "broadband attenuation."
                )
            if any(per_mic_bands.get(mic_id, ())):
                raise ValueError(
                    "SourceOcclusion unblocked microphones must have zero "
                    "band attenuation."
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioSceneSnapshot:
    """Static scene state and canonical arrays consumed by simulation backends."""

    stage_id: str
    sources: tuple[AudioSourceSpec, ...]
    arrays: tuple[MicrophoneArraySpec, ...]
    environment: AcousticEnvironmentSpec
    occlusion: tuple[SourceOcclusion, ...] | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.stage_id, "AudioSceneSnapshot.stage_id")
        sources = tuple(self.sources)
        arrays = tuple(self.arrays)
        _require_unique_ids([source.source_id for source in sources], "source id")
        _require_unique_ids([array.array_id for array in arrays], "array id")
        if not isinstance(self.environment, AcousticEnvironmentSpec):
            raise ValueError(
                "AudioSceneSnapshot.environment must be an AcousticEnvironmentSpec."
            )
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "arrays", arrays)
        if self.occlusion is not None:
            occlusion = tuple(self.occlusion)
            _require_unique_ids(
                [f"{record.array_id}:{record.source_id}" for record in occlusion],
                "occlusion record id",
            )
            arrays_by_id = {array.array_id: array for array in arrays}
            source_ids = {source.source_id for source in sources}
            for record in occlusion:
                if record.array_id not in arrays_by_id:
                    raise ValueError(
                        "SourceOcclusion.array_id must reference a scene array."
                    )
                if record.source_id not in source_ids:
                    raise ValueError(
                        "SourceOcclusion.source_id must reference a scene source."
                    )
                expected_mic_ids = {
                    microphone.mic_id
                    for microphone in arrays_by_id[record.array_id].microphones
                }
                if set(record.per_mic_blocked) != expected_mic_ids:
                    raise ValueError(
                        "SourceOcclusion microphone ids must match the referenced "
                        "array."
                    )
            object.__setattr__(self, "occlusion", occlusion)

    def array_by_id(self, array_id: str) -> MicrophoneArraySpec:
        """Return the canonical array by id or raise a clear error."""

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
            _require_non_empty(key, f"{field_name} key")
            if isinstance(value, bool):
                raise ValueError(f"{field_name} values must not be booleans.")
            _require_probability(value, f"{field_name} value")
        return
    _require_probability(absorption, field_name)


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{field_name} must be a non-empty string.")


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
