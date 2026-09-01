from __future__ import annotations

import pytest

from isaac_audio_sensors.core.fidelity import (
    ACOUSTIC_FIDELITY_LADDER,
    AcousticFidelityLevel,
    AcousticFidelityMetadata,
    fidelity_level_for_backend,
)


def test_ladder_exposes_current_levels_in_order():
    assert tuple(item.level for item in ACOUSTIC_FIDELITY_LADDER) == (
        AcousticFidelityLevel.L2,
        AcousticFidelityLevel.L3,
        AcousticFidelityLevel.L4,
    )
    assert tuple(item.public_name for item in ACOUSTIC_FIDELITY_LADDER) == (
        "analytic_acoustics",
        "advanced_realism",
        "sim_real_calibration",
    )


def test_implemented_l2_maps_to_the_canonical_backend():
    by_level = _ladder_by_level()

    assert (
        by_level[AcousticFidelityLevel.L2].lifecycle_status == "supported_optional_v1"
    )

    assert by_level[AcousticFidelityLevel.L2].backend_ids == ("analytic_acoustics",)
    assert by_level[AcousticFidelityLevel.L2].optional_dependencies == (
        "room",
        "pyroomacoustics",
        "scipy",
        "soundfile",
    )

    for metadata in (by_level[AcousticFidelityLevel.L2],):
        assert metadata.runtime_selectable_v1 is True
        assert "AudioSensorFrame v2" in metadata.frame_contract
        for backend_id in metadata.backend_ids:
            assert fidelity_level_for_backend(backend_id) is metadata


def test_implemented_level_names_all_canonical_directivity_families():
    by_level = _ladder_by_level()
    for level in (AcousticFidelityLevel.L2,):
        modeled = " ".join(by_level[level].models)
        for family in ("omni", "cardioid", "supercardioid", "figure_eight"):
            assert family in modeled


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
        with pytest.raises(ValueError, match="Unknown implemented v1 audio backend"):
            fidelity_level_for_backend(future_family)


def _ladder_by_level() -> dict[AcousticFidelityLevel, AcousticFidelityMetadata]:
    return {item.level: item for item in ACOUSTIC_FIDELITY_LADDER}
