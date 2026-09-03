"""Scene helpers shared by backends and CLI commands."""

from __future__ import annotations

from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)


def active_sources(
    scene: AudioSceneSnapshot,
    time_window: AudioTimeWindow,
) -> tuple[AudioSourceSpec, ...]:
    """Return sources overlapping a half-open simulation window."""

    return tuple(
        sorted(
            (
                source
                for source in scene.sources
                if source.is_active_in(
                    time_window.start_time_s,
                    time_window.end_time_s,
                )
            ),
            key=lambda source: (source.start_time_s, source.source_id),
        )
    )


def timestamp_ms_from_start_time(start_time_s: float) -> int:
    """Return the canonical integer-millisecond frame timestamp."""

    return int(round(start_time_s * 1000.0))


def deterministic_frame_id(
    *,
    backend_id: str,
    stage_id: str,
    array_id: str,
    start_time_s: float,
    frame_index: int,
) -> str:
    """Create a stable frame id for traces and tests."""

    timestamp_ms = timestamp_ms_from_start_time(start_time_s)
    return f"{backend_id}_{stage_id}_{array_id}_{timestamp_ms}_{frame_index}"


def deterministic_frame_name(
    *,
    backend_id: str,
    stage_id: str,
    array_id: str,
    start_time_s: float,
    frame_index: int,
) -> str:
    """Create a human-readable stable frame name for trace displays."""

    timestamp_ms = timestamp_ms_from_start_time(start_time_s)
    return f"{stage_id}/{array_id}/{backend_id}/frame{frame_index}_t{timestamp_ms}ms"
