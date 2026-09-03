from __future__ import annotations

import inspect

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.backends.base import get_backend, registered_backend_ids
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.plugins import (
    AudioFeatureExtractor,
    DoaEstimator,
    PluginDeclaration,
    PluginRegistry,
    PropagationBackend,
    get_default_registry,
)


class _MeanFeatureExtractor:
    def extract(self, samples, sample_rate_hz):
        del sample_rate_hz
        return np.mean(samples, axis=1, dtype=np.float32), {"statistic": "mean"}


class _WrongBackend:
    backend_id = "different"

    def propagate(self, scene, array_id, time_window):
        del scene, array_id, time_window


def _feature_declaration(
    plugin_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    devices: tuple[str, ...] = ("cpu",),
) -> PluginDeclaration:
    return PluginDeclaration(
        plugin_id=plugin_id,
        kind="audio_feature_extractor",
        fidelity_level=None,
        required_dependencies=dependencies,
        supported_devices=devices,
        supported_profiles=("training_features",),
        deterministic=True,
        output_contract={"shape": (4,), "dtype": "float32"},
        description="Test feature extractor.",
        provenance="tests.contract.test_plugins",
    )


def _propagation_declaration(plugin_id: str) -> PluginDeclaration:
    return PluginDeclaration(
        plugin_id=plugin_id,
        kind="propagation_backend",
        fidelity_level="L2",
        required_dependencies=(),
        supported_devices=("cpu",),
        supported_profiles=("waveform_fidelity",),
        deterministic=True,
        output_contract={
            "shape": "MicrophoneSignalBlock",
            "dtype": "MicrophoneSignalBlock",
        },
        description="Test propagation backend.",
        provenance="tests.contract.test_plugins",
    )


def test_protocols_and_canonical_signature() -> None:
    assert isinstance(AnalyticAcoustics(), PropagationBackend)
    assert isinstance(_MeanFeatureExtractor(), AudioFeatureExtractor)
    assert tuple(inspect.signature(AnalyticAcoustics.propagate).parameters) == (
        "self",
        "scene",
        "array_id",
        "time_window",
    )
    registry = get_default_registry()
    assert isinstance(
        registry.resolve("doa_estimator", "tdoa_least_squares"),
        DoaEstimator,
    )
    assert isinstance(registry.resolve("doa_estimator", "srp_phat"), DoaEstimator)


def test_registry_validation_and_dependency_errors() -> None:
    registry = PluginRegistry()
    declaration = _feature_declaration("mean_feature")
    registry.register(declaration, _MeanFeatureExtractor)
    with pytest.raises(ConfigValidationError, match="Duplicate.*mean_feature"):
        registry.register(declaration, _MeanFeatureExtractor)
    with pytest.raises(ConfigValidationError, match="Unknown plugin kind"):
        registry.resolve("classifier", "missing")

    dependency = "isaac_audio_sensors_dependency_that_does_not_exist"
    registry.register(
        _feature_declaration("missing_dep", dependencies=(dependency,)),
        _MeanFeatureExtractor,
    )
    with pytest.raises(ConfigValidationError, match=dependency):
        registry.resolve(
            "audio_feature_extractor",
            "missing_dep",
            runtime_profile="training_features",
        )


def test_registry_rejects_capability_and_factory_mismatches() -> None:
    registry = PluginRegistry()
    registry.register(_feature_declaration("mean_feature"), _MeanFeatureExtractor)
    with pytest.raises(ConfigValidationError, match="does not support device 'cuda'"):
        registry.resolve(
            "audio_feature_extractor",
            "mean_feature",
            device="cuda",
            runtime_profile="training_features",
        )
    registry.register(_feature_declaration("invalid_feature"), object)
    with pytest.raises(ConfigValidationError, match="AudioFeatureExtractor"):
        registry.resolve(
            "audio_feature_extractor",
            "invalid_feature",
            runtime_profile="training_features",
        )
    registry.register(_propagation_declaration("wrong_backend_id"), _WrongBackend)
    with pytest.raises(ConfigValidationError, match="produced backend id"):
        registry.resolve("propagation_backend", "wrong_backend_id")


def test_default_registry_exposes_only_analytic_runtime_backend() -> None:
    declarations = {
        (item.kind, item.plugin_id): item
        for item in get_default_registry().declarations()
    }
    assert set(declarations) == {
        ("propagation_backend", "analytic_acoustics"),
        ("doa_estimator", "tdoa_least_squares"),
        ("doa_estimator", "srp_phat"),
    }
    analytic = declarations[("propagation_backend", "analytic_acoustics")]
    assert analytic.fidelity_level == "L2"
    assert analytic.required_dependencies == ()
    assert analytic.supported_profiles == ("waveform_fidelity",)
    assert dict(analytic.output_contract) == {
        "shape": "MicrophoneSignalBlock",
        "dtype": "MicrophoneSignalBlock",
    }
    assert registered_backend_ids() == ("analytic_acoustics",)
    assert isinstance(get_backend("analytic_acoustics"), AnalyticAcoustics)


@pytest.mark.parametrize(
    "legacy_id",
    ("geometry_only", "tdoa_synthetic", "room_acoustics", "room_acoustics_srp"),
)
def test_removed_runtime_backend_ids_fail_without_aliases(legacy_id: str) -> None:
    message = f"Unknown audio simulation backend '{legacy_id}'"
    with pytest.raises(ValueError, match=message):
        get_backend(legacy_id)


@pytest.mark.parametrize(
    "module_name",
    (
        "isaac_audio_sensors.core.backends.geometry",
        "isaac_audio_sensors.core.backends.tdoa",
        "isaac_audio_sensors.core.backends.room_acoustics",
    ),
)
def test_removed_backend_modules_are_not_importable(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        __import__(module_name)
