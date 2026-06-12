# API Freeze

This document defines the public compatibility surface for
`isaac-audio-sensors` `1.0.0` and compatible v1 releases. The project is a
standalone open-source Isaac Sim/Lab audio sensor package. It is not tied to a
downstream research project, and the pure Python core must remain importable
without Isaac Sim, Isaac Lab, Omniverse, `pyroomacoustics`, `scipy`,
`soundfile`, protobuf, ROS 2, CUDA, or torch installed.

The distribution version is currently `1.1.0`. The frame schema version
is independent and remains `ias.audio_sensor_frame.v1` for all compatible v1
releases.

[V1 Public Scope](v1_scope.md) is the single source of truth for release
promises and non-promises. This API freeze defines compatibility for those
promises; it does not make SquadBot, Alex, ROS 2/downstream adapters, sim-real
calibration, real hardware benchmarks, complete L3/L4 fidelity, or realistic
material/occlusion acoustics into v1 release gates.

The file name is retained for existing documentation links; the active release
target is `1.1.0`.

## Stable For V1-Compatible Releases

Stable APIs should keep names, import paths, required fields, and documented
semantics compatible throughout the v1 line. Compatible releases may add
optional fields, new enum values where documented as open-ended, stricter
validation for invalid inputs, and bug fixes that preserve valid behavior.

## AudioSensorFrame V1 Breaking Change Policy

`AudioSensorFrame` v1 is already the stable public data contract. The schema
version is separate from the Python package version and must remain
`ias.audio_sensor_frame.v1` for compatible v1 frame records.

Renaming public fields is a breaking change for v1. Removing public fields is a
breaking change for v1. Changing the meaning of units, timestamps, provenance,
coordinate convention, ambiguity fields, diagnostics namespaces, stable backend
identifiers, or bearing sectors is a breaking change for v1. Changing
`schema_version` away from `ias.audio_sensor_frame.v1` is a breaking change.
Changing bearing-sector semantics is a breaking change.

The active audit guardrails require these exact policy statements:

- schema version is separate from the Python package version.
- Renaming public fields is a breaking change.
- Removing public fields is a breaking change.
- Changing `schema_version` away from `ias.audio_sensor_frame.v1` is a breaking change.
- Changing bearing-sector semantics is a breaking change.
- `geometry_only`, `tdoa_synthetic`, and `room_acoustics` are stable backend identifiers.
- Additive optional fields and additive diagnostics namespaces are compatible.
- Corrected bearing-sector behavior is the stable v1 contract.

`geometry_only`, `tdoa_synthetic`, and `room_acoustics` are stable backend
identifiers. They are public values in frames, configs, trace examples, docs,
the acoustic fidelity ladder, and backend selection. They must not be renamed
within the v1 line.

Additive optional fields and additive diagnostics namespaces are compatible
when existing readers can ignore them. A documented bug fix is compatible only
when it corrects an inconsistency, keeps existing public field names, keeps the
serialized frame shape readable by v1 readers, and is covered by tests.

Corrected bearing-sector behavior is the stable v1 contract. The recent sector
consistency fix is treated as a bug correction because it aligned the emitted
sector labels with the documented clockwise convention; it does not reopen the
contract for reshaping.

## V1 Frame Schema Evolution Policy

This section defines exactly what a compatible v1 release may add to an
`AudioSensorFrame` v1 record without a new schema version. Downstream readers
must tolerate these additions; producers must not rely on anything beyond
them.

A compatible v1 release **may add**:

- new optional top-level frame fields;
- new optional detection, `doa`, and pose fields;
- new keys inside any `diagnostics` dictionary (frame-level or
  detection-level), including new top-level diagnostics namespaces;
- new values for enum-like string fields that are documented as open-ended
  (for example `class_label`, diagnostics strings, and `detection_mode`
  values beyond the documented ones);
- new optional keyword-only constructor parameters with backward-compatible
  defaults on public backends and sensors.

A compatible v1 release **must not**:

