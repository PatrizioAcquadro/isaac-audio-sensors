"""AudioSensorFrame JSON Schema generation."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DOA_FIELDS,
    FRAME_PROVENANCE_VALUES,
    FRAME_SCHEMA_VERSION,
    FRAME_TOP_LEVEL_FIELDS,
    FRAME_UNITS,
    OBSERVATION_FIELDS,
    OPTIONAL_DOA_FIELDS,
    OPTIONAL_FRAME_UNIT_KEYS,
    OPTIONAL_OBSERVATION_FIELDS,
    POSE3D_FIELDS,
)


def audio_sensor_frame_json_schema() -> dict[str, Any]:
    """Return the v3 ``AudioSensorFrame`` JSON Schema."""

    pose_schema: dict[str, Any] = {
        "type": "object",
        "description": (
            "World-frame pose using x_forward_y_right_z_up_clockwise_bearing."
        ),
        "additionalProperties": False,
        "required": list(POSE3D_FIELDS),
        "properties": {
            "position_m": {
                "type": "array",
                "description": "Position in meters.",
                "minItems": 3,
                "maxItems": 3,
                "items": {"type": "number"},
            },
            "orientation_xyzw": {
                "description": "Quaternion orientation in x, y, z, w order.",
                "oneOf": [
                    {"type": "null"},
                    {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 4,
                        "items": {"type": "number"},
                    },
                ],
            },
            "frame": {
                "type": "string",
                "description": "Coordinate frame name; current examples use world.",
                "minLength": 1,
            },
            "coordinate_convention": {
                "type": "string",
                "description": "Stable coordinate and bearing convention.",
                "const": COORDINATE_CONVENTION,
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://isaac-audio-sensors.dev/schemas/audio_sensor_frame.v3.schema.json"
        ),
        "title": "Isaac Audio Sensors AudioSensorFrame v3",
        "description": (
            "Observed-only AudioSensorFrame v3 contract. timestamp_ms is derived from "
            "start_time_s, sample_rate_hz records the selected array rate, and "
            "max_observations limits only the perception output."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": list(FRAME_TOP_LEVEL_FIELDS),
        "properties": {
            "schema_version": {
                "description": "Frame schema id for the breaking v3 contract.",
                "const": FRAME_SCHEMA_VERSION,
            },
            "frame_id": {
                "type": "string",
                "description": "Stable machine-readable frame identifier.",
                "minLength": 1,
            },
            "frame_name": {
                "type": "string",
                "description": "Human-readable frame name; defaults to frame_id.",
                "minLength": 1,
            },
            "timestamp_ms": {
                "type": "integer",
                "description": (
                    "Derived frame timestamp: round(start_time_s * 1000)."
                ),
            },
            "start_time_s": {
                "type": "number",
                "description": "Inclusive frame-window start time in seconds.",
            },
            "end_time_s": {
                "type": "number",
                "description": "Exclusive frame-window end time in seconds.",
            },
            "sample_rate_hz": {
                "type": "integer",
                "description": "Sample rate copied from the selected array.",
                "minimum": 1,
            },
            "frame_index": {
                "type": "integer",
                "description": "Non-negative producer frame index.",
                "minimum": 0,
            },
            "producer_id": {
                "type": "string",
                "description": "Identifier of the frame's signal producer.",
                "minLength": 1,
            },
            "array_id": {
                "type": "string",
                "description": "Microphone-array identifier.",
                "minLength": 1,
            },
            "channel_validity": {
                "type": "object",
                "description": "Per-microphone validity for the observed signal block.",
                "minProperties": 1,
                "additionalProperties": {"type": "boolean"},
            },
            "array_pose": {"oneOf": [{"type": "null"}, pose_schema]},
            "coordinate_convention": {
                "type": "string",
                "description": "Stable coordinate and bearing convention.",
                "const": COORDINATE_CONVENTION,
            },
            "units": {
                "type": "object",
                "description": "Stable unit names and meanings for frame fields.",
                "required": sorted(set(FRAME_UNITS) - set(OPTIONAL_FRAME_UNIT_KEYS)),
                "additionalProperties": False,
                "properties": {
                    key: {"type": "string", "const": value}
                    for key, value in sorted(FRAME_UNITS.items())
                },
            },
            "provenance": {
                "description": "Stable producer provenance namespace.",
                "enum": sorted(FRAME_PROVENANCE_VALUES),
            },
            "max_observations": {
                "type": ["integer", "null"],
                "description": "Output-only observation cap; null means unlimited.",
                "minimum": 0,
            },
            "observations": {
                "type": "array",
                "description": "Signal-derived or typed external observations.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        name
                        for name in OBSERVATION_FIELDS
                        if name not in OPTIONAL_OBSERVATION_FIELDS
                    ],
                    "properties": {
                        "observation_id": {"type": "string", "minLength": 1},
                        "origin": {
                            "type": "string",
                            "enum": ["external_system", "signal_derived"],
                        },
                        "detector_id": {"type": "string", "minLength": 1},
                        "detection_score": {"type": ["number", "null"]},
                        "doa": {
                            "oneOf": [
                                {"type": "null"},
                                {
                                    "type": "object",
                                    "description": (
                                        "Direction-of-arrival estimate with explicit "
                                        "candidate and ambiguity representation."
                                    ),
                                    "additionalProperties": False,
                                    "required": [
                                        name
                                        for name in DOA_FIELDS
                                        if name not in OPTIONAL_DOA_FIELDS
                                    ],
                                    "properties": {
                                        "estimated_bearing_deg": {
                                            "type": ["number", "null"]
                                        },
                                        "candidate_bearing_deg": {
                            "type": "array",
                            "description": (
                                "Candidate bearings in degrees "
                                "clockwise from array forward."
                                            ),
                                            "items": {"type": "number"},
                                        },
                                        "bearing_sector": {
                            "type": ["string", "null"],
                            "description": (
                                "Canonical 8-sector label using "
                                "corrected half-open v1 sector semantics."
                                            ),
                                        },
                                        "bearing_confidence": {
                                            "type": "number",
                                            "minimum": 0.0,
                                            "maximum": 1.0,
                                            "description": (
                                                "Estimator-local direction "
                                                "reliability; not a probability "
                                                "or cross-estimator calibrated "
                                                "quantity."
                                            ),
                                        },
                                        "ambiguity_class": {
                                            "type": ["string", "null"],
                                            "description": (
                                                "Stable ambiguity class namespace when "
                                                "a bearing is not unique."
                                            ),
                                        },
                                        "ambiguity_reason": {
                                            "type": ["string", "null"],
                                            "description": (
                                                "Human-readable explanation for "
                                                "ambiguity_class."
                                            ),
                                        },
                                        "estimated_elevation_deg": {
                                            "type": ["number", "null"],
                                            "minimum": -90.0,
                            "maximum": 90.0,
                            "description": (
                                "Elevation in degrees up from the "
                                "array's forward/right plane when resolvable."
                                            ),
                                        },
                                        "candidate_elevation_deg": {
                                            "type": "array",
                                            "items": {
                                                "type": "number",
                                                "minimum": -90.0,
                                                "maximum": 90.0,
                            },
                            "description": (
                                "Candidate elevations in degrees up "
                                "from the array's forward/right plane."
                                            ),
                                        },
                                    },
                                },
                            ],
                        },
                        "diagnostics": {"type": "object"},
                    },
                },
            },
            "aggregate_per_mic_rms": {
                "type": "object",
                "description": "Per-microphone aggregate RMS values in linear units.",
                "additionalProperties": {"type": "number"},
            },
            "waveform_paths": {
                "type": "array",
                "description": "Optional producer artifact paths.",
                "items": {"type": "string"},
            },
            "diagnostics": {
                "type": "object",
                "description": (
                    "Open-ended additive diagnostics; stable namespaces keep "
                    "their documented meanings."
                ),
            },
        },
    }
