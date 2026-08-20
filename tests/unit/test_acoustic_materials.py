"""Acoustic material resolution and provenance tests."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

from isaac_audio_sensors.core.acoustics.materials import (
    LEGACY_MATERIAL_ALIASES,
    MATERIAL_BAND_CENTERS_HZ,
    MATERIAL_TABLE,
    PYROOMACOUSTICS_MATERIAL_CITATION,
    PYROOMACOUSTICS_MATERIALS_SHA256,
    MaterialEntry,
    known_material_ids,
    resolve_material,
    resolve_material_coefficients,
    validate_material_table,
)
from isaac_audio_sensors.core.constants import OCCLUSION_BAND_CENTERS_HZ
from isaac_audio_sensors.core.types import RoomAcousticsSpec
from isaac_audio_sensors.isaac.occlusion import (
    DEFAULT_MATERIAL_TRANSMISSION_DB,
    UsdTransmissionLossResolver,
)

MEASURED = {
    "pra.rough_concrete": (0.02, 0.03, 0.03, 0.03, 0.04, 0.07),
    "pra.brickwork": (0.01, 0.02, 0.02, 0.03, 0.03, 0.04),
    "pra.plasterboard": (0.15, 0.10, 0.06, 0.04, 0.04, 0.05),
    "pra.glass_3mm": (0.08, 0.04, 0.03, 0.03, 0.02, 0.02),
    "pra.wood_1_6cm": (0.18, 0.12, 0.10, 0.09, 0.08, 0.07),
    "pra.carpet_cotton": (0.07, 0.31, 0.49, 0.81, 0.66, 0.54),
    "pra.curtains_cotton_0_5": (0.30, 0.45, 0.65, 0.56, 0.59, 0.71),
}
NOMINAL_TRANSMISSION = {
    "concrete": (33.0, 36.0, 40.0, 44.0, 50.0, 55.0),
    "brick": (30.0, 33.0, 37.0, 42.0, 48.0, 52.0),
    "metal": (20.0, 25.0, 30.0, 35.0, 39.0, 42.0),
    "drywall": (15.0, 22.0, 29.0, 34.0, 39.0, 44.0),
    "plaster": (15.0, 22.0, 29.0, 34.0, 39.0, 44.0),
    "glass": (18.0, 22.0, 26.0, 30.0, 33.0, 36.0),
    "wood": (15.0, 19.0, 23.0, 26.0, 29.0, 32.0),
    "fabric": (3.0, 4.0, 6.0, 9.0, 12.0, 15.0),
    "curtain": (3.0, 4.0, 6.0, 9.0, 12.0, 15.0),
}


def test_frozen_material_table_rows_and_source_provenance_are_exact():
    assert MATERIAL_BAND_CENTERS_HZ == OCCLUSION_BAND_CENTERS_HZ
    assert MATERIAL_BAND_CENTERS_HZ == (
        125.0,
        250.0,
        500.0,
        1000.0,
        2000.0,
        4000.0,
    )
    assert len(MATERIAL_TABLE) == 16
    assert PYROOMACOUSTICS_MATERIALS_SHA256 == (
        "1249f0cfdcd4598cf98ec9be05230f910e53aa1da4861d7fe3f88de23a24e0e0"
    )
    for material_id, absorption in MEASURED.items():
        entry = MATERIAL_TABLE[material_id]
        assert entry.absorption == absorption
        assert entry.transmission_db is None
        assert entry.evidence == "measured"
        assert entry.citation == PYROOMACOUSTICS_MATERIAL_CITATION
    for alias, transmission in NOMINAL_TRANSMISSION.items():
        entry = MATERIAL_TABLE[f"nominal.{alias}"]
        assert entry.transmission_db == transmission
        assert entry.evidence == "nominal"
        assert entry.citation is None
    assert DEFAULT_MATERIAL_TRANSMISSION_DB == NOMINAL_TRANSMISSION


def test_table_and_vectors_are_immutable_and_aliases_are_exact():
    assert isinstance(MATERIAL_TABLE, MappingProxyType)
    assert isinstance(LEGACY_MATERIAL_ALIASES, MappingProxyType)
    with pytest.raises(TypeError):
        MATERIAL_TABLE["new"] = MATERIAL_TABLE["nominal.wood"]  # type: ignore[index]
    for alias, target in LEGACY_MATERIAL_ALIASES.items():
        assert resolve_material(alias).material_id == target
        assert resolve_material(alias.upper()).material_id == target
    with pytest.raises(ValueError, match="Unknown material id.*known ids"):
        resolve_material("rough_concrete", application="room fixture")
    assert known_material_ids() == tuple(MATERIAL_TABLE)


def test_family_resolution_propagates_evidence_without_promotion():
    measured = resolve_material_coefficients(
        "pra.rough_concrete",
        "absorption",
        application="room",
    )
    assert measured.evidence_record() == {
        "material_id": "pra.rough_concrete",
        "coefficient": "absorption",
        "evidence": "measured",
        "citation": PYROOMACOUSTICS_MATERIAL_CITATION,
    }
    nominal = resolve_material_coefficients("wood", "transmission_db")
    assert nominal.evidence_record() == {
        "material_id": "nominal.wood",
        "coefficient": "transmission_db",
        "evidence": "nominal",
    }
    with pytest.raises(
        ValueError,
        match=r"pra\.rough_concrete.*no requested.*transmission",
    ):
        resolve_material_coefficients(
            "pra.rough_concrete",
            "transmission_db",
            application="occluder:/World/Wall",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"material_id": ""}, "nonempty"),
        ({"absorption": (0.1,) * 7}, "6-value"),
        ({"absorption": (0.1, 0.1, 0.1, 0.1, 0.1, 1.1)}, r"\[0, 1\]"),
        ({"transmission_db": (1.0, 1.0, 1.0, 1.0, 1.0, -1.0)}, "non-negative"),
        ({"evidence": "invented"}, "invalid evidence"),
        ({"citation": "not allowed"}, "cannot cite"),
    ],
)
def test_material_validation_fails_closed(mutation, message):
    base = MATERIAL_TABLE["nominal.wood"]
    invalid = replace(base, **mutation)
    with pytest.raises(ValueError, match=message):
        validate_material_table((invalid,), {})


def test_material_validation_rejects_duplicates_alias_cycles_and_unknown_targets():
    entry = MATERIAL_TABLE["nominal.wood"]
    with pytest.raises(ValueError, match="Duplicate material id"):
        validate_material_table((entry, entry), {})
    with pytest.raises(ValueError, match="cycle"):
        validate_material_table((entry,), {"a": "b", "b": "a"})
    with pytest.raises(ValueError, match="unknown id"):
        validate_material_table((entry,), {"a": "nominal.missing"})


def test_room_spec_accepts_only_resolvable_absorption_material_ids():
    room = RoomAcousticsSpec(
        room_id="material_room",
        dimensions_m=(6.0, 6.0, 3.0),
        absorption="pra.rough_concrete",
        max_order=1,
    )
    assert room.absorption == "pra.rough_concrete"
    with pytest.raises(ValueError, match="Unknown material id 'missing'"):
        replace(room, absorption="missing")


class _Prim:
    def __init__(self, attributes):
        self.attributes = attributes


class _Stage:
    def __init__(self, prim):
        self.prim = prim

    def GetPrimAtPath(self, _path):
        return self.prim


def test_usd_material_resolution_precedence_and_fail_closed_matrix():
    prim = _Prim(
        {
            "ias:transmission_loss_db_bands": (1, 2, 3, 4, 5, 6),
            "ias:transmission_loss_db": 12.0,
            "ias:acoustic_material_id": "nominal.wood",
        }
    )
    resolver = UsdTransmissionLossResolver(_Stage(prim))
    assert resolver.loss_for("/World/Wall").band_db == (1, 2, 3, 4, 5, 6)
    prim.attributes = {"ias:transmission_loss_db": 12.0}
    flat = resolver.loss_for("/World/Wall")
    assert flat.band_db is None
    assert flat.expanded_band_db == (12.0,) * 6
    prim.attributes = {"ias:acoustic_material_id": "nominal.glass"}
    assert resolver.loss_for("/World/Wall").material == "nominal.glass"
    prim.attributes = {"ias:acoustic_material_id": "pra.rough_concrete"}
    with pytest.raises(ValueError, match="no requested transmission_db"):
        resolver.loss_for("/World/Wall")
    prim.attributes = {"ias:acoustic_material_id": "unknown.explicit"}
    with pytest.raises(ValueError, match="unknown.explicit.*occluder"):
        resolver.loss_for("/World/Wall")
    prim.attributes = {"ias:transmission_loss_db_bands": (1, 2, 3, 4, 5, 6, 7)}
    with pytest.raises(ValueError, match="exactly 6"):
        resolver.loss_for("/World/Wall")


def test_nominal_entry_validation_rejects_measured_without_citation():
    invalid = MaterialEntry(
        material_id="measured.missing",
        description="invalid",
        absorption=(0.1,) * 6,
        transmission_db=None,
        evidence="measured",
        citation=None,
    )
    with pytest.raises(ValueError, match="needs a citation"):
        validate_material_table((invalid,), {})