- remove, rename, or repurpose any documented v1 field or diagnostics key
  used for provenance identification;
- change the units, required-ness, or documented semantics of existing
  fields;
- change `schema_version` away from `ias.audio_sensor_frame.v1`;
- make a previously optional field required, or start emitting frames that
  existing v1 readers cannot parse;
- add new required constructor parameters to stable public APIs.

New optional fields must be absent-tolerant: a v1 reader that ignores them
must still interpret the frame correctly. New diagnostics keys are evidence,
not contract: producers may add them in any compatible release, and readers
must not require them. Schema additions that need validation guarantees must
be regenerated into `docs/schemas/audio_sensor_frame.v1.schema.json` with
`make export-schema` as forward-compatible optional fields.

Package import and version:

- `import isaac_audio_sensors`
- `isaac_audio_sensors.__version__`

Primary core data models:

- `Pose3D`
- `AudioSourceSpec`
- `AudioTimeWindow`
- `MicrophoneSpec`
- `MicrophoneArraySpec`
- `RoomAcousticsSpec`
- `AudioSceneSnapshot`
- `DoaEstimate`
- `AudioDetection`
- `AudioSensorFrame`

Microphone array helpers:

- `create_microphone_array`
- `arbitrary_microphone_array`
- `microphone_layout`
- `microphone_world_positions`

Backend selection, configuration, and core backends:

- `AudioSimulationBackend`
- `GeometryBackend`
- `TdoaSyntheticBackend`
- `RoomAcousticsBackend`
- `get_backend`
- `load_audio_config`
- `validate_audio_config`
- `build_scene_snapshot`
- backend ids `geometry_only`, `tdoa_synthetic`, and `room_acoustics`

Supported optional L2 room-acoustics diagnostics are stable by name in the v1
line, though compatible releases may add more diagnostic keys. Frame diagnostics
include `room_config`, `pyroomacoustics_version`, `speed_of_sound_mps`,
`sample_rate_hz`, `active_source_count`, `scheduled_source_ids`,
`per_source_rir_summary`, and `per_source_rir_length_samples`. Detection
diagnostics include `estimated_tdoa_matrix_s`, `gcc_phat_peaks`,
`direct_path_delay_s`, `per_mic_rms`, `rir_length_samples`,
`rir_peak_delay_s`, `waveform_sample_count`, `source_waveform_mode`,
`room_source_position_m`, and `room_microphone_positions_m`.

`room_acoustics` remains optional: pure package import and L0/L1 use do not
require `pyroomacoustics`, `scipy`, or `soundfile`. Missing
`pyroomacoustics` raises `OptionalDependencyUnavailable` lazily when L2 is
used. `soundfile` is required only for real file-backed `audio_asset_path`
loading, not generated waveforms.

Acoustic fidelity ladder metadata:

- `AcousticFidelityLevel`
- `AcousticFidelityMetadata`
- `ACOUSTIC_FIDELITY_LADDER`
- `fidelity_level_for_backend`

Frame trace and schema helpers:

- `frame_to_trace_dict`
- `frame_from_trace_dict`
- `write_frame_trace`
- `read_frame_trace`
- `append_frame_jsonl`
- `AudioFrameJsonlWriter`
- `audio_sensor_frame_json_schema`
- `write_audio_sensor_frame_json_schema`

CLI commands:

- `isaac-audio-sensors validate-config`
- `isaac-audio-sensors simulate`
- `isaac-audio-sensors export-trace`
- `isaac-audio-sensors export-schema`

Isaac Sim explicit lifecycle:

- `IsaacAudioArraySensor.from_stage(...)`
- `IsaacAudioArraySensor.from_config(...)`
- `start(...)`
- `stop()`
- `reset()`
- `update(...)`
- `capture(...)`
- `get_latest_frame()`
- `configure_writer(...)`
- `close()`
- `build_stage_snapshot(...)` with explicit `array_prim_path`
- `create_sound_prim(...)`
- `create_listener_prim(...)`

