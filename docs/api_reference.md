# API Reference

The stable, provisional, experimental, and private compatibility surfaces are
defined in [API Freeze 0.1](api_freeze_0_1.md).
[V1 Public Scope](v1_scope.md) defines the package promise boundary and the
explicit v1 non-promises.

Primary imports are available from `isaac_audio_sensors` for common model and
backend classes. More specific helpers live under:

- `isaac_audio_sensors.core`
- `isaac_audio_sensors.core.backends`
- `isaac_audio_sensors.core.doa`
- `isaac_audio_sensors.isaac`
- `isaac_audio_sensors.lab`

The CLI entry point is:

```bash
isaac-audio-sensors --help
```

## AudioSensorFrame V1

`AudioSensorFrame` is the public frame contract for trace files and downstream
adapters. Its `schema_version` is `ias.audio_sensor_frame.v1`; that schema
version is independent from the Python package version. New frames include:

- `schema_version`: currently `ias.audio_sensor_frame.v1`;
- `frame_id` and `frame_name`: deterministic machine and display identifiers;
- `timestamp_ms`, `start_time_s`, `end_time_s`, `sample_rate_hz`, and
  `frame_index`;
- `array_pose`: `Pose3D` for the array at frame time;
- per-detection `source_pose` when the source pose is known, otherwise `null`;
- `coordinate_convention` and explicit `units`;
- `provenance`: `synthetic/core`, `room_acoustics`, `isaac_live`, or
  `replay/trace`;
- `max_events`: deterministic detection limit used for the frame.

The v1 coordinate policy is
`x_forward_y_right_z_up_clockwise_bearing`: local `+X` is array forward, local
`+Y` is array right, `+Z` is up, positions are meters, and bearings are degrees
clockwise from array forward.

Stable units:

| Key | Value | Meaning |
| --- | --- | --- |
| `position` | `m` | Positions and offsets in meters |
| `orientation` | `quaternion_xyzw` | Quaternion order `[x, y, z, w]` |
| `bearing` | `deg_clockwise_from_array_forward` | Degrees clockwise from array forward |
| `distance` | `m` | Source and microphone distances in meters |
| `time` | `s` | Frame start/end times in seconds |
| `timestamp` | `ms` | Integer timestamps in milliseconds |
| `sample_rate` | `Hz` | Audio sample rate |
| `rms` | `linear` | Linear RMS amplitude |
| `gain` | `dB` | Gain in decibels |

Timestamp semantics:

- `timestamp_ms` is milliseconds.
- `start_time_s` and `end_time_s` are seconds.
- `frame_index` is non-negative when present.
- `end_time_s` must be greater than `start_time_s` when both are present.

Detections preserve `detection_id`, `source_id`, `class_label`,
`detection_mode`, `timestamp_ms`, `ground_truth_bearing_deg`,
`source_distance_m`, `doa`, `source_pose`, `per_mic_delay_s`, `per_mic_rms`,
`audio_asset_path`, and `diagnostics`.

DOA estimates preserve `estimated_bearing_deg`, `candidate_bearing_deg`,
`bearing_sector`, `bearing_confidence`, `ambiguity_class`, and
`ambiguity_reason`. Two-microphone front/back ambiguity must remain explicit:
when the bearing is ambiguous, producers record candidate bearings plus
`ambiguity_class` and `ambiguity_reason`. Isaac Lab tensor views map a non-null
`ambiguity_class` to `ambiguity_mask=True`.

Diagnostics are open-ended and may grow additively. These top-level namespaces
are stable and must remain readable when their corresponding path is used:

- `stage_snapshot`: Isaac Sim live stage snapshot and transform provenance.
- `stage_binding`: Isaac Lab cloned-stage binding evidence and time-code
  mapping.
- `entity_binding`: Isaac Lab scene/entity tensor binding evidence.

The JSON Schema is stored at:

```text
docs/schemas/audio_sensor_frame.v1.schema.json
```

Example traces are stored at:

```text
examples/traces/minimal_frame.v1.json
examples/traces/multi_detection_frame.v1.json
examples/traces/ambiguity_frame.v1.json
examples/traces/diagnostics_provenance_sequence.v1.ndjson
```

