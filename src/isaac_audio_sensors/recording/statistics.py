"""Deterministic, bounded statistics for validated dataset sessions."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.recording.loader import LoadedFrame
from isaac_audio_sensors.recording.manifest import (
    AudioDatasetManifest,
    ShardRecord,
)


@dataclass(frozen=True, slots=True)
class Statistics:
    """Statistics accumulated without retaining dataset frame records."""

    episode_count: int
    shard_count: int
    frame_count: int
    observation_count: int
    audio_sample_count: int
    attributed_audio_sample_count: int
    tail_audio_sample_count: int
    audio_duration_seconds: float
    audio_duration_seconds_by_shard: tuple[tuple[str, float], ...]
    episode_frame_counts: tuple[tuple[str, int], ...]
    episode_timestamp_spans_ms: tuple[tuple[str, int], ...]
    label_counts: tuple[tuple[str, int], ...]
    audio_ranges_nonempty: int
    audio_ranges_empty: int
    frames_with_observations: int
    frames_with_waveform_paths: int
    waveform_path_count: int
    visual_sync_count: int
    frames_without_observations: int
    channel_count: int
    sample_rate_hz: int
    observed_channel_counts: tuple[int, ...]
    observed_sample_rates_hz: tuple[int, ...]
    channel_count_consistent: bool
    sample_rate_consistent: bool
    dropped_frame_count: int
    bytes_by_asset_kind: tuple[tuple[str, int], ...]
    verified_shard_count: int
    skipped_shard_count: int
    verified_asset_count: int

    @classmethod
    def empty(cls) -> Statistics:
        """Return the deterministic empty value used for fatal open failures."""

        return cls(
            episode_count=0,
            shard_count=0,
            frame_count=0,
            observation_count=0,
            audio_sample_count=0,
            attributed_audio_sample_count=0,
            tail_audio_sample_count=0,
            audio_duration_seconds=0.0,
            audio_duration_seconds_by_shard=(),
            episode_frame_counts=(),
            episode_timestamp_spans_ms=(),
            label_counts=(),
            audio_ranges_nonempty=0,
            audio_ranges_empty=0,
            frames_with_observations=0,
            frames_with_waveform_paths=0,
            waveform_path_count=0,
            visual_sync_count=0,
            frames_without_observations=0,
            channel_count=0,
            sample_rate_hz=0,
            observed_channel_counts=(),
            observed_sample_rates_hz=(),
            channel_count_consistent=False,
            sample_rate_consistent=False,
            dropped_frame_count=0,
            bytes_by_asset_kind=(),
            verified_shard_count=0,
            skipped_shard_count=0,
            verified_asset_count=0,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable statistics schema."""

        return {
            "asset_bytes": dict(self.bytes_by_asset_kind),
            "audio": {
                "attributed_sample_count": self.attributed_audio_sample_count,
                "duration_seconds_by_shard": dict(self.audio_duration_seconds_by_shard),
                "sample_count": self.audio_sample_count,
                "tail_sample_count": self.tail_audio_sample_count,
                "total_duration_seconds": self.audio_duration_seconds,
            },
            "consistency": {
                "channel_count": self.channel_count,
                "channel_count_consistent": self.channel_count_consistent,
                "observed_channel_counts": list(self.observed_channel_counts),
                "observed_sample_rates_hz": list(self.observed_sample_rates_hz),
                "sample_rate_consistent": self.sample_rate_consistent,
                "sample_rate_hz": self.sample_rate_hz,
            },
            "counts": {
                "observations": self.observation_count,
                "episodes": self.episode_count,
                "frames": self.frame_count,
                "shards": self.shard_count,
            },
            "dropped_frames": {"total": self.dropped_frame_count},
            "episodes": {
                episode_id: {
                    "frame_count": frame_count,
                    "timestamp_span_ms": dict(self.episode_timestamp_spans_ms)[
                        episode_id
                    ],
                }
                for episode_id, frame_count in self.episode_frame_counts
            },
            "integrity": {
                "skipped_shards": self.skipped_shard_count,
                "verified_assets": self.verified_asset_count,
                "verified_shards": self.verified_shard_count,
            },
            "labels": dict(self.label_counts),
            "missingness": {
                "frames_with_empty_audio_range": self.audio_ranges_empty,
                "frames_without_observations": self.frames_without_observations,
            },
            "modalities": {
                "audio_ranges_empty": self.audio_ranges_empty,
                "audio_ranges_nonempty": self.audio_ranges_nonempty,
                "frames_with_observations": self.frames_with_observations,
                "frames_with_waveform_paths": self.frames_with_waveform_paths,
                "visual_sync_count": self.visual_sync_count,
                "waveform_path_count": self.waveform_path_count,
            },
        }