The stage-authoring helpers `attach_sound_source_attrs(...)`,
`attach_microphone_array_attrs(...)`, and `attach_microphone_attrs(...)` are
stable by their module paths under `isaac_audio_sensors.isaac.stage_audio`.

## Provisional But Supported

Provisional APIs are supported in compatible v1 releases and should not be
removed or renamed without a deprecation path. Their detailed config fields,
diagnostics payloads, and selection heuristics may grow as Isaac Sim/Lab
integration is validated on more assets. Changes must be additive or documented
with a deprecation note.

Isaac Sim semantic discovery and pose resolution:

- `IsaacAudioDiscoveryCfg`
- `IsaacAudioSceneBindingCfg`
- `discover_stage_audio(...)`
- `IsaacAudioArraySensor.from_discovered_stage(...)`
- `discover_sound_sources(...)`
- `discover_listeners(...)`
- `discover_microphone_arrays(...)`
- `IsaacStagePoseResolver`
- `resolve_world_pose(...)`
- `StagePose`
- discovery record types such as `DiscoveredAudioArray`,
  `DiscoveredAudioSource`, `IsaacAudioDiscoveryResult`, `ArrayRecord`,
  `SourceRecord`, and `ListenerRecord`

Isaac Lab sensor wrapper and class recovery:

- `AudioArraySensorCfg`
- `AudioArraySensorData`
- `AudioArraySensor`
- `AudioArraySensorClasses`
- `ensure_isaac_lab_sensor_classes()`
- `get_audio_array_sensor_classes(...)`

Isaac Lab stage and entity binding:

- `LabAudioStageBindingCfg`
- `LabAudioEntityBindingCfg`
- `LabAudioSourceEntityCfg`
- `AudioArraySensor.bind_env(...)`
- `AudioArraySensor.bind_envs(...)`
- `AudioArraySensor.bind_provider(...)`
- `AudioArraySensor.bind_lab_stage(...)`
- `AudioArraySensor.bind_lab_scene(...)`
- `AudioArraySensor.bind_lab_env(...)`
- `AudioArraySensor.bind_lab_entities(...)`
- `AudioArraySensor.bind_lab_scene_entities(...)`
- `AudioArraySensor.bind_lab_env_entities(...)`
- `AudioArraySensor.from_lab_scene(...)`
- `AudioArraySensor.from_scene_snapshot(...)`
- `AudioArraySensor.from_lab_entities(...)`

Reference Omniverse extension UX and optional Replicator capability:

- import-safe extension package under `exts/isaac_audio_sensors.omni`
- selected-prim array/source/base binding through the reference UI/controller
- array/source `ias:*` metadata authoring
- semantic discovery, start/update/stop lifecycle controls, and debug overlays
- package-native latest-frame JSON, JSONL trace, and config import/export

Optional Omniverse Replicator recording path:

- `AudioSensorReplicatorRecorder`
- `AudioSensorReplicatorRecorder.start(...)`
- `AudioSensorReplicatorRecorder.write_frame(...)`
- `AudioSensorReplicatorRecorder.flush()`
- `AudioSensorReplicatorRecorder.stop()`
- `ReplicatorRecorderStatus`
- `ReplicatorWriteResult`
- `ReplicatorIntegrationError`
- `audio_sensor_frame_replicator_payload(...)`
- `require_replicator_core()`
- `DEFAULT_REPLICATOR_WRITER_NAME`
- `DEFAULT_REPLICATOR_ANNOTATOR_NAME`
- `PAYLOAD_SCHEMA_VERSION`

The Replicator path is optional and imported lazily. Compatible v1 releases
should preserve readable missing-runtime errors, full `AudioSensorFrame` v1
payload recovery, and additive payload metadata. Writer and annotator
registration details may vary by Isaac/Kit runtime and are recorded as
diagnostics rather than treated as stable core behavior. Replicator is supported
only as an optional extension capability: core package import,
`AudioSensorFrame`, JSON/JSONL export, `IsaacAudioArraySensor`, and the Isaac
Lab sensor APIs must remain usable without `omni.replicator.core`.

