# Product Boundary and Compatibility

## Decision

`isaac-audio-sensors` is a reusable robot-audition SDK, not a robot task, acquisition campaign, downstream policy, or scientific evidence repository.

The maintained product owns simulator-independent audio contracts and backends, calibration contracts, generic recording/replay, Isaac Sim integration, Isaac Lab observations, the Kit extension, small examples/fixtures, and release tooling.

Robot-specific mounts, assets, adapters, policies, task orchestration, acceptance criteria, datasets, holdouts, and experiment evidence remain with their owning downstream project.

## Current Compatibility Line

The current package is `3.0.0` on the v3 compatibility line. R5.0 previously removed the v1 root convenience imports; v3 keeps that semantic subsystem boundary, makes entity-owned directivity and amplitude-gain semantics authoritative, makes `AudioSceneSnapshot` the sole propagation-backend array-state authority, replaces the room-only scene contract with one analytic acoustic-environment contract, separates microphone signals from perception, and introduced the observed-only frame contract. The pre-07.2 confidence correction advances that contract to `ias.audio_sensor_frame.v4` without compatibility shims.

The root exposes only `__version__`; contracts and services live under their owning modules. The CLI composes those public services without becoming a dependency of lower components.

The curated v3 entrypoint inventory is:

- `isaac_audio_sensors`: `__version__`.
- `isaac_audio_sensors.core`: `AcousticEnvironmentSpec`, `AcousticSurfaceSpec`, `AudioObservation`, `AudioPerceptionPipeline`, `AudioSceneSnapshot`, `AudioSensorFrame`, `AudioSourceSpec`, `AudioTimeWindow`, `DirectivityPattern`, `DoaEstimate`, `MicrophoneArraySpec`, `MicrophoneSignalBlock`, `MicrophoneSpec`, `ObservationOrigin`, `Pose3D`, and `SourceOcclusion`.
- `isaac_audio_sensors.recording`: `AppendFrameResult`, `AudioDatasetManifest`, `CreationProvenance`, `DatasetLayoutError`, `DatasetSplitError`, `DeviceProvenance`, `Finding`, `LoadedFrame`, `ReplayEvent`, `SessionDataset`, `SessionRecorder`, `SessionRecorderError`, `SplitPlan`, `Statistics`, `ValidationReport`, `apply_split_plan`, `build_split_plan`, `export_session_flac`, `manifest_from_dict`, `manifest_to_dict`, `read_dataset_manifest`, `read_split_plan`, `replay_session`, `validate_dataset`, `write_dataset_manifest`, and `write_split_plan`.
- `isaac_audio_sensors.isaac`: `AudioSensorReplicatorRecorder`, `DiscoveredAudioArray`, `DiscoveredAudioSource`, `IsaacAudioArraySensor`, `IsaacAudioDiscoveryCfg`, `IsaacAudioDiscoveryResult`, `IsaacAudioSceneBindingCfg`, `IsaacStagePoseResolver`, `ReplicatorIntegrationError`, `ReplicatorRecorderStatus`, `StagePose`, `audio_sensor_frame_replicator_payload`, `attach_microphone_array_attrs`, `attach_microphone_attrs`, `attach_sound_source_attrs`, `build_stage_snapshot`, `create_listener_prim`, `create_sound_prim`, `discover_stage_audio`, `require_isaac_usd`, `require_replicator_core`, and `resolve_world_pose`.
- `isaac_audio_sensors.lab`: `AudioArraySensor`, `AudioArraySensorCfg`, `AudioArraySensorData`, `EntityBindingCfg`, and `SourceEntityCfg`.
- `isaac_audio_sensors.kit`: `ExtensionController`.
- `isaac_audio_sensors.schemas`: no root exports.
- `isaac_audio_sensors.schemas.generate`: `audio_calibration_profile_json_schema`, `audio_dataset_manifest_json_schema`, `audio_sensor_frame_json_schema`, and `write_json_schema`.

Advanced public services remain importable from their canonical modules; they are not implied package-root entrypoints. The exact inventory above is enforced in fresh processes by `tests/contract/test_public_surface.py`.

Current serialized versions and their ownership are listed in [[topics/public-contracts-and-recording|Public Contracts and Recording]]: frame v4, dataset-manifest v4, frame-record v2 and calibration-profile v1. The confidence migration changes only the embedded frame contract; frame v1–v3 inputs are rejected.

## Consumer readiness migration

The 7.1 assessment adds validation tooling and evidence; it changes no public
API, tensor shape or serialized version. Consumers upgrading from an older
revision must adopt the existing unreleased v3 contracts:

