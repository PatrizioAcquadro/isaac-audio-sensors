"""Contract tests for ``ias.audio_dataset_manifest.v1``."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from isaac_audio_sensors.core.constants import DATASET_MANIFEST_SCHEMA_VERSION
from isaac_audio_sensors.core.dataset_manifest import AssetRecord, ManifestPose
from isaac_audio_sensors.core.io.manifests import (
    manifest_from_dict,
    manifest_to_dict,
    read_dataset_manifest,
    write_dataset_manifest,
)
from isaac_audio_sensors.core.schema import audio_dataset_manifest_json_schema

SCHEMA_PATH = Path("docs/schemas/audio_dataset_manifest.v1.schema.json")
FIXTURE_DIR = Path("examples/manifests")

INVALID_MESSAGES = {
    "invalid_asset_checksum_format.json": "64 lowercase hexadecimal",
    "invalid_channel_order_duplicate.json": "channel_order must not contain duplicates",
    "invalid_checksum_format.json": "configuration_sha256",
    "invalid_complete_manifest_incomplete_shard.json": "incomplete shards",
    "invalid_completion_state_unknown.json": "completion_state",
    "invalid_coordinate_frame.json": "coordinate_convention",
    "invalid_frame_range_nonmonotonic.json": "frame range must be monotonic",
    "invalid_id_whitespace.json": "dataset_id",
    "invalid_path_absolute.json": "relative POSIX path",
    "invalid_path_parent_traversal.json": "relative POSIX path",
    "invalid_runtime_profile_unknown.json": "runtime_profile",
    "invalid_split_unknown_group.json": "unknown groups",
    "invalid_timestamp_negative.json": "non-negative integer",
    "invalid_timestamps_nonmonotonic.json": "timestamps_ms",
    "invalid_units_position.json": "canonical unit values",
}


def test_generated_schema_matches_checked_in_schema_exactly():
    generated = (
        json.dumps(audio_dataset_manifest_json_schema(), indent=2, sort_keys=True)
        + "\n"
    )

    assert SCHEMA_PATH.read_text(encoding="utf-8") == generated
    assert (
        audio_dataset_manifest_json_schema()["properties"]["schema_version"][
            "const"
        ]
        == DATASET_MANIFEST_SCHEMA_VERSION
    )


def test_valid_manifest_fixtures_round_trip(tmp_path):
    paths = sorted(FIXTURE_DIR.glob("*.json"))
    assert [path.name for path in paths] == [
        "minimal_manifest.v1.json",
        "multi_episode_manifest.v1.json",
    ]

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = read_dataset_manifest(path)
        assert manifest_to_dict(manifest) == payload
        assert manifest_from_dict(payload) == manifest
        written = write_dataset_manifest(manifest, tmp_path / path.name)
        assert written.read_text(encoding="utf-8") == path.read_text(
            encoding="utf-8"
        )


@pytest.mark.parametrize(("filename", "message"), sorted(INVALID_MESSAGES.items()))
def test_invalid_manifest_fixtures_fail_closed(filename, message):
    with pytest.raises(ValueError, match=message):
        read_dataset_manifest(FIXTURE_DIR / "invalid" / filename)


def test_paths_and_checksum_formats_are_enforced_directly():
    with pytest.raises(ValueError, match="relative POSIX path"):
        AssetRecord(
            asset_id="trace",
            path="C:\\capture\\trace.ndjson",
            kind="frame_trace_jsonl",
            sha256="a" * 64,
        )
    with pytest.raises(ValueError, match="relative POSIX path"):
        AssetRecord(
            asset_id="trace",
            path="shards/../trace.ndjson",
            kind="frame_trace_jsonl",
            sha256="a" * 64,
        )
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        AssetRecord(
            asset_id="trace",
            path="trace.ndjson",
            kind="frame_trace_jsonl",
            sha256="A" * 64,
        )


def test_completion_state_never_promotes_an_incomplete_shard():
    complete = read_dataset_manifest(FIXTURE_DIR / "minimal_manifest.v1.json")
    incomplete_shard = replace(complete.shards[0], completion_state="incomplete")

    incomplete_manifest = replace(
        complete,
        shards=(incomplete_shard,),
        completion_state="incomplete",
    )
    assert incomplete_manifest.completion_state == "incomplete"
    with pytest.raises(ValueError, match="incomplete shards"):
        replace(complete, shards=(incomplete_shard,))


@pytest.mark.parametrize(
    "orientation",
    [
        (0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, math.nan),
        (0.0, 0.0, math.inf, 1.0),
    ],
)
def test_manifest_pose_rejects_zero_and_nonfinite_quaternions(orientation):
    with pytest.raises(ValueError, match="finite|non-zero"):
        ManifestPose(
            entity_id="array",
            entity_kind="array",
            timestamp_ms=0,
            position_m=(0.0, 0.0, 0.0),
            orientation_xyzw=orientation,
            frame="world",
        )


def test_manifest_pose_normalizes_valid_non_unit_quaternion():
    pose = ManifestPose(
        entity_id="array",
        entity_kind="array",
        timestamp_ms=0,
        position_m=(0.0, 0.0, 0.0),
        orientation_xyzw=(0.0, 0.0, 0.0, 2.0),
        frame="world",
    )

    assert pose.orientation_xyzw == (0.0, 0.0, 0.0, 1.0)


def test_manifest_reader_normalizes_non_unit_quaternion_before_serialization():
    payload = manifest_to_dict(
        read_dataset_manifest(FIXTURE_DIR / "minimal_manifest.v1.json")
    )
    payload["episodes"][0]["array_poses"][0]["orientation_xyzw"] = [0, 0, 0, 3]

    manifest = manifest_from_dict(payload)
    normalized = manifest_to_dict(manifest)

    assert normalized["episodes"][0]["array_poses"][0]["orientation_xyzw"] == [
        0.0,
        0.0,
        0.0,
        1.0,
    ]
