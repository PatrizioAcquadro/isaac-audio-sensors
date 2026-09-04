from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from isaac_audio_sensors.recording.manifest import AssetRecord
from isaac_audio_sensors.recording.serialization import (
    manifest_from_dict,
    manifest_to_dict,
    read_dataset_manifest,
    write_dataset_manifest,
)
from isaac_audio_sensors.schemas.generate import audio_dataset_manifest_json_schema

FIXTURE_DIR = Path("examples/manifests")

INVALID_MESSAGES = {
    "asset_checksum": "64 lowercase hexadecimal",
    "channel_order": "channel_order must not contain duplicates",
    "configuration_checksum": "configuration_sha256",
    "incomplete_shard": "incomplete shards",
    "completion_state": "completion_state",
    "coordinate_frame": "coordinate_convention",
    "frame_range": "frame range must be monotonic",
    "dataset_id": "dataset_id",
    "absolute_path": "relative POSIX path",
    "parent_path": "relative POSIX path",
    "runtime_profile": "runtime_profile",
    "split_group": "unknown groups",
    "timestamp": "non-negative integer",
    "timestamps": "timestamps_ms",
    "units": "canonical unit values",
}


def test_valid_manifest_fixtures_round_trip(tmp_path):
    paths = sorted(FIXTURE_DIR.glob("*.json"))
    assert [path.name for path in paths] == [
        "minimal_manifest.v4.json",
        "multi_episode_manifest.v4.json",
    ]

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = read_dataset_manifest(path)
        assert manifest_to_dict(manifest) == payload
        assert manifest_from_dict(payload) == manifest
        written = write_dataset_manifest(manifest, tmp_path / path.name)
        assert written.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("case", "message"), sorted(INVALID_MESSAGES.items()))
def test_invalid_manifest_payloads_fail_closed(case, message):
    with pytest.raises(ValueError, match=message):
        manifest_from_dict(_invalid_manifest(case))


def test_paths_and_checksum_formats_are_enforced_directly():
    with pytest.raises(ValueError, match="relative POSIX path"):
        AssetRecord(
            asset_id="trace",
            path="C:\\capture\\trace.ndjson",
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
    complete = read_dataset_manifest(FIXTURE_DIR / "minimal_manifest.v4.json")
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
    "mutate",
    [
        lambda payload: payload.__setitem__("sample_rate_hz", "48000"),
        lambda payload: payload.__setitem__("creation_timestamp_ms", True),
        lambda payload: payload.__setitem__("unknown", None),
        lambda payload: payload.pop("schema_version"),
    ],
)
def test_manifest_parser_rejects_coercions_extra_and_missing_fields(mutate):
    payload = manifest_to_dict(
        read_dataset_manifest(FIXTURE_DIR / "minimal_manifest.v4.json")
    )
    mutate(payload)

    with pytest.raises((TypeError, ValueError), match="canonical|integer"):
        manifest_from_dict(payload)


def _invalid_manifest(case: str) -> dict:
    payload = json.loads((FIXTURE_DIR / "minimal_manifest.v4.json").read_text())
    mutations = {
        "asset_checksum": lambda value: value["shards"][0]["assets"][0].__setitem__(
            "sha256", "bad"
        ),
        "channel_order": lambda value: value["channel_order"].__setitem__(1, "ch0"),
        "configuration_checksum": lambda value: value.__setitem__(
            "configuration_sha256", "bad"
        ),
        "incomplete_shard": lambda value: value["shards"][0].__setitem__(
            "completion_state", "incomplete"
        ),
        "completion_state": lambda value: value.__setitem__(
            "completion_state", "interrupted"
        ),
        "coordinate_frame": lambda value: value.__setitem__(
            "coordinate_convention", "legacy_y_forward"
        ),
        "frame_range": lambda value: value["episodes"][0].__setitem__("start_frame", 2),
        "dataset_id": lambda value: value.__setitem__("dataset_id", "bad id"),
        "absolute_path": lambda value: value["shards"][0]["assets"][0].__setitem__(
            "path", "/tmp/frames.ndjson"
        ),
        "parent_path": lambda value: value["shards"][0]["assets"][0].__setitem__(
            "path", "../frames.ndjson"
        ),
        "runtime_profile": lambda value: value.__setitem__("runtime_profile", "fast"),
        "split_group": lambda value: value["splits"][0].__setitem__(
            "group_ids", ["unknown"]
        ),
        "timestamp": lambda value: value.__setitem__("creation_timestamp_ms", -1),
        "timestamps": lambda value: value["episodes"][0].__setitem__(
            "timestamps_ms", [20, 0]
        ),
        "units": lambda value: value["units"].__setitem__("position", "cm"),
    }
    result = deepcopy(payload)
    mutations[case](result)
    return result


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_previous_manifest_versions_are_rejected(version):
    payload = json.loads((FIXTURE_DIR / "minimal_manifest.v4.json").read_text())
    payload["schema_version"] = f"ias.audio_dataset_manifest.{version}"
    with pytest.raises(ValueError, match="schema_version"):
        manifest_from_dict(payload)
    with pytest.raises(ValidationError):
        Draft202012Validator(audio_dataset_manifest_json_schema()).validate(payload)


@pytest.mark.parametrize(
    "field", ["array_poses", "labels", "visual_sync_asset_ids", "source_truth"]
)
def test_removed_episode_metadata_is_rejected(field):
    payload = json.loads((FIXTURE_DIR / "minimal_manifest.v4.json").read_text())
    payload["episodes"][0][field] = []
    with pytest.raises(ValueError, match="exact canonical"):
        manifest_from_dict(payload)
    with pytest.raises(ValidationError):
        Draft202012Validator(audio_dataset_manifest_json_schema()).validate(payload)


def test_visual_sync_assets_are_rejected():
    payload = json.loads((FIXTURE_DIR / "minimal_manifest.v4.json").read_text())
    payload["shards"][0]["assets"][0]["kind"] = "visual_sync"
    with pytest.raises(ValueError, match="AssetRecord.kind"):
        manifest_from_dict(payload)
    with pytest.raises(ValidationError):
        Draft202012Validator(audio_dataset_manifest_json_schema()).validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", ""),
        ("trajectory_id", "bad/id"),
        ("source_asset_ids", "asset"),
        ("source_asset_ids", ["a", "a"]),
        ("source_asset_ids", ["bad/id"]),
    ],
)
def test_learning_identity_metadata_is_validated(field, value):
    payload = json.loads((FIXTURE_DIR / "minimal_manifest.v4.json").read_text())
    target = payload if field == "session_id" else payload["episodes"][0]
    target[field] = value
    with pytest.raises(ValueError, match=field):
        manifest_from_dict(payload)


def test_unknown_and_known_empty_asset_inventories_round_trip():
    payload = json.loads((FIXTURE_DIR / "minimal_manifest.v4.json").read_text())
    for assets in (None, [], ["asset-a", "asset-b"]):
        payload["episodes"][0]["source_asset_ids"] = assets
        payload["episodes"][0]["trajectory_id"] = "trajectory-a"
        assert manifest_to_dict(manifest_from_dict(payload)) == payload
