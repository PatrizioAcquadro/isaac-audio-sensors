# Isaac Lab

`isaac_audio_sensors.lab` exposes audio observations through an Isaac
Lab-compatible sensor layer.

The supported v1 Lab scope is defined in [V1 Public Scope](v1_scope.md). Isaac
Lab support is a package sensor path with its own live validation gate; Alex,
SquadBot, ROS 2, and downstream task validation are not v1 release gates for
the sensor package.

When Isaac Lab is initialized before import, the public classes are real Isaac
Lab subclasses:

- `AudioArraySensorCfg(SensorBaseCfg)`
- `AudioArraySensor(SensorBase)`

In a normal Python environment without Isaac Lab, the same module imports with a
fallback class set. The fallback does not pretend to inherit from Isaac Lab; it
exists so core tests, examples, and downstream tooling can exercise the same
audio conversion logic without importing `carb`, `omni`, or `isaaclab`.

For live Isaac Lab use, launch Kit/AppLauncher before importing this package.
The smoke script follows that order and resolves classes through the public
hardening API:

```python
# after AppLauncher/SimulationApp initialization
from isaac_audio_sensors.lab import ensure_isaac_lab_sensor_classes

classes = ensure_isaac_lab_sensor_classes()
AudioArraySensor = classes.sensor
AudioArraySensorCfg = classes.cfg
```

If fallback classes were imported before AppLauncher, call
`ensure_isaac_lab_sensor_classes()` after AppLauncher and use the returned
classes. The function reloads the Lab modules once when real Lab bases are now
available. If recovery cannot prove real `SensorBaseCfg`/`SensorBase`
inheritance, it raises `IsaacLabUnavailable` with restart/import-order
instructions rather than returning silent fallback classes.

## Configuration

`AudioArraySensorCfg` includes the Isaac Lab sensor fields plus audio-specific
settings:

- `prim_path`: Isaac Lab sensor prim path or env regex path.
- `update_period`: seconds between buffer refreshes. `0.0` updates every step.
- `history_length`: carried for `SensorBaseCfg` compatibility.
- `debug_vis`: toggles the no-op debug visualization hook.
- `backend`: `geometry_only`, `tdoa_synthetic`, or `room_acoustics`.
- `microphone_layout`: built-in layout name used before a bound spec exists.
- `sample_rate_hz`: default sample rate for generated array specs.
- `max_events`: fixed event dimension for RL tensors.
- `num_mics`: optional fixed microphone dimension. When omitted, it is derived
  from the bound `MicrophoneArraySpec`.
- `device`: optional torch device for fallback/offline allocation. In an active
  Isaac Lab simulation, `SensorBase` initialization uses the simulation device.
- `ambiguity_policy`: currently `none` or `front_hemisphere` for TDOA-style
  backends.
- `compute_path`: `auto` (default), `scalar`, or `batched`. Selects between
  the per-env scalar reference pipeline and the batched tensor fast path for
  entity bindings. See "Batched Compute Path" below.
- `writer_path`: reserved JSONL trace export option.
- `write_waveforms` and `waveform_dir`: enable per-frame multichannel WAV
  export for the `room_acoustics` backend. Frames are written under
  `waveform_dir` (default `outputs/audio_waveforms`) with one `env_{id}`
  subdirectory per environment, and `AudioSensorFrame.waveform_paths` is
  populated.

## Tensor Buffers

`AudioArraySensor.data` returns `AudioArraySensorData` with fixed-shape buffers.
In Lab mode and in the torch-backed fallback, buffers are torch tensors on the
sensor device:

| Field | Shape | dtype | Padding |
| --- | --- | --- | --- |
| `event_presence` | `[num_envs, max_events]` | `torch.bool` | `False` |
| `bearing_deg` | `[num_envs, max_events]` | `torch.float32` | `nan` |
| `confidence` | `[num_envs, max_events]` | `torch.float32` | `0.0` |
| `sector_onehot` | `[num_envs, max_events, 8]` | `torch.float32` | `0.0` |
| `per_mic_rms` | `[num_envs, max_events, num_mics]` | `torch.float32` | `0.0` |
| `ambiguity_mask` | `[num_envs, max_events]` | `torch.bool` | `False` |

`event_presence` is the authoritative mask separating detections from padding.
`bearing_deg` uses `nan` only for padded or unknown bearings. Sector ordering is
the package `SECTOR_ORDER`: `straight`, `straight_right`, `right`,
`behind_right`, `behind`, `behind_left`, `left`, `straight_left`.