Export the schema from code:

```bash
isaac-audio-sensors export-schema --out /tmp/audio_sensor_frame.v1.schema.json
```

## Acoustic Fidelity Ladder

The acoustic fidelity ladder is available from the import-safe core:

```python
from isaac_audio_sensors import (
    ACOUSTIC_FIDELITY_LADDER,
    AcousticFidelityLevel,
    fidelity_level_for_backend,
)
```

`ACOUSTIC_FIDELITY_LADDER` contains one metadata record for each level:

- L0 `geometry_only`: stable v1 runtime backend id.
- L1 `tdoa_synthetic`: stable v1 runtime backend id.
- L2 `room_acoustics`: supported optional v1 runtime backend id.
- L3 `advanced_realism`: provisional v1 future backend family, not a complete
  v1 runtime backend.
- L4 `sim_real_calibration`: experimental/tooling v1 future family, not a
  stable v1 runtime backend.

`fidelity_level_for_backend("geometry_only")`,
`fidelity_level_for_backend("tdoa_synthetic")`, and
`fidelity_level_for_backend("room_acoustics")` return the L0, L1, and L2
metadata records respectively. L3/L4 are represented in the ladder metadata
with no selectable v1 backend ids, so they do not change `KNOWN_BACKENDS`,
config validation, or `get_backend(...)`.

Each metadata record includes `level`, `public_name`, `lifecycle_status`,
`backend_ids`, `backend_family`, `models`, `does_not_model`,
`optional_dependencies`, `frame_contract`, and `runtime_selectable_v1`.

All current and future ladder levels emit, or must emit, `AudioSensorFrame`
v1-compatible records until a future schema version is introduced. Advanced
realism and calibration work should extend through optional config, optional
diagnostics, optional artifacts, and optional dependency extras.

## Room Acoustics Backend

`RoomAcousticsBackend` is the supported optional L2 v1 backend. It is
import-safe without optional dependencies:

```python
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend

print(RoomAcousticsBackend.is_available())
```

Install the backend with the `room` extra:

```bash
python -m pip install -e ".[room]"
```

When available, the backend builds a `pyroomacoustics.ShoeBox` from
`RoomAcousticsSpec`, computes RIRs, generates per-microphone waveforms, and
uses GCC-PHAT to estimate TDOA from those waveforms. The direct-path delay is
diagnostic comparison data rather than the DOA input. Generated source
waveforms are deterministic. File-backed `audio_asset_path` values must be
relative files under the checkout, are downmixed when multichannel, and must
match the frame sample rate. `soundfile` is used only for those file-backed
assets.

The stable optional L2 diagnostic names are:

- frame: `room_config`, `pyroomacoustics_version`, `speed_of_sound_mps`,
  `sample_rate_hz`, `active_source_count`, `scheduled_source_ids`,
  `per_source_rir_summary`, and `per_source_rir_length_samples`;
- detection: `estimated_tdoa_matrix_s`, `gcc_phat_peaks`,
  `direct_path_delay_s`, `per_mic_rms`, `rir_length_samples`,
  `rir_peak_delay_s`, `waveform_sample_count`, `source_waveform_mode`,
  `room_source_position_m`, and `room_microphone_positions_m`.

Multiple active sources use deterministic half-open window scheduling and
`max_events` truncation. In v1, scheduled sources are simulated independently;
the backend does not provide mixed-source separation.

L2 is approximate shoebox acoustics. It does not promise realistic occlusion,
material behavior, directivity, calibrated microphone response, production
beamforming, or sim-real transfer.

## Live Isaac Sensor

`IsaacAudioArraySensor.from_stage(...)` binds a stage and array prim path. The
sensor supports `start()`, `stop()`, `reset()`, `update()`,
`get_latest_frame()`, `configure_writer()`, and `close()`.

Each `update()` rebuilds a stage snapshot, follows moved USD transforms,
applies active sound windows, respects `max_events`, stores the latest frame,
and can append JSONL frames through `AudioFrameJsonlWriter`. Live-stage frames
use provenance `isaac_live` and include
`frame.diagnostics["stage_snapshot"]` with transform provenance and time-code
details.

