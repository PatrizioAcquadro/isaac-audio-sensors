"""Public calibration-profile v1 dataclasses and compatibility checks."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from isaac_audio_sensors.core.constants import (
    CALIBRATION_PROFILE_SCHEMA_VERSION,
    CALIBRATION_PROFILE_UNITS,
    COORDINATE_CONVENTION,
)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MEASUREMENT_STATUSES = (
    "measured",
    "nominal_not_measured",
    "unmeasured",
    "unsupported",
)
_VALUE_STATUSES = frozenset({"measured", "nominal_not_measured"})


@dataclass(frozen=True, slots=True, kw_only=True)
class ScalarCalibrationValue:
    """Scalar whose evidence state cannot be mistaken for a measurement."""

    status: str
    value: float | None
    uncertainty: float | None = None

    def __post_init__(self) -> None:
        _require_status(self.status, "ScalarCalibrationValue.status")
        if self.status in _VALUE_STATUSES:
            if self.value is None:
                raise ValueError(
                    "ScalarCalibrationValue measured or nominal values require value."
                )
            _require_finite(self.value, "ScalarCalibrationValue.value")
        elif self.value is not None:
            raise ValueError(
                "ScalarCalibrationValue unmeasured or unsupported values must be null."
            )
        if self.uncertainty is not None:
            _require_finite(
                self.uncertainty,
                "ScalarCalibrationValue.uncertainty",
            )
            if self.uncertainty < 0.0:
                raise ValueError(
                    "ScalarCalibrationValue.uncertainty must be non-negative."
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class MicrophoneGeometry:
    """Microphone position with provenance and uncertainty in an array frame."""

    channel_id: str
    status: str
    position_m: tuple[float, float, float] | None
    uncertainty_m: tuple[float, float, float] | None
    frame: str

    def __post_init__(self) -> None:
        _require_id(self.channel_id, "MicrophoneGeometry.channel_id")
        _require_status(self.status, "MicrophoneGeometry.status")
        _require_id(self.frame, "MicrophoneGeometry.frame")
        if self.status in _VALUE_STATUSES:
            if self.position_m is None:
                raise ValueError(
                    "MicrophoneGeometry measured or nominal geometry requires "
                    "position_m."
                )
            object.__setattr__(
                self,
                "position_m",
                _finite_tuple(self.position_m, 3, "MicrophoneGeometry.position_m"),
            )
        elif self.position_m is not None:
            raise ValueError(
                "MicrophoneGeometry unmeasured or unsupported position_m must be null."
            )
        if self.uncertainty_m is not None:
            uncertainty = _finite_tuple(
                self.uncertainty_m,
                3,
                "MicrophoneGeometry.uncertainty_m",
            )
            if any(value < 0.0 for value in uncertainty):
                raise ValueError(
                    "MicrophoneGeometry.uncertainty_m must be non-negative."
                )
            object.__setattr__(self, "uncertainty_m", uncertainty)


@dataclass(frozen=True, slots=True, kw_only=True)
class FrequencyResponsePoint:
    """One complex response sample in explicit frequency units."""

    frequency_hz: float
    magnitude_db: float
    phase_deg: float | None = None

    def __post_init__(self) -> None:
        _require_finite(self.frequency_hz, "FrequencyResponsePoint.frequency_hz")
        if self.frequency_hz <= 0.0:
            raise ValueError("FrequencyResponsePoint.frequency_hz must be positive.")
        _require_finite(self.magnitude_db, "FrequencyResponsePoint.magnitude_db")
        if self.phase_deg is not None:
            _require_finite(self.phase_deg, "FrequencyResponsePoint.phase_deg")


@dataclass(frozen=True, slots=True, kw_only=True)
class FrequencyResponse:
    """Frequency-response samples with an explicit evidence status."""

    status: str
    points: tuple[FrequencyResponsePoint, ...] = field(default_factory=tuple)
    uncertainty_db: float | None = None

    def __post_init__(self) -> None:
        _require_status(self.status, "FrequencyResponse.status")
        points = tuple(self.points)
        if self.status in _VALUE_STATUSES and not points:
            raise ValueError(
                "FrequencyResponse measured or nominal responses require points."
            )
        if self.status not in _VALUE_STATUSES and points:
            raise ValueError(
                "FrequencyResponse unmeasured or unsupported responses must be empty."
            )
        frequencies = tuple(point.frequency_hz for point in points)
        if any(
            current <= previous
            for previous, current in zip(frequencies, frequencies[1:], strict=False)
        ):
            raise ValueError(
                "FrequencyResponse frequencies must be strictly increasing."
            )
        if self.uncertainty_db is not None:
            _require_finite(self.uncertainty_db, "FrequencyResponse.uncertainty_db")
            if self.uncertainty_db < 0.0:
                raise ValueError(
                    "FrequencyResponse.uncertainty_db must be non-negative."
                )
        object.__setattr__(self, "points", points)


@dataclass(frozen=True, slots=True, kw_only=True)
class UsableFrequencyRange:
    """Usable band with explicit measurement support."""

    status: str
    minimum_hz: float | None
    maximum_hz: float | None

    def __post_init__(self) -> None:
        _require_status(self.status, "UsableFrequencyRange.status")
        if self.status in _VALUE_STATUSES:
            if self.minimum_hz is None or self.maximum_hz is None:
                raise ValueError(
                    "UsableFrequencyRange measured or nominal ranges require bounds."
                )
            _require_finite(self.minimum_hz, "UsableFrequencyRange.minimum_hz")
            _require_finite(self.maximum_hz, "UsableFrequencyRange.maximum_hz")
            if self.minimum_hz <= 0.0 or self.maximum_hz <= self.minimum_hz:
                raise ValueError(
                    "UsableFrequencyRange bounds must be positive and monotonic."
                )
        elif self.minimum_hz is not None or self.maximum_hz is not None:
            raise ValueError(
                "UsableFrequencyRange unmeasured or unsupported bounds must be null."
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ChannelCalibration:
    """All channel-local correction and response fields."""

    channel_id: str
    gain_db: ScalarCalibrationValue
    delay_s: ScalarCalibrationValue
    polarity: ScalarCalibrationValue
    frequency_response: FrequencyResponse
    self_noise_db_spl: ScalarCalibrationValue
    usable_frequency_range: UsableFrequencyRange

    def __post_init__(self) -> None:
        _require_id(self.channel_id, "ChannelCalibration.channel_id")
        if self.polarity.value is not None and self.polarity.value not in {-1.0, 1.0}:
            raise ValueError("ChannelCalibration.polarity value must be -1 or 1.")


@dataclass(frozen=True, slots=True, kw_only=True)
class CalibrationMetric:
    """Named fit or holdout metric with explicit units."""

    name: str
    value: float
    unit: str

    def __post_init__(self) -> None:
        _require_id(self.name, "CalibrationMetric.name")
        _require_finite(self.value, "CalibrationMetric.value")
        _require_text(self.unit, "CalibrationMetric.unit")


@dataclass(frozen=True, slots=True, kw_only=True)
class FittedModelParameter:
    """One fitted parameter and its uncertainty/evidence state."""

    name: str
    unit: str
    estimate: ScalarCalibrationValue

    def __post_init__(self) -> None:
        _require_id(self.name, "FittedModelParameter.name")
        _require_text(self.unit, "FittedModelParameter.unit")


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplicabilityLimits:
    """Environmental and frequency envelope for deterministic application."""

    temperature_min_c: float | None
    temperature_max_c: float | None
    frequency_min_hz: float | None
    frequency_max_hz: float | None
    environment_tags: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_optional_range(
            self.temperature_min_c,
            self.temperature_max_c,
            "ApplicabilityLimits temperature",
            positive=False,
        )
        _validate_optional_range(
            self.frequency_min_hz,
            self.frequency_max_hz,
            "ApplicabilityLimits frequency",
            positive=True,
        )
        tags = tuple(self.environment_tags)
        for tag in tags:
            _require_id(tag, "ApplicabilityLimits.environment_tags")
        _require_unique(tags, "ApplicabilityLimits.environment_tags")
        object.__setattr__(self, "environment_tags", tags)


@dataclass(frozen=True, slots=True, kw_only=True)
class RawMeasurementReference:
    """Checksummed portable reference to raw calibration evidence."""

    path: str
    sha256: str

    def __post_init__(self) -> None:
        _require_relative_path(self.path, "RawMeasurementReference.path")
        _require_sha256(self.sha256, "RawMeasurementReference.sha256")


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioCalibrationProfile:
    """Replayable calibration contract independent of package version."""

    profile_id: str
    profile_version: str
    device_id: str
    device_model: str
    array_id: str
    channel_order: tuple[str, ...]
    reference_rig_bom_path: str
    microphone_geometry: tuple[MicrophoneGeometry, ...]
    array_frame: str
    source_frame: str
    coordinate_convention: str
    units: dict[str, str]
    sample_rate_hz: int
    temperature_c: ScalarCalibrationValue
    speed_of_sound_policy: str
    speed_of_sound_mps: ScalarCalibrationValue
    environment_description: str
    channels: tuple[ChannelCalibration, ...]
    source_id: str
    speaker_id: str
    pose_measurement_method: str
    reference_signal: str
    acquisition_procedure: str
    fitted_model_parameters: tuple[FittedModelParameter, ...]
    fit_metrics: tuple[CalibrationMetric, ...]
    holdout_metrics: tuple[CalibrationMetric, ...]
    applicability_limits: ApplicabilityLimits
    uncertainty_notes: str
    raw_measurements: tuple[RawMeasurementReference, ...]
    tool_version: str
    created_at: str
    unmeasured_fields: tuple[str, ...]
    evidence_status: str
    schema_version: str = CALIBRATION_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("profile_id", "profile_version", "device_id", "array_id"):
            _require_id(getattr(self, name), f"AudioCalibrationProfile.{name}")
        if self.schema_version != CALIBRATION_PROFILE_SCHEMA_VERSION:
            raise ValueError(
                "AudioCalibrationProfile.schema_version must be "
                f"{CALIBRATION_PROFILE_SCHEMA_VERSION!r}."
            )
        _require_text(self.device_model, "AudioCalibrationProfile.device_model")
        channel_order = _unique_id_tuple(
            self.channel_order,
            "AudioCalibrationProfile.channel_order",
            require_non_empty=True,
        )
        _require_relative_path(
            self.reference_rig_bom_path,
            "AudioCalibrationProfile.reference_rig_bom_path",
        )
        _require_id(self.array_frame, "AudioCalibrationProfile.array_frame")
        _require_id(self.source_frame, "AudioCalibrationProfile.source_frame")
        if self.array_frame == self.source_frame:
            raise ValueError(
                "AudioCalibrationProfile array_frame and source_frame must differ."
            )
        if self.coordinate_convention != COORDINATE_CONVENTION:
            raise ValueError(
                "AudioCalibrationProfile.coordinate_convention must be "
                f"{COORDINATE_CONVENTION!r}."
            )
        if self.units != CALIBRATION_PROFILE_UNITS:
            raise ValueError(
                "AudioCalibrationProfile.units must use the canonical unit values "
                f"{CALIBRATION_PROFILE_UNITS}."
            )
        if int(self.sample_rate_hz) <= 0:
            raise ValueError("AudioCalibrationProfile.sample_rate_hz must be positive.")
        if self.speed_of_sound_policy not in {
            "fixed",
            "measured",
            "temperature_derived",
        }:
            raise ValueError(
                "AudioCalibrationProfile.speed_of_sound_policy must be fixed, "
                "measured, or temperature_derived."
            )
        for name in (
            "environment_description",
            "pose_measurement_method",
            "reference_signal",
            "acquisition_procedure",
            "uncertainty_notes",
            "tool_version",
        ):
            _require_text(getattr(self, name), f"AudioCalibrationProfile.{name}")
        _require_id(self.source_id, "AudioCalibrationProfile.source_id")
        _require_id(self.speaker_id, "AudioCalibrationProfile.speaker_id")
        _require_utc_timestamp(self.created_at, "AudioCalibrationProfile.created_at")
        _require_status(self.evidence_status, "AudioCalibrationProfile.evidence_status")

        geometry = tuple(self.microphone_geometry)
        channels = tuple(self.channels)
        if tuple(item.channel_id for item in geometry) != channel_order:
            raise ValueError(
                "AudioCalibrationProfile microphone geometry order must match "
                "channel_order."
            )
        if tuple(item.channel_id for item in channels) != channel_order:
            raise ValueError(
                "AudioCalibrationProfile channel calibration order must match "
                "channel_order."
            )
        if any(item.frame != self.array_frame for item in geometry):
            raise ValueError(
                "AudioCalibrationProfile microphone geometry frame must match "
                "array_frame."
            )
        unmeasured_fields = tuple(self.unmeasured_fields)
        for name in unmeasured_fields:
            _require_text(name, "AudioCalibrationProfile.unmeasured_fields")
        _require_unique(unmeasured_fields, "AudioCalibrationProfile.unmeasured_fields")
        if self.evidence_status in {"nominal_not_measured", "unmeasured"} and not (
            unmeasured_fields
        ):
            raise ValueError(
                "Nominal or unmeasured profiles must list unmeasured_fields."
            )
        raw_measurements = tuple(self.raw_measurements)
        _require_unique(
            tuple(item.path for item in raw_measurements),
            "AudioCalibrationProfile raw measurement paths",
        )
        object.__setattr__(self, "channel_order", channel_order)
        object.__setattr__(self, "units", dict(self.units))
        object.__setattr__(self, "sample_rate_hz", int(self.sample_rate_hz))
        object.__setattr__(self, "microphone_geometry", geometry)
        object.__setattr__(self, "channels", channels)
        object.__setattr__(
            self,
            "fitted_model_parameters",
            tuple(self.fitted_model_parameters),
        )
        object.__setattr__(self, "fit_metrics", tuple(self.fit_metrics))
        object.__setattr__(self, "holdout_metrics", tuple(self.holdout_metrics))
        object.__setattr__(self, "raw_measurements", raw_measurements)
        object.__setattr__(self, "unmeasured_fields", unmeasured_fields)


def check_profile_compatibility(
    profile: AudioCalibrationProfile,
    array_spec_like: object,
) -> None:
    """Raise before use when a profile does not exactly match an array spec."""

    array_id = _get_value(array_spec_like, "array_id")
    if array_id != profile.array_id:
        raise ValueError(
            f"Calibration profile array identity {profile.array_id!r} does not "
            f"match {array_id!r}."
        )
    device_id = _get_value(array_spec_like, "device_id", required=False)
    if device_id is not None and device_id != profile.device_id:
        raise ValueError(
            f"Calibration profile device identity {profile.device_id!r} does not "
            f"match {device_id!r}."
        )
    microphones = _get_value(array_spec_like, "microphones")
    channel_order = tuple(_get_value(item, "mic_id") for item in microphones)
    if len(channel_order) != len(profile.channel_order):
        raise ValueError(
            "Calibration profile channel count does not match the array spec."
        )
    if channel_order != profile.channel_order:
        raise ValueError(
            "Calibration profile channel order does not match the array spec."
        )
    sample_rate_hz = int(_get_value(array_spec_like, "sample_rate_hz"))
    if sample_rate_hz != profile.sample_rate_hz:
        raise ValueError(
            "Calibration profile sample rate does not match the array spec."
        )
    convention = _get_value(array_spec_like, "coordinate_convention")
    if convention != profile.coordinate_convention:
        raise ValueError(
            "Calibration profile coordinate frame convention does not match the "
            "array spec."
        )
    array_frame = _get_value(array_spec_like, "array_frame", required=False)
    if array_frame is not None and array_frame != profile.array_frame:
        raise ValueError(
            "Calibration profile array frame does not match the array spec."
        )


def _get_value(value: object, name: str, *, required: bool = True) -> Any:
    if isinstance(value, Mapping):
        result = value.get(name)
    else:
        result = getattr(value, name, None)
    if required and result is None:
        raise ValueError(
            f"Array spec is missing required compatibility field {name!r}."
        )
    return result


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _require_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be a non-empty stable id using letters, numbers, "
            "'.', '_', ':', or '-'."
        )


def _require_status(value: str, field_name: str) -> None:
    if value not in MEASUREMENT_STATUSES:
        raise ValueError(f"{field_name} must be one of {list(MEASUREMENT_STATUSES)}.")


def _require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite.")


def _finite_tuple(values: object, length: int, field_name: str):
    result = tuple(float(value) for value in values)  # type: ignore[union-attr]
    if len(result) != length or not all(math.isfinite(value) for value in result):
        raise ValueError(f"{field_name} must contain {length} finite values.")
    return result


def _unique_id_tuple(
    values: object,
    field_name: str,
    *,
    require_non_empty: bool = False,
) -> tuple[str, ...]:
    result = tuple(values)  # type: ignore[arg-type]
    if require_non_empty and not result:
        raise ValueError(f"{field_name} must not be empty.")
    for value in result:
        _require_id(value, field_name)
    _require_unique(result, field_name)
    return result


def _require_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates.")


def _require_relative_path(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in posix_path.parts
        or "\\" in value
    ):
        raise ValueError(
            f"{field_name} must be a relative POSIX path without parent traversal."
        )


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be 64 lowercase hexadecimal characters.")


def _require_utc_timestamp(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    if not value.endswith("Z"):
        raise ValueError(f"{field_name} must be an ISO-8601 UTC timestamp ending in Z.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a valid ISO-8601 UTC timestamp."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0.0:
        raise ValueError(f"{field_name} must be a UTC timestamp.")


def _validate_optional_range(
    minimum: float | None,
    maximum: float | None,
    field_name: str,
    *,
    positive: bool,
) -> None:
    if (minimum is None) != (maximum is None):
        raise ValueError(f"{field_name} bounds must both be set or both be null.")
    if minimum is None or maximum is None:
        return
    _require_finite(minimum, f"{field_name} minimum")
    _require_finite(maximum, f"{field_name} maximum")
    if positive and minimum <= 0.0:
        raise ValueError(f"{field_name} minimum must be positive.")
    if maximum <= minimum:
        raise ValueError(f"{field_name} bounds must be monotonic.")
