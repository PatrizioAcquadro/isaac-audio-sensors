# Public API Inventory

This is the S1.7 public-name freeze for package version `1.8.0`. Names listed
as stable must not be removed, renamed, or given incompatible required
parameters during the v1 line. Compatible minor releases may add public names
and optional parameters. Provisional names require a deprecation path before
removal. Experimental and private implementation details follow the lifecycle
rules in [API Freeze](api_freeze_0_1.md).

## Stable Identifiers And Values

| Category | Frozen values |
| --- | --- |
| Frame schema | `ias.audio_sensor_frame.v1` |
| Dataset schema | `ias.audio_dataset_manifest.v1` |
| Calibration schema | `ias.audio_calibration_profile.v1` |
| Runtime profiles | `training_features`, `waveform_fidelity` (default) |
| Propagation backend ids | `geometry_only`, `tdoa_synthetic`, `room_acoustics`, `room_acoustics_srp` |
| DOA plugin ids | `tdoa_least_squares`, `srp_phat` |
| Plugin kinds | `propagation_backend`, `doa_estimator`, `audio_feature_extractor` |
| Plugin devices | `cpu`, `cuda` |

## Stable Umbrella Imports

`isaac_audio_sensors` retains the complete `1.7.0` export set:

```text
__version__
AudioDetection AudioSceneSnapshot AudioSensorFrame AudioSimulationBackend
AudioSourceSpec AudioTimeWindow ACOUSTIC_FIDELITY_LADDER
AcousticFidelityLevel AcousticFidelityMetadata DoaEstimate GeometryBackend
MicrophoneArraySpec MicrophoneSpec Pose3D RoomAcousticsBackend
RoomAcousticsSpec SourceOcclusion TdoaSyntheticBackend
audio_sensor_frame_json_schema fidelity_level_for_backend
```

`isaac_audio_sensors.core` retains the `1.7.0` names below:

```text
AudioDetection AudioSceneSnapshot AudioSensorConfig AudioSensorFrame
AudioSimulationBackend AudioSourceSpec AudioTimeWindow
ACOUSTIC_FIDELITY_LADDER AcousticFidelityLevel AcousticFidelityMetadata
DoaEstimate GeometryBackend MicrophoneArraySpec MicrophoneSpec Pose3D
RoomAcousticsBackend RoomAcousticsSpec SourceOcclusion TdoaSyntheticBackend
audio_sensor_frame_json_schema build_scene_snapshot create_microphone_array
fidelity_level_for_backend get_backend load_audio_config
microphone_world_positions validate_audio_config
write_audio_sensor_frame_json_schema
```

Stage 1 adds and freezes these `isaac_audio_sensors.core` names:

```text
AudioCalibrationProfile AudioDatasetManifest AudioFeatureExtractor
CapabilityReport CapabilityStatus DoaEstimator GccPhatLeastSquaresEstimator
PackActivationError PackError PackValidationError PluginAvailability
PluginDeclaration PluginRegistry PropagationBackend SrpPhatEstimator
activate_pack audio_calibration_profile_json_schema
audio_dataset_manifest_json_schema check_profile_compatibility
discover_capabilities discover_pack_installs get_default_registry
validate_declaration validate_pack_install
write_audio_calibration_profile_json_schema
write_audio_dataset_manifest_json_schema
```

`AudioSensorConfig.runtime_profile` is additive and defaults to
`waveform_fidelity` both through TOML loading and direct construction, so the
`1.7.0` keyword-only constructor remains usable.

## Stable IO And Plugin Imports

The `isaac_audio_sensors.core.io` `1.7.0` names remain frozen:

```text
AudioFrameJsonlWriter ContinuousWaveformWriter FrameWaveformWriter
WaveformSink WaveformWriteResult append_frame_jsonl frame_from_trace_dict
frame_to_trace_dict generated_impulse_metadata read_frame_trace
waveform_safe_filename write_frame_trace write_multichannel_wav
```

Stage 1 adds stable versioned-contract IO names:

```text
calibration_profile_from_dict calibration_profile_to_dict
dataset_manifest_from_dict dataset_manifest_to_dict manifest_from_dict
manifest_to_dict read_calibration_profile read_dataset_manifest
write_calibration_profile write_dataset_manifest
```

The complete `isaac_audio_sensors.core.plugins` public set is:

