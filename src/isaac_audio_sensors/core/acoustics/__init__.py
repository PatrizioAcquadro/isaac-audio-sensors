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
    validate_material_table,
)

__all__ = [
    "LEGACY_MATERIAL_ALIASES",
    "MATERIAL_BAND_CENTERS_HZ",
    "MATERIAL_TABLE",
    "PYROOMACOUSTICS_MATERIALS_SHA256",
    "PYROOMACOUSTICS_MATERIAL_CITATION",
    "MaterialEntry",
    "MaterialResolution",
    "known_material_ids",
    "resolve_material",
    "resolve_material_coefficients",
    "validate_material_table",
]
