"""Pure acoustic environment, material, and occlusion helpers."""

from isaac_audio_sensors.core.acoustics.environments import (
    environment_to_world_point,
    free_field_environment,
    half_space_environment,
    polygon_prism_environment,
    shoebox_environment,
    shoebox_environment_from_bounds,
    surface_set_environment,
    world_to_environment_point,
)
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

__all__ = [
    "LEGACY_MATERIAL_ALIASES",
    "MATERIAL_BAND_CENTERS_HZ",
    "MATERIAL_TABLE",
    "OCCLUDED_FACTOR_THRESHOLD",
    "PYROOMACOUSTICS_MATERIALS_SHA256",
    "PYROOMACOUSTICS_MATERIAL_CITATION",
    "MaterialEntry",
    "MaterialResolution",
    "environment_to_world_point",
    "free_field_environment",
    "half_space_environment",
    "known_material_ids",
    "occlusion_band_attenuation_db",
    "occlusion_detection_diagnostics",
    "occlusion_extra_gain_db",
    "occlusion_flag",
    "occlusion_per_mic_extra_gain_db",
    "polygon_prism_environment",
    "resolve_material",
    "resolve_material_coefficients",
    "shoebox_environment",
    "shoebox_environment_from_bounds",
    "surface_set_environment",
    "world_to_environment_point",
]
