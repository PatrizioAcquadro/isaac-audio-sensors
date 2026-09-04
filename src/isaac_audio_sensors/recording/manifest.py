"""Public dataset-manifest v4 dataclasses and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    RUNTIME_PROFILES,
)
from isaac_audio_sensors.recording.constants import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_MANIFEST_UNITS,
)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMPLETION_STATES = frozenset({"incomplete", "complete"})
_ASSET_KINDS = frozenset({"frame_trace_jsonl", "audio_wav", "audio_flac"})
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
    """Ranges, identities, and synchronization data for one episode."""

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
    trajectory_id: str | None = None
    source_asset_ids: tuple[str, ...] | None = None
    reset_markers: tuple[ResetMarker, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("episode_id", "scene_id", "environment_id", "split_group"):
            _require_id(getattr(self, name), f"EpisodeRecord.{name}")
        trajectory_id, source_asset_ids = _learning_identities(
            self.trajectory_id, self.source_asset_ids
        )
        object.__setattr__(self, "trajectory_id", trajectory_id)
        object.__setattr__(self, "source_asset_ids", source_asset_ids)
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
    session_id: str
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
        _require_id(self.session_id, "AudioDatasetManifest.session_id")
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
                f"AudioDatasetManifest.dtype must be one of {sorted(_DTYPES)}."
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
                    f"ShardRecord references unknown episode ids: {sorted(unknown)}."
                )
        all_assets = tuple(asset for shard in shards for asset in shard.assets)
        _require_unique(
            tuple(asset.asset_id for asset in all_assets),
            "AudioDatasetManifest asset ids",
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
                    f"SplitRecord references unknown groups: {sorted(unknown)}."
                )
            overlap = assigned_groups.intersection(split.group_ids)
            if overlap:
                raise ValueError(
                    f"SplitRecord groups must not cross splits: {sorted(overlap)}."
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


def _learning_identities(
    trajectory_id: str | None, source_asset_ids: object
) -> tuple[str | None, tuple[str, ...] | None]:
    if trajectory_id is not None:
        _require_id(trajectory_id, "trajectory_id")
    assets = None
    if source_asset_ids is not None:
        if not isinstance(source_asset_ids, (list, tuple)):
            raise ValueError("source_asset_ids must be a sequence of ids or None.")
        assets = _unique_id_tuple(source_asset_ids, "source_asset_ids")
    return trajectory_id, assets


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


def _require_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates.")


def _require_completion_state(value: str, field_name: str) -> None:
    if value not in _COMPLETION_STATES:
        raise ValueError(
            f"{field_name}.completion_state must be one of "
            f"{sorted(_COMPLETION_STATES)}."
        )