```text
PLUGIN_KINDS SUPPORTED_PLUGIN_DEVICES AudioFeatureExtractor DoaEstimator
GccPhatLeastSquaresEstimator PluginAvailability PluginDeclaration
PluginFactory PluginOutputContract PluginRegistry PropagationBackend
SrpPhatEstimator get_default_registry validate_declaration
```

The lower-level `core.plugins.protocols`, `declarations`, `registry`, and
`adapters` module exports are the corresponding module-qualified forms of
these names and share the same stable lifecycle.

## Existing Isaac And Lab Imports

All `1.7.0` exports from these modules are retained and frozen at their
documented stable or provisional lifecycle:

| Module | Frozen exported names |
| --- | --- |
| `isaac_audio_sensors.core.backends` | `AudioSimulationBackend`, `GeometryBackend`, `RoomAcousticsBackend`, `RoomAcousticsSrpBackend`, `TdoaSyntheticBackend`, `get_backend` |
| `isaac_audio_sensors.core.doa` | `bearing_deg_to_sector_name`, `deduplicate_candidate_bearings`, `sector_bounds_deg`, `two_mic_candidate_bearings` |
| `isaac_audio_sensors.core.fidelity` | `ACOUSTIC_FIDELITY_LADDER`, `AcousticFidelityLevel`, `AcousticFidelityMetadata`, `fidelity_level_for_backend` |
| `isaac_audio_sensors.isaac` | `ArrayRecord`, `DiscoveredAudioArray`, `DiscoveredAudioSource`, `IsaacAudioArraySensor`, `IsaacAudioDiscoveryCfg`, `IsaacAudioDiscoveryResult`, `IsaacAudioSceneBindingCfg`, `IsaacStagePoseResolver`, `ListenerRecord`, `MicrophoneRigProfile`, `AudioSensorReplicatorRecorder`, `ReplicatorIntegrationError`, `ReplicatorRecorderStatus`, `SoundProfile`, `SourceRecord`, `StagePose`, `attach_microphone_array_attrs`, `attach_microphone_attrs`, `attach_sound_source_attrs`, `build_stage_snapshot`, `create_listener_prim`, `create_sound_prim`, `discover_stage_audio`, `discover_microphone_arrays`, `audio_sensor_frame_replicator_payload`, `default_microphone_rig_profiles`, `default_object_profile_mappings`, `default_sound_profiles`, `require_isaac_usd`, `require_replicator_core`, `resolve_world_pose` |
| `isaac_audio_sensors.isaac.replicator` | `DEFAULT_REPLICATOR_ANNOTATOR_NAME`, `DEFAULT_REPLICATOR_WRITER_NAME`, `PAYLOAD_SCHEMA_VERSION`, `AudioSensorReplicatorRecorder`, `ReplicatorIntegrationError`, `ReplicatorRecorderStatus`, `ReplicatorWriteResult`, `audio_sensor_frame_replicator_payload`, `require_replicator_core` |
| `isaac_audio_sensors.lab` | `AudioArraySensor`, `AudioArraySensorClasses`, `AudioArraySensorCfg`, `AudioArraySensorData`, `LabAudioEntityBindingCfg`, `LabAudioSourceEntityCfg`, `LabAudioStageBindingCfg`, `ensure_isaac_lab_sensor_classes`, `get_audio_array_sensor_classes` |
| `isaac_audio_sensors_omni` | `Extension` |

`isaac_audio_sensors.isaac.viz` remains experimental as documented, even
though its module exports remain available.

## Provisional Stage 1 Tooling

These lower-level pack/capability module exports are supported but provisional
because their host/runtime and artifact-management policies may grow
additively:

```text
isaac_audio_sensors.core.capabilities:
  CapabilityReport CapabilityStatus acoustic_pack_artifact_name
  discover_capabilities

isaac_audio_sensors.core.packs:
  PACK_MANIFEST_SCHEMA PackActivationError PackError PackValidationError
  activate_pack active_pack_manifest active_pack_root default_pack_root
  discover_pack_installs validate_pack_install
```

The stable umbrella names in those groups still obey the no-removal rule; the
provisional classification applies to lower-level management details and
return-shape growth.

## CLI Names

The public command remains `isaac-audio-sensors`. Frozen subcommands are
`validate-config`, `simulate`, `export-trace`, and `export-schema`;
`capabilities` is the additive Stage 1 capability-report command.

Public dataset/calibration names are only the explicitly inventoried umbrella,
IO, schema, and reader/writer exports. Nested record implementation classes
that are not re-exported are not accidentally promoted by this inventory.
