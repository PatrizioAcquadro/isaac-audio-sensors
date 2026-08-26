"""Internal deterministic episode and shard planning."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from isaac_audio_sensors.recording._records import (
    _require_non_negative_int,
    _require_positive_int,
)

ID_LIMIT = 100_000


@dataclass(frozen=True, slots=True)
class ShardBoundary:
    """A deterministic half-open output shard boundary."""

    shard_id: str
    shard_ordinal: int
    start_frame: int
    frame_count: int
    episode_ids: tuple[str, ...]
    split_groups: tuple[str, ...]
    exclusive_oversized_episode: bool


def episode_id(ordinal: int) -> str:
    """Derive the fixed-width episode id for ``ordinal``."""

    return _ordinal_id("episode", ordinal)


def shard_id(ordinal: int) -> str:
    """Derive the fixed-width shard id for ``ordinal``."""

    return _ordinal_id("shard", ordinal)


def _ordinal_id(prefix: str, ordinal: int) -> str:
    _require_non_negative_int(ordinal, f"{prefix} ordinal")
    if ordinal >= ID_LIMIT:
        raise ValueError(
            f"{prefix} ordinal {ordinal} exceeds the five-digit limit (99999)."
        )
    return f"{prefix}_{ordinal:05d}"


class ShardPlanner:
    """Incrementally compute deterministic episode and shard boundaries."""

    def __init__(
        self,
        *,
        shard_max_frames: int,
        shard_episode_aligned: bool = True,
    ) -> None:
        _require_positive_int(shard_max_frames, "shard_max_frames")
        if not isinstance(shard_episode_aligned, bool):
            raise ValueError("shard_episode_aligned must be a bool.")
        self.shard_max_frames = shard_max_frames
        self.shard_episode_aligned = shard_episode_aligned
        self._next_episode_ordinal = 0
        self._current_episode_ordinal: int | None = None
        self._current_split_group: str | None = None
        self._current_episode_frames = 0
        self._buffer_start = 0
        self._buffer_frames = 0
        self._episode_oversized = False
        self._open_start = 0
        self._open_frames = 0
        self._open_episode_ids: list[str] = []
        self._open_split_groups: list[str] = []
        self._next_dataset_frame = 0
        self._next_shard_ordinal = 0
        self._finished = False

    def feed_frame(
        self,
        episode_ordinal: int,
        split_group: str,
    ) -> tuple[ShardBoundary, ...]:
        """Feed one written frame and return newly finalized boundaries."""

        if self._finished:
            raise RuntimeError("ShardPlanner is already finished.")
        self._start_or_validate_episode(episode_ordinal, split_group)
        self._current_episode_frames += 1
        emitted: list[ShardBoundary] = []
        if self.shard_episode_aligned:
            if self._buffer_frames == 0:
                self._buffer_start = self._next_dataset_frame
            self._buffer_frames += 1
            self._next_dataset_frame += 1
            if self._buffer_frames == self.shard_max_frames:
                if self._open_frames:
                    emitted.append(self._emit_open(exclusive=False))
                emitted.append(
                    self._emit_range(
                        start_frame=self._buffer_start,
                        frame_count=self._buffer_frames,
                        episode_ids=(episode_id(episode_ordinal),),
                        split_groups=(split_group,),
                        exclusive=True,
                    )
                )
                self._buffer_frames = 0
                self._episode_oversized = True
        else:
            if self._open_frames == 0:
                self._open_start = self._next_dataset_frame
            current_id = episode_id(episode_ordinal)
            if current_id not in self._open_episode_ids:
                self._open_episode_ids.append(current_id)
            if split_group not in self._open_split_groups:
                self._open_split_groups.append(split_group)
            self._open_frames += 1
            self._next_dataset_frame += 1
            if self._open_frames == self.shard_max_frames:
                emitted.append(self._emit_open(exclusive=False))
        return tuple(emitted)

    def end_episode(self, episode_ordinal: int) -> tuple[ShardBoundary, ...]:
        """End the current non-empty episode and return finalized boundaries."""

        if self._current_episode_ordinal is None:
            raise ValueError("No episode is open.")
        if episode_ordinal != self._current_episode_ordinal:
            raise ValueError(
                f"Cannot end episode {episode_ordinal}; episode "
                f"{self._current_episode_ordinal} is open."
            )
        if self._current_episode_frames == 0:
            raise ValueError(f"Episode {episode_id(episode_ordinal)} has no frames.")
        emitted: list[ShardBoundary] = []
        if self.shard_episode_aligned:
            assert self._current_split_group is not None
            if self._episode_oversized:
                if self._buffer_frames:
                    emitted.append(
                        self._emit_range(
                            start_frame=self._buffer_start,
                            frame_count=self._buffer_frames,
                            episode_ids=(episode_id(episode_ordinal),),
                            split_groups=(self._current_split_group,),
                            exclusive=True,
                        )
                    )
                    self._buffer_frames = 0
            else:
                if self._open_frames and (
                    self._open_frames + self._buffer_frames > self.shard_max_frames
                    or self._current_split_group not in self._open_split_groups
                ):
                    emitted.append(self._emit_open(exclusive=False))
                if self._open_frames == 0:
                    self._open_start = self._buffer_start
                self._open_frames += self._buffer_frames
                self._open_episode_ids.append(episode_id(episode_ordinal))
                if self._current_split_group not in self._open_split_groups:
                    self._open_split_groups.append(self._current_split_group)
                self._buffer_frames = 0
        self._current_episode_ordinal = None
        self._current_split_group = None
        self._current_episode_frames = 0
        self._episode_oversized = False
        self._next_episode_ordinal += 1
        return tuple(emitted)

    def finish(self) -> tuple[ShardBoundary, ...]:
        """Finish the stream, rejecting an unterminated episode."""

        if self._finished:
            return ()
        if self._current_episode_ordinal is not None:
            raise ValueError(
                f"Episode {episode_id(self._current_episode_ordinal)} is still open."
            )
        self._finished = True
        if self._open_frames:
            return (self._emit_open(exclusive=False),)
        return ()

    def _start_or_validate_episode(
        self, episode_ordinal: int, split_group: str
    ) -> None:
        _require_non_negative_int(episode_ordinal, "episode ordinal")
        episode_id(episode_ordinal)
        if not isinstance(split_group, str) or not split_group:
            raise ValueError("split_group must be a non-empty string.")
        if self._current_episode_ordinal is None:
            if episode_ordinal != self._next_episode_ordinal:
                raise ValueError(
                    "Episodes must be fed in contiguous ordinal order; expected "
                    f"{self._next_episode_ordinal}, got {episode_ordinal}."
                )
            self._current_episode_ordinal = episode_ordinal
            self._current_split_group = split_group
        elif (
            episode_ordinal != self._current_episode_ordinal
            or split_group != self._current_split_group
        ):
            raise ValueError("End the current episode before feeding another one.")

    def _emit_open(self, *, exclusive: bool) -> ShardBoundary:
        result = self._emit_range(
            start_frame=self._open_start,
            frame_count=self._open_frames,
            episode_ids=tuple(self._open_episode_ids),
            split_groups=tuple(self._open_split_groups),
            exclusive=exclusive,
        )
        self._open_frames = 0
        self._open_episode_ids.clear()
        self._open_split_groups.clear()
        return result

    def _emit_range(
        self,
        *,
        start_frame: int,
        frame_count: int,
        episode_ids: tuple[str, ...],
        split_groups: tuple[str, ...],
        exclusive: bool,
    ) -> ShardBoundary:
        if frame_count <= 0:
            raise AssertionError("Internal error: attempted to emit an empty shard.")
        result = ShardBoundary(
            shard_id=shard_id(self._next_shard_ordinal),
            shard_ordinal=self._next_shard_ordinal,
            start_frame=start_frame,
            frame_count=frame_count,
            episode_ids=episode_ids,
            split_groups=split_groups,
            exclusive_oversized_episode=exclusive,
        )
        self._next_shard_ordinal += 1
        return result


def episode_seed(dataset_id: str, session_seed: int, n: int) -> int:
    """Derive the reproducible 63-bit episode seed."""

    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError("dataset_id must be a non-empty string.")
    _require_non_negative_int(session_seed, "session_seed")
    _require_non_negative_int(n, "episode ordinal")
    digest = hashlib.sha256(f"{dataset_id}:{session_seed}:{n}".encode()).digest()[:8]
    return int.from_bytes(digest, "big") >> 1


__all__: list[str] = []
