"""Public dataclasses for audio scenes, arrays, detections, and frames."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
    DETECTION_MODES,
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
    forward_vec_world: Vector3
    right_vec_world: Vector3
    up_vec_world: Vector3
    microphones: tuple[MicrophoneSpec, ...]
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    coordinate_convention: str = COORDINATE_CONVENTION

    def __post_init__(self) -> None:
        _require_non_empty(self.array_id, "MicrophoneArraySpec.array_id")
        _require_non_empty(self.prim_path, "MicrophoneArraySpec.prim_path")
        _require_non_empty(
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
        for field_name in ("forward_vec_world", "right_vec_world", "up_vec_world"):
            object.__setattr__(
                self,
                field_name,
                as_vector3(
                    getattr(self, field_name), f"MicrophoneArraySpec.{field_name}"
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
    """Optional shoebox room-acoustics configuration."""

    room_id: str
    dimensions_m: Vector3
    absorption: float | dict[str, float]
    max_order: int
    air_absorption: bool = False
    ray_tracing: bool = False

    def __post_init__(self) -> None:
        _require_non_empty(self.room_id, "RoomAcousticsSpec.room_id")
        object.__setattr__(
            self,
            "dimensions_m",
            as_vector3(self.dimensions_m, "RoomAcousticsSpec.dimensions_m"),
        )
        if any(component <= 0.0 for component in self.dimensions_m):
            raise ValueError("RoomAcousticsSpec.dimensions_m values must be positive.")
        if isinstance(self.absorption, dict):
            for key, value in self.absorption.items():
                _require_non_empty(key, "RoomAcousticsSpec.absorption key")
                _require_probability(value, "RoomAcousticsSpec.absorption value")
        else:
            _require_probability(self.absorption, "RoomAcousticsSpec.absorption")
        if int(self.max_order) < 0:
            raise ValueError("RoomAcousticsSpec.max_order must be non-negative.")
        object.__setattr__(self, "max_order", int(self.max_order))


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioTimeWindow:
    """Half-open simulation window ``[start_time_s, end_time_s)``."""

    start_time_s: float
    end_time_s: float
    timestamp_ms: int
    sample_rate_hz: int
    frame_index: int | None = None

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


@dataclass(frozen=True, slots=True, kw_only=True)
class DoaEstimate:
    """Direction-of-arrival estimate with explicit ambiguity representation."""

    estimated_bearing_deg: float | None
    candidate_bearing_deg: tuple[float, ...] = field(default_factory=tuple)
    bearing_sector: str | None = None
    bearing_confidence: float = 0.0
    ambiguity_class: str | None = None
    ambiguity_reason: str | None = None

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
    per_mic_delay_s: dict[str, float] = field(default_factory=dict)
    per_mic_rms: dict[str, float] = field(default_factory=dict)
    audio_asset_path: str | None = None
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
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioSensorFrame:
    """One microphone-array observation window."""

    frame_id: str
    timestamp_ms: int
    backend_id: str
    array_id: str
    detections: tuple[AudioDetection, ...] = field(default_factory=tuple)
    aggregate_per_mic_rms: dict[str, float] = field(default_factory=dict)
    waveform_paths: tuple[str, ...] = field(default_factory=tuple)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.frame_id, "AudioSensorFrame.frame_id")
        _require_non_empty(self.backend_id, "AudioSensorFrame.backend_id")
        _require_non_empty(self.array_id, "AudioSensorFrame.array_id")
        object.__setattr__(self, "timestamp_ms", int(self.timestamp_ms))
        object.__setattr__(self, "detections", tuple(self.detections))
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
class AudioSceneSnapshot:
    """Static scene state consumed by simulation backends."""

    stage_id: str
    timestamp_ms: int
    sources: tuple[AudioSourceSpec, ...]
    arrays: tuple[MicrophoneArraySpec, ...]
    room: RoomAcousticsSpec | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.stage_id, "AudioSceneSnapshot.stage_id")
        object.__setattr__(self, "timestamp_ms", int(self.timestamp_ms))
        sources = tuple(self.sources)
        arrays = tuple(self.arrays)
        _require_unique_ids([source.source_id for source in sources], "source id")
        _require_unique_ids([array.array_id for array in arrays], "array id")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "arrays", arrays)

    def array_by_id(self, array_id: str) -> MicrophoneArraySpec:
        """Return an array by id or raise a clear error."""

        for array in self.arrays:
            if array.array_id == array_id:
                return array
        raise KeyError(f"AudioSceneSnapshot has no array {array_id!r}.")


def _require_non_empty(value: str, field_name: str) -> None:
    if value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty.")


def _require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite.")


def _require_probability(value: float, field_name: str) -> None:
    _require_finite(value, field_name)
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0.")


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