Stage binding entry points:

- `build_stage_snapshot(stage, timestamp_ms=..., array_prim_path=...)`;
- optional `robot_base_prim_path` for robot-mounted arrays;
- optional `source_prim_path` for selecting one source prim;
- optional `usd_time_code` or `time_code` for explicit USD time reads;
- optional `diagnostics_out` for transform provenance.

`IsaacStagePoseResolver` and `resolve_world_pose(...)` are reusable lower-level
helpers. They compute world poses through `pxr.UsdGeom` when available and keep
import-safe fallbacks for `ias:position_world`, `ias:orientation_world_quat`,
`xformOp:translate`, `xformOp:orient`, and fake-stage `attributes`.

`IsaacAudioArraySensor.from_stage(...)` accepts `robot_base_prim_path`,
`usd_time_code_scale`, and `usd_time_code_offset`. `update(...,
usd_time_code=...)` and `capture(..., usd_time_code=...)` can override the time
code per frame. Without an explicit override, `update(sim_time_s=...)` uses the
simulation time as the USD time code.

Semantic discovery APIs:

- `IsaacAudioDiscoveryCfg`: typed discovery roots, array/source roots,
  include/exclude globs and regexes, robot/base array restriction, name/type
  patterns, class-label overrides, default microphone layout, default active
  windows, required array/source flags, and metadata precedence diagnostics.
- `IsaacAudioSceneBindingCfg`: Isaac Sim-facing binding config with
  `preferred_array`, `preferred_source`, and `rediscover_each_update`.
- `discover_stage_audio(stage, cfg=...)`: returns discovered array/source
  records, selected entities, and diagnostics.
- `IsaacAudioArraySensor.from_discovered_stage(stage, binding_cfg=...)`:
  constructs a live sensor without exact path wiring.

Discovery detects arrays from `ias:array_id`, `ias:layout_name`, child
microphone prims, explicit offset metadata, or configured array name/type
patterns. It detects sources from USD type `Sound`, native `filePath` and
`inputs:file` style attrs, `ias:source_id`, `ias:class_label`, asset metadata,
or configured source name patterns.

Authoring helpers in `isaac_audio_sensors.isaac.stage_audio` create common
ordinary USD custom attributes without requiring a custom schema:
`attach_microphone_array_attrs(...)`, `attach_microphone_attrs(...)`, and
`attach_sound_source_attrs(...)` cover array ids, layout, sample rate,
coordinate convention, microphone ids/offsets/orientations/gain/self-noise,
source ids, class labels, audio asset paths, active windows, gain, and
directivity.

Debug visualization uses structured primitives that are available without
Isaac. When `omni.isaac.debug_draw` is available, `IsaacDebugDrawer` draws
microphones, sources, bearing rays, and sector wedges.

The reference Kit extension under `exts/isaac_audio_sensors.omni` uses the same
public Isaac helpers. Its controller can author array/source `ias:*` metadata,
bind explicit or discovered stage prims, run `IsaacAudioArraySensor`, retain
serialized overlay primitives when debug draw is unavailable, and export
package JSON/JSONL traces plus a reusable binding/config summary. It is not a
core package dependency. Optional Replicator recording is available only through
the extension path inside Isaac Sim/Kit; it imports `omni.replicator.core`
lazily, records recoverable `AudioSensorFrame` v1 payloads when available, and
does not affect the core JSON/JSONL export contract.

## Isaac Lab AudioArraySensor

`isaac_audio_sensors.lab.AudioArraySensorCfg` is a real `SensorBaseCfg`
subclass when imported after Isaac Lab is initialized. Outside Isaac Lab, it is
a fallback config with the same public fields and validation.

Use `ensure_isaac_lab_sensor_classes()` in live Isaac Lab processes that require
real inheritance. It returns `AudioArraySensorClasses` with `.sensor`, `.cfg`,
`.data`, `.lab_types`, and `.real`. `get_audio_array_sensor_classes()` can also
return import-safe fallback classes when `require_real=False`.

Primary fields:

