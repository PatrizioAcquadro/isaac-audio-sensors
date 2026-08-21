"""Pure construction of finalized recording manifests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from isaac_audio_sensors.core.constants import COORDINATE_CONVENTION
from isaac_audio_sensors.recording.constants import DATASET_MANIFEST_UNITS
from isaac_audio_sensors.recording.manifest import (
    AssetRecord,
    AudioDatasetManifest,
    CreationProvenance,
    DeviceProvenance,
    EpisodeRecord,
    ShardRecord,
)


def shard_record(marker: Mapping[str, Any]) -> ShardRecord:
    shard_id = marker["shard_id"]
    return ShardRecord(
        shard_id=shard_id,
        episode_ids=tuple(marker["episode_ids"]),
        assets=tuple(
            AssetRecord(
                asset_id=(
                    f"{shard_id}."
                    f"{'frames' if entry['path'] == 'frames.jsonl' else 'audio'}"
                ),
                path=f"shards/{shard_id}/{entry['path']}",
                kind=(
                    "frame_trace_jsonl"
                    if entry["path"] == "frames.jsonl"
                    else "audio_wav"
                ),
                sha256=entry["sha256"],
            )
            for entry in marker["files"]
        ),
        completion_state="complete",
    )


def build_manifest(
    *,
    configuration: Mapping[str, Any],
    configuration_sha256: str,
    creation_timestamp_ms: int,
    creation: CreationProvenance,
    device: DeviceProvenance,
    license: str,
    source: str,
    coordinate_frames: Sequence[str],
    time_base: str,
    episodes: tuple[EpisodeRecord, ...],
    markers: Sequence[Mapping[str, Any]],
    completion_state: str,
) -> AudioDatasetManifest:
    return AudioDatasetManifest(
        dataset_id=configuration["dataset_id"],
        creation_timestamp_ms=creation_timestamp_ms,
        creation=creation,
        license=license,
        source=source,
        runtime_profile="waveform_fidelity",
        device=device,
        coordinate_convention=COORDINATE_CONVENTION,
        coordinate_frames=tuple(coordinate_frames),
        time_base=time_base,
        sample_rate_hz=configuration["sample_rate_hz"],
        channel_order=tuple(configuration["channel_order"]),
        units=dict(DATASET_MANIFEST_UNITS),
        dtype="float32",
        episodes=episodes,
        shards=tuple(shard_record(marker) for marker in markers),
        calibration_profile=None,
        configuration_sha256=configuration_sha256,
        split_grouping_key=configuration["split_grouping_key"],
        splits=(),
        completion_state=completion_state,
    )


__all__: list[str] = []
