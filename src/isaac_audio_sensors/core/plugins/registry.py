"""Capability-aware registry for import-safe audio plugins."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from isaac_audio_sensors.core.constants import DEFAULT_RUNTIME_PROFILE
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.plugins.adapters import (
    GccPhatLeastSquaresEstimator,
    SrpPhatEstimator,
)
from isaac_audio_sensors.core.plugins.declarations import (
    PLUGIN_KINDS,
    PluginDeclaration,
)
from isaac_audio_sensors.core.plugins.protocols import (
    ActivityDetector,
    AudioFeatureExtractor,
    DoaEstimator,
    PropagationBackend,
)
from isaac_audio_sensors.core.plugins.pyroomacoustics import (
    PyroomacousticsSrpEstimator,
)

PluginFactory = Callable[..., object]


@dataclass(frozen=True, slots=True)
class PluginAvailability:
    """Current dependency availability recorded for one plugin."""

    available: bool
    missing_dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Registration:
    declaration: PluginDeclaration
    factory: PluginFactory


class PluginRegistry:
    """Capability-aware registry for structural audio plugin contracts.

    Dependency names are located, without importing their modules, when a
    plugin is registered. ``probe_availability`` and ``resolve`` perform the
    authoritative import probe. A missing dependency never prevents
    registration, so capability reports retain unavailable plugin entries.
    """

    def __init__(self) -> None:
        self._registrations: dict[str, dict[str, _Registration]] = {
            kind: {} for kind in PLUGIN_KINDS
        }
        self._availability: dict[tuple[str, str], PluginAvailability] = {}

    def register(
        self,
        declaration: PluginDeclaration,
        factory: PluginFactory,
    ) -> None:
        """Register one unique declaration and callable factory."""

        if not isinstance(declaration, PluginDeclaration):
            raise ConfigValidationError(
                "PluginRegistry.register requires a PluginDeclaration."
            )
        if declaration.kind not in self._registrations:
            raise ConfigValidationError(
                f"Unknown plugin kind {declaration.kind!r}; expected one of "
                f"{list(PLUGIN_KINDS)}."
            )
        if not callable(factory):
            raise ConfigValidationError(
                f"Factory for plugin {declaration.plugin_id!r} must be callable."
            )
        registrations = self._registrations[declaration.kind]
        if declaration.plugin_id in registrations:
            raise ConfigValidationError(
                f"Duplicate {declaration.kind} plugin id "
                f"{declaration.plugin_id!r}."
            )

        registrations[declaration.plugin_id] = _Registration(declaration, factory)
        self._availability[(declaration.kind, declaration.plugin_id)] = (
            _locate_dependencies(declaration.required_dependencies)
        )

    def declarations(self, kind: str | None = None) -> tuple[PluginDeclaration, ...]:
        """Return declarations in deterministic kind/id order."""

        if kind is not None:
            self._require_kind(kind)
            return tuple(
                registration.declaration
                for _plugin_id, registration in sorted(
                    self._registrations[kind].items()
                )
            )
        return tuple(
            registration.declaration
            for plugin_kind in PLUGIN_KINDS
            for _plugin_id, registration in sorted(
                self._registrations[plugin_kind].items()
            )
        )

    def probe_availability(
        self,
        kind: str,
        plugin_id: str,
    ) -> PluginAvailability:
        """Import required dependencies and record their current availability."""

        registration = self._registration(kind, plugin_id)
        availability = _import_dependencies(
            registration.declaration.required_dependencies
        )
        self._availability[(kind, plugin_id)] = availability
        return availability

    def availability(self, kind: str, plugin_id: str) -> PluginAvailability:
        """Return the last recorded non-importing or explicit probe state."""

        self._registration(kind, plugin_id)
        return self._availability[(kind, plugin_id)]

    def resolve(
        self,
        kind: str,
        plugin_id: str,
        *,
        device: str = "cpu",
        runtime_profile: str = DEFAULT_RUNTIME_PROFILE,
        factory_kwargs: Mapping[str, object] | None = None,
        **factory_overrides: object,
    ) -> object:
        """Validate capabilities and instantiate one registered plugin."""

        registration = self._registration(kind, plugin_id)
        declaration = registration.declaration
        if device not in declaration.supported_devices:
            raise ConfigValidationError(
                f"Plugin {plugin_id!r} ({kind}) does not support device {device!r}; "
                f"supported devices: {list(declaration.supported_devices)}."
            )
        if runtime_profile not in declaration.supported_profiles:
            raise ConfigValidationError(
                f"Plugin {plugin_id!r} ({kind}) does not support runtime profile "
                f"{runtime_profile!r}; supported profiles: "
                f"{list(declaration.supported_profiles)}."
            )
        availability = self.probe_availability(kind, plugin_id)
        if not availability.available:
            missing = ", ".join(
                repr(item) for item in availability.missing_dependencies
            )
            raise ConfigValidationError(
                f"Plugin {plugin_id!r} ({kind}) is unavailable because required "
                f"dependency {missing} could not be imported. Install the plugin's "
                "optional dependencies and retry."
            )
        construction_kwargs = dict(factory_kwargs or {})
        overlap = construction_kwargs.keys() & factory_overrides.keys()
        if overlap:
            raise ConfigValidationError(
                f"Duplicate factory kwargs for plugin {plugin_id!r}: "
                f"{sorted(overlap)}."
            )
        construction_kwargs.update(factory_overrides)
        try:
            instance = registration.factory(**construction_kwargs)
        except Exception as exc:
            raise ConfigValidationError(
                f"Factory for plugin {plugin_id!r} ({kind}) failed: {exc}"
            ) from exc
        _validate_instance(declaration, instance)
        return instance

    def _require_kind(self, kind: str) -> None:
        if kind not in self._registrations:
            raise ConfigValidationError(
                f"Unknown plugin kind {kind!r}; expected one of {list(PLUGIN_KINDS)}."
            )

    def _registration(self, kind: str, plugin_id: str) -> _Registration:
        self._require_kind(kind)
        try:
            return self._registrations[kind][plugin_id]
        except KeyError as exc:
            known = sorted(self._registrations[kind])
            raise ConfigValidationError(
                f"Unknown {kind} plugin id {plugin_id!r}; registered ids: {known}."
            ) from exc


def _validate_instance(declaration: PluginDeclaration, instance: object) -> None:
    if declaration.kind == "propagation_backend":
        if not isinstance(instance, PropagationBackend):
            raise ConfigValidationError(
                f"Plugin {declaration.plugin_id!r} does not satisfy "
                "PropagationBackend."
            )
        if instance.backend_id != declaration.plugin_id:
            raise ConfigValidationError(
                f"Plugin {declaration.plugin_id!r} factory produced backend id "
                f"{instance.backend_id!r}."
            )
        return
    if declaration.kind == "activity_detector":
        if not isinstance(instance, ActivityDetector):
            raise ConfigValidationError(
                f"Plugin {declaration.plugin_id!r} does not satisfy "
                "ActivityDetector."
            )
        if instance.detector_id != declaration.plugin_id:
            raise ConfigValidationError(
                f"Plugin {declaration.plugin_id!r} factory produced detector id "
                f"{instance.detector_id!r}."
            )
        return
    if declaration.kind == "doa_estimator":
        if not isinstance(instance, DoaEstimator):
            raise ConfigValidationError(
                f"Plugin {declaration.plugin_id!r} does not satisfy DoaEstimator."
            )
        return
    if not isinstance(instance, AudioFeatureExtractor):
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} does not satisfy AudioFeatureExtractor."
        )


def _locate_dependencies(dependencies: tuple[str, ...]) -> PluginAvailability:
    missing: list[str] = []
    for dependency in dependencies:
        try:
            located = importlib.util.find_spec(dependency) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            located = False
        if not located:
            missing.append(dependency)
    return PluginAvailability(not missing, tuple(missing))


def _import_dependencies(dependencies: tuple[str, ...]) -> PluginAvailability:
    missing: list[str] = []
    for dependency in dependencies:
        try:
            importlib.import_module(dependency)
        except ImportError:
            missing.append(dependency)
    return PluginAvailability(not missing, tuple(missing))


def _lazy_analytic_backend(**kwargs: object) -> object:
    from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics

    return AnalyticAcoustics(**kwargs)


def _lazy_auditok_detector(**kwargs: object) -> object:
    from isaac_audio_sensors.core.plugins.auditok import AuditokActivityDetector

    return AuditokActivityDetector(**kwargs)


def _built_in_declarations() -> tuple[tuple[PluginDeclaration, PluginFactory], ...]:
    both_profiles = ("training_features", "waveform_fidelity")
    backend_contract = {
        "shape": "MicrophoneSignalBlock",
        "dtype": "MicrophoneSignalBlock",
    }
    doa_contract = {"shape": (), "dtype": "DoaEstimate"}
    activity_contract = {"shape": (), "dtype": "ActivityDecision"}
    return (
        (
            PluginDeclaration(
                plugin_id="analytic_acoustics",
                kind="propagation_backend",
                fidelity_level="L2",
                required_dependencies=(),
                supported_devices=("cpu",),
                supported_profiles=("waveform_fidelity",),
                deterministic=True,
                output_contract=backend_contract,
                description=(
                    "Environment-routed analytic propagation with optional "
                    "closed-room solvers."
                ),
                provenance="isaac_audio_sensors.core.backends.analytic",
            ),
            _lazy_analytic_backend,
        ),
        (
            PluginDeclaration(
                plugin_id="auditok",
                kind="activity_detector",
                fidelity_level=None,
                required_dependencies=("auditok",),
                supported_devices=("cpu",),
                supported_profiles=both_profiles,
                deterministic=True,
                output_contract=activity_contract,
                description="Fixed-threshold generic acoustic activity detection.",
                provenance="isaac_audio_sensors.core.plugins.auditok",
            ),
            _lazy_auditok_detector,
        ),
        (
            PluginDeclaration(
                plugin_id="tdoa_least_squares",
                kind="doa_estimator",
                fidelity_level=None,
                required_dependencies=(),
                supported_devices=("cpu",),
                supported_profiles=both_profiles,
                deterministic=True,
                output_contract=doa_contract,
                description="GCC-PHAT pair delays with least-squares direction.",
                provenance="isaac_audio_sensors.core.doa.gcc_phat",
            ),
            GccPhatLeastSquaresEstimator,
        ),
        (
            PluginDeclaration(
                plugin_id="pyroomacoustics_srp",
                kind="doa_estimator",
                fidelity_level=None,
                required_dependencies=("pyroomacoustics",),
                supported_devices=("cpu",),
                supported_profiles=both_profiles,
                deterministic=True,
                output_contract=doa_contract,
                description="PyRoomAcoustics SRP-PHAT direction candidate.",
                provenance="isaac_audio_sensors.core.plugins.pyroomacoustics",
            ),
            PyroomacousticsSrpEstimator,
        ),
        (
            PluginDeclaration(
                plugin_id="srp_phat",
                kind="doa_estimator",
                fidelity_level=None,
                required_dependencies=(),
                supported_devices=("cpu",),
                supported_profiles=both_profiles,
                deterministic=True,
                output_contract=doa_contract,
                description="Deterministic steered-response-power PHAT direction.",
                provenance="isaac_audio_sensors.core.doa.srp_phat",
            ),
            SrpPhatEstimator,
        ),
    )


_DEFAULT_REGISTRY = PluginRegistry()
for _declaration, _factory in _built_in_declarations():
    _DEFAULT_REGISTRY.register(_declaration, _factory)


def get_default_registry() -> PluginRegistry:
    """Return the process-wide registry populated with built-in plugins."""

    return _DEFAULT_REGISTRY


__all__ = [
    "PluginAvailability",
    "PluginFactory",
    "PluginRegistry",
    "get_default_registry",
]
