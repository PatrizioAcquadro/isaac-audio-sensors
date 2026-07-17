"""JSON Schema export for public audio sensor frame traces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.constants import (
    CALIBRATION_PROFILE_SCHEMA_VERSION,
    CALIBRATION_PROFILE_UNITS,
    COORDINATE_CONVENTION,
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_MANIFEST_UNITS,
    DETECTION_FIELDS,
    DOA_FIELDS,
    FRAME_PROVENANCE_VALUES,
    FRAME_SCHEMA_VERSION,
    FRAME_TOP_LEVEL_FIELDS,
    FRAME_UNITS,
    OPTIONAL_DETECTION_FIELDS,
    OPTIONAL_DOA_FIELDS,
    POSE3D_FIELDS,
    RUNTIME_PROFILES,
)


def audio_sensor_frame_json_schema() -> dict[str, Any]:
    """Return the v1 ``AudioSensorFrame`` JSON Schema."""

    pose_schema: dict[str, Any] = {
        "type": "object",
        "description": (
            "World-frame pose using x_forward_y_right_z_up_clockwise_bearing."
        ),
        "additionalProperties": True,
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
                "description": "Coordinate frame name; v1 examples use world.",
                "minLength": 1,
            },
            "coordinate_convention": {
                "type": "string",
                "description": "Stable v1 coordinate and bearing convention.",
                "const": COORDINATE_CONVENTION,
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://isaac-audio-sensors.dev/schemas/audio_sensor_frame.v1.schema.json"
        ),
        "title": "Isaac Audio Sensors AudioSensorFrame v1",
        "description": (
            "Stable AudioSensorFrame v1 trace contract. The schema_version is "
            "separate from the Python package version. Public fields, unit "
            "meanings, timestamp semantics, provenance values, coordinate "
            "convention, ambiguity representation, stable backend identifiers, "
            "and bearing-sector semantics are compatibility commitments for v1."
        ),
        "type": "object",
        "additionalProperties": True,
        "required": list(FRAME_TOP_LEVEL_FIELDS),
        "properties": {
            "schema_version": {
                "description": "Stable frame schema id for all compatible v1 frames.",
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
                "description": "Frame timestamp in integer milliseconds.",
            },
            "start_time_s": {
                "type": ["number", "null"],
                "description": "Inclusive frame-window start time in seconds.",
            },
            "end_time_s": {
                "type": ["number", "null"],
                "description": "Exclusive frame-window end time in seconds.",
            },
            "sample_rate_hz": {
                "type": ["integer", "null"],
                "description": "Audio sample rate in Hz when known.",
                "minimum": 1,
            },
            "frame_index": {
                "type": ["integer", "null"],
                "description": "Non-negative producer frame index when present.",
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
                "description": "Stable v1 coordinate and bearing convention.",
                "const": COORDINATE_CONVENTION,
            },
            "units": {
                "type": "object",
                "description": "Stable unit names and meanings for v1 fields.",
                "required": sorted(FRAME_UNITS),
                "additionalProperties": {"type": "string"},
                "properties": {
                    key: {"type": "string", "const": value}
                    for key, value in sorted(FRAME_UNITS.items())
                },
            },
            "provenance": {
                "description": "Stable producer provenance namespace.",
                "enum": sorted(FRAME_PROVENANCE_VALUES),
            },
            "max_events": {
                "type": ["integer", "null"],
                "description": "Non-negative deterministic detection cap when set.",
                "minimum": 0,
            },
            "detections": {
                "type": "array",
                "description": "Detected, scheduled, or externally described events.",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
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
                        "timestamp_ms": {"type": "integer"},
                        "ground_truth_bearing_deg": {"type": ["number", "null"]},
                        "ground_truth_elevation_deg": {
                            "type": ["number", "null"],
                            "minimum": -90.0,
                            "maximum": 90.0,
                            "description": (
                                "Optional additive v1 field: oracle source "
                                "elevation in degrees up from the array's "
                                "forward/right plane. Absent in older v1 "
                                "traces."
                            ),
                        },
                        "source_distance_m": {"type": ["number", "null"]},
                        "doa": {
                            "type": "object",
                            "description": (
                                "Direction-of-arrival estimate with explicit "
                                "candidate and ambiguity representation."
                            ),
                            "additionalProperties": True,
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
                                        "Optional additive v1 field: elevation "
                                        "in degrees up from the array's "
                                        "forward/right plane when the producer "
                                        "can resolve it (rank-3 layouts). "
                                        "Absent in older v1 traces."
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
                                        "Optional additive v1 field: candidate "
                                        "elevations in degrees up from the "
                                        "array's forward/right plane. Absent "
                                        "in older v1 traces."
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
                                "Optional additive v1 field: true when the "
                                "producer determined the direct source-to-"
                                "array path is occluded (e.g. Isaac raycast "
                                "occlusion). Absent in older v1 traces."
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


def write_audio_sensor_frame_json_schema(path: str | Path) -> Path:
    """Write the v1 frame schema as stable, sorted JSON."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(audio_sensor_frame_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def audio_dataset_manifest_json_schema() -> dict[str, Any]:
    """Return the v1 ``AudioDatasetManifest`` JSON Schema."""

    stable_id = {
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    }
    sha256 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    relative_path = {
        "type": "string",
        "minLength": 1,
        "pattern": "^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\\.\\.(?:/|$))[^\\\\]+$",
    }
    pose = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "entity_id",
            "entity_kind",
            "timestamp_ms",
            "position_m",
            "orientation_xyzw",
            "frame",
        ],
        "properties": {
            "entity_id": stable_id,
            "entity_kind": {"enum": ["array", "source"]},
            "timestamp_ms": {"type": "integer", "minimum": 0},
            "position_m": _fixed_number_array(3),
            "orientation_xyzw": {
                "oneOf": [{"type": "null"}, _fixed_number_array(4)]
            },
            "frame": stable_id,
        },
    }
    reset = {
        "type": "object",
        "additionalProperties": False,
        "required": ["step_index", "frame_index", "timestamp_ms"],
        "properties": {
            "step_index": {"type": "integer", "minimum": 0},
            "frame_index": {"type": "integer", "minimum": 0},
            "timestamp_ms": {"type": "integer", "minimum": 0},
        },
    }
    source_truth = {
        "type": "object",
        "additionalProperties": False,
        "required": ["source_id", "timestamp_ms", "class_label", "active", "pose"],
        "properties": {
            "source_id": stable_id,
            "timestamp_ms": {"type": "integer", "minimum": 0},
            "class_label": {"type": "string", "minLength": 1},
            "active": {"type": "boolean"},
            "pose": pose,
        },
    }
    episode = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "episode_id",
            "scene_id",
            "environment_id",
            "seed",
            "start_step",
            "end_step",
            "start_frame",
            "end_frame",
            "timestamps_ms",
            "split_group",
            "reset_markers",
            "array_poses",
            "source_truth",
            "labels",
            "visual_sync_asset_ids",
        ],
        "properties": {
            "episode_id": stable_id,
            "scene_id": stable_id,
            "environment_id": stable_id,
            "seed": {"type": "integer", "minimum": 0},
            "start_step": {"type": "integer", "minimum": 0},
            "end_step": {"type": "integer", "minimum": 0},
            "start_frame": {"type": "integer", "minimum": 0},
            "end_frame": {"type": "integer", "minimum": 0},
            "timestamps_ms": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "integer", "minimum": 0},
            },
            "split_group": stable_id,
            "reset_markers": {"type": "array", "items": reset},
            "array_poses": {"type": "array", "items": pose},
            "source_truth": {"type": "array", "items": source_truth},
            "labels": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "visual_sync_asset_ids": {
                "type": "array",
                "uniqueItems": True,
                "items": stable_id,
            },
        },
    }
    asset = {
        "type": "object",
        "additionalProperties": False,
        "required": ["asset_id", "path", "kind", "sha256"],
        "properties": {
            "asset_id": stable_id,
            "path": relative_path,
            "kind": {
                "enum": [
                    "audio_flac",
                    "audio_wav",
                    "frame_trace_jsonl",
                    "visual_sync",
                ]
            },
            "sha256": sha256,
        },
    }
    shard = {
        "type": "object",
        "additionalProperties": False,
        "required": ["shard_id", "episode_ids", "assets", "completion_state"],
        "properties": {
            "shard_id": stable_id,
            "episode_ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": stable_id,
            },
            "assets": {"type": "array", "items": asset},
            "completion_state": {"enum": ["complete", "incomplete"]},
        },
    }
    split = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "group_ids"],
        "properties": {
            "name": {"enum": ["test", "train", "validation"]},
            "group_ids": {
                "type": "array",
                "uniqueItems": True,
                "items": stable_id,
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://isaac-audio-sensors.dev/schemas/"
            "audio_dataset_manifest.v1.schema.json"
        ),
        "title": "Isaac Audio Sensors AudioDatasetManifest v1",
        "description": (
            "Portable, checksummed dataset contract. Its schema version is "
            "independent of the Python package version; constructors enforce "
            "cross-record ordering, reference, split, and completion invariants."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": [
            "dataset_id",
            "creation_timestamp_ms",
            "creation",
            "license",
            "source",
            "runtime_profile",
            "device",
            "coordinate_convention",
            "coordinate_frames",
            "time_base",
            "sample_rate_hz",
            "channel_order",
            "units",
            "dtype",
            "episodes",
            "shards",
            "calibration_profile",
            "configuration_sha256",
            "split_grouping_key",
            "splits",
            "completion_state",
            "schema_version",
        ],
        "properties": {
            "dataset_id": stable_id,
            "creation_timestamp_ms": {"type": "integer", "minimum": 0},
            "creation": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "tool_name",
                    "tool_version",
                    "isaac_sim_version",
                    "isaac_lab_version",
                    "kit_version",
                    "backend_id",
                    "estimator_id",
                ],
                "properties": {
                    "tool_name": stable_id,
                    "tool_version": {"type": "string", "minLength": 1},
                    "isaac_sim_version": {"type": ["string", "null"]},
                    "isaac_lab_version": {"type": ["string", "null"]},
                    "kit_version": {"type": ["string", "null"]},
                    "backend_id": stable_id,
                    "estimator_id": stable_id,
                },
            },
            "license": {"type": "string", "minLength": 1},
            "source": {"type": "string", "minLength": 1},
            "runtime_profile": {"enum": list(RUNTIME_PROFILES)},
            "device": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "device_id",
                    "device_type",
                    "platform",
                    "compute_device",
                ],
                "properties": {
                    "device_id": stable_id,
                    "device_type": {"type": "string", "minLength": 1},
                    "platform": {"type": "string", "minLength": 1},
                    "compute_device": {"type": "string", "minLength": 1},
                },
            },
            "coordinate_convention": {"const": COORDINATE_CONVENTION},
            "coordinate_frames": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": stable_id,
            },
            "time_base": {"enum": ["monotonic", "simulation_time", "utc"]},
            "sample_rate_hz": {"type": "integer", "minimum": 1},
            "channel_order": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": stable_id,
            },
            "units": _constant_units_schema(DATASET_MANIFEST_UNITS),
            "dtype": {"enum": ["float32", "float64", "int16", "int24", "int32"]},
            "episodes": {"type": "array", "items": episode},
            "shards": {"type": "array", "items": shard},
            "calibration_profile": {
                "oneOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["profile_id", "profile_version", "path", "sha256"],
                        "properties": {
                            "profile_id": stable_id,
                            "profile_version": stable_id,
                            "path": relative_path,
                            "sha256": sha256,
                        },
                    },
                ]
            },
            "configuration_sha256": sha256,
            "split_grouping_key": stable_id,
            "splits": {"type": "array", "items": split},
            "completion_state": {"enum": ["complete", "incomplete"]},
            "schema_version": {"const": DATASET_MANIFEST_SCHEMA_VERSION},
        },
    }


