"""Scene helpers shared by backends and CLI commands."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    SourceOcclusion,
)

# A detection is flagged occluded once at least half of the direct
# source-to-microphone rays are blocked.
OCCLUDED_FACTOR_THRESHOLD = 0.5


def active_sources(
    scene: AudioSceneSnapshot,
    time_window: AudioTimeWindow,
) -> tuple[AudioSourceSpec, ...]:
    """Return sources overlapping a half-open simulation window."""

    active = sorted(
        (
            source
            for source in scene.sources
            if source.is_active_in(time_window.start_time_s, time_window.end_time_s)
        ),
        key=lambda source: (source.start_time_s, source.source_id, source.prim_path),
    )
    if time_window.max_events is not None:
        active = active[: time_window.max_events]
    return tuple(active)


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


def deterministic_frame_name(
    *,
    backend_id: str,
    stage_id: str,
    array_id: str,
    timestamp_ms: int,
    frame_index: int | None = None,
) -> str:
    """Create a human-readable stable frame name for trace displays."""

    suffix = (
        f"t{timestamp_ms}ms"
        if frame_index is None
        else f"frame{frame_index}_t{timestamp_ms}ms"
    )
    return f"{stage_id}/{array_id}/{backend_id}/{suffix}"


def deterministic_detection_id(
    *,
    frame_id: str,
    source_id: str | None,
    index: int,
) -> str:
    """Create a stable detection id inside a frame."""

    source_component = source_id or "unknown_source"
    return f"{frame_id}_{source_component}_{index:02d}"


def occlusion_extra_gain_db(occlusion: SourceOcclusion | None) -> float:
    """Extra (negative) gain a backend applies for one occluded source."""

    return 0.0 if occlusion is None else -float(occlusion.attenuation_db)


def occlusion_amplitude_scale(occlusion: SourceOcclusion | None) -> float:
    """Linear amplitude scale equivalent of ``occlusion_extra_gain_db``."""

    return 10.0 ** (occlusion_extra_gain_db(occlusion) / 20.0)


def occlusion_flag(occlusion: SourceOcclusion | None) -> bool:
    """Detection ``occluded`` flag for one occlusion record."""

    return (
        occlusion is not None
        and occlusion.occlusion_factor >= OCCLUDED_FACTOR_THRESHOLD
    )


def occlusion_detection_diagnostics(
    occlusion: SourceOcclusion | None,
) -> dict[str, Any]:
    """Additive per-detection diagnostics; empty when occlusion is absent."""

    if occlusion is None:
        return {}
    return {
        "occlusion": {
            "occlusion_factor": occlusion.occlusion_factor,
            "attenuation_db": occlusion.attenuation_db,
            "per_mic_blocked": dict(occlusion.per_mic_blocked),
            "hit_prim_paths": list(occlusion.hit_prim_paths),
        }
    }
