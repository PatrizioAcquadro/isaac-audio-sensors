"""Acoustic material table with fail-closed provenance.

This module is intentionally dependency-free.  In particular, material ids
are never delegated to a runtime pyroomacoustics database: the exact vectors
validated here are the values applied by room and Isaac integrations.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from isaac_audio_sensors.core.constants import OCCLUSION_BAND_CENTERS_HZ

EvidenceTag = Literal["measured", "nominal"]
CoefficientFamily = Literal["absorption", "transmission_db"]

MATERIAL_BAND_CENTERS_HZ = OCCLUSION_BAND_CENTERS_HZ
PYROOMACOUSTICS_MATERIALS_SHA256 = (
    "1249f0cfdcd4598cf98ec9be05230f910e53aa1da4861d7fe3f88de23a24e0e0"
)
PYROOMACOUSTICS_MATERIAL_CITATION = (
    "Michael Vorl\u00e4nder, Auralization: Fundamentals of Acoustics, Modelling, "
    "Simulation, Algorithms, and Acoustic Virtual Reality, Springer, 1st "
    "edition, 2008; coefficients distributed by pyroomacoustics 0.10.1."
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterialEntry:
    """One immutable, evidence-homogeneous acoustic material record."""

    material_id: str
    description: str
    absorption: tuple[float, ...] | None
    transmission_db: tuple[float, ...] | None
    evidence: EvidenceTag
    citation: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterialResolution:
    """A validated coefficient-family selection from the frozen table."""

    material_id: str
    coefficient: CoefficientFamily
    values: tuple[float, ...]
    evidence: EvidenceTag
    citation: str | None
    description: str

    def evidence_record(self) -> dict[str, str]:
        """Return the additive frame-diagnostic provenance record."""

        record = {
            "material_id": self.material_id,
            "coefficient": self.coefficient,
            "evidence": self.evidence,
        }
        if self.evidence == "measured":
            assert self.citation is not None
            record["citation"] = self.citation
        return record


def _entry(
    material_id: str,
    description: str,
    *,
    absorption: tuple[float, ...] | None,
    transmission_db: tuple[float, ...] | None = None,
    evidence: EvidenceTag,
    citation: str | None,
) -> MaterialEntry:
    return MaterialEntry(
        material_id=material_id,
        description=description,
        absorption=absorption,
        transmission_db=transmission_db,
        evidence=evidence,
        citation=citation,
    )


_MEASURED_ENTRIES = (
    _entry(
        "pra.rough_concrete",
        "Rough concrete",
        absorption=(0.02, 0.03, 0.03, 0.03, 0.04, 0.07),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.brickwork",
        "Walls, rendered brickwork",
        absorption=(0.01, 0.02, 0.02, 0.03, 0.03, 0.04),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.plasterboard",
        "2 \u00d7 13 mm plasterboard on steel frame, 50 mm mineral wool in "
        "cavity, surface painted",
        absorption=(0.15, 0.10, 0.06, 0.04, 0.04, 0.05),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.glass_3mm",
        "Single pane of glass, 3 mm",
        absorption=(0.08, 0.04, 0.03, 0.03, 0.02, 0.02),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.wood_1_6cm",
        "Wood, 1.6 cm thick, on 4 cm wooden planks",
        absorption=(0.18, 0.12, 0.10, 0.09, 0.08, 0.07),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.carpet_cotton",
        "Cotton carpet",
        absorption=(0.07, 0.31, 0.49, 0.81, 0.66, 0.54),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.curtains_cotton_0_5",
        "Cotton curtains (0.5 kg/m\u00b2), draped to approximately 3/4 area, "
        "approximately 130 mm from wall",
        absorption=(0.30, 0.45, 0.65, 0.56, 0.59, 0.71),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
)


def _nominal(
    name: str,
    absorption: float,
    transmission_db: tuple[float, ...],
) -> MaterialEntry:
    return _entry(
        f"nominal.{name}",
        f"Nominal {name} compatibility preset",
        absorption=(float(absorption),) * len(MATERIAL_BAND_CENTERS_HZ),
        transmission_db=transmission_db,
        evidence="nominal",
        citation=None,
    )


_NOMINAL_ENTRIES = (
    _nominal("concrete", 0.05, (33.0, 36.0, 40.0, 44.0, 50.0, 55.0)),
    _nominal("brick", 0.04, (30.0, 33.0, 37.0, 42.0, 48.0, 52.0)),
    _nominal("metal", 0.05, (20.0, 25.0, 30.0, 35.0, 39.0, 42.0)),
    _nominal("drywall", 0.10, (15.0, 22.0, 29.0, 34.0, 39.0, 44.0)),
    _nominal("plaster", 0.10, (15.0, 22.0, 29.0, 34.0, 39.0, 44.0)),
    _nominal("glass", 0.05, (18.0, 22.0, 26.0, 30.0, 33.0, 36.0)),
    _nominal("wood", 0.10, (15.0, 19.0, 23.0, 26.0, 29.0, 32.0)),
    _nominal("fabric", 0.40, (3.0, 4.0, 6.0, 9.0, 12.0, 15.0)),
    _nominal("curtain", 0.40, (3.0, 4.0, 6.0, 9.0, 12.0, 15.0)),
)

LEGACY_MATERIAL_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "concrete": "nominal.concrete",
        "brick": "nominal.brick",
        "metal": "nominal.metal",
        "drywall": "nominal.drywall",
        "plaster": "nominal.plaster",
        "glass": "nominal.glass",
        "wood": "nominal.wood",
        "fabric": "nominal.fabric",
        "curtain": "nominal.curtain",
    }
)


def _build_material_table(
    entries: Sequence[MaterialEntry],
    aliases: Mapping[str, str],
) -> Mapping[str, MaterialEntry]:
    """Validate and return an immutable id mapping, failing on any ambiguity."""

    by_id: dict[str, MaterialEntry] = {}
    band_count = len(MATERIAL_BAND_CENTERS_HZ)
    for entry in entries:
        material_id = str(entry.material_id)
        if not material_id.strip():
            raise ValueError("Material id must be nonempty.")
        if material_id in by_id:
            raise ValueError(f"Duplicate material id {material_id!r}.")
        if not str(entry.description).strip():
            raise ValueError(f"Material {material_id!r} description must be nonempty.")
        if entry.evidence not in {"measured", "nominal"}:
            raise ValueError(
                f"Material {material_id!r} has invalid evidence {entry.evidence!r}."
            )
        if entry.evidence == "measured" and not (
            isinstance(entry.citation, str) and entry.citation.strip()
        ):
            raise ValueError(f"Measured material {material_id!r} needs a citation.")
        if entry.evidence == "nominal" and entry.citation is not None:
            raise ValueError(f"Nominal material {material_id!r} cannot cite a source.")
        if entry.absorption is None and entry.transmission_db is None:
            raise ValueError(f"Material {material_id!r} has no coefficient family.")
        for family, values in (
            ("absorption", entry.absorption),
            ("transmission_db", entry.transmission_db),
        ):
            if values is None:
                continue
            if not isinstance(values, tuple) or len(values) != band_count:
                raise ValueError(
                    f"Material {material_id!r} {family} must be an immutable "
                    f"{band_count}-value tuple."
                )
            for value in values:
                if not math.isfinite(float(value)):
                    raise ValueError(
                        f"Material {material_id!r} {family} values must be finite."
                    )
                if family == "absorption" and not 0.0 <= float(value) <= 1.0:
                    raise ValueError(
                        f"Material {material_id!r} absorption must be in [0, 1]."
                    )
                if family == "transmission_db" and float(value) < 0.0:
                    raise ValueError(
                        f"Material {material_id!r} transmission must be non-negative."
                    )
        by_id[material_id] = entry

    normalized_aliases: dict[str, str] = {}
    for raw_alias, target in aliases.items():
        alias = str(raw_alias).strip().lower()
        if not alias:
            raise ValueError("Material alias must be nonempty.")
        if alias in normalized_aliases:
            raise ValueError(f"Duplicate material alias {alias!r}.")
        if alias in by_id:
            raise ValueError(f"Material alias {alias!r} duplicates a canonical id.")
        normalized_aliases[alias] = str(target)
    for alias, target in normalized_aliases.items():
        seen = {alias}
        while target.lower() in normalized_aliases:
            target = target.lower()
            if target in seen:
                raise ValueError(f"Material alias cycle includes {alias!r}.")
            seen.add(target)
            target = normalized_aliases[target]
        if target not in by_id:
            raise ValueError(f"Material alias {alias!r} targets unknown id {target!r}.")
    return MappingProxyType(by_id)


MATERIAL_TABLE = _build_material_table(
    _MEASURED_ENTRIES + _NOMINAL_ENTRIES,
    LEGACY_MATERIAL_ALIASES,
)


def known_material_ids() -> tuple[str, ...]:
    """Return canonical material ids in frozen table order."""

    return tuple(MATERIAL_TABLE)


def resolve_material(
    material_id: str, *, application: str = "material"
) -> MaterialEntry:
    """Resolve one exact canonical id or frozen case-insensitive legacy alias."""

    if not isinstance(material_id, str) or not material_id.strip():
        raise ValueError(f"{application} material id must be a nonempty string.")
    authored = material_id.strip()
    canonical = authored if authored in MATERIAL_TABLE else None
    if canonical is None:
        canonical = LEGACY_MATERIAL_ALIASES.get(authored.lower())
    if canonical is None:
        raise ValueError(
            f"Unknown material id {authored!r} for {application}; known ids are "
            f"{known_material_ids()} and legacy aliases are "
            f"{tuple(LEGACY_MATERIAL_ALIASES)}."
        )
    return MATERIAL_TABLE[canonical]


def resolve_material_coefficients(
    material_id: str,
    coefficient: CoefficientFamily,
    *,
    application: str = "material",
) -> MaterialResolution:
    """Resolve a requested family and reject known entries where it is absent."""

    if coefficient not in {"absorption", "transmission_db"}:
        raise ValueError(f"Unknown coefficient family {coefficient!r}.")
    entry = resolve_material(material_id, application=application)
    values = getattr(entry, coefficient)
    if values is None:
        raise ValueError(
            f"Material id {entry.material_id!r} for {application} has no requested "
            f"{coefficient} coefficients; known ids are {known_material_ids()}."
        )
    return MaterialResolution(
        material_id=entry.material_id,
        coefficient=coefficient,
        values=values,
        evidence=entry.evidence,
        citation=entry.citation,
        description=entry.description,
    )
