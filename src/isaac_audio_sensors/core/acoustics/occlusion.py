"""Occlusion attenuation, flags, and diagnostics shared by audio backends."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.types import SourceOcclusion

# A detection is flagged occluded once at least half of the direct
# source-to-microphone rays are blocked.
OCCLUDED_FACTOR_THRESHOLD = 0.5


def _occlusion_factor(occlusion: SourceOcclusion | None) -> float:
    if occlusion is None:
        return 0.0
    blocked = tuple(occlusion.per_mic_blocked.values())
    return sum(blocked) / len(blocked)


def occlusion_flag(occlusion: SourceOcclusion | None) -> bool:
    """Detection ``occluded`` flag for one occlusion record."""

    return (
        occlusion is not None
        and _occlusion_factor(occlusion) >= OCCLUDED_FACTOR_THRESHOLD
    )


def occlusion_per_mic_extra_gain_db(
    occlusion: SourceOcclusion | None,
    mic_ids: tuple[str, ...],
) -> dict[str, float]:
    """Per-microphone extra (negative) gain for one occlusion record.

    The record must provide exactly one value for every requested microphone.
    """

    if occlusion is None:
        return {mic_id: 0.0 for mic_id in mic_ids}
    if set(occlusion.per_mic_attenuation_db) != set(mic_ids):
        raise ValueError(
            "SourceOcclusion microphone ids do not match the selected array."
        )
    return {
        mic_id: -float(occlusion.per_mic_attenuation_db[mic_id])
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
        "occlusion_factor": _occlusion_factor(occlusion),
        "per_mic_blocked": dict(occlusion.per_mic_blocked),
        "per_mic_attenuation_db": dict(occlusion.per_mic_attenuation_db),
        "occlusion_model": occlusion.occlusion_model,
    }
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
    return {"occlusion": diagnostics}


__all__ = [
    "OCCLUDED_FACTOR_THRESHOLD",
    "occlusion_band_attenuation_db",
    "occlusion_detection_diagnostics",
    "occlusion_flag",
    "occlusion_per_mic_extra_gain_db",
]