Metadata that does not fit naturally into tensors is stored per environment:
`frame_ids`, `frame_names`, `latest_frames`, and per event `source_ids` and
`class_labels`.

## Binding Model

The sensor does not assume a single global scene. Explicit binding remains
supported:

```python
sensor = AudioArraySensor(cfg)
sensor.bind_envs(scene_snapshots=(env0_snapshot, env1_snapshot), sensors=array_spec)
sensor.update(dt=0.05, force_recompute=True)
obs = sensor.data
```

Use `bind_env(env_id=..., scene_snapshot=..., sensor=...)` to replace one cloned
environment binding. Use `bind_provider(provider=..., num_envs=..., num_mics=...)`
when scene snapshots are generated on demand; the provider receives requested
`env_ids` and returns `{env_id: (snapshot, array_spec)}`.

For Isaac Lab cloned environments, `bind_lab_stage(...)` can auto-bind from a
USD/stage-like object:

```python
from isaac_audio_sensors.lab import (
    LabAudioStageBindingCfg,
    ensure_isaac_lab_sensor_classes,
)

classes = ensure_isaac_lab_sensor_classes()
AudioArraySensor = classes.sensor
AudioArraySensorCfg = classes.cfg

cfg = AudioArraySensorCfg(
    prim_path="{ENV_REGEX_NS}/Robot/audio_array",
    update_period=0.05,
    backend="tdoa_synthetic",
    microphone_layout="quad_front",
    max_events=2,
)
sensor = AudioArraySensor(cfg).bind_lab_stage(
    stage=stage,
    binding_cfg=LabAudioStageBindingCfg(
        num_envs=2,
        env_namespace_pattern="/World/envs/env_{env_id}",
        array_prim_path="Robot/audio_array",
        source_prim_paths=("Sources/speaker",),
        source_ids=("speaker",),
        class_labels=("Speech",),
        microphone_layout="quad_front",
    ),
)
```

`array_prim_path`, `source_prim_paths`, and discovery roots may be relative to
each clone namespace or include `{ENV_REGEX_NS}`, `{ENV_NS}`, `{env_id}`, and
`{ENV_ID}` placeholders. In a real USD runtime, the provider uses
`UsdGeom.Xformable(...).ComputeLocalToWorldTransform(...)`, so nested parent
Xforms under paths such as `/World/envs/env_0/Robot/link/Sources/speaker` are
included in the world pose. Duck-typed fake stages remain supported through
`ias:position_world` and simple `xformOp:translate`/`xformOp:orient` stacks.

Stage-backed updates re-read only the requested `env_ids`. Moving a source
local Xform, a parent Xform, or an array Xform/orientation is reflected in the
next selected update without invalidating other environment rows. Generated
frames include `frame.diagnostics["stage_binding"]` with transform provenance
such as `usd:ComputeLocalToWorldTransform`, `xformOp:stack`, or
`ias:position_world`.

Semantic cloned-env discovery can replace explicit array and source paths:

```python
sensor = AudioArraySensor(cfg).bind_lab_stage(
    stage=stage,
    binding_cfg=LabAudioStageBindingCfg(
        num_envs=2,
        env_namespace_pattern="/World/envs/env_{env_id}",
        discover_arrays=True,
        array_discovery_root_path="Robot",
        preferred_array="HeadMicArray",
        discover_sources=True,
        source_discovery_root_path="Sources",
        microphone_layout="quad_front",
    ),
)
```

Array discovery matches `ias:array_id`, `ias:layout_name`, direct child
microphone prims with `ias:microphone_id`, and configured array name/type
patterns inside each clone namespace. Source discovery matches source metadata
attributes, source-like USD type names, or source-like prim names. Diagnostics
record the per-env selected array, candidate reasons, source discovery reasons,
and transform provenance under `frame.diagnostics["stage_binding"]`.

### Scene-anchored rooms

For the `room_acoustics` backend, a designated room prim's world-aligned
bounding box can set the shoebox dimensions **and** placement per cloned env:

```python
binding_cfg = LabAudioStageBindingCfg(
    num_envs=2,
    env_namespace_pattern="/World/envs/env_{env_id}",
    array_prim_path="Robot/audio_array",
    source_prim_paths=("Sources/speaker",),
    microphone_layout="quad_front",
    room_prim_path="Room",  # resolved per env like other relative paths
    room_max_order=1,
)
```

- `room_prim_path` (default `None`, disabled) resolves per env like source
  paths. A missing prim raises an error naming the resolved path. Real USD
  prims use `UsdGeom.BBoxCache`; duck-typed stages provide
  `ias:room_min_world`/`ias:room_max_world` or `ias:room_size_m`.
