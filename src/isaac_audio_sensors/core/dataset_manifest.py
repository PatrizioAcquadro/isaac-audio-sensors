"""Public dataset-manifest v1 dataclasses and validation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_MANIFEST_UNITS,
    RUNTIME_PROFILES,
)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMPLETION_STATES = frozenset({"incomplete", "complete"})
_ASSET_KINDS = frozenset(
    {"frame_trace_jsonl", "audio_wav", "audio_flac", "visual_sync"}
)
_DTYPES = frozenset({"float32", "float64", "int16", "int24", "int32"})
_TIME_BASES = frozenset({"simulation_time", "monotonic", "utc"})
_SPLIT_NAMES = frozenset({"train", "validation", "test"})


@dataclass(frozen=True, slots=True, kw_only=True)
class CreationProvenance:
    """Tool and runtime provenance for one dataset."""

    tool_name: str
    tool_version: str
    isaac_sim_version: str | None = None
    isaac_lab_version: str | None = None
    kit_version: str | None = None
    backend_id: str
    estimator_id: str

    def __post_init__(self) -> None:
        _require_id(self.tool_name, "CreationProvenance.tool_name")
        _require_text(self.tool_version, "CreationProvenance.tool_version")
        _require_id(self.backend_id, "CreationProvenance.backend_id")
        _require_id(self.estimator_id, "CreationProvenance.estimator_id")
        for name in ("isaac_sim_version", "isaac_lab_version", "kit_version"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, f"CreationProvenance.{name}")


@dataclass(frozen=True, slots=True, kw_only=True)
class DeviceProvenance:
    """Capture-device identity without runtime-specific dependencies."""

    device_id: str
    device_type: str
    platform: str
    compute_device: str

    def __post_init__(self) -> None:
        _require_id(self.device_id, "DeviceProvenance.device_id")
        _require_text(self.device_type, "DeviceProvenance.device_type")
        _require_text(self.platform, "DeviceProvenance.platform")
        _require_text(self.compute_device, "DeviceProvenance.compute_device")


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestPose:
    """Timestamped pose for a stable array or source id."""

    entity_id: str
    entity_kind: str
    timestamp_ms: int
    position_m: tuple[float, float, float]
    orientation_xyzw: tuple[float, float, float, float] | None
    frame: str

    def __post_init__(self) -> None:
        _require_id(self.entity_id, "ManifestPose.entity_id")
        if self.entity_kind not in {"array", "source"}:
            raise ValueError("ManifestPose.entity_kind must be 'array' or 'source'.")
        _require_non_negative_int(self.timestamp_ms, "ManifestPose.timestamp_ms")
        object.__setattr__(
            self,
            "position_m",
            _finite_tuple(self.position_m, 3, "ManifestPose.position_m"),
        )
        if self.orientation_xyzw is not None:
            object.__setattr__(
                self,
                "orientation_xyzw",
                _finite_tuple(
                    self.orientation_xyzw,
                    4,
                    "ManifestPose.orientation_xyzw",
                ),
            )
        _require_id(self.frame, "ManifestPose.frame")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceTruth:
    """Ground-truth source state at one episode timestamp."""

    source_id: str
    timestamp_ms: int
    class_label: str
    active: bool
    pose: ManifestPose

    def __post_init__(self) -> None:
        _require_id(self.source_id, "SourceTruth.source_id")
        _require_non_negative_int(self.timestamp_ms, "SourceTruth.timestamp_ms")
        _require_text(self.class_label, "SourceTruth.class_label")
        if self.pose.entity_kind != "source":
            raise ValueError("SourceTruth.pose must have entity_kind 'source'.")
        if self.pose.entity_id != self.source_id:
            raise ValueError("SourceTruth.pose entity_id must match source_id.")
        if self.pose.timestamp_ms != self.timestamp_ms:
            raise ValueError("SourceTruth.pose timestamp_ms must match timestamp_ms.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResetMarker:
    """Explicit simulator reset boundary inside an episode."""

    step_index: int
    frame_index: int
    timestamp_ms: int

    def __post_init__(self) -> None:
        _require_non_negative_int(self.step_index, "ResetMarker.step_index")
        _require_non_negative_int(self.frame_index, "ResetMarker.frame_index")
        _require_non_negative_int(self.timestamp_ms, "ResetMarker.timestamp_ms")


@dataclass(frozen=True, slots=True, kw_only=True)
class EpisodeRecord:
    """Ranges, identities, truth, and synchronization data for one episode."""

    episode_id: str
    scene_id: str
    environment_id: str
    seed: int
    start_step: int
    end_step: int
    start_frame: int
    end_frame: int
    timestamps_ms: tuple[int, ...]
    split_group: str
    reset_markers: tuple[ResetMarker, ...] = field(default_factory=tuple)
    array_poses: tuple[ManifestPose, ...] = field(default_factory=tuple)
    source_truth: tuple[SourceTruth, ...] = field(default_factory=tuple)
    labels: tuple[str, ...] = field(default_factory=tuple)
    visual_sync_asset_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("episode_id", "scene_id", "environment_id", "split_group"):
            _require_id(getattr(self, name), f"EpisodeRecord.{name}")
        _require_non_negative_int(self.seed, "EpisodeRecord.seed")
        _require_range(self.start_step, self.end_step, "EpisodeRecord step")
        _require_range(self.start_frame, self.end_frame, "EpisodeRecord frame")
        timestamps = tuple(int(value) for value in self.timestamps_ms)
        if not timestamps:
            raise ValueError("EpisodeRecord.timestamps_ms must not be empty.")
        _require_monotonic(timestamps, "EpisodeRecord.timestamps_ms")
        object.__setattr__(self, "timestamps_ms", timestamps)
        resets = tuple(self.reset_markers)
        for reset in resets:
            if not self.start_step <= reset.step_index <= self.end_step:
                raise ValueError("EpisodeRecord reset step is outside the step range.")
            if not self.start_frame <= reset.frame_index <= self.end_frame:
                raise ValueError(
                    "EpisodeRecord reset frame is outside the frame range."
                )
            if reset.timestamp_ms not in timestamps:
                raise ValueError(
                    "EpisodeRecord reset timestamp is absent from timestamps_ms."
                )
        _require_monotonic(
            tuple(reset.timestamp_ms for reset in resets),
            "EpisodeRecord.reset_markers timestamps",
        )
        object.__setattr__(self, "reset_markers", resets)
        array_poses = tuple(self.array_poses)
        if any(pose.entity_kind != "array" for pose in array_poses):
            raise ValueError("EpisodeRecord.array_poses must contain array poses.")
        _validate_pose_timestamps(array_poses, timestamps, "array_poses")
        object.__setattr__(self, "array_poses", array_poses)
        source_truth = tuple(self.source_truth)
        _validate_truth_timestamps(source_truth, timestamps)
        object.__setattr__(self, "source_truth", source_truth)
        object.__setattr__(
            self,
            "labels",
            _unique_text_tuple(self.labels, "EpisodeRecord.labels"),
        )
        object.__setattr__(
            self,
            "visual_sync_asset_ids",
            _unique_id_tuple(
                self.visual_sync_asset_ids,
                "EpisodeRecord.visual_sync_asset_ids",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AssetRecord:
    """Portable, checksummed manifest asset."""

    asset_id: str
    path: str
    kind: str
    sha256: str

    def __post_init__(self) -> None:
        _require_id(self.asset_id, "AssetRecord.asset_id")
        _require_relative_path(self.path, "AssetRecord.path")
        if self.kind not in _ASSET_KINDS:
            raise ValueError(f"AssetRecord.kind must be one of {sorted(_ASSET_KINDS)}.")
        suffix = PurePosixPath(self.path).suffix.lower()
        if self.kind == "frame_trace_jsonl" and suffix not in {".jsonl", ".ndjson"}:
            raise ValueError("frame_trace_jsonl assets must use .jsonl or .ndjson.")
        if self.kind == "audio_wav" and suffix != ".wav":
            raise ValueError("audio_wav assets must use .wav.")
        if self.kind == "audio_flac" and suffix != ".flac":
            raise ValueError("audio_flac assets must use .flac.")
        _require_sha256(self.sha256, "AssetRecord.sha256")


@dataclass(frozen=True, slots=True, kw_only=True)
class ShardRecord:
    """Episode-to-asset join with an explicit publication state."""

    shard_id: str
    episode_ids: tuple[str, ...]
    assets: tuple[AssetRecord, ...]
    completion_state: str

    def __post_init__(self) -> None:
        _require_id(self.shard_id, "ShardRecord.shard_id")
        episode_ids = _unique_id_tuple(
            self.episode_ids,
            "ShardRecord.episode_ids",
            require_non_empty=True,
        )
        assets = tuple(self.assets)
        _require_unique(
            tuple(asset.asset_id for asset in assets),
            "ShardRecord asset ids",
        )
        _require_unique(
            tuple(asset.path for asset in assets),
            "ShardRecord asset paths",
        )
        _require_completion_state(self.completion_state, "ShardRecord")
        if self.completion_state == "complete" and not assets:
            raise ValueError("A complete ShardRecord must contain assets.")
        object.__setattr__(self, "episode_ids", episode_ids)
        object.__setattr__(self, "assets", assets)


@dataclass(frozen=True, slots=True, kw_only=True)
class SplitRecord:
    """Deterministic split assignment expressed in leakage groups."""

    name: str
    group_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.name not in _SPLIT_NAMES:
            raise ValueError(f"SplitRecord.name must be one of {sorted(_SPLIT_NAMES)}.")
        object.__setattr__(
            self,
            "group_ids",
            _unique_id_tuple(self.group_ids, "SplitRecord.group_ids"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CalibrationProfileReference:
    """Portable reference to the profile used for capture."""

    profile_id: str
    profile_version: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _require_id(self.profile_id, "CalibrationProfileReference.profile_id")
        _require_id(
            self.profile_version,
            "CalibrationProfileReference.profile_version",
        )
        _require_relative_path(self.path, "CalibrationProfileReference.path")
        _require_sha256(self.sha256, "CalibrationProfileReference.sha256")


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioDatasetManifest:
    """Portable dataset-level contract independent of package version."""

    dataset_id: str
    creation_timestamp_ms: int
    creation: CreationProvenance
    license: str
    source: str
    runtime_profile: str
    device: DeviceProvenance
    coordinate_convention: str
    coordinate_frames: tuple[str, ...]
    time_base: str
    sample_rate_hz: int
    channel_order: tuple[str, ...]
    units: dict[str, str]
    dtype: str
    episodes: tuple[EpisodeRecord, ...]
    shards: tuple[ShardRecord, ...]
    calibration_profile: CalibrationProfileReference | None
    configuration_sha256: str
    split_grouping_key: str
    splits: tuple[SplitRecord, ...]
    completion_state: str
    schema_version: str = DATASET_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_id(self.dataset_id, "AudioDatasetManifest.dataset_id")
        if self.schema_version != DATASET_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                "AudioDatasetManifest.schema_version must be "
                f"{DATASET_MANIFEST_SCHEMA_VERSION!r}."
            )
        _require_non_negative_int(
            self.creation_timestamp_ms,
            "AudioDatasetManifest.creation_timestamp_ms",
        )
        _require_text(self.license, "AudioDatasetManifest.license")
        _require_text(self.source, "AudioDatasetManifest.source")
        if self.runtime_profile not in RUNTIME_PROFILES:
            raise ValueError(
                "AudioDatasetManifest.runtime_profile must be one of "
                f"{list(RUNTIME_PROFILES)}."
            )
        if self.coordinate_convention != COORDINATE_CONVENTION:
            raise ValueError(
                "AudioDatasetManifest.coordinate_convention must be "
                f"{COORDINATE_CONVENTION!r}."
            )
        frames = _unique_id_tuple(
            self.coordinate_frames,
            "AudioDatasetManifest.coordinate_frames",
            require_non_empty=True,
        )
        if self.time_base not in _TIME_BASES:
            raise ValueError(
                f"AudioDatasetManifest.time_base must be one of {sorted(_TIME_BASES)}."
            )
        if int(self.sample_rate_hz) <= 0:
            raise ValueError("AudioDatasetManifest.sample_rate_hz must be positive.")
        object.__setattr__(self, "sample_rate_hz", int(self.sample_rate_hz))
        channel_order = _unique_id_tuple(
            self.channel_order,
            "AudioDatasetManifest.channel_order",
            require_non_empty=True,
        )
        _require_units(
            self.units,
            DATASET_MANIFEST_UNITS,
            "AudioDatasetManifest.units",
        )
        object.__setattr__(self, "units", dict(self.units))
        if self.dtype not in _DTYPES:
            raise ValueError(
                "AudioDatasetManifest.dtype must be one of " f"{sorted(_DTYPES)}."
            )
        _require_sha256(
            self.configuration_sha256,
            "AudioDatasetManifest.configuration_sha256",
        )
        _require_id(
            self.split_grouping_key,
            "AudioDatasetManifest.split_grouping_key",
        )
        _require_completion_state(self.completion_state, "AudioDatasetManifest")

        episodes = tuple(self.episodes)
        shards = tuple(self.shards)
        splits = tuple(self.splits)
        _require_unique(
            tuple(episode.episode_id for episode in episodes),
            "AudioDatasetManifest episode ids",
        )
        _require_unique(
            tuple(shard.shard_id for shard in shards),
            "AudioDatasetManifest shard ids",
        )
        _require_unique(
            tuple(split.name for split in splits),
            "AudioDatasetManifest split names",
        )
        known_episode_ids = {episode.episode_id for episode in episodes}
        for shard in shards:
            unknown = set(shard.episode_ids) - known_episode_ids
            if unknown:
                raise ValueError(
                    "ShardRecord references unknown episode ids: "
                    f"{sorted(unknown)}."
                )
        all_assets = tuple(asset for shard in shards for asset in shard.assets)
        _require_unique(
            tuple(asset.asset_id for asset in all_assets),
            "AudioDatasetManifest asset ids",
        )
        known_assets = {asset.asset_id for asset in all_assets}
        for episode in episodes:
            unknown = set(episode.visual_sync_asset_ids) - known_assets
            if unknown:
                raise ValueError(
                    "EpisodeRecord references unknown visual sync assets: "
                    f"{sorted(unknown)}."
                )
            for pose in episode.array_poses:
                if pose.frame not in frames:
                    raise ValueError(
                        f"ManifestPose.frame {pose.frame!r} is not a declared "
                        "coordinate frame."
                    )
            for truth in episode.source_truth:
                if truth.pose.frame not in frames:
                    raise ValueError(
                        f"ManifestPose.frame {truth.pose.frame!r} is not a declared "
                        "coordinate frame."
                    )
        known_groups = {episode.split_group for episode in episodes}
        for episode in episodes:
            grouped_value = getattr(episode, self.split_grouping_key, None)
            if grouped_value is not None and episode.split_group != grouped_value:
                raise ValueError(
                    "EpisodeRecord.split_group must match the selected "
                    f"{self.split_grouping_key!r} grouping value."
                )
        assigned_groups: set[str] = set()
        for split in splits:
            unknown = set(split.group_ids) - known_groups
            if unknown:
                raise ValueError(
                    "SplitRecord references unknown groups: " f"{sorted(unknown)}."
                )
            overlap = assigned_groups.intersection(split.group_ids)
            if overlap:
                raise ValueError(
                    "SplitRecord groups must not cross splits: " f"{sorted(overlap)}."
                )
            assigned_groups.update(split.group_ids)
        if self.completion_state == "complete":
            if not episodes or not shards:
                raise ValueError(
                    "A complete AudioDatasetManifest requires episodes and shards."
                )
            incomplete = [
                shard.shard_id
                for shard in shards
                if shard.completion_state != "complete"
            ]
            if incomplete:
                raise ValueError(
                    "A complete AudioDatasetManifest cannot contain incomplete "
                    f"shards: {incomplete}."
                )
        object.__setattr__(self, "coordinate_frames", frames)
        object.__setattr__(self, "channel_order", channel_order)
        object.__setattr__(self, "episodes", episodes)
        object.__setattr__(self, "shards", shards)
        object.__setattr__(self, "splits", splits)


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _require_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be a non-empty stable id using letters, numbers, "
            "'.', '_', ':', or '-'."
        )


def _require_non_negative_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or int(value) != value or int(value) < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")


def _require_range(start: int, end: int, field_name: str) -> None:
    _require_non_negative_int(start, f"{field_name} start")
    _require_non_negative_int(end, f"{field_name} end")
    if end < start:
        raise ValueError(f"{field_name} range must be monotonic.")


def _require_monotonic(values: tuple[int, ...], field_name: str) -> None:
    for value in values:
        _require_non_negative_int(value, field_name)
    if any(
        current < previous
        for previous, current in zip(values, values[1:], strict=False)
    ):
        raise ValueError(f"{field_name} must be non-negative and monotonic.")


def _finite_tuple(values: object, length: int, field_name: str):
    result = tuple(float(value) for value in values)  # type: ignore[union-attr]
    if len(result) != length or not all(math.isfinite(value) for value in result):
        raise ValueError(f"{field_name} must contain {length} finite values.")
    return result


def _require_relative_path(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in posix_path.parts
        or "\\" in value
    ):
        raise ValueError(
            f"{field_name} must be a relative POSIX path without parent traversal."
        )


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be 64 lowercase hexadecimal characters.")


def _require_units(
    units: dict[str, str],
    expected: dict[str, str],
    field_name: str,
) -> None:
    if not isinstance(units, dict) or units != expected:
        raise ValueError(f"{field_name} must use the canonical unit values {expected}.")


def _unique_id_tuple(
    values: object,
    field_name: str,
    *,
    require_non_empty: bool = False,
) -> tuple[str, ...]:
    result = tuple(values)  # type: ignore[arg-type]
    if require_non_empty and not result:
        raise ValueError(f"{field_name} must not be empty.")
    for value in result:
        _require_id(value, field_name)
    _require_unique(result, field_name)
    return result


def _unique_text_tuple(values: object, field_name: str) -> tuple[str, ...]:
    result = tuple(values)  # type: ignore[arg-type]
    for value in result:
        _require_text(value, field_name)
    _require_unique(result, field_name)
    return result


def _require_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates.")


def _require_completion_state(value: str, field_name: str) -> None:
    if value not in _COMPLETION_STATES:
        raise ValueError(
            f"{field_name}.completion_state must be one of "
            f"{sorted(_COMPLETION_STATES)}."
        )


def _validate_pose_timestamps(
    poses: tuple[ManifestPose, ...],
    timestamps: tuple[int, ...],
    field_name: str,
) -> None:
    for pose in poses:
        if pose.timestamp_ms not in timestamps:
            raise ValueError(
                f"EpisodeRecord.{field_name} timestamp is absent from timestamps_ms."
            )
    _require_monotonic(
        tuple(pose.timestamp_ms for pose in poses),
        f"EpisodeRecord.{field_name} timestamps",
    )


def _validate_truth_timestamps(
    truth_records: tuple[SourceTruth, ...],
    timestamps: tuple[int, ...],
) -> None:
    for truth in truth_records:
        if truth.timestamp_ms not in timestamps:
            raise ValueError(
                "EpisodeRecord.source_truth timestamp is absent from timestamps_ms."
            )
    _require_monotonic(
        tuple(truth.timestamp_ms for truth in truth_records),
        "EpisodeRecord.source_truth timestamps",
    )
