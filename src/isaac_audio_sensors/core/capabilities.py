"""Deterministic capability discovery with dependency provenance."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

from isaac_audio_sensors.core.fidelity import ACOUSTIC_FIDELITY_LADDER
from isaac_audio_sensors.core.packs import (
    activate_pack,
    active_pack_manifest,
    active_pack_root,
)


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    """Availability and provenance for one fidelity level or optional feature."""

    capability_id: str
    kind: str
    fidelity_level: str
    status: str
    origin: str
    missing_dependencies: tuple[str, ...]
    actionable_message: str

    @property
    def available(self) -> bool:
        """Return whether the capability can be selected in this process."""

        return self.status == "available"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return {
            "capability_id": self.capability_id,
            "kind": self.kind,
            "fidelity_level": self.fidelity_level,
            "status": self.status,
            "origin": self.origin,
            "missing_dependencies": list(self.missing_dependencies),
            "actionable_message": self.actionable_message,
        }


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    """Frozen, deterministically ordered process capability report."""

    fidelity_levels: tuple[CapabilityStatus, ...]
    optional_features: tuple[CapabilityStatus, ...]
    active_pack: str | None

    @property
    def capabilities(self) -> tuple[CapabilityStatus, ...]:
        """Return all entries in stable fidelity-then-feature order."""

        return self.fidelity_levels + self.optional_features

    def get(self, capability_id: str) -> CapabilityStatus:
        """Return one report entry by id."""

        for capability in self.capabilities:
            if capability.capability_id == capability_id:
                return capability
        raise KeyError(capability_id)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable, deterministic mapping."""

        return {
            "active_pack": self.active_pack,
            "fidelity_levels": [item.to_dict() for item in self.fidelity_levels],
            "optional_features": [
                item.to_dict() for item in self.optional_features
            ],
        }


def acoustic_pack_artifact_name() -> str:
    """Return the exact acoustic-pack artifact for the running package version."""

    from isaac_audio_sensors import __version__

    return (
        "isaac_audio_sensors_acoustic_pack-l2l3-"
        f"{__version__}-linux_x86_64-cp312.tar.gz"
    )


def _is_under(origin: str, root: Path) -> bool:
    try:
        Path(origin).resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _declared_pack_capability(capability_id: str) -> bool:
    manifest = active_pack_manifest()
    if manifest is None:
        return False
    capabilities = manifest.get("capabilities")
    return isinstance(capabilities, list) and any(
        isinstance(item, dict) and item.get("id") == capability_id
        for item in capabilities
    )


def _probe_optional(
    *,
    capability_id: str,
    kind: str,
    fidelity_level: str,
    dependencies: tuple[str, ...],
) -> CapabilityStatus:
    modules = []
    missing = []
    for dependency in dependencies:
        try:
            modules.append(importlib.import_module(dependency))
        except Exception:  # noqa: BLE001 - broken optional binaries are unavailable.
            missing.append(dependency)
    artifact = acoustic_pack_artifact_name()
    if missing:
        return CapabilityStatus(
            capability_id=capability_id,
            kind=kind,
            fidelity_level=fidelity_level,
            status="unavailable",
            origin="absent",
            missing_dependencies=tuple(missing),
            actionable_message=(
                f"Install and explicitly activate {artifact}; missing dependencies: "
                f"{', '.join(missing)}."
            ),
        )

    root = active_pack_root()
    manifest = active_pack_manifest()
    module_origins = [getattr(module, "__file__", None) for module in modules]
    if (
        root is not None
        and manifest is not None
        and _declared_pack_capability(capability_id)
        and all(
            isinstance(origin, str) and _is_under(origin, root)
            for origin in module_origins
        )
    ):
        origin = f"pack:{manifest['pack_id']}@{manifest['pack_version']}"
    else:
        origin = "external-unmanaged"
    return CapabilityStatus(
        capability_id=capability_id,
        kind=kind,
        fidelity_level=fidelity_level,
        status="available",
        origin=origin,
        missing_dependencies=(),
        actionable_message="",
    )


