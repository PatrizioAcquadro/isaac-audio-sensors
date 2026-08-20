"""Tests for the public acoustic fidelity ladder metadata."""

from __future__ import annotations

import importlib

import pytest

import isaac_audio_sensors
from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.constants import KNOWN_BACKENDS
from isaac_audio_sensors.core.fidelity import (
    ACOUSTIC_FIDELITY_LADDER,
    AcousticFidelityLevel,
    AcousticFidelityMetadata,
    fidelity_level_for_backend,
)


def test_ladder_exposes_exact_five_v1_levels_in_order():
    assert tuple(item.level for item in ACOUSTIC_FIDELITY_LADDER) == (
        AcousticFidelityLevel.L0,
        AcousticFidelityLevel.L1,
        AcousticFidelityLevel.L2,
        AcousticFidelityLevel.L3,
        AcousticFidelityLevel.L4,
    )
    assert tuple(item.public_name for item in ACOUSTIC_FIDELITY_LADDER) == (
        "geometry_only",
        "tdoa_synthetic",
        "room_acoustics",
        "advanced_realism",
        "sim_real_calibration",
    )
    assert all(
        isinstance(item, AcousticFidelityMetadata) for item in ACOUSTIC_FIDELITY_LADDER
    )


def test_implemented_l0_l1_l2_map_to_stable_backend_ids():
    by_level = _ladder_by_level()

    assert by_level[AcousticFidelityLevel.L0].lifecycle_status == "stable_v1"
    assert by_level[AcousticFidelityLevel.L1].lifecycle_status == "stable_v1"
    assert (
        by_level[AcousticFidelityLevel.L2].lifecycle_status
        == "supported_optional_v1"
    )

    assert by_level[AcousticFidelityLevel.L0].backend_ids == ("geometry_only",)
    assert by_level[AcousticFidelityLevel.L1].backend_ids == ("tdoa_synthetic",)
    assert by_level[AcousticFidelityLevel.L2].backend_ids == (
        "room_acoustics",
        "room_acoustics_srp",
    )
    assert by_level[AcousticFidelityLevel.L2].optional_dependencies == (
        "room",
        "pyroomacoustics",
        "scipy",
        "soundfile",
    )

    assert frozenset(
        {"geometry_only", "tdoa_synthetic", "room_acoustics", "room_acoustics_srp"}
    ) == KNOWN_BACKENDS
    for backend_id in KNOWN_BACKENDS:
        metadata = fidelity_level_for_backend(backend_id)
        assert backend_id in metadata.backend_ids
        assert metadata.runtime_selectable_v1 is True
        assert "AudioSensorFrame v1" in metadata.frame_contract


def test_l3_l4_are_metadata_only_not_runtime_backends():
    by_level = _ladder_by_level()

    l3 = by_level[AcousticFidelityLevel.L3]
    l4 = by_level[AcousticFidelityLevel.L4]
    assert l3.lifecycle_status == "provisional_v1"
    assert l4.lifecycle_status == "experimental_tooling_v1"
    assert l3.backend_ids == ()
    assert l4.backend_ids == ()
    assert l3.runtime_selectable_v1 is False
    assert l4.runtime_selectable_v1 is False

    for future_family in (l3.backend_family, l4.backend_family):
        assert future_family not in KNOWN_BACKENDS
        with pytest.raises(ValueError, match="Unknown implemented v1 audio backend"):
            fidelity_level_for_backend(future_family)
        with pytest.raises(ValueError, match="Unknown audio simulation backend"):
            get_backend(future_family)


def test_public_ladder_imports_are_import_safe_core_api():
    core = importlib.import_module("isaac_audio_sensors.core")
    fidelity = importlib.import_module("isaac_audio_sensors.core.fidelity")

    assert isaac_audio_sensors.ACOUSTIC_FIDELITY_LADDER is ACOUSTIC_FIDELITY_LADDER
    assert core.ACOUSTIC_FIDELITY_LADDER is ACOUSTIC_FIDELITY_LADDER
    assert fidelity.ACOUSTIC_FIDELITY_LADDER is ACOUSTIC_FIDELITY_LADDER
    assert (
        isaac_audio_sensors.fidelity_level_for_backend("geometry_only")
        is fidelity_level_for_backend("geometry_only")
    )



def _ladder_by_level() -> dict[AcousticFidelityLevel, AcousticFidelityMetadata]:
    return {item.level: item for item in ACOUSTIC_FIDELITY_LADDER}
