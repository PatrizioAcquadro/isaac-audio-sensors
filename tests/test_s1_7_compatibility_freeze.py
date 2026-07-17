"""S1.7 compatibility freeze against the published 1.7.0 surface."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from importlib import import_module
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core import (
    AudioCalibrationProfile,
    AudioDatasetManifest,
    AudioFeatureExtractor,
    DoaEstimator,
    PropagationBackend,
    get_default_registry,
)
from isaac_audio_sensors.core.config import AudioSensorConfig, load_audio_config
from isaac_audio_sensors.core.constants import DEFAULT_RUNTIME_PROFILE
from isaac_audio_sensors.core.io import (
    frame_from_trace_dict,
    frame_to_trace_dict,
    read_calibration_profile,
    read_dataset_manifest,
)

BASELINE_REVISION = "74a4ed6"
TRACE_DIR = Path("examples/traces")

# These are the exact public 1.7.0 artifacts at BASELINE_REVISION. Keeping the
# hashes here makes the compatibility fixture independent of Git availability.
V1_7_ARTIFACT_SHA256 = {
    "configs/isaac_audio_sensors_demo.toml": (
        "d46a38e3f8ef87160b60eeeda622c1b3aac12041f88dc539d1dea6a51d7e6cb4"
    ),
    "docs/schemas/audio_sensor_frame.v1.schema.json": (
        "1f005443a65567961f22e9bec7c50f1f6a3dffa0e017e79de348fd6203b43933"
    ),
    "examples/traces/ambiguity_frame.v1.json": (
        "753f49d83b57edf6c9f79ebb23c76f7f5ee51aa2fd4c6dc645f7ae23dfc7210d"
    ),
    "examples/traces/diagnostics_provenance_sequence.v1.ndjson": (
        "79e4f6483cccffb2953821978f3b74513811496e0877a4139ec0c7e637950b01"
    ),
    "examples/traces/minimal_frame.v1.json": (
        "2070686b033fe2cb232558d68837fd5705995d56bcf45ae033f94e6027db5c0b"
    ),
    "examples/traces/multi_detection_frame.v1.json": (
        "a76a6c0e9d7f5c0a7d0ae62f562028a6f44a7d2944be9953d7589459cd0c214b"
    ),
}

OPTIONAL_DETECTION_DEFAULTS = {
    "occluded": False,
    "ground_truth_elevation_deg": None,
}
OPTIONAL_DOA_DEFAULTS = {
    "estimated_elevation_deg": None,
    "candidate_elevation_deg": [],
}
KNOWN_CANONICAL_EXPANSIONS = frozenset(
    {
        "detection.occluded",
        "detection.ground_truth_elevation_deg",
        "detection.doa.estimated_elevation_deg",
        "detection.doa.candidate_elevation_deg",
    }
)

# Every name exported by the public modules at 1.7.0 is retained. Additive
# public names remain permitted by the compatible-minor evolution policy.
V1_7_PUBLIC_NAMES = {
    "isaac_audio_sensors": {
        "__version__",
        "AudioDetection",
        "AudioSceneSnapshot",
        "AudioSensorFrame",
        "AudioSimulationBackend",
        "AudioSourceSpec",
        "AudioTimeWindow",
        "ACOUSTIC_FIDELITY_LADDER",
        "AcousticFidelityLevel",
        "AcousticFidelityMetadata",
        "DoaEstimate",
        "GeometryBackend",
        "MicrophoneArraySpec",
        "MicrophoneSpec",
        "Pose3D",
        "RoomAcousticsBackend",
        "RoomAcousticsSpec",
        "SourceOcclusion",
        "TdoaSyntheticBackend",
        "audio_sensor_frame_json_schema",
        "fidelity_level_for_backend",
    },
    "isaac_audio_sensors.core": {
        "AudioDetection",
        "AudioSceneSnapshot",
        "AudioSensorConfig",
        "AudioSensorFrame",
        "AudioSimulationBackend",
        "AudioSourceSpec",
        "AudioTimeWindow",
        "ACOUSTIC_FIDELITY_LADDER",
        "AcousticFidelityLevel",
        "AcousticFidelityMetadata",
        "DoaEstimate",
        "GeometryBackend",
        "MicrophoneArraySpec",
        "MicrophoneSpec",
        "Pose3D",
        "RoomAcousticsBackend",
        "RoomAcousticsSpec",
        "SourceOcclusion",
        "TdoaSyntheticBackend",
        "audio_sensor_frame_json_schema",
        "build_scene_snapshot",
        "create_microphone_array",
        "fidelity_level_for_backend",
        "get_backend",
        "load_audio_config",
        "microphone_world_positions",
        "validate_audio_config",
        "write_audio_sensor_frame_json_schema",
    },
    "isaac_audio_sensors.core.backends": {
        "AudioSimulationBackend",
        "GeometryBackend",
        "RoomAcousticsBackend",
        "RoomAcousticsSrpBackend",
        "TdoaSyntheticBackend",
        "get_backend",
    },
    "isaac_audio_sensors.core.doa": {
        "bearing_deg_to_sector_name",
        "deduplicate_candidate_bearings",
        "sector_bounds_deg",
        "two_mic_candidate_bearings",
    },
    "isaac_audio_sensors.core.fidelity": {
        "ACOUSTIC_FIDELITY_LADDER",
        "AcousticFidelityLevel",
        "AcousticFidelityMetadata",
        "fidelity_level_for_backend",
    },
    "isaac_audio_sensors.core.io": {
        "AudioFrameJsonlWriter",
        "ContinuousWaveformWriter",
        "FrameWaveformWriter",
        "WaveformSink",
        "WaveformWriteResult",
        "append_frame_jsonl",
        "frame_from_trace_dict",
        "frame_to_trace_dict",
        "generated_impulse_metadata",
        "read_frame_trace",
        "waveform_safe_filename",
        "write_frame_trace",
        "write_multichannel_wav",
    },
    "isaac_audio_sensors.isaac": {
        "ArrayRecord",
        "DiscoveredAudioArray",
        "DiscoveredAudioSource",
        "IsaacAudioArraySensor",
        "IsaacAudioDiscoveryCfg",
        "IsaacAudioDiscoveryResult",
        "IsaacAudioSceneBindingCfg",
        "IsaacStagePoseResolver",
        "ListenerRecord",
        "MicrophoneRigProfile",
        "AudioSensorReplicatorRecorder",
        "ReplicatorIntegrationError",
        "ReplicatorRecorderStatus",
        "SoundProfile",
        "SourceRecord",
        "StagePose",
        "attach_microphone_array_attrs",
        "attach_microphone_attrs",
        "attach_sound_source_attrs",
        "build_stage_snapshot",
        "create_listener_prim",
        "create_sound_prim",
        "discover_stage_audio",
        "discover_microphone_arrays",
        "audio_sensor_frame_replicator_payload",
        "default_microphone_rig_profiles",
        "default_object_profile_mappings",
        "default_sound_profiles",
        "require_isaac_usd",
        "require_replicator_core",
        "resolve_world_pose",
    },
    "isaac_audio_sensors.isaac.replicator": {
        "DEFAULT_REPLICATOR_ANNOTATOR_NAME",
        "DEFAULT_REPLICATOR_WRITER_NAME",
        "PAYLOAD_SCHEMA_VERSION",
        "AudioSensorReplicatorRecorder",
        "ReplicatorIntegrationError",
        "ReplicatorRecorderStatus",
        "ReplicatorWriteResult",
        "audio_sensor_frame_replicator_payload",
        "require_replicator_core",
    },
    "isaac_audio_sensors.lab": {
        "AudioArraySensor",
        "AudioArraySensorClasses",
        "AudioArraySensorCfg",
        "AudioArraySensorData",
        "LabAudioEntityBindingCfg",
        "LabAudioSourceEntityCfg",
        "LabAudioStageBindingCfg",
        "ensure_isaac_lab_sensor_classes",
        "get_audio_array_sensor_classes",
    },
}

S1_ADDITIVE_CORE_NAMES = {
    "AudioCalibrationProfile",
    "AudioDatasetManifest",
    "AudioFeatureExtractor",
    "CapabilityReport",
    "CapabilityStatus",
    "DoaEstimator",
    "GccPhatLeastSquaresEstimator",
    "PackActivationError",
    "PackError",
    "PackValidationError",
    "PluginAvailability",
    "PluginDeclaration",
    "PluginRegistry",
    "PropagationBackend",
    "SrpPhatEstimator",
    "activate_pack",
    "audio_calibration_profile_json_schema",
    "audio_dataset_manifest_json_schema",
    "check_profile_compatibility",
    "discover_capabilities",
    "discover_pack_installs",
    "get_default_registry",
    "validate_declaration",
    "validate_pack_install",
    "write_audio_calibration_profile_json_schema",
    "write_audio_dataset_manifest_json_schema",
}
S1_ADDITIVE_IO_NAMES = {
    "calibration_profile_from_dict",
    "calibration_profile_to_dict",
    "dataset_manifest_from_dict",
    "dataset_manifest_to_dict",
    "manifest_from_dict",
    "manifest_to_dict",
    "read_calibration_profile",
    "read_dataset_manifest",
    "write_calibration_profile",
    "write_dataset_manifest",
}
S1_PLUGIN_NAMES = {
    "PLUGIN_KINDS",
    "SUPPORTED_PLUGIN_DEVICES",
    "AudioFeatureExtractor",
    "DoaEstimator",
    "GccPhatLeastSquaresEstimator",
    "PluginAvailability",
    "PluginDeclaration",
    "PluginFactory",
    "PluginOutputContract",
    "PluginRegistry",
    "PropagationBackend",
    "SrpPhatEstimator",
    "get_default_registry",
    "validate_declaration",
}


def test_published_1_7_artifacts_are_the_frozen_fixture_corpus():
    for path_text, expected_sha256 in V1_7_ARTIFACT_SHA256.items():
        path = Path(path_text)
        assert path.is_file(), (BASELINE_REVISION, path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256


def test_1_7_traces_round_trip_with_only_documented_default_expansion():
    observed_expansion_kinds: set[str] = set()

    for path, payload in _iter_trace_payloads():
        round_tripped = frame_to_trace_dict(frame_from_trace_dict(payload))
        normalized, expected_added = _normalize_optional_defaults(payload)
        added, removed, changed = _mapping_differences(payload, round_tripped)

        # Semantic equality is exact after applying the documented canonical
        # optional-field defaults to the historical record.
        assert round_tripped == normalized, path

        # Fail if any other key changes, appears, or disappears.
        assert added == expected_added, path
        assert not removed, path
        assert not changed, path
        observed_expansion_kinds.update(_canonical_expansion_kind(p) for p in added)

    # The corpus exercises the complete known expansion set, not merely a
    # subset that could hide a new serializer-side expansion.
    assert observed_expansion_kinds == KNOWN_CANONICAL_EXPANSIONS


def test_1_7_config_loads_with_identical_semantics_and_documented_s1_default():
    config = load_audio_config("configs/isaac_audio_sensors_demo.toml")

    assert DEFAULT_RUNTIME_PROFILE == "waveform_fidelity"
    assert config.runtime_profile == DEFAULT_RUNTIME_PROFILE
    assert config.scene_id == "demo_audio_lab_single_source"
    assert config.default_backend == "tdoa_synthetic"
    assert config.sample_rate_hz == 48_000
    assert config.speed_of_sound_mps == 343.0
    assert config.write_waveforms is False
    assert config.waveform_dir is None
    assert config.tdoa_ambiguity_policy == "none"
    assert tuple(config.arrays) == ("rig_front", "rig_stereo")
    assert tuple(source.source_id for source in config.sources) == (
        "speaker_front_right",
        "speaker_left",
    )
    assert [source.velocity_world_mps for source in config.sources] == [
        None,
        None,
    ]

    # ``AudioSensorConfig`` was already a public core export in 1.7.0. The
    # additive runtime-profile field therefore needs a constructor default as
    # well as a TOML-loader default.
    legacy_constructor_values = {
        field.name: getattr(config, field.name)
        for field in fields(AudioSensorConfig)
        if field.name != "runtime_profile"
    }
    rebuilt = AudioSensorConfig(**legacy_constructor_values)
    assert rebuilt.runtime_profile == DEFAULT_RUNTIME_PROFILE


def test_every_1_7_public_name_remains_importable():
    for module_name, frozen_names in V1_7_PUBLIC_NAMES.items():
        module = import_module(module_name)
        current_exports = set(module.__all__)
        assert frozen_names <= current_exports, (
            module_name,
            sorted(frozen_names - current_exports),
        )
        for name in frozen_names:
            assert hasattr(module, name), (module_name, name)


def test_stage_1_public_name_inventory_is_present_and_plugin_set_is_exact():
    core = import_module("isaac_audio_sensors.core")
    io = import_module("isaac_audio_sensors.core.io")
    plugins = import_module("isaac_audio_sensors.core.plugins")

    assert set(core.__all__) >= S1_ADDITIVE_CORE_NAMES
    assert set(io.__all__) >= S1_ADDITIVE_IO_NAMES
    assert set(plugins.__all__) == S1_PLUGIN_NAMES
    for module, names in (
        (core, S1_ADDITIVE_CORE_NAMES),
        (io, S1_ADDITIVE_IO_NAMES),
        (plugins, S1_PLUGIN_NAMES),
    ):
        for name in names:
            assert hasattr(module, name), (module.__name__, name)


def test_stage_1_contract_and_plugin_consumers_use_public_exports():
    manifest = read_dataset_manifest("examples/manifests/minimal_manifest.v1.json")
    profile = read_calibration_profile(
        "examples/calibration/respeaker_xvf3800_nominal.v1.json"
    )
    assert isinstance(manifest, AudioDatasetManifest)
    assert isinstance(profile, AudioCalibrationProfile)

    registry = get_default_registry()
    assert isinstance(
        registry.resolve("propagation_backend", "geometry_only"),
        PropagationBackend,
    )
    assert isinstance(
        registry.resolve("doa_estimator", "tdoa_least_squares"),
        DoaEstimator,
    )
    assert isinstance(AudioFeatureExtractor, type)


def _iter_trace_payloads():
    for path in sorted(TRACE_DIR.iterdir()):
        if path.suffix == ".json":
            yield path, json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix == ".ndjson":
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                yield Path(f"{path}:{line_number}"), json.loads(line)


def _normalize_optional_defaults(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], set[str]]:
    normalized = dict(payload)
    normalized_detections = []
    expected_added: set[str] = set()
    for index, detection in enumerate(payload["detections"]):
        detection_path = f"detections[{index}]"
        for field_name in OPTIONAL_DETECTION_DEFAULTS:
            if field_name not in detection:
                expected_added.add(f"{detection_path}.{field_name}")
        for field_name in OPTIONAL_DOA_DEFAULTS:
            if field_name not in detection["doa"]:
                expected_added.add(f"{detection_path}.doa.{field_name}")
        normalized_detections.append(
            {
                **OPTIONAL_DETECTION_DEFAULTS,
                **detection,
                "doa": {**OPTIONAL_DOA_DEFAULTS, **detection["doa"]},
            }
        )
    normalized["detections"] = normalized_detections
    return normalized, expected_added


def _mapping_differences(
    before: Any,
    after: Any,
    *,
    path: str = "",
) -> tuple[set[str], set[str], set[str]]:
    added: set[str] = set()
    removed: set[str] = set()
    changed: set[str] = set()
    if isinstance(before, dict) and isinstance(after, dict):
        added.update(_join_path(path, key) for key in after.keys() - before.keys())
        removed.update(_join_path(path, key) for key in before.keys() - after.keys())
        for key in before.keys() & after.keys():
            nested = _mapping_differences(
                before[key], after[key], path=_join_path(path, key)
            )
            added.update(nested[0])
            removed.update(nested[1])
            changed.update(nested[2])
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            changed.add(path)
        else:
            for index, (before_item, after_item) in enumerate(
                zip(before, after, strict=True)
            ):
                nested = _mapping_differences(
                    before_item, after_item, path=f"{path}[{index}]"
                )
                added.update(nested[0])
                removed.update(nested[1])
                changed.update(nested[2])
    elif type(before) is not type(after) or before != after:
        changed.add(path)
    return added, removed, changed


def _join_path(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _canonical_expansion_kind(path: str) -> str:
    _, detection_field = path.split("]", maxsplit=1)
    return "detection" + detection_field
