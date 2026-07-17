"""Deterministic JSON serialization for calibration profiles."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.calibration_profile import (
    ApplicabilityLimits,
    AudioCalibrationProfile,
    CalibrationMetric,
    ChannelCalibration,
    FittedModelParameter,
    FrequencyResponse,
    FrequencyResponsePoint,
    MicrophoneGeometry,
    RawMeasurementReference,
    ScalarCalibrationValue,
    UsableFrequencyRange,
)
from isaac_audio_sensors.core.constants import (
    CALIBRATION_PROFILE_SCHEMA_VERSION,
    CALIBRATION_PROFILE_UNITS,
    COORDINATE_CONVENTION,
)


def calibration_profile_to_dict(
    profile: AudioCalibrationProfile,
) -> dict[str, Any]:
    """Return a JSON-ready dictionary for one calibration profile."""

    return _serialize(profile)


def write_calibration_profile(
    profile: AudioCalibrationProfile,
    path: str | Path,
) -> Path:
    """Write one deterministic pretty JSON calibration profile."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(calibration_profile_to_dict(profile), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return output_path


def calibration_profile_from_dict(payload: dict[str, Any]) -> AudioCalibrationProfile:
    """Rebuild an ``AudioCalibrationProfile`` from a JSON dictionary."""

    return AudioCalibrationProfile(
        profile_id=str(payload["profile_id"]),
        profile_version=str(payload["profile_version"]),
        schema_version=str(
            payload.get("schema_version", CALIBRATION_PROFILE_SCHEMA_VERSION)
        ),
        device_id=str(payload["device_id"]),
        device_model=str(payload["device_model"]),
        array_id=str(payload["array_id"]),
        channel_order=tuple(payload["channel_order"]),
        reference_rig_bom_path=str(payload["reference_rig_bom_path"]),
        microphone_geometry=tuple(
            _geometry_from_dict(item) for item in payload["microphone_geometry"]
        ),
        array_frame=str(payload["array_frame"]),
        source_frame=str(payload["source_frame"]),
        coordinate_convention=str(
            payload.get("coordinate_convention", COORDINATE_CONVENTION)
        ),
        units=dict(payload.get("units", CALIBRATION_PROFILE_UNITS)),
        sample_rate_hz=int(payload["sample_rate_hz"]),
        temperature_c=_scalar_from_dict(payload["temperature_c"]),
        speed_of_sound_policy=str(payload["speed_of_sound_policy"]),
        speed_of_sound_mps=_scalar_from_dict(payload["speed_of_sound_mps"]),
        environment_description=str(payload["environment_description"]),
        channels=tuple(_channel_from_dict(item) for item in payload["channels"]),
        source_id=str(payload["source_id"]),
        speaker_id=str(payload["speaker_id"]),
        pose_measurement_method=str(payload["pose_measurement_method"]),
        reference_signal=str(payload["reference_signal"]),
        acquisition_procedure=str(payload["acquisition_procedure"]),
        fitted_model_parameters=tuple(
            FittedModelParameter(
                name=str(item["name"]),
                unit=str(item["unit"]),
                estimate=_scalar_from_dict(item["estimate"]),
            )
            for item in payload.get("fitted_model_parameters", ())
        ),
        fit_metrics=tuple(
            _metric_from_dict(item) for item in payload.get("fit_metrics", ())
        ),
        holdout_metrics=tuple(
            _metric_from_dict(item) for item in payload.get("holdout_metrics", ())
        ),
        applicability_limits=_limits_from_dict(payload["applicability_limits"]),
        uncertainty_notes=str(payload["uncertainty_notes"]),
        raw_measurements=tuple(
            RawMeasurementReference(path=str(item["path"]), sha256=str(item["sha256"]))
            for item in payload.get("raw_measurements", ())
        ),
        tool_version=str(payload["tool_version"]),
        created_at=str(payload["created_at"]),
        unmeasured_fields=tuple(payload.get("unmeasured_fields", ())),
        evidence_status=str(payload["evidence_status"]),
    )