| Consumer assumption | Required adoption |
| --- | --- |
| Published package equals this checkout | Select a compatible source revision; 3.0.0 remains unreleased. The local verified Sim/Lab combination is recorded in [[experiments/consumer-audio-operating-envelope|7.1 evidence]], not a blanket version promise. |
| Frame v3 or unavailable confidence encoded as zero | Read/write `ias.audio_sensor_frame.v4`; preserve null confidence. Manifest v4, frame-record v2 and calibration v1 remain independent. Older frame versions are rejected; preserve archived originals rather than relabeling their schemas. |
| Source-conditioned detections or stable source IDs | Consume `AudioObservation`. Signal-derived observation IDs are frame-local event identities, not persistent tracks, source identities or class labels. Association stays downstream. |
| Six legacy Lab tensors, event RMS or zero meaning unavailable | Consume the current observed tensors with every corresponding mask and truncation count. Null confidence maps to zero with a false confidence mask; a measured zero keeps a true mask. Do not choose ambiguity candidates as selected directions. |
| An implicit detector, sample rate or estimator | Configure `energy_threshold_dbfs` and `doa_enabled` explicitly. Sample rate belongs to the array / `EntityBindingCfg`; the current CUDA entity path requires 16 kHz and explicit audio assets. Capacity does not select or constrain the true source count. |
| Imports or device fallback before simulator setup | Import Lab classes after `AppLauncher`; use the active simulation CUDA device and the supported optional dependencies. There is no implicit CPU fallback for CUDA entity inference. |
| Bearings/timestamps are immediately actionable global state | Bearings use array-local clockwise `[0,360)` degrees, +X forward / +Y right / +Z up. Core poses use meters and XYZW; entity bindings declare quaternion order/frame. Preserve acquisition windows, elapsed sample clocks and warm-up/discontinuity semantics. Frame timestamps derive from window start; observation freshness is distinct from perceptual response. |

[[topics/isaac-lab-integration|Lab Integration]] owns exact tensor fields and
masking/scaling. [[topics/public-contracts-and-recording|Public Contracts]] owns
serialization, confidence and coordinate semantics. Task-specific calibration,
head-pose association, queues, dependency pins and adapter migration remain
consumer-owned; SDK 7.1 does not certify those paths.

## Stable Promises

The v3 line promises the documented semantic import boundary, signal block, observed sensor frame, dataset-manifest, and calibration-profile contracts; the exact four-value entity directivity contract; amplitude `gain_db` semantics; snapshot-authoritative `propagate(scene, array_id, time_window)` signal production; deterministic L0/L1 behavior; optional supported L2 behavior; generic plugin contracts; package JSON/JSONL; generic recording/replay; supported lazy Isaac Sim and Isaac Lab paths; and the Kit extension as the reference UX.

Compatible releases preserve required fields, meanings, units, provenance values, coordinate convention, ambiguity representation, stable producer identifiers, sector behavior, and named diagnostic namespaces.

Bug fixes, stricter invalid-input rejection, additive optional fields/diagnostics, and new optional capabilities are compatible when existing readers and configurations retain their documented meaning.

## Non-Promises

The package does not promise a downstream robot or project as a release gate, real hardware benchmarks, automatic calibration, complete L3/L4 realism, production perception, mandatory ROS 2 integration, or sim-to-real transfer.

Simulation validation cannot be promoted to a physical claim without measurements, calibration evidence, controlled data, and an explicit validation protocol.

Optional Replicator, room-acoustics, Isaac, Kit, GPU, and pack capabilities do not become core import dependencies.

## Breaking Changes

Removing or renaming stable public fields, changing their semantics, changing units/provenance/coordinates/ambiguity/sector meaning, or silently changing a serialized shape is breaking and requires a new schema or major compatibility decision.

Version 3 intentionally removes `audio.effects.directivity`, its pattern/frequency-point records, Lab `microphone_relative_offsets_m`, `RoomAcousticsSpec`, `AudioSceneSnapshot.room`, `[room]`, parallel sample-rate inputs, `max_events`, `AudioDetection`, source-conditioned detection assembly, and frame v1/v2. Consumers must migrate to entity-owned directivity, `EntityBindingCfg.microphones`, `AcousticEnvironmentSpec`, `AudioSceneSnapshot.environment`, `[environment]`, array-owned sample rates, `MicrophoneSignalBlock`, `AudioObservation`, output-only `max_observations`, and the current observed frame contract. The subsequent nullable-confidence migration requires frame v4. No alias, fallback parser, or parallel runtime implementation is retained.

Experimental or private names may change with clear release notes, but downstream project-specific surfaces are not preserved through permanent shims.

## Maintenance removals in unreleased 3.0

Unused lower-level conveniences are removed without aliases: `gcc_phat_delay`,
`estimate_tdoa_matrix`, `rms_by_channel`, `validate_tdoa_array`, `layout_rank_xy`,
`angular_error_deg`, and the `core.fidelity` metadata module. Use
`estimate_tdoa_diagnostics` for waveform-derived pair delays and peaks, the
maintained estimator for geometry admission, and `layout_rank_xyz` for spatial
rank. `active_sources` remains available to downstream scene consumers.

Capability discovery retains the base Analytic level and reports optional room,
codec, and configured Geometry capabilities directly. It no longer advertises
the speculative L4 level or a separate unavailable L3 placeholder. Model scope
and qualification limits belong to the canonical acoustic topics and status,
not a parallel prose catalog embedded in Python. Frame v4, manifest v4,
frame-record v2, and calibration v1 are unchanged.

USD adapters now use `GetAttributes`, `GetAttribute`, `CreateAttribute`,
`GetTypeName`, `SetTypeName`, and stage prim methods. Dictionary-backed fake
fields are no longer a production interface; host tests implement the same USD
methods. Authored IAS metadata and lazy optional-runtime imports remain supported.

## Consequences

The core stays portable and testable, optional runtimes remain lazy, downstream ownership is explicit, and release archives can be audited against one generic product boundary.

Consumers must maintain their own adapters and validation, and physical or task-level readiness must be reported separately from package correctness.
