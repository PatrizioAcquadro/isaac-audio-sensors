"""Deterministic capability discovery with dependency provenance."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from isaac_audio_sensors.core.fidelity import ACOUSTIC_FIDELITY_LADDER
from isaac_audio_sensors.core.plugins.registry import get_default_registry

_BUNDLED_ROOT = Path(__file__).resolve().parents[1] / "_bundled"


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
        return self.status == "available"

    def to_dict(self) -> dict[str, object]:
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

    @property
    def capabilities(self) -> tuple[CapabilityStatus, ...]:
        return self.fidelity_levels + self.optional_features

    def get(self, capability_id: str) -> CapabilityStatus:
        for capability in self.capabilities:
            if capability.capability_id == capability_id:
                return capability
        raise KeyError(capability_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "fidelity_levels": [item.to_dict() for item in self.fidelity_levels],
            "optional_features": [
                item.to_dict() for item in self.optional_features
            ],
        }


def _is_under(origin: str, root: Path) -> bool:
    try:
        Path(origin).resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _module_origins(module: ModuleType) -> tuple[str, ...]:
    origin = getattr(module, "__file__", None)
    if isinstance(origin, str):
        return (origin,)
    paths = getattr(module, "__path__", None)
    return tuple(str(path) for path in paths) if paths is not None else ()


def _probe_optional(
    *,
    capability_id: str,
    kind: str,
    fidelity_level: str,
    dependencies: tuple[str, ...],
) -> CapabilityStatus:
    modules: list[ModuleType] = []
    missing: list[str] = []
    for dependency in dependencies:
        try:
            modules.append(importlib.import_module(dependency))
        except Exception:  # noqa: BLE001 - broken optional binaries are unavailable
            missing.append(dependency)
    if missing:
        return CapabilityStatus(
            capability_id=capability_id,
            kind=kind,
            fidelity_level=fidelity_level,
            status="unavailable",
            origin="absent",
            missing_dependencies=tuple(missing),
            actionable_message=(
                "Install isaac-audio-sensors[room]; missing dependencies: "
                f"{', '.join(missing)}."
            ),
        )

    origins = tuple(origin for module in modules for origin in _module_origins(module))
    bundled = bool(origins) and all(
        _is_under(origin, _BUNDLED_ROOT) for origin in origins
    )
    return CapabilityStatus(
        capability_id=capability_id,
        kind=kind,
        fidelity_level=fidelity_level,
        status="available",
        origin="bundled" if bundled else "external",
        missing_dependencies=(),
        actionable_message="",
    )


def _base_level(level: str, public_name: str) -> CapabilityStatus:
    return CapabilityStatus(
        capability_id=level,
        kind="fidelity_level",
        fidelity_level=level,
        status="available",
        origin="bundled",
        missing_dependencies=(),
        actionable_message=f"{public_name} is provided by the bundled base.",
    )


def _unavailable_future_level(level: str, public_name: str) -> CapabilityStatus:
    if level == "L3":
        message = (
            f"Complete {public_name} is unavailable; material-aware "
            "ray/transmission occlusion remains bundled."
        )
    else:
        message = f"{public_name} is not a released runtime capability in Stage 1."
    return CapabilityStatus(
        capability_id=level,
        kind="fidelity_level",
        fidelity_level=level,
        status="unavailable",
        origin="absent",
        missing_dependencies=(),
        actionable_message=message,
    )


def discover_capabilities() -> CapabilityReport:
    """Discover bundled, external, and absent capabilities."""

    backend_declarations = get_default_registry().declarations(
        "propagation_backend"
    )
    optional_backends = tuple(
        _probe_optional(
            capability_id=declaration.plugin_id,
            kind="backend",
            fidelity_level=declaration.fidelity_level or "",
            dependencies=declaration.required_dependencies,
        )
        for declaration in backend_declarations
        if declaration.required_dependencies
    )
    backend_capabilities = {
        capability.capability_id: capability for capability in optional_backends
    }
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
            level_capabilities = tuple(
                backend_capabilities[declaration.plugin_id]
                for declaration in backend_declarations
                if declaration.fidelity_level == level
                and declaration.plugin_id in backend_capabilities
            )
            available = bool(level_capabilities) and all(
                item.available for item in level_capabilities
            )
            origins = {item.origin for item in level_capabilities}
            origin = origins.pop() if available and len(origins) == 1 else "absent"
            missing = tuple(
                sorted(
                    {
                        dependency
                        for capability in level_capabilities
                        for dependency in capability.missing_dependencies
                    }
                )
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
                            "Install isaac-audio-sensors[room] to enable the "
                            "L2 room backends."
                        )
                    ),
                )
            )
        else:
            fidelity_levels.append(
                _unavailable_future_level(level, metadata.public_name)
            )

    return CapabilityReport(
        fidelity_levels=tuple(fidelity_levels),
        optional_features=(*optional_backends, waveform_wav, waveform_flac),
    )


__all__ = ["CapabilityReport", "CapabilityStatus", "discover_capabilities"]
