"""Occlusion attenuation shared by audio backends."""

from __future__ import annotations

from isaac_audio_sensors.core.types import SourceOcclusion


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
__all__ = [
    "occlusion_band_attenuation_db",
    "occlusion_per_mic_extra_gain_db",
]