- The derived `RoomAcousticsSpec` gets `origin_m` = the box's minimum corner,
  per-env `room_id` (`{room_id}_env_{env_id}`), and
  `anchor_prim_path` = the resolved prim path.
- `room_absorption_from_tags` (default `True`) reads `ias:absorption` from the
  prim, else an `ias:material`/USD-semantics label looked up in
  `room_semantic_absorption` (defaults to `DEFAULT_SEMANTIC_ABSORPTION`), else
  `room_absorption`.
- `room_out_of_bounds` (`"error"`, default, or `"clamp"`) controls what
  happens when a mic/source leaves the room: errors name the offending
  `source:<id>`/`mic:<id>` and the anchor prim; clamps are reported through
  the `room_clamped_position_ids` frame diagnostic.

Per-env derivation results (dimensions, origin, absorption provenance) are
recorded under `frame.diagnostics["stage_binding"]["room"]`. Entity-tensor
bindings have no stage to anchor to; `LabAudioEntityBindingCfg.room` accepts
an explicit `RoomAcousticsSpec` (use `origin_m` to place it in world space).

Scene and environment wrappers can be bound without manually extracting the raw
stage:

```python
sensor = AudioArraySensor(cfg).bind_lab_scene(
    scene=scene,
    binding_cfg=LabAudioStageBindingCfg(
        array_prim_path="{ENV_NS}/Robot/audio_array",
        discover_sources=True,
        source_discovery_root_path="Sources",
        microphone_layout=None,
    ),
)
```

Stage resolution accepts objects with `Traverse()`, `.stage`, `.get_stage()`,
`.sim.stage`, `.world.stage`, or a live `omni.usd` context. `num_envs` is taken
from `LabAudioStageBindingCfg.num_envs` first, then common scene/env attributes
such as `num_envs` when allowed. Microphone offsets can come from
config-provided offsets, child microphone prim metadata, or a built-in layout
name.

## Scene Entity Tensor Binding

RL tasks usually work with `InteractiveScene` entities and tensor state buffers
rather than raw USD paths. `LabAudioEntityBindingCfg` and
`LabAudioSourceEntityCfg` bind those objects directly:

```python
from isaac_audio_sensors.lab import (
    LabAudioEntityBindingCfg,
    LabAudioSourceEntityCfg,
)

entity_binding = LabAudioEntityBindingCfg(
    num_envs=scene.num_envs,
    robot_entity_name="robot",
    array_mount_body_name="head",
    array_relative_position_m=(0.08, 0.0, 0.0),
    microphone_layout="quad_front",
    source_entities=(
        LabAudioSourceEntityCfg(
            entity_name="speaker",
            source_id="speaker",
            class_label="Speech",
            start_time_s=0.0,
            duration_s=1.0,
        ),
    ),
)
sensor = AudioArraySensor(cfg).bind_lab_entities(
    scene=scene,
    binding_cfg=entity_binding,
)
```

The resolver is duck typed and does not import Isaac Lab entity classes. It
tries `scene["robot"]`, `scene.robot`, `scene.articulations["robot"]`,
`scene.rigid_objects["speaker"]`, and `scene.rigid_object_collections[...]`.
It reads tensor fields on the entity or `entity.data`, including
`root_state_w`, `root_pos_w`, `root_quat_w`, `body_state_w`, `body_pos_w`, and
`body_quat_w`. Body/link names can come from `body_names`, `link_names`, or the
same fields under `.data`.

When `array_mount_body_name` is set, the microphone array world pose is resolved
from that robot body/link pose plus `array_relative_position_m` and
`array_relative_orientation_quat`. The relative offset is rotated by the body
orientation, and the array basis vectors are derived from the composed world
orientation. Sources are resolved from each configured source entity root or
body/link pose, with optional source-relative offsets, active windows, gain,
directivity, `source_id`, and `class_label`.

Entity tensors are assumed to be world-frame by default because Isaac Lab
`*_w` buffers are world-frame. If a task exposes env-local state instead, set
`state_position_frame="env"` and provide `env_origins` or `scene.env_origins`;
the provider then adds origins exactly once. Leave the default
`state_position_frame="world"` for normal `root_state_w`/`body_state_w` buffers
so clone origins are not double-applied.

Entity-backed updates follow the same selected-env contract as stage binding:
the provider receives only requested `env_ids`, indexes only those rows, keeps
the observation buffers on the sensor device, and converts selected pose rows to
core dataclasses at the backend boundary. Generated frames include
`frame.diagnostics["entity_binding"]` with robot entity/body, pose tensor
provenance, array relative pose, array world pose, source entity/body
provenance, env-origin mode, tensor device, and per-env read counts.

