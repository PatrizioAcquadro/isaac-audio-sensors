"""AudioDatasetManifest JSON Schema generation."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.constants import COORDINATE_CONVENTION, RUNTIME_PROFILES
from isaac_audio_sensors.recording.constants import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_MANIFEST_UNITS,
)
from isaac_audio_sensors.schemas._common import (
    _constant_units_schema,
    _relative_path_schema,
    _sha256_schema,
    _stable_id_schema,
)


def audio_dataset_manifest_json_schema() -> dict[str, Any]:
    """Return the v4 ``AudioDatasetManifest`` JSON Schema."""

    stable_id = _stable_id_schema()
    sha256 = _sha256_schema()
    relative_path = _relative_path_schema()
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
    episode = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "episode_id",
            "scene_id",
            "trajectory_id",
            "source_asset_ids",
            "environment_id",
            "seed",
            "start_step",
            "end_step",
            "start_frame",
            "end_frame",
            "timestamps_ms",
            "split_group",
            "reset_markers",
        ],
        "properties": {
            "episode_id": stable_id,
            "scene_id": stable_id,
            "trajectory_id": {"anyOf": [stable_id, {"type": "null"}]},
            "source_asset_ids": {
                "type": ["array", "null"],
                "items": stable_id,
                "uniqueItems": True,
            },
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
            "audio_dataset_manifest.v4.schema.json"
        ),
        "title": "Isaac Audio Sensors AudioDatasetManifest v4",
        "description": (
            "Portable, checksummed dataset contract. Its schema version is "
            "independent of the Python package version; constructors enforce "
            "cross-record ordering, reference, split, and completion invariants."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": [
            "dataset_id",
            "session_id",
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
            "session_id": stable_id,
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
