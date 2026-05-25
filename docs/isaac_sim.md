# Isaac Sim

The `isaac_audio_sensors.isaac` layer provides optional helpers for Isaac Sim
and Omniverse USD stages.

The supported v1 Isaac Sim scope is defined in [V1 Public Scope](v1_scope.md):
the live sensor path is supported, the Kit extension is the reference UX, and
Replicator is only an optional extension capability.

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
  backend diagnostics, movement diagnostics, writer diagnostics, JSON evidence,
  config JSON, and JSONL frame traces under ignored `outputs/`.

Latest local Task 6 validation was rerun on 2026-05-24 local time
(`2026-05-25T02:46Z` Kit log timestamp) with the Isaac Python runtime selected
by `ISAAC_SIM_COMMAND`. It passed with `pxr` and `omni` imported, headless
`SimulationApp` bootstrap, `kit_app_version` `5.1.0`, Kit build
`107.3.3+production.229672.69cbf6ad.gl`, Torch `2.7.0+cu128`, and an NVIDIA
GeForce RTX 4090 visible through CUDA and `nvidia-smi` driver `570.211.01`.
The artifact's `isaacsim_version` and `kit_version` fields were `unavailable`;
the generated local evidence report preserves the exact `python_executable`
path recorded by the smoke.

The smoke authored a synthetic USD stage inside Isaac Sim and produced:

- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.json`
- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.frames.jsonl`
- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.config.json`

The JSONL trace contains 6 valid `AudioSensorFrame` v1 records: 3
`geometry_only` frames and 3 `tdoa_synthetic` frames. Semantic discovery
selected array `rig_front` at `/World/RobotBase/ArrayMount/AudioArray` and
source `speaker_front` at `/World/MovingSource/Sound`. Both required backends
proved changed source pose, array pose, bearing, stage time code, backend
diagnostics, and debug primitives after live USD motion. The evidence records
debug primitive kinds `microphone`, `source`, `bearing_ray`, and
`sector_wedge`, with labels for `mic:front`, `mic:left`, `mic:rear`,
`mic:right`, `source:speaker_front`, bearing rays, and `sector:straight`.
`room_acoustics` was skipped with an explicit evidence reason because
`pyroomacoustics` was not installed in that Isaac runtime.

The local report generator parses the Isaac Sim JSON/config/JSONL evidence and
the other live gates, then writes:

- `outputs/isaac_audio_sensors/live_validation_evidence.md`
- `outputs/isaac_audio_sensors/live_validation_evidence.pdf`

Run it with `make live-evidence-report`. The generator is
`scripts/generate_live_evidence_report.py`.

## Reference Extension UX

The source distribution includes a lightweight Kit extension at
`exts/isaac_audio_sensors.omni`. Load it from Isaac Sim by adding the repository
`exts/` directory to the Extension Manager search paths, then enable
`Isaac Audio Sensors`. The Kit manifest uses version `1.0.0-rc.1` because
Omniverse Kit requires SemVer in `extension.toml`; the Python package version
remains `1.0.0rc1`. The extension entrypoint is import-safe in normal Python:
it does not import `omni`, `pxr`, Isaac Sim, a display, CUDA, or a GPU until
the live stage or UI path is used.

The extension window is organized around the live authoring workflow:

- `Stage`: refreshes the current stage selection, shows selected prim paths,
  binds the first selected prim as the array, source, or robot/base frame, and
  runs semantic discovery from configurable roots.
- `Author Array`: configures target prim path, array id, layout
  (`quad_front`, `quad_cross`, `stereo_y`, `two_mic_y`, `mono`), sample rate,
  coordinate convention, and optional child microphone prim authoring.
- `Author Source`: configures target prim path, source id, class label, audio
  URI, start time, duration, and gain.
- `Sensor`: selects one implemented v1 backend (`geometry_only`,
  `tdoa_synthetic`, `room_acoustics`), ambiguity policy, update period, max
  events, debug overlay toggle, JSONL writer toggle/path, and
  start/stop/update lifecycle buttons.
- `Replicator`: optionally enables the Omniverse-native writer path, sets output
  directory, writer name, and annotator name, and exposes start, flush, stop,
  write-count, and latest-artifact status.
- `Export`: writes the latest frame JSON, writes a reusable
  stage-binding/config summary, and loads a saved config summary.

The authoring buttons use ordinary USD custom attributes under `ias:*`; they do
not register or require a custom USD schema. If the target prim exists, the
extension attaches or updates metadata on that prim. If no prim exists at the
target path, the extension defines a minimal prim and adds fallback world pose
metadata so a one-array, one-source live scene can run immediately. Array
authoring reuses `attach_microphone_array_attrs(...)` and
`attach_microphone_attrs(...)`; source authoring reuses `create_sound_prim(...)`
and `attach_sound_source_attrs(...)`.

The `Start` action builds an `IsaacAudioArraySensor` from the current stage. It
uses the explicit array prim path when that prim exists; otherwise it falls back
to semantic discovery through `IsaacAudioSceneBindingCfg` and
`discover_stage_audio(...)`. `Stop` leaves the latest frame available, and
`Update` forces one frame, updates latest-frame status, appends to the JSONL
trace when enabled, and refreshes overlay state.

Debug overlay records are built with `build_debug_primitives(...)` and rendered
through `IsaacDebugDrawer` when `omni.isaac.debug_draw` is available. The same
structured primitives are retained when debug draw is unavailable, so the UI
still reports primitive count/labels and the config export still contains the
serialized microphone, source, bearing-ray, and sector-wedge evidence.

Default export paths are ignored public-output paths:

- latest frame JSON: `outputs/isaac_audio_sensors/extension_latest_frame.json`;
- JSONL trace: `outputs/isaac_audio_sensors/extension_trace.frames.jsonl`;
- reusable binding/config summary:
  `outputs/isaac_audio_sensors/extension_binding.json`.
- Replicator output directory:
  `outputs/isaac_audio_sensors/replicator/`.

Latest local extension UX validation was rerun on 2026-05-24 local time
(`2026-05-25T02:47Z` Kit log timestamp) with:

```bash
make live-omniverse-extension-ux ISAAC_SIM_COMMAND="$ISAAC_SIM_PYTHON"
```

It passed using the host-visible runtime with `kit_app_version` `5.1.0`, Kit
build `107.3.3+production.229672.69cbf6ad.gl`, an NVIDIA GeForce RTX 4090
visible through Torch CUDA, and `nvidia-smi` driver `570.211.01`. The
artifact's `isaacsim_version` and `kit_version` fields were `unavailable`.
The Kit extension manager enabled
`isaac_audio_sensors.omni-1.0.0-rc.1`, `omni.usd` provided the stage, and the
selection API set `/World/Rig/AudioArray`, `/World/Sources/SpeakerA`, and
`/World/Rig`. The workflow authored one array and one source, discovered
`rig_front` and `speaker_a`, selected `tdoa_synthetic`, started/updated/stopped
the sensor, exported latest frame JSON plus reusable config JSON, and wrote one
valid `AudioSensorFrame` v1 JSONL record.

The same evidence recorded 7 overlay primitives with kinds `microphone`,
`source`, `bearing_ray`, and `sector_wedge`. Replicator was available as
`omni.replicator.core`; the extension registered `IsaacAudioSensorFrameWriter`,
wrote one payload and `audio_sensor_frames.jsonl`, flushed once, and stopped.
The local Kit shape did not expose a supported simple Python annotator
registration method, so the evidence records
`AnnotatorRegistry has no supported register method` while the writer path and
package JSON/JSONL path still pass. Headless viewport screenshot capture was
unavailable because the active viewport had no `capture_to_file` method; the
serialized overlay primitives remain in the JSON evidence.

Practical Isaac Sim workflow:

1. Open Isaac Sim with the repository available on disk.
2. In `Window -> Extensions`, add the repository `exts/` directory to search
   paths and enable `Isaac Audio Sensors`.
3. Select or create a prim for the array target, then click `Refresh` and
   `Use Array`.
4. In `Author Array`, choose an array id and layout, then click
   `Create/Attach Array`.
5. Select or create a sound-source prim, click `Use Source`, configure source
   metadata, then click `Create/Attach Source`.
6. Optionally select a robot/base prim and click `Use Base`.
7. Click `Discover` and confirm the array/source ids in the discovery status.
8. Pick `geometry_only`, `tdoa_synthetic`, or `room_acoustics`; set update
   period, max events, overlay, and JSONL writer path.
9. Click `Start`, then `Update`; the latest-frame and overlay labels should
   show detection count, backend, bearing, sector, and primitive count.
10. Optionally, in `Replicator`, enable recording, set the output directory, click
    `Start`, click `Update` again, then click `Flush`.
11. In `Export`, write the latest JSON frame and config JSON. Use `Load Config`
    on a later run to restore backend, prim paths, roots, writer paths,
    update settings, overlay setting, and Replicator settings.
12. Click `Stop` in `Sensor`, then `Stop` in `Replicator`.

Recording paths:

- Package-native JSON/JSONL is the stable v1 package trace path. It writes full
  `AudioSensorFrame` v1 records through `AudioFrameJsonlWriter` and
  `write_frame_trace`.
- Omniverse-native Replicator is a supported optional v1 extension recording
  capability. It is imported lazily from `omni.replicator.core`, registers
  `IsaacAudioSensorFrameWriter`, writes a recoverable payload containing the
  full `AudioSensorFrame` v1 object plus backend, array/source ids, bearing,
  sector, diagnostics namespaces, overlay metadata, extension config, and
  provenance, and flushes a manifest/status file.

Replicator remains optional at package import time and is not a core dependency.
Core import, `AudioSensorFrame`, JSON/JSONL export, `IsaacAudioArraySensor`,
and the Isaac Lab sensor do not depend on Replicator availability. If
`omni.replicator.core`, `WriterRegistry`, writer lookup, output path creation,
write, or flush is unavailable, the extension reports a readable status/error
and leaves the package JSON/JSONL path usable. Some Isaac/Kit versions do not
expose a simple Python annotator registration API; in that case the writer
still records audio frames and the config/evidence records the annotator API
status.

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
`exts/` is included as a reference Kit UX for authoring arrays and sources,
binding a live stage, visualizing debug primitives, exporting package
JSON/JSONL evidence, and recording Omniverse-native Replicator payloads.
