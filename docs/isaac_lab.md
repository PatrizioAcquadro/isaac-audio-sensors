# Isaac Lab

`isaac_audio_sensors.lab` exposes audio observations through an Isaac
Lab-compatible sensor layer.

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
- `writer_path` and `write_waveforms`: reserved export options.

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

```python
from isaac_audio_sensors.lab import ensure_isaac_lab_sensor_classes

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
sensor = AudioArraySensor(cfg).bind_envs(
    scene_snapshots=(env0_snapshot, env1_snapshot),
    sensors=(env0_array, env1_array),
)
sensor.update(dt=0.05, force_recompute=True)
audio_obs = {
    "audio/event_presence": sensor.data.event_presence,
    "audio/bearing_deg": sensor.data.bearing_deg,
    "audio/confidence": sensor.data.confidence,
    "audio/sector_onehot": sensor.data.sector_onehot,
    "audio/per_mic_rms": sensor.data.per_mic_rms,
    "audio/ambiguity_mask": sensor.data.ambiguity_mask,
}
```

## Live Smoke Evidence

The live smoke launches Isaac Lab, imports the sensor layer after runtime
initialization, resolves the public classes through
`ensure_isaac_lab_sensor_classes()`, checks both subclass relationships with
`issubclass`, binds a minimal two-environment setup, auto-binds a two-env stage,
binds a duck-typed entity scene with articulation/rigid-object tensors,
verifies tensor shapes/device, resets one environment, performs selected-env
updates, proves semantic cloned-env discovery for two stage environments, and
records before/after entity-source bearing changes.
It writes JSON evidence under `outputs/isaac_audio_sensors/`.

```bash
make live-isaac-lab-audio ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
make live-isaac-lab-audio-gpu ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
```

The GPU target additionally records `torch.cuda` and `nvidia-smi` evidence and
fails if any audio tensor, timestamp tensor, or outdated-mask tensor is on CPU
or split across devices.

If a full Isaac Lab simulation context is unavailable, the smoke still records
the exact blocker. The pure tests remain authoritative for tensor conversion,
padding, selected `env_ids`, reset, import-order recovery, and cloned-env stage
binding behavior.
