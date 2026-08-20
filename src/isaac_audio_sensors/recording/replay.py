"""Ordered, read-only replay events built on the checked session loader."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from isaac_audio_sensors.recording.layout import DatasetLayoutError
from isaac_audio_sensors.recording.loader import LoadedFrame, SessionDataset
from isaac_audio_sensors.recording.manifest import EpisodeRecord

ReplayEventKind = Literal["episode_start", "frame", "reset", "episode_end"]


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """One event in the original dataset/episode/reset order."""

    kind: ReplayEventKind
    episode: EpisodeRecord | None = None
    frame: LoadedFrame | None = None
    audio: np.ndarray | None = None
    frame_index: int | None = None
    timestamp_ms: int | None = None
    episode_id: str | None = None


def replay_session(
    session_root: str | Path,
    *,
    with_audio: bool = False,
    allow_incomplete: bool = False,
    verify_checksums: bool = True,
) -> Iterator[ReplayEvent]:
    """Replay a session without creating or modifying anything below its root."""

    if not isinstance(with_audio, bool):
        raise TypeError("with_audio must be a bool.")
    root = Path(session_root)
    before = _session_snapshot(root)
    try:
        dataset = SessionDataset.open(
            root,
            allow_incomplete=allow_incomplete,
            verify_checksums=verify_checksums,
        )
        for episode, frames in dataset.iter_episodes():
            yield ReplayEvent(
                kind="episode_start",
                episode=episode,
                episode_id=episode.episode_id,
            )
            resets = {marker.frame_index: marker for marker in episode.reset_markers}
            previous_timestamp: int | None = None
            frame_count = 0
            for item in frames:
                timestamp = item.frame.timestamp_ms
                if previous_timestamp is not None and timestamp < previous_timestamp:
                    raise DatasetLayoutError(
                        f"session {root} episode {episode.episode_id}: non-monotonic "
                        f"timestamp at frame {item.dataset_frame_index} "
                        f"(shard {item.shard_id} file frames.jsonl line "
                        f"{item.line_number})."
                    )
                previous_timestamp = timestamp
                reset = resets.pop(item.dataset_frame_index, None)
                if reset is not None:
                    if reset.timestamp_ms != timestamp:
                        raise DatasetLayoutError(
                            f"session {root} episode {episode.episode_id}: reset "
                            f"timestamp mismatch at frame {item.dataset_frame_index}."
                        )
                    yield ReplayEvent(
                        kind="reset",
                        frame_index=reset.frame_index,
                        timestamp_ms=reset.timestamp_ms,
                        episode_id=episode.episode_id,
                    )
                audio = dataset.read_frame_audio(item) if with_audio else None
                yield ReplayEvent(
                    kind="frame",
                    frame=item,
                    audio=audio,
                    frame_index=item.dataset_frame_index,
                    timestamp_ms=timestamp,
                    episode_id=episode.episode_id,
                )
                frame_count += 1
            expected_count = episode.end_frame - episode.start_frame + 1
            if frame_count != expected_count:
                raise DatasetLayoutError(
                    f"session {root} episode {episode.episode_id}: replayed "
                    f"{frame_count} frames; expected {expected_count} at frame "
                    f"{episode.start_frame + frame_count}."
                )
            if resets:
                first = min(resets)
                raise DatasetLayoutError(
                    f"session {root} episode {episode.episode_id}: reset marker "
                    f"has no record at frame {first}."
                )
            yield ReplayEvent(kind="episode_end", episode_id=episode.episode_id)
    finally:
        after = _session_snapshot(root)
        if after != before:
            raise DatasetLayoutError(
                f"session {root}: replay modified the session directory inventory "
                "or mtimes."
            )


def _session_snapshot(root: Path) -> tuple[tuple[str, str, int, int], ...]:
    if not root.exists():
        return ()
    paths = (root, *sorted(root.rglob("*"), key=lambda item: item.as_posix()))
    result: list[tuple[str, str, int, int]] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError as exc:
            raise DatasetLayoutError(
                f"session {root}: cannot inspect read-only replay inventory: {exc}"
            ) from exc
        relative = "." if path == root else path.relative_to(root).as_posix()
        result.append(
            (
                relative,
                "dir" if path.is_dir() else "file",
                stat.st_size,
                stat.st_mtime_ns,
            )
        )
    return tuple(result)


__all__ = ["ReplayEvent", "ReplayEventKind", "replay_session"]
