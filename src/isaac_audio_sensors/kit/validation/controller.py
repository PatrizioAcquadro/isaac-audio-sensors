"""Stateful capability, device, and calibration validation."""

from __future__ import annotations

from dataclasses import dataclass

from isaac_audio_sensors.core.capabilities import (
    CapabilityReport,
    discover_capabilities,
)

from .checks import (
    check_backend_available,
    check_calibration_profile,
    check_device_supported,
)
from .results import ValidationReport


@dataclass(frozen=True, slots=True)
class CapabilityState:
    """One immutable capability-discovery snapshot."""

    capabilities: CapabilityReport
    available_backend_ids: tuple[str, ...]
    captured_at_generation: int


def _available_backend_ids(report: CapabilityReport) -> tuple[str, ...]:
    from isaac_audio_sensors.core.backends.base import registered_backend_ids

    optional = {
        capability.capability_id: capability.available
        for capability in report.optional_features
        if capability.kind == "backend"
    }
    return tuple(
        backend_id
        for backend_id in registered_backend_ids()
        if optional.get(backend_id, True)
    )


class ValidationController:
    """Cache expensive capability facts and validate stateful dependencies."""

    def __init__(self) -> None:
        self._capability_state: CapabilityState | None = None
        self._capability_generation = 0
        self._capabilities_stale = False
        self._capability_invalidation_reason: str | None = None

    @property
    def capability_state(self) -> CapabilityState:
        if self._capability_state is None:
            raise RuntimeError(
                "Capability state has never been refreshed; call "
                "refresh_capabilities(reason) first."
            )
        if self._capabilities_stale:
            reason = self._capability_invalidation_reason or "unspecified change"
            return self.refresh_capabilities(
                f"lazy refresh after invalidation: {reason}"
            )
        return self._capability_state

    def refresh_capabilities(self, reason: str) -> CapabilityState:
        """Discover optional capabilities and cache one fresh snapshot."""

        del reason
        report = discover_capabilities()
        generation = self._capability_generation + 1
        snapshot = CapabilityState(
            capabilities=report,
            available_backend_ids=_available_backend_ids(report),
            captured_at_generation=generation,
        )
        self._capability_generation = generation
        self._capability_state = snapshot
        self._capabilities_stale = False
        self._capability_invalidation_reason = None
        return snapshot

    def invalidate(self, reason: str) -> None:
        self._capabilities_stale = True
        self._capability_invalidation_reason = reason

    def validate_backend_available(self, backend_id: str) -> ValidationReport:
        if self._capability_state is None:
            state = self.refresh_capabilities(
                f"initial backend availability validation: {backend_id}"
            )
        else:
            state = self.capability_state
        try:
            capability = state.capabilities.get(backend_id)
        except KeyError:
            actionable_message = ""
        else:
            actionable_message = capability.actionable_message
        return ValidationReport(
            check_backend_available(
                backend_id,
                state.available_backend_ids,
                actionable_message=actionable_message,
            )
        )

    def validate_backend_device(self, backend_id: str, device: str) -> ValidationReport:
        from isaac_audio_sensors.core.plugins.registry import get_default_registry

        supported: tuple[str, ...] = ()
        for declaration in get_default_registry().declarations("propagation_backend"):
            if declaration.plugin_id == backend_id:
                supported = declaration.supported_devices
                break
        return ValidationReport(check_device_supported(backend_id, device, supported))

    def validate_calibration_profile(
        self,
        profile_path: str,
        array_spec_like: object,
    ) -> ValidationReport:
        requested = profile_path.strip()
        if not requested:
            return ValidationReport()
        from isaac_audio_sensors.core.calibration_profile import (
            check_profile_compatibility,
        )
        from isaac_audio_sensors.core.io.calibration import read_calibration_profile

        try:
            profile = read_calibration_profile(requested)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return ValidationReport(
                check_calibration_profile(requested, read_error=str(exc))
            )
        try:
            check_profile_compatibility(profile, array_spec_like)
        except ValueError as exc:
            return ValidationReport(
                check_calibration_profile(
                    requested,
                    compatibility_error=str(exc),
                )
            )
        return ValidationReport(check_calibration_profile(requested))


__all__ = ["CapabilityState", "ValidationController"]
