# Architecture

`isaac-audio-sensors` is split into four layers.

## Pure Core

`isaac_audio_sensors.core` contains dataclasses, microphone-array geometry,
backend protocols, config loading, JSON Schema export, trace IO, and DOA
helpers. It must import in a normal Python environment without Isaac Sim, Isaac
Lab, Omniverse, ROS 2, protobuf, or downstream project modules.

The core frame boundary is `AudioSensorFrame` schema
`ias.audio_sensor_frame.v1`. It carries deterministic IDs/names, array and
source poses, explicit units, provenance, time-window fields, and `max_events`
semantics for downstream consumers.

## Isaac Sim

`isaac_audio_sensors.isaac` contains lazy Isaac Sim helpers for authoring and
discovering sound sources, listeners, and microphone arrays on a USD-like stage.
`IsaacAudioArraySensor` can bind an explicit array prim path, or it can bind a
stage through `IsaacAudioSceneBindingCfg` and semantic discovery. Discovery
uses `ias:*` metadata, native sound attrs, USD type/name signals, child
microphone prims, robot/base context, and configurable filters. Each update
rebuilds the stage snapshot, so moved source/array USD transforms and active
sound windows are reflected in the emitted frame.

The Sim snapshot path uses `IsaacStagePoseResolver` for live world poses. In a
USD runtime it prefers lazy `pxr.UsdGeom` APIs, including `UsdGeom.XformCache`
or `ComputeLocalToWorldTransform`. For import-safe tests and non-Isaac
environments it falls back to `ias:position_world`,
`ias:orientation_world_quat`, and simple `xformOp` parent stacks. Diagnostics
attached under `frame.diagnostics["stage_snapshot"]` identify transform
provenance, time code, source poses, array poses, optional robot/base pose, and
microphone child offsets, discovery reasons, selected array/source, and
metadata provenance.

Debug visualization is split into pure structured primitives and a lazy Isaac
debug-draw renderer. The structured path is always available for tests,
fallback export, and future USD geometry authoring.

## Isaac Lab

`isaac_audio_sensors.lab` adapts core frames into Isaac Lab sensor data. When
the module is imported after Isaac Lab/Kit is initialized,
`AudioArraySensorCfg` inherits `SensorBaseCfg` and `AudioArraySensor` inherits
`SensorBase`. When Isaac Lab is unavailable, fallback classes keep the package
importable and run the same torch-backed tensor conversion tests without
claiming Isaac Lab inheritance.

Live Lab code should resolve classes through
`ensure_isaac_lab_sensor_classes()`. That API detects the pre-AppLauncher
fallback import case, reloads the Lab modules once when real Lab bases are now
available, and otherwise raises an explicit `IsaacLabUnavailable` recovery
error.

The Lab layer owns fixed-shape RL buffers:
`event_presence`, `bearing_deg`, `confidence`, `sector_onehot`, `per_mic_rms`,
and `ambiguity_mask`. The sensor follows the `SensorBase` lazy-data model:
`update(dt)` advances timestamps and marks buffers outdated, while `data`
refreshes only the environments that need recomputation. `reset(env_ids)` and
selected `update(..., env_ids=[...])` operate on environment-indexed buffers.

Cloned environments can be represented through explicit binding:
`bind_envs(...)` for one snapshot/spec per environment, `bind_env(...)` for
single-env replacement, or `bind_provider(...)` for on-demand scene snapshots.
For USD/stage-backed tasks, `bind_lab_stage(...)` plus
`LabAudioStageBindingCfg` maps clone namespaces such as
`/World/envs/env_{env_id}` to per-env array/source prims and re-reads live
transforms for requested env ids. In a USD runtime this uses
`UsdGeom.Xformable.ComputeLocalToWorldTransform`, including nested parent
Xforms and array orientation. Duck-typed stages use the same binding path with
`ias:position_world` and simple `xformOp` fallback stacks. Scene/env wrappers
can be bound through `bind_lab_scene(...)` and `bind_lab_env(...)`. Array and
source metadata can be explicit or semantically discovered inside each clone
namespace; selected `env_ids` re-read only the requested cloned environments.

For RL task scenes, `bind_lab_entities(...)` plus
`LabAudioEntityBindingCfg` bypasses USD paths and reads common Lab entity
tensors directly. The provider resolves scene objects through duck-typed
patterns such as `scene["robot"]`, `scene.robot`,
`scene.articulations["robot"]`, and `scene.rigid_objects["speaker"]`, then
reads root/body pose tensors from the entity or `entity.data`. It composes
robot/body-mounted array poses from body pose plus array-relative pose, resolves
source root/body poses in deterministic config order, indexes only requested
`env_ids`, and converts selected rows to pure core dataclasses at the backend
boundary. Diagnostics are attached under `frame.diagnostics["entity_binding"]`.

World-frame tensor state is the default. If a task provides env-frame positions,
the entity provider can add configured or scene-provided `env_origins`; this is
an explicit mode so normal Isaac Lab `*_w` buffers are not double-shifted. The
explicit snapshot/provider APIs remain the stable lower-level contract for
custom task adapters.

## Extension And Writer

The `exts/isaac_audio_sensors.omni` wrapper provides a developer Kit extension
entry point. It can configure/start/stop/update a live sensor and export the
latest frame when loaded in Isaac. A full Replicator annotator/writer
registration is not implemented in this iteration; the supported writer path is
the package JSONL writer, `AudioFrameJsonlWriter`.

## Optional Project Adapters

Downstream projects can adapt `AudioSensorFrame` records into their own message
or graph contracts outside the core package. Those adapters should remain
optional and should not become install or import dependencies for this package.