- `prim_path`, `update_period`, `history_length`, `debug_vis`;
- `backend`, `microphone_layout`, `sample_rate_hz`;
- `max_events`, `num_mics`, `device`, `ambiguity_policy`;
- `write_waveforms`, `writer_path`.

`isaac_audio_sensors.lab.AudioArraySensor` is a real `SensorBase` subclass in
the same Lab runtime condition. It supports:

- `bind_env(env_id, scene_snapshot, sensor)`;
- `bind_envs(scene_snapshots, sensors)`;
- `bind_provider(provider, num_envs, num_mics=None)`;
- `bind_lab_stage(stage, binding_cfg)`;
- `bind_lab_scene(scene, binding_cfg)`;
- `bind_lab_env(env, binding_cfg)`;
- `bind_lab_entities(scene, binding_cfg)`;
- `bind_lab_scene_entities(scene, binding_cfg)`;
- `bind_lab_env_entities(env, binding_cfg)`;
- `from_lab_entities(cfg, scene, binding_cfg)`;
- `update(dt, force_recompute=False, env_ids=None)`;
- `reset(env_ids=None)`;
- lazy `data`.

`LabAudioStageBindingCfg` describes cloned-stage binding with optional
`num_envs`, `env_namespace_pattern`, explicit `array_prim_path`, semantic
`discover_arrays`, explicit `source_prim_paths`, semantic `discover_sources`,
optional `source_ids` and `class_labels`, microphone layout or offsets, child
microphone discovery, and optional USD time-code mapping. Path templates
support `{ENV_REGEX_NS}`, `{ENV_NS}`, `{env_id}`, and `{ENV_ID}`.

`bind_lab_stage(...)` resolves array/source world poses from
`UsdGeom.Xformable(...).ComputeLocalToWorldTransform(...)` when `pxr.UsdGeom`
is available. Duck-typed stages remain supported through `ias:position_world`
and simple `xformOp` stacks. Provider diagnostics are attached to generated
frames under `frame.diagnostics["stage_binding"]`.

`LabAudioEntityBindingCfg` describes scene/entity tensor binding for RL tasks.
Important fields are `num_envs`, optional `scene`/`env`, `robot_entity_name`,
`array_mount_body_name`, `array_relative_position_m`,
`array_relative_orientation_quat`, `microphone_layout` or
`microphone_relative_offsets_m`, `source_entities`, optional
`env_namespace_pattern`, `state_position_frame`, `env_origins`, `device`,
`state_quat_order`, and diagnostics settings.

`LabAudioSourceEntityCfg` describes one source entity with `entity_name`,
optional `body_name`, `source_id`, `class_label`, active window, gain,
directivity, optional source-relative pose, and optional fallback `prim_path`.

`bind_lab_entities(...)` resolves common Lab scene patterns without hard Isaac
Lab imports: `scene[name]`, `scene.<name>`, `scene.articulations[name]`,
`scene.rigid_objects[name]`, `scene.rigid_object_collections[name]`,
`env.scene`, and `env.unwrapped.scene`. Pose tensors may live on the entity or
`entity.data`. Supported field families are `root_state_w`,
`root_pos_w`/`root_quat_w`, `body_state_w`, and
`body_pos_w`/`body_quat_w`; body names may come from `body_names`,
`link_names`, or `.data`.

Entity provider diagnostics are attached under
`frame.diagnostics["entity_binding"]`. They include robot entity/body, body
index, tensor provenance, array relative/world pose, source entity/body
provenance, env-origin mode, tensor device, and selected-env read counts.

`AudioArraySensorData` exposes these tensor buffers in Lab/torch mode:

- `event_presence`: bool `[num_envs, max_events]`;
- `bearing_deg`: float32 `[num_envs, max_events]`, padded with `nan`;
- `confidence`: float32 `[num_envs, max_events]`;
- `sector_onehot`: float32 `[num_envs, max_events, 8]`;
- `per_mic_rms`: float32 `[num_envs, max_events, num_mics]`;
- `ambiguity_mask`: bool `[num_envs, max_events]`.

Metadata fields include `frame_ids`, `frame_names`, `source_ids`,
`class_labels`, `latest_frames`, `last_update_time_s`, `microphone_ids`, and
`waveform_paths`.
