"""Deterministic JSON serialization for dataset manifests."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_MANIFEST_UNITS,
)
from isaac_audio_sensors.recording.manifest import (
    AssetRecord,
    AudioDatasetManifest,
    CalibrationProfileReference,
    CreationProvenance,
    DeviceProvenance,
    EpisodeRecord,
    ManifestPose,
    ResetMarker,
    ShardRecord,
    SourceTruth,
    SplitRecord,
)


def manifest_to_dict(manifest: AudioDatasetManifest) -> dict[str, Any]:
    """Return a JSON-ready dictionary for one dataset manifest."""

    return _serialize(manifest)


def write_dataset_manifest(
    manifest: AudioDatasetManifest,
    path: str | Path,
) -> Path:
    """Write one deterministic pretty JSON dataset manifest."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest_to_dict(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def manifest_from_dict(payload: dict[str, Any]) -> AudioDatasetManifest:
    """Rebuild an ``AudioDatasetManifest`` from a JSON dictionary."""

    calibration_payload = payload.get("calibration_profile")
    return AudioDatasetManifest(
        dataset_id=str(payload["dataset_id"]),
        schema_version=str(
            payload.get("schema_version", DATASET_MANIFEST_SCHEMA_VERSION)
        ),
        creation_timestamp_ms=int(payload["creation_timestamp_ms"]),
        creation=_creation_from_dict(payload["creation"]),
        license=str(payload["license"]),
        source=str(payload["source"]),
        runtime_profile=str(payload["runtime_profile"]),
        device=_device_from_dict(payload["device"]),
        coordinate_convention=str(
            payload.get("coordinate_convention", COORDINATE_CONVENTION)
        ),
        coordinate_frames=tuple(payload["coordinate_frames"]),
        time_base=str(payload["time_base"]),
        sample_rate_hz=int(payload["sample_rate_hz"]),
        channel_order=tuple(payload["channel_order"]),
        units=dict(payload.get("units", DATASET_MANIFEST_UNITS)),
        dtype=str(payload["dtype"]),
        episodes=tuple(_episode_from_dict(item) for item in payload["episodes"]),
        shards=tuple(_shard_from_dict(item) for item in payload["shards"]),
        calibration_profile=(
            None
            if calibration_payload is None
            else CalibrationProfileReference(
                profile_id=str(calibration_payload["profile_id"]),
                profile_version=str(calibration_payload["profile_version"]),
                path=str(calibration_payload["path"]),
                sha256=str(calibration_payload["sha256"]),
            )
        ),
        configuration_sha256=str(payload["configuration_sha256"]),
        split_grouping_key=str(payload["split_grouping_key"]),
        splits=tuple(
            SplitRecord(name=str(item["name"]), group_ids=tuple(item["group_ids"]))
            for item in payload.get("splits", ())
        ),
        completion_state=str(payload["completion_state"]),
    )


def read_dataset_manifest(path: str | Path) -> AudioDatasetManifest:
    """Read and validate one pretty JSON dataset manifest."""

    return manifest_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


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


def _creation_from_dict(payload: dict[str, Any]) -> CreationProvenance:
    return CreationProvenance(
        tool_name=str(payload["tool_name"]),
        tool_version=str(payload["tool_version"]),
        isaac_sim_version=payload.get("isaac_sim_version"),
        isaac_lab_version=payload.get("isaac_lab_version"),
        kit_version=payload.get("kit_version"),
        backend_id=str(payload["backend_id"]),
        estimator_id=str(payload["estimator_id"]),
    )


def _device_from_dict(payload: dict[str, Any]) -> DeviceProvenance:
    return DeviceProvenance(
        device_id=str(payload["device_id"]),
        device_type=str(payload["device_type"]),
        platform=str(payload["platform"]),
        compute_device=str(payload["compute_device"]),
    )


def _pose_from_dict(payload: dict[str, Any]) -> ManifestPose:
    orientation = payload.get("orientation_xyzw")
    return ManifestPose(
        entity_id=str(payload["entity_id"]),
        entity_kind=str(payload["entity_kind"]),
        timestamp_ms=int(payload["timestamp_ms"]),
        position_m=tuple(payload["position_m"]),
        orientation_xyzw=None if orientation is None else tuple(orientation),
        frame=str(payload["frame"]),
    )


def _truth_from_dict(payload: dict[str, Any]) -> SourceTruth:
    return SourceTruth(
        source_id=str(payload["source_id"]),
        timestamp_ms=int(payload["timestamp_ms"]),
        class_label=str(payload["class_label"]),
        active=bool(payload["active"]),
        pose=_pose_from_dict(payload["pose"]),
    )


def _episode_from_dict(payload: dict[str, Any]) -> EpisodeRecord:
    return EpisodeRecord(
        episode_id=str(payload["episode_id"]),
        scene_id=str(payload["scene_id"]),
        environment_id=str(payload["environment_id"]),
        seed=int(payload["seed"]),
        start_step=int(payload["start_step"]),
        end_step=int(payload["end_step"]),
        start_frame=int(payload["start_frame"]),
        end_frame=int(payload["end_frame"]),
        timestamps_ms=tuple(payload["timestamps_ms"]),
        split_group=str(payload["split_group"]),
        reset_markers=tuple(
            ResetMarker(
                step_index=int(item["step_index"]),
                frame_index=int(item["frame_index"]),
                timestamp_ms=int(item["timestamp_ms"]),
            )
            for item in payload.get("reset_markers", ())
        ),
        array_poses=tuple(
            _pose_from_dict(item) for item in payload.get("array_poses", ())
        ),
        source_truth=tuple(
            _truth_from_dict(item) for item in payload.get("source_truth", ())
        ),
        labels=tuple(payload.get("labels", ())),
        visual_sync_asset_ids=tuple(payload.get("visual_sync_asset_ids", ())),
    )


def _shard_from_dict(payload: dict[str, Any]) -> ShardRecord:
    return ShardRecord(
        shard_id=str(payload["shard_id"]),
        episode_ids=tuple(payload["episode_ids"]),
        assets=tuple(
            AssetRecord(
                asset_id=str(item["asset_id"]),
                path=str(item["path"]),
                kind=str(item["kind"]),
                sha256=str(item["sha256"]),
            )
            for item in payload.get("assets", ())
        ),
        completion_state=str(payload["completion_state"]),
    )
