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
CoefficientFamily = Literal["absorption", "transmission_db", "scattering"]

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
    """One immutable catalog record; scattering has nominal provenance."""

    material_id: str
    description: str
    absorption: tuple[float, ...] | None
    transmission_db: tuple[float, ...] | None
    evidence: EvidenceTag
    citation: str | None
    absorption_band_centers_hz: tuple[float, ...] = MATERIAL_BAND_CENTERS_HZ
    scattering: float = 0.05


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterialResolution:
    """A validated coefficient-family selection from the frozen table."""

    material_id: str
    coefficient: CoefficientFamily
    values: tuple[float, ...]
    evidence: EvidenceTag
    citation: str | None
    description: str
    band_centers_hz: tuple[float, ...] = MATERIAL_BAND_CENTERS_HZ

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
        absorption_band_centers_hz=MATERIAL_BAND_CENTERS_HZ
        + ((8000.0,) if absorption is not None and len(absorption) == 7 else ()),
    )


_MEASURED_ENTRIES = (
    _entry(
        "pra.rough_concrete",
        "Rough concrete",
        absorption=(0.02, 0.03, 0.03, 0.03, 0.04, 0.07, 0.07),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.brickwork",
        "Walls, rendered brickwork",
        absorption=(0.01, 0.02, 0.02, 0.03, 0.03, 0.04, 0.04),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.plasterboard",
        "2 * 13 mm plasterboard on steel frame, 50 mm mineral wool in cavity, "
        "surface painted",
        absorption=(0.15, 0.1, 0.06, 0.04, 0.04, 0.05, 0.05),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.glass_3mm",
        "Single pane of glass, 3 mm",
        absorption=(0.08, 0.04, 0.03, 0.03, 0.02, 0.02, 0.02),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.wood_1_6cm",
        "Wood, 1.6 cm thick, on 4 cm wooden planks",
        absorption=(0.18, 0.12, 0.1, 0.09, 0.08, 0.07, 0.07),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.carpet_cotton",
        "Cotton carpet",
        absorption=(0.07, 0.31, 0.49, 0.81, 0.66, 0.54, 0.48),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.curtains_cotton_0_5",
        "Cotton curtains (0.5 kg/m2) draped to 3/4 area approx. 130 mm from wall",
        absorption=(0.3, 0.45, 0.65, 0.56, 0.59, 0.71, 0.71),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.hard_surface",
        "Walls, hard surfaces average (brick walls, plaster, hard floors, etc.)",
        absorption=(0.02, 0.02, 0.03, 0.03, 0.04, 0.05, 0.05),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.ceramic_tiles",
        "Ceramic tiles with a smooth surface",
        absorption=(0.01, 0.01, 0.01, 0.02, 0.02, 0.02, 0.02),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.linoleum_on_concrete",
        "Linoleum, asphalt, rubber, or cork tile on concrete",
        absorption=(0.02, 0.03, 0.03, 0.03, 0.03, 0.02),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.carpet_rubber_5mm",
        "5 mm rubber carpet on concrete",
        absorption=(0.04, 0.04, 0.08, 0.12, 0.1, 0.1),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.ceiling_fissured_tile",
        "Fissured ceiling tile",
        absorption=(0.49, 0.53, 0.53, 0.75, 0.92, 0.99),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.ceiling_fibre_absorber",
        "Fibre absorber on perforated sheet metal cartridge, 0,5 mm zinc-plated "
        "steel, 1.5 mm hole diameter, 200 mm cavity filled with 20 mm mineral "
        "wool (20 kg/m3), inflammable",
        absorption=(0.48, 0.97, 1.0, 0.97, 1.0, 1.0, 1.0),
        evidence="measured",
        citation=PYROOMACOUSTICS_MATERIAL_CITATION,
    ),
    _entry(
        "pra.ceiling_melamine_foam",
        "Wedge-shaped, melamine foam, ceiling tile",
        absorption=(0.12, 0.33, 0.83, 0.97, 0.98, 0.95),
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
        if not math.isfinite(entry.scattering) or not 0 <= entry.scattering <= 1:
            raise ValueError("Scattering must be finite and in [0, 1].")
        for family, values in (
            ("absorption", entry.absorption),
            ("transmission_db", entry.transmission_db),
        ):
            if values is None:
                continue
            frequencies = (
                entry.absorption_band_centers_hz
                if family == "absorption"
                else MATERIAL_BAND_CENTERS_HZ
            )
            validate_frequencies(frequencies)
            band_count = len(frequencies)
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


def validate_frequencies(frequencies: Sequence[float]) -> None:
    if not frequencies or any(not math.isfinite(f) or f <= 0 for f in frequencies):
        raise ValueError("Frequency centers must be finite and positive.")
    if any(b <= a for a, b in zip(frequencies, frequencies[1:], strict=False)):
        raise ValueError("Frequency centers must be strictly increasing.")


def resample_coefficients(
    values: Sequence[float], frequencies: Sequence[float], targets: Sequence[float]
) -> tuple[float, ...]:
    """Interpolate on log frequency; hold endpoints outside the source range."""
    validate_frequencies(frequencies)
    validate_frequencies(targets)
    if len(values) != len(frequencies) or any(not math.isfinite(v) for v in values):
        raise ValueError("Finite coefficients must match their frequency centers.")
    result = []
    for target in targets:
        if target <= frequencies[0]:
            result.append(float(values[0]))
        elif target >= frequencies[-1]:
            result.append(float(values[-1]))
        else:
            right = next(i for i, f in enumerate(frequencies) if f >= target)
            a, b = frequencies[right - 1 : right + 1]
            fraction = math.log(target / a) / math.log(b / a)
            result.append(
                float(
                    values[right - 1] + fraction * (values[right] - values[right - 1])
                )
            )
    return tuple(result)


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
    band_centers_hz: tuple[float, ...] | None = MATERIAL_BAND_CENTERS_HZ,
) -> MaterialResolution:
    """Resolve a requested family and reject known entries where it is absent."""

    if coefficient not in {"absorption", "transmission_db", "scattering"}:
        raise ValueError(f"Unknown coefficient family {coefficient!r}.")
    entry = resolve_material(material_id, application=application)
    values = getattr(entry, coefficient)
    if values is None:
        raise ValueError(
            f"Material id {entry.material_id!r} for {application} has no requested "
            f"{coefficient} coefficients; known ids are {known_material_ids()}."
        )
    frequencies = (
        entry.absorption_band_centers_hz
        if coefficient == "absorption"
        else MATERIAL_BAND_CENTERS_HZ
    )
    if coefficient == "scattering":
        values = (entry.scattering,) * len(frequencies)
    targets = frequencies if band_centers_hz is None else band_centers_hz
    values = resample_coefficients(values, frequencies, targets)
    return MaterialResolution(
        material_id=entry.material_id,
        coefficient=coefficient,
        values=values,
        evidence="nominal" if coefficient == "scattering" else entry.evidence,
        citation=None if coefficient == "scattering" else entry.citation,
        description=entry.description,
        band_centers_hz=tuple(targets),
    )


# Compatibility broadband labels derive from the same nominal catalogue.
SEMANTIC_ABSORPTION = tuple(
    (alias, resolve_material_coefficients(target, "absorption").values[0])
    for alias, target in LEGACY_MATERIAL_ALIASES.items()
) + (("carpet", 0.30), ("acoustic_panel", 0.70), ("foam", 0.70))
