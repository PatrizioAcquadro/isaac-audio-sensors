from __future__ import annotations

import inspect

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.base import get_backend, registered_backend_ids
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    RoomAcousticsSrpBackend,
)
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.plugins import (
    AudioFeatureExtractor,
    DoaEstimator,
    PluginDeclaration,
    PluginRegistry,
    PropagationBackend,
    get_default_registry,
)
from tests.helpers import quad_array, room_scene, source, time_window


class _MeanFeatureExtractor:
    def extract(self, samples, sample_rate_hz):
        del sample_rate_hz
        return np.mean(samples, axis=1, dtype=np.float32), {"statistic": "mean"}


def _feature_declaration(
    plugin_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    devices: tuple[str, ...] = ("cpu",),
    profiles: tuple[str, ...] = ("training_features",),
    deterministic: bool = True,
    shape: tuple[int, ...] = (4,),
) -> PluginDeclaration:
    return PluginDeclaration(
        plugin_id=plugin_id,
        kind="audio_feature_extractor",
        fidelity_level=None,
        required_dependencies=dependencies,
        supported_devices=devices,
        supported_profiles=profiles,
        deterministic=deterministic,
        output_contract={"shape": shape, "dtype": "float32"},
        description="Test feature extractor.",
        provenance="tests.contract.test_plugins",
    )


def _propagation_declaration(plugin_id: str) -> PluginDeclaration:
    return PluginDeclaration(
        plugin_id=plugin_id,
        kind="propagation_backend",
        fidelity_level="L0",
        required_dependencies=(),
        supported_devices=("cpu",),
        supported_profiles=("waveform_fidelity",),
        deterministic=True,
        output_contract={"shape": "AudioSensorFrame", "dtype": "AudioSensorFrame"},
        description="Test propagation backend.",
        provenance="tests.contract.test_plugins",
    )


def test_protocols_are_structural_and_existing_backends_satisfy_propagation():
    assert isinstance(GeometryBackend(), PropagationBackend)
    assert isinstance(TdoaSyntheticBackend(), PropagationBackend)
    assert isinstance(_MeanFeatureExtractor(), AudioFeatureExtractor)

    registry = get_default_registry()
    assert isinstance(
        registry.resolve("doa_estimator", "tdoa_least_squares"),
        DoaEstimator,
    )
    assert isinstance(registry.resolve("doa_estimator", "srp_phat"), DoaEstimator)


def test_propagation_backend_signature_selects_snapshot_array_by_id():
    expected = ("self", "scene", "array_id", "time_window")

    for backend_type in (
        PropagationBackend,
        GeometryBackend,
        TdoaSyntheticBackend,
        RoomAcousticsBackend,
        RoomAcousticsSrpBackend,
    ):
        assert tuple(inspect.signature(backend_type.simulate).parameters) == expected


def test_declaration_rejects_invalid_identity_kind_and_capabilities():
    with pytest.raises(ConfigValidationError, match="without whitespace"):
        _feature_declaration("bad id")
    with pytest.raises(ConfigValidationError, match="kind must be one of"):
        PluginDeclaration(
            plugin_id="bad_kind",
            kind="classifier",
            fidelity_level=None,
            required_dependencies=(),
            supported_devices=("cpu",),
            supported_profiles=("training_features",),
            deterministic=True,
            output_contract={"shape": (1,), "dtype": "float32"},
            description="Invalid kind.",
            provenance="tests.test_backend_plugins",
        )
    with pytest.raises(ConfigValidationError, match="unsupported values"):
        _feature_declaration("bad_device", devices=("tpu",))
    with pytest.raises(ConfigValidationError, match="unsupported values"):
        _feature_declaration("bad_profile", profiles=("unknown",))
    with pytest.raises(ConfigValidationError, match="must not be empty"):
        _feature_declaration("no_profile", profiles=())


def test_registry_rejects_duplicate_id_within_kind():
    registry = PluginRegistry()
    declaration = _feature_declaration("mean_feature")
    registry.register(declaration, _MeanFeatureExtractor)

    with pytest.raises(ConfigValidationError, match="Duplicate.*mean_feature"):
        registry.register(declaration, _MeanFeatureExtractor)


def test_registry_rejects_unknown_kind_and_id():
    registry = PluginRegistry()

    with pytest.raises(ConfigValidationError, match="Unknown plugin kind"):
        registry.resolve("classifier", "missing")
    with pytest.raises(ConfigValidationError, match="Unknown doa_estimator plugin id"):
        registry.resolve("doa_estimator", "missing")


def test_missing_dependency_registers_but_resolution_fails_actionably():
    registry = PluginRegistry()
    dependency = "isaac_audio_sensors_dependency_that_does_not_exist"
    registry.register(
        _feature_declaration("missing_dep", dependencies=(dependency,)),
        _MeanFeatureExtractor,
    )

    availability = registry.availability("audio_feature_extractor", "missing_dep")
    assert availability.available is False
    assert availability.missing_dependencies == (dependency,)
    with pytest.raises(ConfigValidationError, match=dependency):
        registry.resolve(
            "audio_feature_extractor",
            "missing_dep",
            runtime_profile="training_features",
        )


