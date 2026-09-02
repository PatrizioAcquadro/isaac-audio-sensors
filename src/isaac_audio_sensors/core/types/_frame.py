"""Direction, detection, and sensor-frame contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DETECTION_MODES,
    FRAME_PROVENANCE_VALUES,
    FRAME_SCHEMA_VERSION,
    FRAME_UNITS,
    OPTIONAL_FRAME_UNIT_KEYS,
)
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.math_utils import normalize_bearing_deg
from isaac_audio_sensors.core.types._scene import Pose3D
from isaac_audio_sensors.core.types._validation import (
    coerce_float_dict,
    require_coordinate_convention,
    require_finite,
    require_non_empty,
    require_probability,
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
            require_finite(estimated, "DoaEstimate.estimated_bearing_deg")
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
        require_probability(
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
            require_non_empty(self.bearing_sector, "DoaEstimate.bearing_sector")
        if self.ambiguity_class is not None:
            require_non_empty(self.ambiguity_class, "DoaEstimate.ambiguity_class")
        if self.ambiguity_reason is not None:
            require_non_empty(self.ambiguity_reason, "DoaEstimate.ambiguity_reason")


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
        require_non_empty(self.detection_id, "AudioDetection.detection_id")
        if self.source_id is not None:
            require_non_empty(self.source_id, "AudioDetection.source_id")
        if self.class_label is not None:
            require_non_empty(self.class_label, "AudioDetection.class_label")
        if self.detection_mode not in DETECTION_MODES:
            raise ValueError(
                "AudioDetection.detection_mode must be one of "
                f"{sorted(DETECTION_MODES)}."
            )
        if self.ground_truth_bearing_deg is not None:
            require_finite(
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
            require_finite(self.source_distance_m, "AudioDetection.source_distance_m")
            if self.source_distance_m < 0.0:
                raise ValueError(
                    "AudioDetection.source_distance_m must be non-negative."
                )
        object.__setattr__(
            self,
            "per_mic_delay_s",
            coerce_float_dict(self.per_mic_delay_s, "AudioDetection.per_mic_delay_s"),
        )
        object.__setattr__(
            self,
            "per_mic_rms",
            coerce_float_dict(
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
        require_non_empty(self.frame_id, "AudioSensorFrame.frame_id")
        require_non_empty(self.backend_id, "AudioSensorFrame.backend_id")
        require_non_empty(self.array_id, "AudioSensorFrame.array_id")
        require_non_empty(self.schema_version, "AudioSensorFrame.schema_version")
        if self.frame_name is None:
            object.__setattr__(self, "frame_name", self.frame_id)
        else:
            require_non_empty(self.frame_name, "AudioSensorFrame.frame_name")
        require_coordinate_convention(
            self.coordinate_convention,
            "AudioSensorFrame.coordinate_convention",
        )
        require_non_empty(self.provenance, "AudioSensorFrame.provenance")
        if self.schema_version != FRAME_SCHEMA_VERSION:
            raise ValueError(
                f"AudioSensorFrame.schema_version must be {FRAME_SCHEMA_VERSION!r}."
            )
        if self.provenance not in FRAME_PROVENANCE_VALUES:
            raise ValueError(
                "AudioSensorFrame.provenance must be one of "
                f"{sorted(FRAME_PROVENANCE_VALUES)}."
            )
        require_finite(self.start_time_s, "AudioSensorFrame.start_time_s")
        require_finite(self.end_time_s, "AudioSensorFrame.end_time_s")
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
            coerce_float_dict(
                self.aggregate_per_mic_rms,
                "AudioSensorFrame.aggregate_per_mic_rms",
                non_negative=True,
            ),
        )
        object.__setattr__(self, "waveform_paths", tuple(self.waveform_paths))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))


def _require_elevation_deg(value: float, field_name: str) -> None:
    require_finite(value, field_name)
    if not -90.0 <= float(value) <= 90.0:
        raise ValueError(f"{field_name} must be between -90.0 and 90.0.")
