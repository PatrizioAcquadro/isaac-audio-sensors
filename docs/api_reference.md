# API Reference

The stable, provisional, experimental, and private compatibility surfaces are
defined in [API Freeze 0.1](api_freeze_0_1.md).

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
adapters. New frames include:

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

The JSON Schema is stored at:

```text
docs/schemas/audio_sensor_frame.v1.schema.json
```

Example traces are stored at:

```text
examples/traces/minimal_frame.v1.json
examples/traces/multi_detection_frame.v1.json
```

Export the schema from code:

```bash
isaac-audio-sensors export-schema --out /tmp/audio_sensor_frame.v1.schema.json
```

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

Debug visualization uses structured primitives that are available without
Isaac. When `omni.isaac.debug_draw` is available, `IsaacDebugDrawer` draws
microphones, sources, bearing rays, and sector wedges.

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
