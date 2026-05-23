"""JSON Schema export for public audio sensor frame traces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DETECTION_FIELDS,
    DOA_FIELDS,
    FRAME_PROVENANCE_VALUES,
    FRAME_SCHEMA_VERSION,
    FRAME_TOP_LEVEL_FIELDS,
    FRAME_UNITS,
    POSE3D_FIELDS,
)


def audio_sensor_frame_json_schema() -> dict[str, Any]:
    """Return the v1 ``AudioSensorFrame`` JSON Schema."""

    pose_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": True,
        "required": list(POSE3D_FIELDS),
        "properties": {
            "position_m": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {"type": "number"},
            },
            "orientation_xyzw": {
                "oneOf": [
                    {"type": "null"},
                    {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 4,
                        "items": {"type": "number"},
                    },
                ]
            },
            "frame": {"type": "string", "minLength": 1},
            "coordinate_convention": {
                "type": "string",
                "const": COORDINATE_CONVENTION,
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://isaac-audio-sensors.dev/schemas/audio_sensor_frame.v1.schema.json",
        "title": "Isaac Audio Sensors AudioSensorFrame v1",
        "type": "object",
        "additionalProperties": True,
        "required": list(FRAME_TOP_LEVEL_FIELDS),
        "properties": {
            "schema_version": {"const": FRAME_SCHEMA_VERSION},
            "frame_id": {"type": "string", "minLength": 1},
            "frame_name": {"type": "string", "minLength": 1},
            "timestamp_ms": {"type": "integer"},
            "start_time_s": {"type": ["number", "null"]},
            "end_time_s": {"type": ["number", "null"]},
            "sample_rate_hz": {"type": ["integer", "null"], "minimum": 1},
            "frame_index": {"type": ["integer", "null"], "minimum": 0},
            "backend_id": {"type": "string", "minLength": 1},
            "array_id": {"type": "string", "minLength": 1},
            "array_pose": {"oneOf": [{"type": "null"}, pose_schema]},
            "coordinate_convention": {
                "type": "string",
                "const": COORDINATE_CONVENTION,
            },
            "units": {
                "type": "object",
                "required": sorted(FRAME_UNITS),
                "additionalProperties": {"type": "string"},
                "properties": {
                    key: {"type": "string", "const": value}
                    for key, value in sorted(FRAME_UNITS.items())
                },
            },
            "provenance": {"enum": sorted(FRAME_PROVENANCE_VALUES)},
            "max_events": {"type": ["integer", "null"], "minimum": 0},
            "detections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": list(DETECTION_FIELDS),
                    "properties": {
                        "detection_id": {"type": "string", "minLength": 1},
                        "source_id": {"type": ["string", "null"]},
                        "class_label": {"type": ["string", "null"]},
                        "detection_mode": {"type": "string", "minLength": 1},
                        "timestamp_ms": {"type": "integer"},
                        "ground_truth_bearing_deg": {
                            "type": ["number", "null"]
                        },
                        "source_distance_m": {"type": ["number", "null"]},
                        "doa": {
                            "type": "object",
                            "additionalProperties": True,
                            "required": list(DOA_FIELDS),
                            "properties": {
                                "estimated_bearing_deg": {
                                    "type": ["number", "null"]
                                },
                                "candidate_bearing_deg": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                },
                                "bearing_sector": {"type": ["string", "null"]},
                                "bearing_confidence": {
                                    "type": "number",
                                    "minimum": 0.0,
                                    "maximum": 1.0,
                                },
                                "ambiguity_class": {"type": ["string", "null"]},
                                "ambiguity_reason": {"type": ["string", "null"]},
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
                        "diagnostics": {"type": "object"},
                    },
                },
            },
            "aggregate_per_mic_rms": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            },
            "waveform_paths": {"type": "array", "items": {"type": "string"}},
            "diagnostics": {"type": "object"},
        },
    }


def write_audio_sensor_frame_json_schema(path: str | Path) -> Path:
    """Write the v1 frame schema as stable, sorted JSON."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(audio_sensor_frame_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
