"""Occlusion attenuation, flags, and diagnostics shared by audio backends."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.types import SourceOcclusion

# A detection is flagged occluded once at least half of the direct
# source-to-microphone rays are blocked.
OCCLUDED_FACTOR_THRESHOLD = 0.5


def occlusion_extra_gain_db(occlusion: SourceOcclusion | None) -> float:
    """Extra (negative) gain a backend applies for one occluded source."""

    return 0.0 if occlusion is None else -float(occlusion.attenuation_db)


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


__all__ = [
    "OCCLUDED_FACTOR_THRESHOLD",
    "occlusion_band_attenuation_db",
    "occlusion_detection_diagnostics",
    "occlusion_extra_gain_db",
    "occlusion_flag",
    "occlusion_per_mic_extra_gain_db",
]
