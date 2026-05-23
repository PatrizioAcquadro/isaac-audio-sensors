# Isaac Sim

The `isaac_audio_sensors.isaac` layer provides optional helpers for Isaac Sim
and Omniverse USD stages.

Supported compatibility target:

- Isaac Sim 5.1: live smoke supported when the user's Isaac Python runtime is
  available.
- Pure Python import: supported without Isaac installed.

The helpers use lazy imports. Calling code can import the package normally in a
non-Isaac environment, and Isaac-specific failures are raised only when a live
Isaac helper actually needs `pxr`, `omni`, or `isaacsim`.

Live smoke:

```bash
PYTHONPATH=src "$ISAAC_SIM_PYTHON" scripts/live_isaac_sim_audio_smoke.py
```

The smoke script:

- creates an in-memory USD stage;
- authors sound source, listener, and microphone-array metadata;
- authors nested USD transform stacks for a robot/base frame, moving source
  parent, array prim, and microphone child prims;
- discovers the array and sources semantically from USD metadata, native sound
  attributes, names, and microphone child prims;
- selects the preferred array by id/path/name pattern;
- calls `start()`, repeated `update(...)`, `get_latest_frame()`, and `close()`;
- reads USD time-code-aware world poses on each tick and verifies changed frame
  output after source, parent, array, and microphone movement;
- evaluates the inactive sound window after the authored duration;
- builds debug primitives and uses Isaac debug draw when available;
- records GPU visibility, transform provenance, before/after poses, bearings,
  stage time-code diagnostics, JSON evidence, and JSONL frame traces under
  ignored `outputs/`.

Programmatic lifecycle:

```python
from isaac_audio_sensors.isaac import IsaacAudioArraySensor

sensor = IsaacAudioArraySensor.from_stage(
    stage=stage,
    array_prim_path="/World/RobotBase/ArrayMount/AudioArray",
    robot_base_prim_path="/World/RobotBase",
    backend="tdoa_synthetic",
    usd_time_code_scale=1.0,
    update_period_s=0.05,
    max_events=4,
    debug_draw=True,
    writer_path="outputs/isaac_audio_sensors/frames.jsonl",
)
sensor.start()
frame = sensor.update(sim_time_s=0.0)
latest = sensor.get_latest_frame()
sensor.stop()
sensor.close()
```

Semantic discovery:

```python
from isaac_audio_sensors.isaac import (
    IsaacAudioArraySensor,
    IsaacAudioSceneBindingCfg,
)

binding = IsaacAudioSceneBindingCfg(
    discovery_roots=("/World",),
    robot_base_prim_path="/World/RobotBase",
    restrict_arrays_to_robot=True,
    preferred_array="rig_front",
    required_arrays=True,
    required_sources=True,
)
sensor = IsaacAudioArraySensor.from_discovered_stage(
    stage=stage,
    binding_cfg=binding,
    backend="tdoa_synthetic",
    usd_time_code_scale=1.0,
)
```

Discovery and explicit binding can be mixed. `from_stage(...)` and
`build_stage_snapshot(..., array_prim_path=...)` keep the explicit path API.
`IsaacAudioDiscoveryCfg` and `IsaacAudioSceneBindingCfg` add stage roots, array
roots, source roots, include/exclude glob or regex filters, robot/base array
restriction, class-label overrides, default microphone layout, required
array/source behavior, default source active windows, and metadata precedence
diagnostics.

`update()` rebuilds the stage snapshot every time. For authored metadata, active
sources are selected by half-open windows `[start_time_s, end_time_s)`. A source
with `ias:start_time_s = 0.1` and `ias:duration_s = 0.2` is active for windows
that overlap `[0.1, 0.3)`.

