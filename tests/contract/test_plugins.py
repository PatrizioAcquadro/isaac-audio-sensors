from __future__ import annotations

import inspect
import subprocess
import sys

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.backends.base import get_backend, registered_backend_ids
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.plugins import (
    ActivityDetector,
    AudioFeatureExtractor,
    AuditokActivityDetector,
    DoaEstimator,
    PluginDeclaration,
    PluginRegistry,
    PropagationBackend,
    PyroomacousticsSrpEstimator,
    get_default_registry,
)
from isaac_audio_sensors.core.types import ActivityDecision, DoaEstimate


class _ActivityDetector:
    detector_id = "test_activity"

    def detect(self, samples, sample_rate_hz):
        del samples, sample_rate_hz
        return ActivityDecision(active=False)

    def reset(self) -> None:
        pass


class _WrongDetectorId(_ActivityDetector):
    detector_id = "different"


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


def _activity_declaration(plugin_id: str = "test_activity") -> PluginDeclaration:
    return PluginDeclaration(
        plugin_id=plugin_id,
        kind="activity_detector",
        fidelity_level=None,
        required_dependencies=(),
        supported_devices=("cpu",),
        supported_profiles=("waveform_fidelity",),
        deterministic=True,
        output_contract={"shape": (), "dtype": "ActivityDecision"},
        description="Test activity detector.",
        provenance="tests.contract.test_plugins",
    )


def test_protocols_and_canonical_signature() -> None:
    assert isinstance(AnalyticAcoustics(), PropagationBackend)
    assert isinstance(_ActivityDetector(), ActivityDetector)
    assert isinstance(_MeanFeatureExtractor(), AudioFeatureExtractor)
    assert tuple(inspect.signature(AnalyticAcoustics.propagate).parameters) == (
        "self",
        "scene",
        "array_id",
        "time_window",
    )
    assert tuple(inspect.signature(DoaEstimator.estimate).parameters) == (
        "self",
        "samples",
        "microphone_positions_m",
        "sample_rate_hz",
    )
    registry = get_default_registry()
    assert isinstance(
        registry.resolve("doa_estimator", "tdoa_least_squares"),
        DoaEstimator,
    )
    assert isinstance(registry.resolve("doa_estimator", "srp_phat"), DoaEstimator)
    pyroom = {
        item.plugin_id: item for item in registry.declarations("doa_estimator")
    }
    assert pyroom["pyroomacoustics_srp"].required_dependencies == (
        "pyroomacoustics",
    )
    if registry.availability("doa_estimator", "pyroomacoustics_srp").available:
        assert isinstance(
            registry.resolve("doa_estimator", "pyroomacoustics_srp"),
            DoaEstimator,
        )


@pytest.mark.parametrize("estimator_id", ("tdoa_least_squares", "srp_phat"))
def test_built_in_doa_estimators_run_from_mixture_and_local_geometry(
    estimator_id: str,
) -> None:
    sample_rate_hz = 48_000
    microphone_positions_m = np.asarray(
        (
            (0.05, 0.0, 0.0),
            (0.0, 0.05, 0.0),
            (-0.05, 0.0, 0.0),
            (0.0, -0.05, 0.0),
        )
    )
    rng = np.random.default_rng(17)
    signal = rng.standard_normal(1024)
    samples = np.stack(
        (
            np.roll(signal, -7),
            signal,
            np.roll(signal, 7),
            signal,
        )
    ).astype(np.float32)
    estimator = get_default_registry().resolve("doa_estimator", estimator_id)

    doa, diagnostics = estimator.estimate(
        samples,
        microphone_positions_m,
        sample_rate_hz,
    )

    assert isinstance(doa, DoaEstimate)
    assert diagnostics["doa_estimator"] == estimator_id


def test_activity_detector_declaration_and_registry_contract() -> None:
    registry = PluginRegistry()
    declaration = _activity_declaration()
    registry.register(declaration, _ActivityDetector)

    assert registry.resolve("activity_detector", "test_activity").detector_id == (
        "test_activity"
    )
    assert dict(declaration.output_contract) == {
        "shape": (),
        "dtype": "ActivityDecision",
    }
    with pytest.raises(ConfigValidationError, match="produced detector id"):
        mismatch = _activity_declaration("mismatch")
        registry.register(mismatch, _WrongDetectorId)
        registry.resolve("activity_detector", "mismatch")


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
        ("activity_detector", "auditok"),
        ("propagation_backend", "analytic_acoustics"),
        ("doa_estimator", "tdoa_least_squares"),
        ("doa_estimator", "pyroomacoustics_srp"),
        ("doa_estimator", "srp_phat"),
    }
    auditok = declarations[("activity_detector", "auditok")]
    assert auditok.required_dependencies == ("auditok",)
    assert auditok.supported_devices == ("cpu",)
    assert auditok.supported_profiles == (
        "training_features",
        "waveform_fidelity",
    )
    assert dict(auditok.output_contract) == {
        "shape": (),
        "dtype": "ActivityDecision",
    }
    resolved = get_default_registry().resolve(
        "activity_detector",
        "auditok",
        factory_kwargs={"energy_threshold_dbfs": -40.0},
    )
    assert isinstance(resolved, AuditokActivityDetector)
    with pytest.raises(ConfigValidationError, match="energy_threshold_dbfs"):
        get_default_registry().resolve("activity_detector", "auditok")
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


def test_public_pyroom_estimator_import_is_lazy() -> None:
    command = (
        "import sys; "
        "from isaac_audio_sensors.core.plugins import PyroomacousticsSrpEstimator; "
        "assert PyroomacousticsSrpEstimator.__name__; "
        "assert 'pyroomacoustics' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", command], check=True)
    assert PyroomacousticsSrpEstimator.__name__ == "PyroomacousticsSrpEstimator"


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