## Experimental

Experimental surfaces are useful for development but are not compatibility
anchors for the v1 stable surface. They may change after changelog
documentation.

- `isaac_audio_sensors.isaac.viz`
- structured debug primitive details beyond their documented fields
- diagnostic JSON files emitted by live smoke scripts
- reference Kit extension UI layout and controller implementation details under
  `isaac_audio_sensors.isaac.extension_ui` and `exts/`
- Replicator annotator-registration details and non-contract payload metadata
  beyond the recoverable `AudioSensorFrame` v1 payload
- `isaac_audio_sensors.examples`
- scripts under `scripts/`, except for the command-line contract documented in
  `docs/validation.md`
- extra `room_acoustics` diagnostics beyond the supported optional L2 names
  listed in this document

Package-native `AudioFrameJsonlWriter` remains the stable core recording path.
Omniverse Replicator recording is supported only inside Isaac Sim/Kit runtimes
that expose compatible `omni.replicator.core` APIs. `AudioFrameJsonlWriter`
and package JSON/JSONL exports remain the stable v1 package-native recording
path.

## Internal And Private

Names starting with `_` are private. Provider implementation classes, fake
stage/test helpers, import-cache helpers, and script implementation details are
not public API unless they are explicitly listed above.

## AudioSensorFrame V1 Contract

`AudioSensorFrame` is the primary stable data contract for the v1 line. The public
schema is `ias.audio_sensor_frame.v1`, exported at
`docs/schemas/audio_sensor_frame.v1.schema.json`.

Compatible v1 releases must preserve these top-level JSON fields:

- `schema_version`
- `frame_id`
- `frame_name`
- `timestamp_ms`
- `start_time_s`
- `end_time_s`
- `sample_rate_hz`
- `frame_index`
- `backend_id`
- `array_id`
- `array_pose`
- `coordinate_convention`
- `units`
- `provenance`
- `max_events`
- `detections`
- `aggregate_per_mic_rms`
- `waveform_paths`
- `diagnostics`

Detection objects must preserve:

- `detection_id`
- `source_id`
- `class_label`
- `detection_mode`
- `timestamp_ms`
- `ground_truth_bearing_deg`
- `source_distance_m`
- `doa`
- `source_pose`
- `per_mic_delay_s`
- `per_mic_rms`
- `audio_asset_path`
- `diagnostics`

`Pose3D` objects must preserve `position_m`, `orientation_xyzw`, `frame`, and
`coordinate_convention`. Coordinates use
`x_forward_y_right_z_up_clockwise_bearing`: local `+X` is array forward, local
`+Y` is array right, `+Z` is up, positions are meters, and bearings are degrees
clockwise from array forward.

`DoaEstimate` objects must preserve:

- `estimated_bearing_deg`
- `candidate_bearing_deg`
- `bearing_sector`
- `bearing_confidence`
- `ambiguity_class`
- `ambiguity_reason`

Additive optional v1 DOA fields (absent in traces written before 1.7.0; a
v1 reader that ignores them must still interpret the frame correctly):

- `estimated_elevation_deg`: elevation in degrees up from the array's
  forward/right plane in `[-90, +90]`, positive toward array up; `null`
  unless the producer can resolve elevation (rank-3 microphone layouts).
- `candidate_elevation_deg`: candidate elevations in the same convention.

Detection objects gained the matching additive optional field
`ground_truth_elevation_deg` (oracle source elevation, same convention,
`null` in older traces). `bearing_confidence` covers the full estimated
direction, including elevation when present.

Bearing sectors are frozen as canonical 8-way labels in the
`x_forward_y_right_z_up_clockwise_bearing` convention. Bearings are normalized
into `[0, 360)`, measured clockwise from array forward, and assigned to
half-open 45-degree bins centered on:

