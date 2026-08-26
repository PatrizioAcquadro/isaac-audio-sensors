"""Pure acoustic material definitions and resolution helpers."""

from isaac_audio_sensors.core.acoustics.materials import (
    LEGACY_MATERIAL_ALIASES,
    MATERIAL_BAND_CENTERS_HZ,
    MATERIAL_TABLE,
    PYROOMACOUSTICS_MATERIAL_CITATION,
    PYROOMACOUSTICS_MATERIALS_SHA256,
    MaterialEntry,
    MaterialResolution,
    known_material_ids,
    resolve_material,
    resolve_material_coefficients,
)
from isaac_audio_sensors.core.acoustics.occlusion import (
    OCCLUDED_FACTOR_THRESHOLD,
    occlusion_band_attenuation_db,
    occlusion_detection_diagnostics,
    occlusion_extra_gain_db,
    occlusion_flag,
    occlusion_per_mic_extra_gain_db,
)
from isaac_audio_sensors.core.acoustics.rooms import room_spec_from_bounds

__all__ = [
    "LEGACY_MATERIAL_ALIASES",
    "MATERIAL_BAND_CENTERS_HZ",
    "MATERIAL_TABLE",
    "OCCLUDED_FACTOR_THRESHOLD",
    "PYROOMACOUSTICS_MATERIALS_SHA256",
    "PYROOMACOUSTICS_MATERIAL_CITATION",
    "MaterialEntry",
    "MaterialResolution",
    "known_material_ids",
    "occlusion_band_attenuation_db",
    "occlusion_detection_diagnostics",
    "occlusion_extra_gain_db",
    "occlusion_flag",
    "occlusion_per_mic_extra_gain_db",
    "resolve_material",
    "resolve_material_coefficients",
    "room_spec_from_bounds",
]
