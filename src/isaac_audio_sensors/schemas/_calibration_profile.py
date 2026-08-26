"""AudioCalibrationProfile JSON Schema generation."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.constants import (
    CALIBRATION_PROFILE_SCHEMA_VERSION,
    CALIBRATION_PROFILE_UNITS,
    COORDINATE_CONVENTION,
)
from isaac_audio_sensors.schemas._common import (
    _constant_units_schema,
    _fixed_number_array,
    _relative_path_schema,
    _sha256_schema,
    _stable_id_schema,
)


def audio_calibration_profile_json_schema() -> dict[str, Any]:
    """Return the v1 ``AudioCalibrationProfile`` JSON Schema."""

    stable_id = _stable_id_schema()
    relative_path = _relative_path_schema()
    sha256 = _sha256_schema()
    status = {
        "enum": [
            "measured",
            "nominal_not_measured",
            "unmeasured",
            "unsupported",
        ]
    }
    scalar = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "value", "uncertainty"],
        "properties": {
            "status": status,
            "value": {"type": ["number", "null"]},
            "uncertainty": {"type": ["number", "null"], "minimum": 0.0},
        },
    }
    geometry = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "channel_id",
            "status",
            "position_m",
            "uncertainty_m",
            "frame",
        ],
        "properties": {
            "channel_id": stable_id,
            "status": status,
            "position_m": {"oneOf": [{"type": "null"}, _fixed_number_array(3)]},
            "uncertainty_m": {
                "oneOf": [
                    {"type": "null"},
                    {
                        **_fixed_number_array(3),
                        "items": {"type": "number", "minimum": 0.0},
                    },
                ]
            },
            "frame": stable_id,
        },
    }
    frequency_response = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "points", "uncertainty_db"],
        "properties": {
            "status": status,
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["frequency_hz", "magnitude_db", "phase_deg"],
                    "properties": {
                        "frequency_hz": {"type": "number", "exclusiveMinimum": 0.0},
                        "magnitude_db": {"type": "number"},
                        "phase_deg": {"type": ["number", "null"]},
                    },
                },
            },
            "uncertainty_db": {"type": ["number", "null"], "minimum": 0.0},
        },
    }
    usable_range = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "minimum_hz", "maximum_hz"],
        "properties": {
            "status": status,
            "minimum_hz": {"type": ["number", "null"]},
            "maximum_hz": {"type": ["number", "null"]},
        },
    }
    channel = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "channel_id",
            "gain_db",
            "delay_s",
            "polarity",
            "frequency_response",
            "self_noise_db_spl",
            "usable_frequency_range",
        ],
        "properties": {
            "channel_id": stable_id,
            "gain_db": scalar,
            "delay_s": scalar,
            "polarity": scalar,
            "frequency_response": frequency_response,
            "self_noise_db_spl": scalar,
            "usable_frequency_range": usable_range,
        },
    }
    metric = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "value", "unit"],
        "properties": {
            "name": stable_id,
            "value": {"type": "number"},
            "unit": {"type": "string", "minLength": 1},
        },
    }
    model_parameter = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "unit", "estimate"],
        "properties": {
            "name": stable_id,
            "unit": {"type": "string", "minLength": 1},
            "estimate": scalar,
        },
    }
    optional_number = {"type": ["number", "null"]}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://isaac-audio-sensors.dev/schemas/"
            "audio_calibration_profile.v1.schema.json"
        ),
        "title": "Isaac Audio Sensors AudioCalibrationProfile v1",
        "description": (
            "Fail-closed device calibration contract with explicit measured, "
            "nominal-not-measured, unmeasured, and unsupported states. Its schema "
            "version is independent of the Python package version."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": [
            "profile_id",
            "profile_version",
            "device_id",
            "device_model",
            "array_id",
            "channel_order",
            "reference_rig_bom_path",
            "microphone_geometry",
            "array_frame",
            "source_frame",
            "coordinate_convention",
            "units",
            "sample_rate_hz",
            "temperature_c",
            "speed_of_sound_policy",
            "speed_of_sound_mps",
            "environment_description",
            "channels",
            "source_id",
            "speaker_id",
            "pose_measurement_method",
            "reference_signal",
            "acquisition_procedure",
            "fitted_model_parameters",
            "fit_metrics",
            "holdout_metrics",
            "applicability_limits",
            "uncertainty_notes",
            "raw_measurements",
            "tool_version",
            "created_at",
            "unmeasured_fields",
            "evidence_status",
            "schema_version",
        ],
        "properties": {
            "profile_id": stable_id,
            "profile_version": stable_id,
            "device_id": stable_id,
            "device_model": {"type": "string", "minLength": 1},
            "array_id": stable_id,
            "channel_order": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": stable_id,
            },
            "reference_rig_bom_path": relative_path,
            "microphone_geometry": {"type": "array", "items": geometry},
            "array_frame": stable_id,
            "source_frame": stable_id,
            "coordinate_convention": {"const": COORDINATE_CONVENTION},
            "units": _constant_units_schema(CALIBRATION_PROFILE_UNITS),
            "sample_rate_hz": {"type": "integer", "minimum": 1},
            "temperature_c": scalar,
            "speed_of_sound_policy": {
                "enum": ["fixed", "measured", "temperature_derived"]
            },
            "speed_of_sound_mps": scalar,
            "environment_description": {"type": "string", "minLength": 1},
            "channels": {"type": "array", "items": channel},
            "source_id": stable_id,
            "speaker_id": stable_id,
            "pose_measurement_method": {"type": "string", "minLength": 1},
            "reference_signal": {"type": "string", "minLength": 1},
            "acquisition_procedure": {"type": "string", "minLength": 1},
            "fitted_model_parameters": {
                "type": "array",
                "items": model_parameter,
            },
            "fit_metrics": {"type": "array", "items": metric},
            "holdout_metrics": {"type": "array", "items": metric},
            "applicability_limits": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "temperature_min_c",
                    "temperature_max_c",
                    "frequency_min_hz",
                    "frequency_max_hz",
                    "environment_tags",
                ],
                "properties": {
                    "temperature_min_c": optional_number,
                    "temperature_max_c": optional_number,
                    "frequency_min_hz": optional_number,
                    "frequency_max_hz": optional_number,
                    "environment_tags": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": stable_id,
                    },
                },
            },
            "uncertainty_notes": {"type": "string", "minLength": 1},
            "raw_measurements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path", "sha256"],
                    "properties": {
                        "path": relative_path,
                        "sha256": sha256,
                    },
                },
            },
            "tool_version": {"type": "string", "minLength": 1},
            "created_at": {
                "type": "string",
                "format": "date-time",
                "pattern": "Z$",
            },
            "unmeasured_fields": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "evidence_status": status,
            "schema_version": {"const": CALIBRATION_PROFILE_SCHEMA_VERSION},
        },
    }