World poses are resolved through `IsaacStagePoseResolver`. When `pxr.UsdGeom`
is available, the resolver uses USD world-transform APIs such as
`UsdGeom.XformCache` or `UsdGeom.Xformable(...).ComputeLocalToWorldTransform`.
Duck-typed stages remain supported with fallback `ias:position_world`,
`ias:orientation_world_quat`, `xformOp:translate`, and `xformOp:orient`
attributes. The resolver follows nested parent transforms, so arrays can be
mounted under robot/base prims, sources can live under moving objects, and
microphone child prims can provide array-local offsets through normal USD
transforms.

Frame semantics:

- world frame: the USD stage world frame used by resolved source and array
  poses;
- robot/base frame: optional provenance frame configured with
  `robot_base_prim_path`; moving this prim changes mounted array world poses;
- array frame: local `+X` forward, `+Y` right, `+Z` up, with clockwise bearing
  from array forward;
- microphone frame: microphone child prim offsets are converted into the array
  frame before TDOA and RMS calculations.

`update(sim_time_s=...)` uses simulation time as the USD time code by default.
Callers can pass `usd_time_code=...` to `update()` or `capture()`, set
`usd_time_code_scale`/`usd_time_code_offset` on the sensor, or pass
`usd_time_code` directly to `build_stage_snapshot(...)`.

Native USD/Isaac sound attributes are read on a best-effort basis where the
stage exposes them through ordinary attributes such as `filePath`, `startTime`,
`duration`, and `gain`. Package metadata under `ias:*` is the documented path.
These are ordinary USD custom attributes, not a custom USD schema.

Supported `ias:*` metadata:

| Prim kind | Attribute | Meaning |
| --- | --- | --- |
| Array or listener | `ias:array_id` | Stable array id used by frames and discovery |
| Array | `ias:layout_name` | Named package microphone layout fallback |
| Array | `ias:sample_rate_hz` | Frame sample rate for the array |
| Array | `ias:coordinate_convention` | Coordinate convention string for emitted frames |
| Array | `ias:microphone_relative_offsets_m` | Array-local microphone offsets when child prims are not authored |
| Array | `ias:microphone_ids` | Optional ids matching `ias:microphone_relative_offsets_m` |
| Microphone child | `ias:microphone_id` | Stable microphone id |
| Microphone child | `ias:relative_position_m` | Array-local offset override in meters |
| Microphone child | `ias:relative_orientation_quat` | Array-local microphone orientation in `[x, y, z, w]` order |
| Microphone child | `ias:gain_db` | Per-microphone gain |
| Microphone child | `ias:self_noise_db` | Optional per-microphone self-noise diagnostic |
| Source | `ias:source_id` | Stable source id used by detections |
| Source | `ias:class_label` | Detection class label, such as `Speech` or `Alarm` |
| Source | `ias:audio_asset_path` | Package-level audio asset reference; native `filePath` is also read |
| Source | `ias:start_time_s` | Active-window start time in seconds |
| Source | `ias:duration_s` | Active-window duration in seconds |
| Source | `ias:gain_db` | Source gain in decibels |
| Source | `ias:directivity` | Source directivity label, currently diagnostic |

Array discovery signals are `ias:array_id`, child microphone prims with
`ias:microphone_id`, `ias:layout_name`, configured array name/type patterns, and
explicit `array_prim_path`. Microphones come from direct child prim offsets,
`ias:microphone_relative_offsets_m`/`ias:microphone_ids`, or a named/default
layout. Source discovery signals are USD type `Sound`, `filePath`,
`inputs:file`, `inputs:audio`, `ias:audio_asset_path`, `ias:source_id`,
`ias:class_label`, and configured source name patterns.

Frame diagnostics include `discovery_provenance`, candidate reasons, selected
array/source, source active-window provenance, class-label provenance,
robot/base transform diagnostics when configured, and per-prim transform
provenance. Discovery does not add a custom USD schema; all package metadata is
ordinary custom `ias:*` attributes.

This package is not an official NVIDIA extension. The extension metadata under
`exts/` is included for developers who want a lightweight Kit workflow with
start/stop/update/export controls. Replicator annotator/writer registration is
not implemented yet; use the package JSONL writer for frame recording.