def write_audio_dataset_manifest_json_schema(path: str | Path) -> Path:
    """Write the v1 dataset-manifest schema as stable, sorted JSON."""

    return _write_schema(audio_dataset_manifest_json_schema(), path)


def audio_calibration_profile_json_schema() -> dict[str, Any]:
    """Return the v1 ``AudioCalibrationProfile`` JSON Schema."""

    stable_id = {
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    }
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
            "reference_rig_bom_path": {
                "type": "string",
                "minLength": 1,
                "pattern": "^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\\.\\.(?:/|$))[^\\\\]+$",
            },
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
                        "path": {
                            "type": "string",
                            "minLength": 1,
                            "pattern": (
                                "^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\\.\\."
                                "(?:/|$))[^\\\\]+$"
                            ),
                        },
                        "sha256": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{64}$",
                        },
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


def write_audio_calibration_profile_json_schema(path: str | Path) -> Path:
    """Write the v1 calibration-profile schema as stable, sorted JSON."""

    return _write_schema(audio_calibration_profile_json_schema(), path)


def _fixed_number_array(length: int) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": length,
        "maxItems": length,
        "items": {"type": "number"},
    }


def _constant_units_schema(units: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(units),
        "properties": {
            key: {"type": "string", "const": value}
            for key, value in sorted(units.items())
        },
    }


def _write_schema(schema: dict[str, Any], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
