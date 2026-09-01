"""AudioSensorFrame JSON Schema generation."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DETECTION_FIELDS,
    DOA_FIELDS,
    FRAME_PROVENANCE_VALUES,
    FRAME_SCHEMA_VERSION,
    FRAME_TOP_LEVEL_FIELDS,
    FRAME_UNITS,
    OPTIONAL_DETECTION_FIELDS,
    OPTIONAL_DOA_FIELDS,
    OPTIONAL_FRAME_UNIT_KEYS,
    POSE3D_FIELDS,
)


def audio_sensor_frame_json_schema() -> dict[str, Any]:
    """Return the v2 ``AudioSensorFrame`` JSON Schema."""

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
            "https://isaac-audio-sensors.dev/schemas/audio_sensor_frame.v2.schema.json"
        ),
        "title": "Isaac Audio Sensors AudioSensorFrame v2",
        "description": (
            "AudioSensorFrame v2 trace contract. timestamp_ms is derived from "
            "start_time_s, sample_rate_hz records the selected array rate, and "
            "max_detections limits only the detection output."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": list(FRAME_TOP_LEVEL_FIELDS),
        "properties": {
            "schema_version": {
                "description": "Frame schema id for the breaking v2 contract.",
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
            "backend_id": {
                "type": "string",
                "description": (
                    "Public backend identifier such as geometry_only, "
                    "tdoa_synthetic, room_acoustics, or room_acoustics_srp."
                ),
                "minLength": 1,
            },
            "array_id": {
                "type": "string",
                "description": "Microphone-array identifier.",
                "minLength": 1,
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
            "max_detections": {
                "type": ["integer", "null"],
                "description": "Output-only detection cap; null means unlimited.",
                "minimum": 0,
            },
            "detections": {
                "type": "array",
                "description": "Detected, scheduled, or externally described events.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        name
                        for name in DETECTION_FIELDS
                        if name not in OPTIONAL_DETECTION_FIELDS
                    ],
                    "properties": {
                        "detection_id": {"type": "string", "minLength": 1},
                        "source_id": {"type": ["string", "null"]},
                        "class_label": {"type": ["string", "null"]},
                        "detection_mode": {"type": "string", "minLength": 1},
                        "ground_truth_bearing_deg": {"type": ["number", "null"]},
                        "ground_truth_elevation_deg": {
                            "type": ["number", "null"],
                            "minimum": -90.0,
                            "maximum": 90.0,
                            "description": (
                                "Oracle source elevation in degrees up from the "
                                "array's forward/right plane."
                            ),
                        },
                        "source_distance_m": {"type": ["number", "null"]},
                        "doa": {
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
                                "estimated_bearing_deg": {"type": ["number", "null"]},
                                "candidate_bearing_deg": {
                                    "type": "array",
                                    "description": (
                                        "Candidate bearings in degrees clockwise "
                                        "from array forward."
                                    ),
                                    "items": {"type": "number"},
                                },
                                "bearing_sector": {
                                    "type": ["string", "null"],
                                    "description": (
                                        "Canonical 8-sector label using corrected "
                                        "half-open v1 sector semantics."
                                    ),
                                },
                                "bearing_confidence": {
                                    "type": "number",
                                    "minimum": 0.0,
                                    "maximum": 1.0,
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
                                        "Elevation "
                                        "in degrees up from the array's "
                                        "forward/right plane when the producer "
                                        "can resolve it (rank-3 layouts)."
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
                                        "Candidate "
                                        "elevations in degrees up from the "
                                        "array's forward/right plane."
                                    ),
                                },
                            },
                        },
                        "source_pose": {"oneOf": [{"type": "null"}, pose_schema]},
                        "per_mic_delay_s": {
                            "type": "object",
                            "additionalProperties": {"type": "number"},
                        },
                        "per_mic_rms": {
                            "type": "object",
                            "additionalProperties": {"type": "number"},
                        },
                        "audio_asset_path": {"type": ["string", "null"]},
                        "occluded": {
                            "type": "boolean",
                            "description": (
                                "True when the "
                                "producer determined the direct source-to-"
                                "array path is occluded (e.g. Isaac raycast "
                                "occlusion)."
                            ),
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