## Batched Compute Path

Entity bindings expose pose state as torch tensors, so the L0/L1 math
(bearings, per-microphone delays, RMS) can run as batched tensor ops over
`[num_envs, num_sources, num_mics]` instead of the per-env Python loop. The
fast path reads poses through `LabAudioEntityProvider.pose_tensor_batch()`,
keeps everything on the sensor device with no `.item()` syncs or per-env
dataclass construction, and writes all selected rows in one
`AudioArraySensorData.write_batch()` call. The scalar pipeline remains the
reference implementation; parity tests pin the batched path to it.

`AudioArraySensorCfg.compute_path` selects the path:

- `scalar`: always run the per-env reference pipeline.
- `batched`: require the fast path; raises `ValueError` naming the failed
  prerequisite when it is unavailable.
- `auto` (default): use the fast path when every prerequisite holds,
  otherwise fall back to scalar.

Prerequisites for the batched path:

| Condition | `auto` | `batched` |
| --- | --- | --- |
| Entity binding provider (`pose_tensor_batch`) | required | required |
| `backend` is `geometry_only` or `tdoa_synthetic` | required | required |
| `write_waveforms=False` | required | required |
| `tdoa_synthetic`: >= 3 microphones, rank-2 local XY layout | required | required |
| Binding `diagnostics=False` | required | not required |

The `diagnostics=False` gate keeps `auto` from silently changing the
metadata surface: the batched path produces tensor observations only and
leaves `latest_frames`, `frame_ids`, `frame_names`, per-event
`source_ids`/`class_labels`, `waveform_paths`, and provider diagnostics as
`None`/empty for the rows it writes. Static source ids and class labels are
still available from the binding config. Setting `compute_path="batched"`
opts into that reduced surface explicitly, even with diagnostics enabled.

Numerical notes:

- The batched path computes in float32 (the entity tensor dtype). End-to-end
  bearings match the scalar path within 0.05 degrees (typically much
  closer), confidence within 5e-4, and per-mic RMS within 1e-4 relative.
- `sector_onehot` can differ from the scalar path for bearings within ~1e-3
  degrees of an exact 22.5 + 45k sector boundary.
- TDOA stress controls (delay noise, clock jitter, gain mismatch, air
  absorption) are zero in Lab sensor usage and are not modeled by the
  batched path.

Indicative scale: at 4096 environments (two sources, quad array,
`tdoa_synthetic`) the batched path measured ~5.6 ms/step on one CUDA GPU
where the scalar loop took ~48 s/step — the per-env Python loop, not the
math, dominates at RL scale.

Parity and dispatch coverage lives in the Isaac test lane.
The GPU live gate (`make smoke-isaac-lab`) additionally runs a
batched-vs-scalar parity check on the live runtime and a perf-budget phase:
4096 environments must update under `ISAAC_LAB_PERF_BUDGET_MS` (default
20 ms/step mean; override via the make variable or the smoke script's
`--perf-budget-ms`/`--perf-envs`/`--perf-steps`/`--skip-perf` flags).

## Update And Reset

`AudioArraySensor.update(dt, force_recompute=False)` follows Isaac Lab
`SensorBase` timing: timestamps advance by `dt`, buffers become outdated when
`update_period` elapses, and `data` lazily refreshes outdated environments.

Selected environments are supported:

```python
sensor.update(dt=0.05, force_recompute=True, env_ids=[1, 3])
sensor.reset(env_ids=[1, 3])
```

`reset(env_ids=None)` clears all buffers, timestamps, frame indices, and pending
timestamps for all or selected environments, then marks those environments
outdated. The next `data` access recomputes them if bindings are available.

## RL Observation Example

The copyable example is
`examples/isaac_lab/isaac_lab_audio_observation.py`. It exposes stable
observation keys, selected reset/update usage, and an ambiguity mask split:

```python
from examples.isaac_lab.isaac_lab_audio_observation import (
    ambiguity_observation,
    audio_observation,
    observation_spec,
)

obs = audio_observation(
    sensor,
    dt=0.05,
    update_env_ids=[1],
    reset_env_ids=[1],
)
ambiguous = ambiguity_observation(obs)
spec = observation_spec(obs)
```

