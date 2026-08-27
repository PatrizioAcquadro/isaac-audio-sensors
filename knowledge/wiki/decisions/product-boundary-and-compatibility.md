# Product Boundary and Compatibility

## Decision

`isaac-audio-sensors` is a reusable robot-audition SDK, not a robot task, acquisition campaign, downstream policy, or scientific evidence repository.

The maintained product owns simulator-independent audio contracts and backends, calibration contracts, generic recording/replay, Isaac Sim integration, Isaac Lab observations, the Kit extension, small examples/fixtures, and release tooling.

Robot-specific mounts, assets, adapters, policies, task orchestration, acceptance criteria, datasets, holdouts, and experiment evidence remain with their owning downstream project.

## Current Compatibility Line

The current package is `3.0.0` on the v3 compatibility line. R5.0 previously removed the v1 root convenience imports; v3 keeps that semantic subsystem boundary and makes entity-owned directivity and amplitude-gain semantics authoritative without compatibility shims.

The root exposes only `__version__`; contracts and services live under their owning modules. The CLI composes those public services without becoming a dependency of lower components.

The curated v3 entrypoint inventory is:

- `isaac_audio_sensors`: `__version__`.
- `isaac_audio_sensors.core`: `AudioDetection`, `AudioSceneSnapshot`, `AudioSensorFrame`, `AudioSourceSpec`, `AudioTimeWindow`, `DirectivityPattern`, `DoaEstimate`, `MicrophoneArraySpec`, `MicrophoneSpec`, `Pose3D`, `RoomAcousticsSpec`, and `SourceOcclusion`.
- `isaac_audio_sensors.recording`: `AppendFrameResult`, `AudioDatasetManifest`, `CreationProvenance`, `DatasetLayoutError`, `DatasetSplitError`, `DeviceProvenance`, `Finding`, `LoadedFrame`, `ReplayEvent`, `SessionDataset`, `SessionRecorder`, `SessionRecorderError`, `SplitPlan`, `Statistics`, `ValidationReport`, `apply_split_plan`, `build_split_plan`, `export_session_flac`, `manifest_from_dict`, `manifest_to_dict`, `read_dataset_manifest`, `read_split_plan`, `replay_session`, `validate_dataset`, `write_dataset_manifest`, and `write_split_plan`.
- `isaac_audio_sensors.isaac`: `AudioSensorReplicatorRecorder`, `DiscoveredAudioArray`, `DiscoveredAudioSource`, `IsaacAudioArraySensor`, `IsaacAudioDiscoveryCfg`, `IsaacAudioDiscoveryResult`, `IsaacAudioSceneBindingCfg`, `IsaacStagePoseResolver`, `ReplicatorIntegrationError`, `ReplicatorRecorderStatus`, `StagePose`, `audio_sensor_frame_replicator_payload`, `attach_microphone_array_attrs`, `attach_microphone_attrs`, `attach_sound_source_attrs`, `build_stage_snapshot`, `create_listener_prim`, `create_sound_prim`, `discover_stage_audio`, `require_isaac_usd`, `require_replicator_core`, and `resolve_world_pose`.
- `isaac_audio_sensors.lab`: `AudioArraySensor`, `AudioArraySensorCfg`, `AudioArraySensorData`, `EntityBindingCfg`, and `SourceEntityCfg`.
- `isaac_audio_sensors.kit`: `ExtensionController`.
- `isaac_audio_sensors.schemas`: no root exports.
- `isaac_audio_sensors.schemas.generate`: `audio_calibration_profile_json_schema`, `audio_dataset_manifest_json_schema`, `audio_sensor_frame_json_schema`, and `write_json_schema`.

Advanced public services remain importable from their canonical modules; they are not implied package-root entrypoints. The exact inventory above is enforced in fresh processes by `tests/contract/test_public_surface.py`.

Existing `ias.audio_sensor_frame.v1`, `ias.audio_dataset_manifest.v1`, and `ias.audio_calibration_profile.v1` data contracts may remain valid in a future major package version when their serialized meanings remain useful.

## Stable Promises

The v3 line promises the documented semantic import boundary, sensor frame, dataset-manifest, and calibration-profile contracts; the exact four-value entity directivity contract; amplitude `gain_db` semantics; deterministic L0/L1 behavior; optional supported L2 behavior; generic plugin contracts; package JSON/JSONL; generic recording/replay; supported lazy Isaac Sim and Isaac Lab paths; and the Kit extension as the reference UX.

Compatible releases preserve required fields, meanings, units, provenance values, coordinate convention, ambiguity representation, stable backend identifiers, sector behavior, and named diagnostic namespaces.

Bug fixes, stricter invalid-input rejection, additive optional fields/diagnostics, and new optional capabilities are compatible when existing readers and configurations retain their documented meaning.

## Non-Promises

The package does not promise a downstream robot or project as a release gate, real hardware benchmarks, automatic calibration, complete L3/L4 realism, production perception, mandatory ROS 2 integration, or sim-to-real transfer.

Simulation validation cannot be promoted to a physical claim without measurements, calibration evidence, controlled data, and an explicit validation protocol.

Optional Replicator, room-acoustics, Isaac, Kit, GPU, and pack capabilities do not become core import dependencies.

## Breaking Changes

Removing or renaming stable public fields, changing their semantics, changing units/provenance/coordinates/ambiguity/sector meaning, or silently changing a v1 serialized shape is breaking and requires a new schema or major compatibility decision.

Version 3 intentionally removes `audio.effects.directivity`, its pattern/frequency-point records, and Lab `microphone_relative_offsets_m`. Consumers must migrate to `AudioSourceSpec.directivity`, `MicrophoneSpec.directivity`, and `EntityBindingCfg.microphones`. No alias, fallback parser, or parallel runtime implementation is retained. The package major changes while the three serialized schemas remain v1 because their serialized meanings are preserved.

Experimental or private names may change with clear release notes, but downstream project-specific surfaces are not preserved through permanent shims.

## Consequences

The core stays portable and testable, optional runtimes remain lazy, downstream ownership is explicit, and release archives can be audited against one generic product boundary.

Consumers must maintain their own adapters and validation, and physical or task-level readiness must be reported separately from package correctness.