class StatisticsBuilder:
    """Mutable O(episodes + shards + vocabulary) validation accumulator."""

    def __init__(self, manifest: AudioDatasetManifest) -> None:
        self._manifest = manifest
        self._frame_count = 0
        self._observation_count = 0
        self._audio_sample_count = 0
        self._attributed_audio_sample_count = 0
        self._tail_audio_sample_count = 0
        self._audio_duration_by_shard: dict[str, float] = {}
        self._episode_frame_counts: Counter[str] = Counter()
        self._episode_first_timestamp: dict[str, int] = {}
        self._episode_last_timestamp: dict[str, int] = {}
        self._labels: Counter[str] = Counter()
        self._audio_ranges_nonempty = 0
        self._audio_ranges_empty = 0
        self._frames_with_observations = 0
        self._frames_with_waveform_paths = 0
        self._waveform_path_count = 0
        self._visual_sync_count = 0
        self._frames_without_observations = 0
        self._observed_channel_counts: set[int] = set()
        self._observed_sample_rates: set[int] = set()
        self._dropped_frame_count = 0
        self._bytes_by_asset_kind: Counter[str] = Counter()
        self._verified_shards = 0
        self._skipped_shards = 0
        self._verified_assets = 0
        for episode in manifest.episodes:
            for label in episode.labels:
                self._labels[label] += 1
            self._visual_sync_count += len(episode.visual_sync_asset_ids)

    def add_verified_shard(self, shard: ShardRecord, marker: Mapping[str, Any]) -> None:
        """Add verified marker/header and asset-size facts."""

        audio = marker["audio"]
        sample_count = audio["sample_count"]
        tail_count = marker["tail_samples"]
        self._verified_shards += 1
        self._verified_assets += len(marker["files"])
        self._audio_sample_count += sample_count
        self._tail_audio_sample_count += tail_count
        self._attributed_audio_sample_count += sample_count - tail_count
        self._audio_duration_by_shard[shard.shard_id] = (
            sample_count / audio["sample_rate_hz"]
        )
        self._observed_channel_counts.add(audio["channels"])
        self._observed_sample_rates.add(audio["sample_rate_hz"])
        bytes_by_name = {entry["path"]: entry["bytes"] for entry in marker["files"]}
        for asset in shard.assets:
            name = asset.path.rsplit("/", 1)[-1]
            if name in bytes_by_name:
                self._bytes_by_asset_kind[asset.kind] += bytes_by_name[name]
        self._dropped_frame_count += marker["dropped_frames"]["count"]

    def add_skipped_shard(self) -> None:
        """Record one shard omitted after a verification failure."""

        self._skipped_shards += 1

    def add_frame(self, item: LoadedFrame) -> None:
        """Accumulate one streamed frame and release it immediately."""

        frame = item.frame
        self._frame_count += 1
        self._episode_frame_counts[item.episode_id] += 1
        self._episode_first_timestamp.setdefault(item.episode_id, frame.timestamp_ms)
        self._episode_last_timestamp[item.episode_id] = frame.timestamp_ms
        self._observed_sample_rates.add(frame.sample_rate_hz)
        if item.audio_start_sample == item.audio_end_sample:
            self._audio_ranges_empty += 1
        else:
            self._audio_ranges_nonempty += 1
        waveform_count = len(frame.waveform_paths)
        if waveform_count:
            self._frames_with_waveform_paths += 1
            self._waveform_path_count += waveform_count
        observations = frame.observations
        if observations:
            self._frames_with_observations += 1
        else:
            self._frames_without_observations += 1
        self._observation_count += len(observations)

    def finish(self) -> Statistics:
        """Freeze the accumulator into deterministic sorted tuples."""

        episode_counts = tuple(
            (episode.episode_id, self._episode_frame_counts[episode.episode_id])
            for episode in self._manifest.episodes
        )
        timestamp_spans = tuple(
            (
                episode.episode_id,
                self._episode_last_timestamp.get(episode.episode_id, 0)
                - self._episode_first_timestamp.get(episode.episode_id, 0),
            )
            for episode in self._manifest.episodes
        )
        channel_count = len(self._manifest.channel_order)
        sample_rate = self._manifest.sample_rate_hz
        observed_channels = tuple(sorted(self._observed_channel_counts))
        observed_rates = tuple(sorted(self._observed_sample_rates))
        complete_integrity = self._skipped_shards == 0
        return Statistics(
            episode_count=len(self._manifest.episodes),
            shard_count=len(self._manifest.shards),
            frame_count=self._frame_count,
            observation_count=self._observation_count,
            audio_sample_count=self._audio_sample_count,
            attributed_audio_sample_count=self._attributed_audio_sample_count,
            tail_audio_sample_count=self._tail_audio_sample_count,
            audio_duration_seconds=sum(self._audio_duration_by_shard.values()),
            audio_duration_seconds_by_shard=tuple(
                sorted(self._audio_duration_by_shard.items())
            ),
            episode_frame_counts=episode_counts,
            episode_timestamp_spans_ms=timestamp_spans,
            label_counts=tuple(sorted(self._labels.items())),
            audio_ranges_nonempty=self._audio_ranges_nonempty,
            audio_ranges_empty=self._audio_ranges_empty,
            frames_with_observations=self._frames_with_observations,
            frames_with_waveform_paths=self._frames_with_waveform_paths,
            waveform_path_count=self._waveform_path_count,
            visual_sync_count=self._visual_sync_count,
            frames_without_observations=self._frames_without_observations,
            channel_count=channel_count,
            sample_rate_hz=sample_rate,
            observed_channel_counts=observed_channels,
            observed_sample_rates_hz=observed_rates,
            channel_count_consistent=(
                complete_integrity
                and all(value == channel_count for value in observed_channels)
            ),
            sample_rate_consistent=(
                complete_integrity
                and all(value == sample_rate for value in observed_rates)
            ),
            dropped_frame_count=self._dropped_frame_count,
            bytes_by_asset_kind=tuple(sorted(self._bytes_by_asset_kind.items())),
            verified_shard_count=self._verified_shards,
            skipped_shard_count=self._skipped_shards,
            verified_asset_count=self._verified_assets,
        )


__all__ = ["Statistics"]