| Sector | Center | Inclusive lower bound | Exclusive upper bound |
| --- | ---: | ---: | ---: |
| `straight` | `0.0` | `337.5` | `22.5` |
| `straight_right` | `45.0` | `22.5` | `67.5` |
| `right` | `90.0` | `67.5` | `112.5` |
| `behind_right` | `135.0` | `112.5` | `157.5` |
| `behind` | `180.0` | `157.5` | `202.5` |
| `behind_left` | `225.0` | `202.5` | `247.5` |
| `left` | `270.0` | `247.5` | `292.5` |
| `straight_left` | `315.0` | `292.5` | `337.5` |

The wraparound `straight` bin includes `337.5 <= bearing < 360.0` and
`0.0 <= bearing < 22.5`. The upper boundary belongs to the next clockwise
sector, so `22.5` maps to `straight_right`, `67.5` maps to `right`, and
`337.5` maps to `straight`.

`units` must include these stable keys and values:

- `position`: `m`
- `orientation`: `quaternion_xyzw`
- `bearing`: `deg_clockwise_from_array_forward`
- `distance`: `m`
- `time`: `s`
- `timestamp`: `ms`
- `sample_rate`: `Hz`
- `rms`: `linear`
- `gain`: `dB`

Additive optional unit keys are emitted by current writers but may be absent
in older v1 traces:

- `elevation`: `deg_up_from_array_horizontal`

`timestamp_ms` is an integer timestamp in milliseconds. `start_time_s` and
`end_time_s` are seconds. `frame_index` is non-negative when present.
`end_time_s` must be greater than `start_time_s` when both are present.

`max_events` is deterministic: frame producers must not emit more detections
than the configured limit. When the limit truncates detections, the ordering
must remain deterministic for the backend and input scene.

The allowed frame provenance values are stable:

- `synthetic/core`
- `room_acoustics`
- `isaac_live`
- `replay/trace`

Diagnostics are intentionally open-ended dictionaries. Compatible releases may
add diagnostic keys. They must not remove or rename documented diagnostics used
to identify provenance for current live-stage and Lab bindings without a
deprecation period.

The v1 JSON Schema uses required stable fields plus forward-compatible optional
fields. Compatible v1 releases may add optional frame, detection, DOA, pose, or
diagnostics fields. They must not remove, rename, or change semantics of the
documented v1 fields without creating a new schema version or documenting a
deprecation path.

Two-microphone front/back ambiguity must stay explicit. Producers must use
`doa.ambiguity_class`, `doa.ambiguity_reason`, and
`doa.candidate_bearing_deg` rather than pretending the bearing is unique. Isaac
Lab tensorization exposes the same state through `ambiguity_mask`, where a
non-null `ambiguity_class` maps to `True`.

## Acoustic Fidelity Ladder Compatibility

The public acoustic fidelity ladder is documented in
`docs/acoustic_fidelity.md` and exposed from the pure core through
`ACOUSTIC_FIDELITY_LADDER`, `AcousticFidelityLevel`,
`AcousticFidelityMetadata`, and `fidelity_level_for_backend(...)`.

The v1 levels are:

- L0 `geometry_only`: stable v1 runtime backend id for deterministic bearing,
  distance, and sector labels.
- L1 `tdoa_synthetic`: stable v1 runtime backend id for direct-path synthetic
  delay/RMS diagnostics and explicit ambiguity metadata.
- L2 `room_acoustics`: supported optional v1 runtime backend id using
  `pyroomacoustics` only when that backend is used.
- L3 `advanced_realism`: provisional v1 future backend family for richer
  wave/RIR, occlusion, material, directivity, noise, and estimator realism.
- L4 `sim_real_calibration`: experimental/tooling v1 future family for
  measured array pose, gain, time-offset, noise, validation artifacts, and
  sim-vs-real comparison tools.

