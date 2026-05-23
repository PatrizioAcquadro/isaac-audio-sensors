"""Tests for the public acoustic fidelity ladder metadata."""

from __future__ import annotations

import importlib
from pathlib import Path

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
    assert by_level[AcousticFidelityLevel.L2].backend_ids == ("room_acoustics",)
    assert by_level[AcousticFidelityLevel.L2].optional_dependencies == (
        "room",
        "pyroomacoustics",
        "scipy",
        "soundfile",
    )

    assert frozenset(
        {"geometry_only", "tdoa_synthetic", "room_acoustics"}
    ) == KNOWN_BACKENDS
    for backend_id in KNOWN_BACKENDS:
        metadata = fidelity_level_for_backend(backend_id)
        assert metadata.backend_ids == (backend_id,)
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


def test_ladder_contract_is_documented_and_linked_publicly():
    docs = {
        path: Path(path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "docs/README.md",
            "docs/acoustic_fidelity.md",
            "docs/api_freeze_0_1.md",
            "docs/api_reference.md",
            "docs/backends.md",
            "docs/limitations.md",
            "docs/versioning.md",
            "docs/open_source_release_checklist.md",
        )
    }

    assert "docs/acoustic_fidelity.md" in docs["README.md"]
    assert "acoustic_fidelity.md" in docs["docs/README.md"]

    combined = "\n".join(docs.values())
    for phrase in (
        "L0 `geometry_only`",
        "L1 `tdoa_synthetic`",
        "L2 `room_acoustics`",
        "L3 `advanced_realism`",
        "L4 `sim_real_calibration`",
        "stable v1",
        "supported optional v1",
        "provisional v1",
        "experimental/tooling",
        "AudioSensorFrame v1",
        "not a complete v1 runtime backend",
    ):
        assert phrase in combined


def _ladder_by_level() -> dict[AcousticFidelityLevel, AcousticFidelityMetadata]:
    return {item.level: item for item in ACOUSTIC_FIDELITY_LADDER}