def read_calibration_profile(path: str | Path) -> AudioCalibrationProfile:
    """Read and validate one pretty JSON calibration profile."""

    return calibration_profile_from_dict(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field_info.name: _serialize(getattr(value, field_info.name))
            for field_info in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _serialize(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_serialize(item) for item in value]
    return value


def _scalar_from_dict(payload: dict[str, Any]) -> ScalarCalibrationValue:
    return ScalarCalibrationValue(
        status=str(payload["status"]),
        value=None if payload.get("value") is None else float(payload["value"]),
        uncertainty=(
            None
            if payload.get("uncertainty") is None
            else float(payload["uncertainty"])
        ),
    )


def _geometry_from_dict(payload: dict[str, Any]) -> MicrophoneGeometry:
    position = payload.get("position_m")
    uncertainty = payload.get("uncertainty_m")
    return MicrophoneGeometry(
        channel_id=str(payload["channel_id"]),
        status=str(payload["status"]),
        position_m=None if position is None else tuple(position),
        uncertainty_m=None if uncertainty is None else tuple(uncertainty),
        frame=str(payload["frame"]),
    )


def _frequency_response_from_dict(payload: dict[str, Any]) -> FrequencyResponse:
    return FrequencyResponse(
        status=str(payload["status"]),
        points=tuple(
            FrequencyResponsePoint(
                frequency_hz=float(item["frequency_hz"]),
                magnitude_db=float(item["magnitude_db"]),
                phase_deg=(
                    None
                    if item.get("phase_deg") is None
                    else float(item["phase_deg"])
                ),
            )
            for item in payload.get("points", ())
        ),
        uncertainty_db=(
            None
            if payload.get("uncertainty_db") is None
            else float(payload["uncertainty_db"])
        ),
    )


def _range_from_dict(payload: dict[str, Any]) -> UsableFrequencyRange:
    return UsableFrequencyRange(
        status=str(payload["status"]),
        minimum_hz=(
            None if payload.get("minimum_hz") is None else float(payload["minimum_hz"])
        ),
        maximum_hz=(
            None if payload.get("maximum_hz") is None else float(payload["maximum_hz"])
        ),
    )


def _channel_from_dict(payload: dict[str, Any]) -> ChannelCalibration:
    return ChannelCalibration(
        channel_id=str(payload["channel_id"]),
        gain_db=_scalar_from_dict(payload["gain_db"]),
        delay_s=_scalar_from_dict(payload["delay_s"]),
        polarity=_scalar_from_dict(payload["polarity"]),
        frequency_response=_frequency_response_from_dict(
            payload["frequency_response"]
        ),
        self_noise_db_spl=_scalar_from_dict(payload["self_noise_db_spl"]),
        usable_frequency_range=_range_from_dict(payload["usable_frequency_range"]),
    )


def _metric_from_dict(payload: dict[str, Any]) -> CalibrationMetric:
    return CalibrationMetric(
        name=str(payload["name"]),
        value=float(payload["value"]),
        unit=str(payload["unit"]),
    )


def _limits_from_dict(payload: dict[str, Any]) -> ApplicabilityLimits:
    return ApplicabilityLimits(
        temperature_min_c=(
            None
            if payload.get("temperature_min_c") is None
            else float(payload["temperature_min_c"])
        ),
        temperature_max_c=(
            None
            if payload.get("temperature_max_c") is None
            else float(payload["temperature_max_c"])
        ),
        frequency_min_hz=(
            None
            if payload.get("frequency_min_hz") is None
            else float(payload["frequency_min_hz"])
        ),
        frequency_max_hz=(
            None
            if payload.get("frequency_max_hz") is None
            else float(payload["frequency_max_hz"])
        ),
        environment_tags=tuple(payload.get("environment_tags", ())),
    )