`KNOWN_BACKENDS` and `get_backend(...)` remain limited to implemented runtime
backend ids in v1: `geometry_only`, `tdoa_synthetic`, and `room_acoustics`.
L3 and L4 may appear in ladder metadata and docs, but they are not selectable
stable runtime backends in the v1 line unless future implementations and tests
are added.

All levels must emit, or future implementations must emit, `AudioSensorFrame`
v1-compatible records until a new schema version is introduced. L3/L4
extensions must use optional config, optional diagnostics, optional artifacts,
and optional dependency extras instead of changing stable v1 required fields or
breaking L0-L2 readers.

## Core Compatibility Promises

Core dataclass constructor names and validation semantics are stable for valid
inputs. Patch releases may reject invalid or ambiguous inputs earlier, but they
must not require Isaac, Lab, torch, protobuf, ROS 2, CUDA, or
`pyroomacoustics` for importing `isaac_audio_sensors` or the pure core modules.

Backend compatibility is based on:

- backend ids;
- `simulate(scene, sensor, time_window) -> AudioSensorFrame`;
- deterministic frame ids/names for the same valid scene, array, backend, and
  time window;
- `AudioTimeWindow.max_events` propagation into `AudioSensorFrame.max_events`.

The optional `room_acoustics` backend may require `pyroomacoustics` only when
the backend is used. It is not a full engine-level acoustics replacement.

## Isaac Sim Compatibility Promises

`IsaacAudioArraySensor` keeps a lifecycle-oriented API:

1. construct from config, explicit stage path, or discovered stage;
2. call `start()`;
3. call `update(...)` or `capture(...)`;
4. read `get_latest_frame()`;
5. call `stop()` and `close()`.

Compatible v1 releases must keep live Isaac failures lazy and explicit.
Importing `isaac_audio_sensors.isaac` in a non-Isaac Python process must not
require `pxr`, `omni`, `isaacsim`, CUDA, or an NVIDIA GPU.

For explicit stage binding, `build_stage_snapshot(...)` and
`IsaacAudioArraySensor.from_stage(...)` must continue to support:

- a required array prim path;
- optional robot/base prim path provenance;
- optional source prim filtering;
- USD time-code reads through `usd_time_code` or sensor time-code mapping;
- live re-read of moved source, array, parent, and microphone child transforms;
- fallback `ias:*` attributes and simple `xformOp` stacks for duck-typed tests.

Semantic discovery is provisional but supported. It must continue to discover
common arrays and sources from `ias:*` metadata, native sound attributes,
source-like USD type/name signals, child microphone prims, configured roots and
filters, and preferred array/source selection.

## Isaac Lab Compatibility Promises

When imported after Isaac Lab/Kit initialization, `AudioArraySensorCfg` must be
a real `SensorBaseCfg` subclass and `AudioArraySensor` must be a real
`SensorBase` subclass. In a normal Python process, fallback classes must remain
import-safe and must not silently claim real Lab inheritance.

Live Lab callers should use `ensure_isaac_lab_sensor_classes()` after
AppLauncher initialization when they need real Lab classes. If fallback classes
were imported too early, the recovery API must either return proven real
classes or raise `IsaacLabUnavailable` with import-order guidance.

`AudioArraySensorData` keeps these fixed-shape observation buffers:

- `event_presence`: bool `[num_envs, max_events]`
- `bearing_deg`: float32 `[num_envs, max_events]`
- `confidence`: float32 `[num_envs, max_events]`
- `sector_onehot`: float32 `[num_envs, max_events, 8]`
- `per_mic_rms`: float32 `[num_envs, max_events, num_mics]`
- `ambiguity_mask`: bool `[num_envs, max_events]`

The buffers must stay on the configured sensor/device in torch-backed Lab
paths. GPU-required validation must fail if the Lab runtime falls back to CPU
or splits audio tensors across devices.

Stage binding through `LabAudioStageBindingCfg` must continue to support
cloned-env namespace templates, explicit or discovered arrays and sources,
child microphone metadata, live transform re-reads for selected env ids, and
USD world-transform provenance when `pxr.UsdGeom` is available.