def _base_level(level: str, public_name: str) -> CapabilityStatus:
    return CapabilityStatus(
        capability_id=level,
        kind="fidelity_level",
        fidelity_level=level,
        status="available",
        origin="base",
        missing_dependencies=(),
        actionable_message=f"{public_name} is provided by the import-safe base.",
    )


def _unavailable_future_level(level: str, public_name: str) -> CapabilityStatus:
    if level == "L3":
        message = (
            f"Complete {public_name} is unavailable. Install and explicitly activate "
            f"{acoustic_pack_artifact_name()} for the released waveform-dependent "
            "L2/L3 capabilities; material-aware ray/transmission occlusion remains "
            "available in the base."
        )
    else:
        message = (
            f"{public_name} is not a released runtime capability in Stage 1; "
            "no pack activation can enable it."
        )
    return CapabilityStatus(
        capability_id=level,
        kind="fidelity_level",
        fidelity_level=level,
        status="unavailable",
        origin="absent",
        missing_dependencies=(),
        actionable_message=message,
    )


def discover_capabilities(pack_root: str | Path | None = None) -> CapabilityReport:
    """Discover base, managed-pack, external, and absent capabilities.

    Passing ``pack_root`` is an explicit selection request and activates that
    validated immutable root before optional modules are imported.
    """

    if pack_root is not None:
        activate_pack(pack_root)

    room = _probe_optional(
        capability_id="room_acoustics",
        kind="backend",
        fidelity_level="L2",
        dependencies=("pyroomacoustics",),
    )
    room_srp = _probe_optional(
        capability_id="room_acoustics_srp",
        kind="backend",
        fidelity_level="L2",
        dependencies=("pyroomacoustics",),
    )
    waveform_wav = _probe_optional(
        capability_id="waveform_export_wav",
        kind="waveform_export",
        fidelity_level="L2",
        dependencies=("soundfile",),
    )
    waveform_flac = _probe_optional(
        capability_id="waveform_export_flac",
        kind="waveform_export",
        fidelity_level="L2",
        dependencies=("soundfile",),
    )

    fidelity_levels: list[CapabilityStatus] = []
    for metadata in ACOUSTIC_FIDELITY_LADDER:
        level = metadata.level.value
        if level in {"L0", "L1"}:
            fidelity_levels.append(_base_level(level, metadata.public_name))
        elif level == "L2":
            origins = {room.origin, room_srp.origin}
            available = room.available and room_srp.available
            origin = origins.pop() if available and len(origins) == 1 else "absent"
            missing = tuple(
                sorted(set(room.missing_dependencies + room_srp.missing_dependencies))
            )
            fidelity_levels.append(
                CapabilityStatus(
                    capability_id="L2",
                    kind="fidelity_level",
                    fidelity_level="L2",
                    status="available" if available else "unavailable",
                    origin=origin,
                    missing_dependencies=missing,
                    actionable_message=(
                        ""
                        if available
                        else (
                            "Install and explicitly activate "
                            f"{acoustic_pack_artifact_name()} to enable the L2 room "
                            "backends."
                        )
                    ),
                )
            )
        else:
            fidelity_levels.append(
                _unavailable_future_level(level, metadata.public_name)
            )

    manifest = active_pack_manifest()
    active_pack = (
        None
        if manifest is None
        else f"{manifest['pack_id']}@{manifest['pack_version']}"
    )
    return CapabilityReport(
        fidelity_levels=tuple(fidelity_levels),
        optional_features=(room, room_srp, waveform_wav, waveform_flac),
        active_pack=active_pack,
    )


__all__ = [
    "CapabilityReport",
    "CapabilityStatus",
    "acoustic_pack_artifact_name",
    "discover_capabilities",
]
