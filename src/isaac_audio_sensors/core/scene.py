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
        source
        for source in scene.sources
        if source.is_active_in(time_window.start_time_s, time_window.end_time_s)
    )


def deterministic_frame_id(
    *,
    backend_id: str,
    stage_id: str,
    array_id: str,
    timestamp_ms: int,
    frame_index: int | None = None,
) -> str:
    """Create a stable frame id for traces and tests."""

    suffix = (
        f"{timestamp_ms}" if frame_index is None else f"{timestamp_ms}_{frame_index}"
    )
    return f"{backend_id}_{stage_id}_{array_id}_{suffix}"


def deterministic_detection_id(
    *,
    frame_id: str,
    source_id: str | None,
    index: int,
) -> str:
    """Create a stable detection id inside a frame."""

    source_component = source_id or "unknown_source"
    return f"{frame_id}_{source_component}_{index:02d}"
