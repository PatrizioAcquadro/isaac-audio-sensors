"""Capability-aware registry for import-safe audio plugins."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass

import numpy as np

from isaac_audio_sensors.core.constants import DEFAULT_RUNTIME_PROFILE
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.plugins.adapters import (
    GccPhatLeastSquaresEstimator,
    SrpPhatEstimator,
)
from isaac_audio_sensors.core.plugins.declarations import (
    PLUGIN_KINDS,
    PluginDeclaration,
)
from isaac_audio_sensors.core.plugins.protocols import (
    AudioFeatureExtractor,
    DoaEstimator,
    PropagationBackend,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    DoaEstimate,
    RoomAcousticsSpec,
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
    """Registry with fail-closed capability and self-test validation.

    Dependency names are located, without importing their modules, when a
    plugin is registered. ``probe_availability`` and ``resolve`` perform the
    authoritative import probe. A missing dependency never prevents
    registration, so capability reports retain unavailable plugin entries.
    """

    def __init__(self, *, validate_on_register: bool = True) -> None:
        self._registrations: dict[str, dict[str, _Registration]] = {
            kind: {} for kind in PLUGIN_KINDS
        }
        self._availability: dict[tuple[str, str], PluginAvailability] = {}
        self._validated: set[tuple[str, str]] = set()
        self._validate_on_register = validate_on_register

    def register(
        self,
        declaration: PluginDeclaration,
        factory: PluginFactory,
    ) -> None:
        """Register one declaration and reject ids or factories that lie."""

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

        availability = _locate_dependencies(declaration.required_dependencies)
        if self._validate_on_register and availability.available:
            validate_declaration(declaration, factory)
            self._validated.add((declaration.kind, declaration.plugin_id))
        registrations[declaration.plugin_id] = _Registration(declaration, factory)
        self._availability[(declaration.kind, declaration.plugin_id)] = availability

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
        **factory_kwargs: object,
    ) -> object:
        """Validate capabilities and instantiate one registered plugin."""

        registration = self._registration(kind, plugin_id)
        declaration = registration.declaration
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
        registration_key = (kind, plugin_id)
        if registration_key not in self._validated:
            validate_declaration(declaration, registration.factory)
            self._validated.add(registration_key)
        return registration.factory(**factory_kwargs)

    def instantiate_registered(
        self,
        kind: str,
        plugin_id: str,
        **factory_kwargs: object,
    ) -> object:
        """Instantiate a known id without eager capability resolution.

        This compatibility path preserves the historical ``get_backend``
        behavior: optional room dependencies are checked by ``simulate``, not
        by backend object construction. New plugin consumers should use
        ``resolve`` so capability mismatches fail before construction.
        """

        registration = self._registration(kind, plugin_id)
        return registration.factory(**factory_kwargs)

    def validate_declaration(
        self,
        declaration: PluginDeclaration,
        factory: PluginFactory,
    ) -> None:
        """Run the public factory shape and determinism self-test hook."""

        validate_declaration(declaration, factory)

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


def validate_declaration(
    declaration: PluginDeclaration,
    factory: PluginFactory,
) -> None:
    """Validate structural output, declared shape/dtype, and determinism."""

    if not callable(factory):
        raise ConfigValidationError(
            f"Factory for plugin {declaration.plugin_id!r} must be callable."
        )
    try:
        instance = factory()
    except Exception as exc:
        raise ConfigValidationError(
            f"Factory self-test for plugin {declaration.plugin_id!r} failed: {exc}"
        ) from exc

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
        if declaration.output_contract != {
            "shape": "AudioSensorFrame",
            "dtype": "AudioSensorFrame",
        }:
            raise ConfigValidationError(
                f"Plugin {declaration.plugin_id!r} has an invalid propagation "
                "output_contract."
            )
        if declaration.deterministic:
            fixture = _propagation_fixture()
            first = _run_propagation_plugin(declaration, instance, fixture)
            try:
                second_instance = factory()
            except Exception as exc:
                raise ConfigValidationError(
                    f"Determinism self-test for plugin {declaration.plugin_id!r} "
                    f"failed: {exc}"
                ) from exc
            second = _run_propagation_plugin(
                declaration, second_instance, fixture
            )
            if not _outputs_equal(first, second):
                raise ConfigValidationError(
                    f"Plugin {declaration.plugin_id!r} declares "
                    "deterministic=True but returned different or "
                    "unverifiable AudioSensorFrame results for identical inputs."
                )
        return

    fixture = _signal_fixture()
    first = _run_signal_plugin(declaration, instance, fixture)
    _validate_signal_output(declaration, first)
    if declaration.deterministic:
        try:
            second_instance = factory()
            second = _run_signal_plugin(declaration, second_instance, fixture)
        except Exception as exc:
            raise ConfigValidationError(
                f"Determinism self-test for plugin {declaration.plugin_id!r} "
                f"failed: {exc}"
            ) from exc
        _validate_signal_output(declaration, second)
        if not _outputs_equal(first, second):
            raise ConfigValidationError(
                f"Plugin {declaration.plugin_id!r} declares deterministic=True "
                "but returned different results for identical seeded inputs."
            )


def _run_signal_plugin(
    declaration: PluginDeclaration,
    instance: object,
    fixture: tuple[np.ndarray, np.ndarray, int],
) -> object:
    samples, positions, sample_rate_hz = fixture
    try:
        if declaration.kind == "doa_estimator":
            if not isinstance(instance, DoaEstimator):
                raise ConfigValidationError(
                    f"Plugin {declaration.plugin_id!r} does not satisfy DoaEstimator."
                )
            return instance.estimate(samples.copy(), positions.copy(), sample_rate_hz)
        if not isinstance(instance, AudioFeatureExtractor):
            raise ConfigValidationError(
                f"Plugin {declaration.plugin_id!r} does not satisfy "
                "AudioFeatureExtractor."
            )
        return instance.extract(samples.copy(), sample_rate_hz)
    except ConfigValidationError:
        raise
    except Exception as exc:
        raise ConfigValidationError(
            f"Self-test execution for plugin {declaration.plugin_id!r} failed: {exc}"
        ) from exc


def _run_propagation_plugin(
    declaration: PluginDeclaration,
    instance: object,
    fixture: tuple[AudioSceneSnapshot, object, AudioTimeWindow],
) -> AudioSensorFrame:
    scene, sensor, time_window = fixture
    if not isinstance(instance, PropagationBackend):
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} does not satisfy PropagationBackend."
        )
    if instance.backend_id != declaration.plugin_id:
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} factory produced backend id "
            f"{instance.backend_id!r}."
        )
    try:
        output = instance.simulate(scene, sensor, time_window)  # type: ignore[arg-type]
    except Exception as exc:
        raise ConfigValidationError(
            f"Determinism self-test for plugin {declaration.plugin_id!r} "
            f"could not execute: {exc}"
        ) from exc
    if not isinstance(output, AudioSensorFrame):
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} returned {type(output).__name__}; "
            "expected AudioSensorFrame."
        )
    if output.backend_id != declaration.plugin_id:
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} returned frame backend id "
            f"{output.backend_id!r}."
        )
    return output


def _propagation_fixture() -> tuple[AudioSceneSnapshot, object, AudioTimeWindow]:
    sensor = create_microphone_array(
        array_id="plugin_validation_array",
        prim_path="/World/PluginValidation/Array",
        layout_name="quad_cross",
        position_world=(2.0, 2.0, 1.0),
        sample_rate_hz=8_000,
    )
    source = AudioSourceSpec(
        source_id="plugin_validation_impulse",
        prim_path="/World/PluginValidation/Source",
        class_label="impulse",
        audio_asset_path="generated://impulse",
        position_world=(3.0, 2.0, 1.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        start_time_s=0.0,
        duration_s=0.02,
        gain_db=0.0,
    )
    scene = AudioSceneSnapshot(
        stage_id="plugin_validation_scene",
        timestamp_ms=0,
        sources=(source,),
        arrays=(sensor,),
        room=RoomAcousticsSpec(
            room_id="plugin_validation_room",
            dimensions_m=(6.0, 5.0, 3.0),
            absorption=0.3,
            max_order=1,
        ),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=0.02,
        timestamp_ms=0,
        sample_rate_hz=sensor.sample_rate_hz,
        frame_index=0,
        max_events=1,
    )
    return scene, sensor, window


def _validate_signal_output(
    declaration: PluginDeclaration,
    output: object,
) -> None:
    if not isinstance(output, tuple) or len(output) != 2:
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} must return a (result, diagnostics) "
            "tuple."
        )
    result, diagnostics = output
    if not isinstance(diagnostics, dict):
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} diagnostics must be a dict."
        )
    contract = declaration.output_contract
    if declaration.kind == "doa_estimator":
        if not isinstance(result, DoaEstimate):
            raise ConfigValidationError(
                f"Plugin {declaration.plugin_id!r} output shape/type does not match "
                "declared scalar DoaEstimate contract."
            )
        if contract["shape"] != () or contract["dtype"] != "DoaEstimate":
            raise ConfigValidationError(
                f"Plugin {declaration.plugin_id!r} has an invalid DOA output_contract."
            )
        return

    if not isinstance(result, np.ndarray):
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} feature result must be a numpy ndarray."
        )
    expected_shape = tuple(contract["shape"])
    if result.shape != expected_shape:
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} returned feature shape {result.shape}; "
            f"declared shape is {expected_shape}."
        )
    try:
        expected_dtype = np.dtype(contract["dtype"])
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} declares invalid NumPy dtype "
            f"{contract['dtype']!r}."
        ) from exc
    if result.dtype != expected_dtype:
        raise ConfigValidationError(
            f"Plugin {declaration.plugin_id!r} returned dtype {result.dtype}; "
            f"declared dtype is {expected_dtype}."
        )


def _signal_fixture() -> tuple[np.ndarray, np.ndarray, int]:
    sample_rate_hz = 8_000
    rng = np.random.default_rng(20260717)
    source = rng.standard_normal(256)
    samples = np.stack(
        (
            source,
            np.roll(source, 1),
            np.roll(source, 2),
            np.roll(source, 1),
        )
    )
    positions = np.asarray(
        (
            (0.04, 0.0, 0.0),
            (0.0, 0.04, 0.0),
            (-0.04, 0.0, 0.0),
            (0.0, -0.04, 0.0),
        ),
        dtype=float,
    )
    return samples, positions, sample_rate_hz


def _outputs_equal(left: object, right: object) -> bool:
    if isinstance(left, np.ndarray) and isinstance(right, np.ndarray):
        return bool(np.array_equal(left, right, equal_nan=True))
    if is_dataclass(left) and is_dataclass(right) and type(left) is type(right):
        return all(
            _outputs_equal(getattr(left, field.name), getattr(right, field.name))
            for field in fields(left)
        )
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            _outputs_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, (tuple, list)) and isinstance(right, type(left)):
        return len(left) == len(right) and all(
            _outputs_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    try:
        equal = left == right
    except (TypeError, ValueError):
        return False
    return bool(equal) if isinstance(equal, (bool, np.bool_)) else False


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


def _lazy_geometry_backend(**kwargs: object) -> object:
    from isaac_audio_sensors.core.backends.geometry import GeometryBackend

    return GeometryBackend(**kwargs)


def _lazy_tdoa_backend(**kwargs: object) -> object:
    from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend

    return TdoaSyntheticBackend(**kwargs)


def _lazy_room_backend(**kwargs: object) -> object:
    from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend

    return RoomAcousticsBackend(**kwargs)


def _lazy_room_srp_backend(**kwargs: object) -> object:
    from isaac_audio_sensors.core.backends.room_acoustics import (
        RoomAcousticsSrpBackend,
    )

    return RoomAcousticsSrpBackend(**kwargs)


def _built_in_declarations() -> tuple[tuple[PluginDeclaration, PluginFactory], ...]:
    both_profiles = ("training_features", "waveform_fidelity")
    backend_contract = {"shape": "AudioSensorFrame", "dtype": "AudioSensorFrame"}
    doa_contract = {"shape": (), "dtype": "DoaEstimate"}
    return (
        (
            PluginDeclaration(
                plugin_id="geometry_only",
                kind="propagation_backend",
                fidelity_level="L0",
                required_dependencies=(),
                supported_devices=("cpu",),
                supported_profiles=both_profiles,
                deterministic=True,
                output_contract=backend_contract,
                description="Deterministic geometry-only bearing baseline.",
                provenance="isaac_audio_sensors.core.backends.geometry",
            ),
            _lazy_geometry_backend,
        ),
        (
            PluginDeclaration(
                plugin_id="tdoa_synthetic",
                kind="propagation_backend",
                fidelity_level="L1",
                required_dependencies=(),
                supported_devices=("cpu",),
                supported_profiles=both_profiles,
                deterministic=True,
                output_contract=backend_contract,
                description="Seeded deterministic synthetic direct-path TDOA.",
                provenance="isaac_audio_sensors.core.backends.tdoa",
            ),
            _lazy_tdoa_backend,
        ),
        (
            PluginDeclaration(
                plugin_id="room_acoustics",
                kind="propagation_backend",
                fidelity_level="L2",
                required_dependencies=("pyroomacoustics",),
                supported_devices=("cpu",),
                supported_profiles=("waveform_fidelity",),
                deterministic=True,
                output_contract=backend_contract,
                description=(
                    "Seed-stable optional shoebox room acoustics with GCC-PHAT."
                ),
                provenance="isaac_audio_sensors.core.backends.room_acoustics",
            ),
            _lazy_room_backend,
        ),
        (
            PluginDeclaration(
                plugin_id="room_acoustics_srp",
                kind="propagation_backend",
                fidelity_level="L2",
                required_dependencies=("pyroomacoustics",),
                supported_devices=("cpu",),
                supported_profiles=("waveform_fidelity",),
                deterministic=True,
                output_contract=backend_contract,
                description="Seed-stable optional room acoustics with SRP-PHAT DOA.",
                provenance="isaac_audio_sensors.core.backends.room_acoustics",
            ),
            _lazy_room_srp_backend,
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


_DEFAULT_REGISTRY = PluginRegistry(validate_on_register=False)
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
    "validate_declaration",
]