def test_importable_stdlib_dependency_resolves_normally():
    registry = PluginRegistry()
    registry.register(
        _feature_declaration("stdlib_dep", dependencies=("sys",)),
        _MeanFeatureExtractor,
    )

    assert registry.availability("audio_feature_extractor", "stdlib_dep").available
    assert isinstance(
        registry.resolve(
            "audio_feature_extractor",
            "stdlib_dep",
            runtime_profile="training_features",
        ),
        _MeanFeatureExtractor,
    )


def test_resolution_rejects_unsupported_device_and_profile():
    registry = PluginRegistry()
    registry.register(_feature_declaration("mean_feature"), _MeanFeatureExtractor)

    with pytest.raises(ConfigValidationError, match="does not support device 'cuda'"):
        registry.resolve(
            "audio_feature_extractor",
            "mean_feature",
            device="cuda",
            runtime_profile="training_features",
        )
    with pytest.raises(
        ConfigValidationError,
        match="does not support runtime profile 'waveform_fidelity'",
    ):
        registry.resolve(
            "audio_feature_extractor",
            "mean_feature",
            runtime_profile="waveform_fidelity",
        )


def test_resolution_rejects_factory_protocol_and_backend_id_mismatch():
    registry = PluginRegistry()
    registry.register(_feature_declaration("invalid_feature"), object)
    registry.register(_propagation_declaration("wrong_backend_id"), GeometryBackend)

    with pytest.raises(ConfigValidationError, match="AudioFeatureExtractor"):
        registry.resolve(
            "audio_feature_extractor",
            "invalid_feature",
            runtime_profile="training_features",
        )
    with pytest.raises(ConfigValidationError, match="produced backend id"):
        registry.resolve("propagation_backend", "wrong_backend_id")


def test_default_registry_builtin_inventory_and_capabilities():
    declarations = {
        (item.kind, item.plugin_id): item
        for item in get_default_registry().declarations()
    }
    assert set(declarations) == {
        ("propagation_backend", "geometry_only"),
        ("propagation_backend", "tdoa_synthetic"),
        ("propagation_backend", "room_acoustics"),
        ("propagation_backend", "room_acoustics_srp"),
        ("doa_estimator", "tdoa_least_squares"),
        ("doa_estimator", "srp_phat"),
    }
    assert not any(
        kind == "audio_feature_extractor" for kind, _plugin_id in declarations
    )
    assert declarations[("propagation_backend", "geometry_only")].fidelity_level == "L0"
    assert (
        declarations[("propagation_backend", "tdoa_synthetic")].fidelity_level == "L1"
    )
    for plugin_id in ("room_acoustics", "room_acoustics_srp"):
        declaration = declarations[("propagation_backend", plugin_id)]
        assert declaration.fidelity_level == "L2"
        assert declaration.required_dependencies == ("pyroomacoustics",)
        assert declaration.supported_profiles == ("waveform_fidelity",)
    assert all(item.supported_devices == ("cpu",) for item in declarations.values())
    assert all(item.deterministic for item in declarations.values())
    assert registered_backend_ids() == (
        "geometry_only",
        "tdoa_synthetic",
        "room_acoustics",
        "room_acoustics_srp",
    )


def test_room_backend_registry_availability_matches_optional_dependency():
    registry = get_default_registry()
    if RoomAcousticsBackend.is_available():
        assert isinstance(
            registry.resolve("propagation_backend", "room_acoustics"),
            RoomAcousticsBackend,
        )
        assert isinstance(get_backend("room_acoustics"), RoomAcousticsBackend)
    else:
        with pytest.raises(ConfigValidationError, match="pyroomacoustics"):
            registry.resolve("propagation_backend", "room_acoustics")
        with pytest.raises(ConfigValidationError, match="pyroomacoustics"):
            get_backend("room_acoustics")


def test_tdoa_registry_routing_preserves_seeded_frame():
    kwargs = {"seed": 713, "noise_std_s": 1e-6, "clock_jitter_s": 2e-7}
    array = quad_array()
    scene = room_scene(source("speaker", (3.0, 2.0, 0.5)), array=array)
    window = time_window(end_time_s=0.1)

    direct = TdoaSyntheticBackend(**kwargs).simulate(scene, array.array_id, window)
    registered = get_backend("tdoa_synthetic", **kwargs).simulate(
        scene,
        array.array_id,
        window,
    )

    assert frame_to_trace_dict(registered) == frame_to_trace_dict(direct)


def test_get_backend_unknown_id_error_text_is_frozen():
    with pytest.raises(ValueError) as error:
        get_backend("unknown")

    assert str(error.value) == "Unknown audio simulation backend 'unknown'."


def test_get_backend_checks_device_and_runtime_profile_before_factory():
    with pytest.raises(ConfigValidationError, match="does not support device 'cuda'"):
        get_backend("geometry_only", device="cuda")
    with pytest.raises(ConfigValidationError, match="does not support runtime profile"):
        get_backend("room_acoustics", runtime_profile="training_features")
