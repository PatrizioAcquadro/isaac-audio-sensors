"""Resolve acoustic USD properties without promoting visual labels to evidence."""

from __future__ import annotations

from dataclasses import dataclass

from isaac_audio_sensors.core.acoustics.materials import (
    MATERIAL_BAND_CENTERS_HZ,
    resample_coefficients,
    resolve_material,
    resolve_material_coefficients,
)

ATTRS = {
    "absorption": "ias:absorption",
    "transmission_db": "ias:transmission_loss_db",
    "scattering": "ias:scattering",
}
# Match construction descriptions, not generic visual substance names.
DEFAULT_ASSOCIATIONS = {
    "rough_concrete": "pra.rough_concrete",
    "rendered_brickwork": "pra.brickwork",
    "glass_3mm": "pra.glass_3mm",
    "wood_1_6cm": "pra.wood_1_6cm",
    "carpet_cotton": "pra.carpet_cotton",
    "curtains_cotton_0_5": "pra.curtains_cotton_0_5",
    "ceramic_tiles": "pra.ceramic_tiles",
    "linoleum_on_concrete": "pra.linoleum_on_concrete",
    "rubber_5mm": "pra.carpet_rubber_5mm",
    "ceiling_fissured_tile": "pra.ceiling_fissured_tile",
    "ceiling_fibre_absorber": "pra.ceiling_fibre_absorber",
    "ceiling_melamine_foam": "pra.ceiling_melamine_foam",
}


@dataclass(frozen=True)
class Curve:
    values: tuple[float, ...]
    frequencies: tuple[float, ...]
    origin: str
    evidence: str
    citation: str | None = None

    def at(self, frequencies):
        return resample_coefficients(self.values, self.frequencies, frequencies)


@dataclass(frozen=True)
class AcousticMaterial:
    absorption: Curve
    scattering: Curve
    transmission_db: Curve | None


def attribute(prim, name, time=None):
    attr = prim.GetAttribute(name)
    return attr.Get(time) if attr and time is not None else attr.Get() if attr else None


def _explicit(prim, family, time):
    import math

    name = ATTRS[family]
    bands = attribute(prim, name + "_bands", time)
    value = attribute(prim, name, time) if bands is None else bands
    if value is None:
        return None
    values = (
        (float(value),) if isinstance(value, (int, float)) else tuple(map(float, value))
    )
    frequencies = attribute(prim, name + "_frequencies_hz", time)
    if frequencies is None:
        if len(values) == 1:
            frequencies = (1000.0,)
        elif len(values) == 6:
            frequencies = MATERIAL_BAND_CENTERS_HZ
        else:
            raise ValueError(
                f"{prim.GetPath()} {name}: explicit frequency centers required"
            )
    frequencies = tuple(map(float, frequencies))
    resample_coefficients(values, frequencies, frequencies)
    if any(
        not math.isfinite(v) or v < 0 or (family != "transmission_db" and v > 1)
        for v in values
    ):
        raise ValueError(f"{prim.GetPath()} {name}: invalid coefficients")
    return Curve(values, frequencies, f"authored:{prim.GetPath()}:{name}", "authored")


def resolve(
    prim, bound_material, *, time, associations, fallback_id, fallback_scattering
):
    # An inherited construction override precedes its children's bound materials.
    hierarchy = []
    current = prim
    while current and not current.IsPseudoRoot():
        hierarchy.append(current)
        current = current.GetParent()
    owners = hierarchy + ([bound_material] if bound_material else [])
    selected: dict[str, Curve] = {}
    for owner in owners:
        material_id = attribute(owner, "ias:acoustic_material_id", time)
        if material_id is None:
            material_id = attribute(owner, "ias:material", time)
        entry = resolve_material(material_id) if material_id is not None else None
        for family in ATTRS:
            if family in selected:
                continue
            curve = _explicit(owner, family, time)
            if curve is None and family == "scattering":
                scattering_id = attribute(owner, "ias:scattering_material_id", time)
                if scattering_id is not None:
                    r = resolve_material_coefficients(
                        scattering_id, family, band_centers_hz=None
                    )
                    curve = Curve(
                        r.values,
                        r.band_centers_hz,
                        f"preset:{r.material_id}",
                        r.evidence,
                        r.citation,
                    )
            if (
                curve is None
                and entry is not None
                and getattr(entry, family) is not None
            ):
                r = resolve_material_coefficients(
                    entry.material_id, family, band_centers_hz=None
                )
                curve = Curve(
                    r.values,
                    r.band_centers_hz,
                    f"preset:{entry.material_id}",
                    r.evidence,
                    r.citation,
                )
            if curve is not None:
                selected[family] = curve
    labels = [str(bound_material.GetPath())] if bound_material else []
    labels.append(str(prim.GetPath()))
    for owner in hierarchy:
        labels.extend(
            str(a.Get())
            for a in owner.GetAttributes()
            if a.GetName().endswith(":semanticData")
        )
    import re

    tokens = set(re.findall(r"[a-z0-9]+", " ".join(labels).lower()))
    match = next(
        (
            material_id
            for label, material_id in associations.items()
            if set(re.findall(r"[a-z0-9]+", label.lower())) <= tokens
        ),
        None,
    )
    if match:
        entry = resolve_material(match)
        for family in ATTRS:
            if family not in selected and getattr(entry, family) is not None:
                r = resolve_material_coefficients(match, family, band_centers_hz=None)
                selected[family] = Curve(
                    r.values,
                    r.band_centers_hz,
                    f"association:{match}",
                    "nominal",
                    r.citation,
                )
    if "absorption" not in selected:
        r = resolve_material_coefficients(
            fallback_id, "absorption", band_centers_hz=None
        )
        selected["absorption"] = Curve(
            r.values,
            r.band_centers_hz,
            f"fallback:{fallback_id}",
            "nominal",
            r.citation,
        )
    selected.setdefault(
        "scattering",
        Curve((fallback_scattering,), (1000.0,), "fallback:scattering", "nominal"),
    )
    return AcousticMaterial(
        selected["absorption"], selected["scattering"], selected.get("transmission_db")
    )
