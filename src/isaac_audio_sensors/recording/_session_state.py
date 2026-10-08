"""Recorder configuration validation and durable episode state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .manifest import CreationProvenance, ResetMarker, _learning_identities, _require_id

_REQUIRED_CONFIGURATION_KEYS = frozenset(
    {
        "backend_id",
        "channel_order",
        "dataset_id",
        "dtype",
        "hop_sample_count",
        "runtime_profile",
        "sample_rate_hz",
        "session_seed",
        "shard_episode_aligned",
        "shard_max_frames",
        "split_grouping_key",
        "window_sample_count",
    }
)


def validate_configuration(
    configuration: Mapping[str, Any], creation: CreationProvenance
) -> None:
    missing = sorted(_REQUIRED_CONFIGURATION_KEYS - configuration.keys())
    if missing:
        raise ValueError(f"configuration is missing required keys: {missing}")
    if configuration["runtime_profile"] != "waveform_fidelity":
        raise ValueError("unsupported runtime profile for dataset layout v1")
    if configuration["dtype"] != "float32":
        raise ValueError("dataset recorder requires dtype 'float32'")
    for key in (
        "sample_rate_hz",
        "shard_max_frames",
        "window_sample_count",
        "hop_sample_count",
    ):
        value = configuration[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"configuration.{key} must be a positive integer")
    seed = configuration["session_seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("configuration.session_seed must be a non-negative integer")
    if not isinstance(configuration["shard_episode_aligned"], bool):
        raise ValueError("configuration.shard_episode_aligned must be a bool")
    preserve = configuration.get("preserve_time_gaps", False)
    if type(preserve) is not bool:
        raise ValueError("configuration.preserve_time_gaps must be a bool")
    channels = configuration["channel_order"]
    if (
        not isinstance(channels, list)
        or not channels
        or any(not isinstance(value, str) or not value for value in channels)
        or len(set(channels)) != len(channels)
    ):
        raise ValueError("configuration.channel_order must contain unique ids")
    for key in ("dataset_id", "split_grouping_key", "backend_id"):
        if not isinstance(configuration[key], str) or not configuration[key]:
            raise ValueError(f"configuration.{key} must be a non-empty string")
    _require_id(
        configuration.get("session_id", configuration["dataset_id"]),
        "configuration.session_id",
    )
    if creation.backend_id != configuration["backend_id"]:
        raise ValueError("creation.backend_id must match configuration.backend_id")


@dataclass(slots=True)
class _EpisodeState:
    ordinal: int
    scene_id: str
    environment_id: str
    split_group: str
    seed: int
    start_frame: int
    trajectory_id: str | None = None
    source_asset_ids: tuple[str, ...] | None = None
    frame_count: int = 0
    last_timestamp_ms: int | None = None
    timestamps_ms: list[int] = field(default_factory=list)
    first_producer_step: int | None = None
    last_producer_step: int | None = None
    reset_markers: list[ResetMarker] = field(default_factory=list)
    published_frame_count: int = 0
    published_last_step: int | None = None
    ended: bool = False
    end_frame: int | None = None

    def __post_init__(self) -> None:
        self.trajectory_id, self.source_asset_ids = _learning_identities(
            self.trajectory_id, self.source_asset_ids
        )

    def state_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "scene_id": self.scene_id,
            "trajectory_id": self.trajectory_id,
            "source_asset_ids": self.source_asset_ids,
            "environment_id": self.environment_id,
            "split_group": self.split_group,
            "seed": self.seed,
            "start_frame": self.start_frame,
            "frame_count": self.frame_count,
            "last_timestamp_ms": self.last_timestamp_ms,
            "timestamps_ms": list(self.timestamps_ms),
            "first_producer_step": self.first_producer_step,
            "last_producer_step": self.last_producer_step,
            "reset_markers": [
                {
                    "step_index": marker.step_index,
                    "frame_index": marker.frame_index,
                    "timestamp_ms": marker.timestamp_ms,
                }
                for marker in self.reset_markers
            ],
            "published_frame_count": self.published_frame_count,
            "published_last_step": self.published_last_step,
            "ended": self.ended,
            "end_frame": self.end_frame,
        }

    @classmethod
    def from_dict(cls, item: Mapping[str, Any]) -> _EpisodeState:
        return cls(
            ordinal=int(item["ordinal"]),
            scene_id=str(item["scene_id"]),
            trajectory_id=item["trajectory_id"],
            source_asset_ids=item["source_asset_ids"],
            environment_id=str(item["environment_id"]),
            split_group=str(item["split_group"]),
            seed=int(item["seed"]),
            start_frame=int(item["start_frame"]),
            frame_count=int(item.get("frame_count", 0)),
            last_timestamp_ms=(
                None
                if item.get("last_timestamp_ms") is None
                else int(item["last_timestamp_ms"])
            ),
            timestamps_ms=[int(value) for value in item.get("timestamps_ms", ())],
            first_producer_step=(
                None
                if item.get("first_producer_step") is None
                else int(item["first_producer_step"])
            ),
            last_producer_step=(
                None
                if item.get("last_producer_step") is None
                else int(item["last_producer_step"])
            ),
            reset_markers=[
                ResetMarker(
                    step_index=int(marker["step_index"]),
                    frame_index=int(marker["frame_index"]),
                    timestamp_ms=int(marker["timestamp_ms"]),
                )
                for marker in item.get("reset_markers", ())
            ],
            published_frame_count=int(item.get("published_frame_count", 0)),
            published_last_step=(
                None
                if item.get("published_last_step") is None
                else int(item["published_last_step"])
            ),
            ended=bool(item.get("ended", False)),
            end_frame=(
                None if item.get("end_frame") is None else int(item["end_frame"])
            ),
        )