Entity binding through `LabAudioEntityBindingCfg` and
`LabAudioSourceEntityCfg` must continue to support common Isaac Lab scene/entity
patterns by duck typing:

- `scene[name]`
- `scene.<name>`
- `scene.articulations[name]`
- `scene.rigid_objects[name]`
- `scene.rigid_object_collections[name]`
- `env.scene`
- `env.unwrapped.scene`

Supported pose tensor families are `root_state_w`,
`root_pos_w`/`root_quat_w`, `body_state_w`, and
`body_pos_w`/`body_quat_w`, on the entity or `entity.data`. Body names may come
from `body_names`, `link_names`, or the same fields under `.data`.

The entity binding contract covers common Isaac Lab tensor/entity patterns. It
does not promise support for arbitrary custom asset APIs unless those layouts
are tested or adapted through `bind_provider(...)`.

## Diagnostics And Provenance

Diagnostics are compatibility evidence, not a narrow schema. The following
top-level diagnostic namespaces are supported and should remain readable when
their corresponding path is used:

- `frame.diagnostics["stage_snapshot"]` for Isaac Sim live stage capture;
- `frame.diagnostics["stage_binding"]` for Isaac Lab cloned-stage binding;
- `frame.diagnostics["entity_binding"]` for Isaac Lab entity tensor binding.

Compatible releases may add fields to these dictionaries. Existing fields that
identify transform provenance, selected array/source, time code, robot/body
source, env-origin handling, tensor device, and selected-env read counts should
not be removed in the v1 line without a deprecation note.

The namespace meanings are stable even though their inner dictionaries are
open-ended:

- `stage_snapshot` records live Isaac Sim stage evidence such as selected prims,
  transform source, stage time code, and discovery or pose provenance.
- `stage_binding` records Isaac Lab cloned-stage binding evidence such as
  environment id, namespace expansion, selected array/source prims, transform
  source, and time-code mapping.
- `entity_binding` records Isaac Lab scene/entity tensor evidence such as robot
  entity and body, source entity and body, env-origin handling, tensor device,
  and selected-env reads.

## Deprecation Policy

For compatible v1 releases, stable APIs should not be removed or renamed. If a stable API must
change, add a replacement first, document the deprecation in `CHANGELOG.md`,
keep the old path working through the next compatible pre-release or patch
release, and add tests for both old and new paths while both are supported.

Provisional APIs follow the same no-surprise rule for names and import paths,
but fields and diagnostics may grow. Experimental APIs may change with a
changelog note.

Semantic versioning expectation:

- patch release: bug fixes, validation, docs, and compatible additive API work;
- minor release: new public APIs, promotion of provisional APIs, or compatible
  public-surface expansion;
- major release: incompatible public API changes.

## API Change Release Checklist

Before any release candidate or compatible release that changes public API,
verify:

- `docs/api_freeze_0_1.md` lists each stable, provisional, experimental, and
  private surface correctly.
- `docs/api_reference.md`, README examples, and trace examples match the
  current API.
- `docs/schemas/audio_sensor_frame.v1.schema.json` is regenerated with
  `make export-schema` when schema code changes.
- Existing `AudioSensorFrame` v1 required fields and documented provenance
  values remain compatible, or a new schema version is created.
- Core import works without Isaac Sim, Isaac Lab, Omniverse, `pyroomacoustics`,
  protobuf, ROS 2, CUDA, or torch.
- Public import tests cover `isaac_audio_sensors`, `isaac_audio_sensors.isaac`,
  and `isaac_audio_sensors.lab` in an optional-dependency-blocked process.
- `make test`, `make lint`, `make build`, `make import-smoke`,
  `make validate-config`, `make export-schema`, `make audit-dist`, and
  `git diff --check` pass.
- Live Isaac Sim and Isaac Lab GPU smoke checks are attempted on an installed
  Isaac runtime, or exact blockers are recorded in the release notes.
