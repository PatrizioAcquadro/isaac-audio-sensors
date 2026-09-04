"""Ordered, read-only replay events built on the checked session loader."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

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
        for item in frames:
            timestamp = item.frame.timestamp_ms
            reset = resets.get(item.dataset_frame_index)
            if reset is not None:
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
        yield ReplayEvent(kind="episode_end", episode_id=episode.episode_id)


__all__ = ["ReplayEvent", "replay_session"]