The observation keys are fixed:
`audio/event_presence`, `audio/bearing_deg`, `audio/confidence`,
`audio/sector_onehot`, `audio/per_mic_rms`, and `audio/ambiguity_mask`.
All values are dense tensors on the sensor device. `audio/event_presence`
separates real detections from padding, while
`audio/ambiguous_event_presence` marks detections whose TDOA estimate has
front/back ambiguity.

## Live Smoke Evidence

The live smoke launches Isaac Lab, imports the sensor layer after runtime
initialization, resolves the public classes through
`ensure_isaac_lab_sensor_classes()`, checks both subclass relationships with
`issubclass`, binds a minimal two-environment setup, auto-binds a two-env stage,
and binds an entity tensor scene for robot/source pose reads. It verifies tensor
shape, dtype, and device for every RL-facing buffer plus timestamp/outdated
bookkeeping, proves selected-env update/reset with row comparisons, proves
semantic cloned-env discovery for two stage environments, and records
before/after entity-source bearing changes. When a full real
`InteractiveScene`/`RigidObject` entity probe is blocked by the local Isaac
Lab/PhysX runtime, the evidence records the blocker and keeps the closest
supported tensor-scene path active.
It writes JSON evidence under `outputs/isaac_audio_sensors/`.

```bash
make live-isaac-lab-audio
make smoke-isaac-lab
```

Both gates default to the official Isaac Lab launcher
(`~/IsaacLab/isaaclab.sh -p`); override with
`ISAAC_LAB_PYTHON="$HOME/IsaacLab/isaaclab.sh -p"` style values for a
non-default install. For a GUI run of the smoke, append `--viz kit` when
invoking the script directly (headless is the Isaac Lab 3.x default when
`--viz` is omitted).

The GPU target additionally records `torch.cuda` and `nvidia-smi` evidence and
fails if any audio tensor, timestamp tensor, or outdated-mask tensor is on CPU
or split across devices.
It also records a `batched_parity` block (max bearing/confidence/RMS deltas
between the scalar and batched compute paths on the live runtime) and a `perf`
block (`num_envs`, `steps`, `ms_per_step_mean`, `ms_per_step_p95`, `budget_ms`,
`compute_path`) for the batched perf-budget phase, and fails when parity or the
budget is violated.

The 2026-05-24 local-time live Lab GPU run used:

```bash
make smoke-isaac-lab ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
```

It wrote `outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json` with
`status: "passed"` on Isaac Lab `0.54.2`, Isaac Sim `5.1.0`, Kit
`107.3.3+production.229672.69cbf6ad.gl`, Torch `2.7.0+cu128`, and
`NVIDIA GeForce RTX 4090`. The same artifact records CUDA device `cuda:0`,
the `nvidia-smi` device line, and the exact `python_executable` path used by
the local Isaac Lab runtime. The generated local evidence report preserves that
absolute runtime path under ignored `outputs/` rather than publishing it as a
portable package path. The evidence records `classes_real: true`,
`fallback_classes_used_in_lab: false`, `AudioArraySensorCfg` as a real
`SensorBaseCfg` subclass, and `AudioArraySensor` as a real `SensorBase`
subclass.

The same evidence records two envs, two max events, and four microphones. Every
RL-facing tensor and bookkeeping tensor was on `cuda:0`: `event_presence`,
`bearing_deg`, `confidence`, `sector_onehot`, `per_mic_rms`, `ambiguity_mask`,
`last_update_time_s`, `_timestamp`, `_timestamp_last_update`, and
`_is_outdated`. Selected-env update, reset, and repopulate checks passed for the
explicit binding, `pxr.Usd.Stage` binding, and entity tensor binding paths.
The RL observation example reported stable keys and CUDA tensors for
`audio/event_presence`, `audio/bearing_deg`, `audio/confidence`,
`audio/sector_onehot`, `audio/per_mic_rms`, and `audio/ambiguity_mask`.

Stage binding ran against a real `pxr.Usd.Stage` inside the live Lab/Kit
runtime, with transform provenance recorded as
`usd:ComputeLocalToWorldTransform`. Entity binding ran inside the live Lab
runtime against CUDA tensor-backed scene/entity objects. A full real
`InteractiveScene`/`RigidObject` probe remains blocked in this local runtime:
the evidence records prior GPU SimulationContext PhysX CUDA illegal-memory
errors and CPU SimulationContext Kit-shutdown hangs, so the required target
keeps the stable live tensor-scene entity path active.

If a full Isaac Lab simulation context is unavailable, the smoke still records
the exact blocker. The pure tests remain authoritative for tensor conversion,
padding, selected `env_ids`, reset, import-order recovery, and cloned-env stage
binding behavior.
