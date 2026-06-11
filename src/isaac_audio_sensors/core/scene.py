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


def occlusion_per_mic_extra_gain_db(
    occlusion: SourceOcclusion | None,
    mic_ids: tuple[str, ...],
) -> dict[str, float]:
    """Per-microphone extra (negative) gain for one occlusion record.

    Microphones missing from ``per_mic_attenuation_db`` (or all of them when
    the map is absent) fall back to the uniform per-source ``attenuation_db``.
    """

    uniform = occlusion_extra_gain_db(occlusion)
    if occlusion is None or not occlusion.per_mic_attenuation_db:
        return {mic_id: uniform for mic_id in mic_ids}
    return {
        mic_id: -float(occlusion.per_mic_attenuation_db.get(mic_id, -uniform))
        for mic_id in mic_ids
    }


def occlusion_band_attenuation_db(
    occlusion: SourceOcclusion | None,
    mic_id: str,
) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    """Per-band attenuation for one microphone, or None for broadband-only."""

    if (
        occlusion is None
        or not occlusion.band_centers_hz
        or mic_id not in occlusion.per_mic_band_attenuation_db
    ):
        return None
    return (
        occlusion.band_centers_hz,
        occlusion.per_mic_band_attenuation_db[mic_id],
    )


def occlusion_detection_diagnostics(
    occlusion: SourceOcclusion | None,
) -> dict[str, Any]:
    """Additive per-detection diagnostics; empty when occlusion is absent."""

    if occlusion is None:
        return {}
    diagnostics: dict[str, Any] = {
        "occlusion_factor": occlusion.occlusion_factor,
        "attenuation_db": occlusion.attenuation_db,
        "per_mic_blocked": dict(occlusion.per_mic_blocked),
        "hit_prim_paths": list(occlusion.hit_prim_paths),
    }
    if occlusion.per_mic_attenuation_db:
        diagnostics["per_mic_attenuation_db"] = dict(
            occlusion.per_mic_attenuation_db
        )
    if occlusion.per_mic_band_attenuation_db:
        diagnostics["per_mic_band_attenuation_db"] = {
            mic_id: list(bands)
            for mic_id, bands in occlusion.per_mic_band_attenuation_db.items()
        }
        diagnostics["band_centers_hz"] = list(occlusion.band_centers_hz)
    if occlusion.per_mic_hit_prim_paths:
        diagnostics["per_mic_hit_prim_paths"] = {
            mic_id: list(paths)
            for mic_id, paths in occlusion.per_mic_hit_prim_paths.items()
        }
    if occlusion.hit_materials:
        diagnostics["hit_materials"] = dict(occlusion.hit_materials)
    if occlusion.occlusion_model is not None:
        diagnostics["occlusion_model"] = occlusion.occlusion_model
    return {"occlusion": diagnostics}
