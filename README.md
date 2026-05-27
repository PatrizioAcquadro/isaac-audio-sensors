# isaac-audio-sensors

`isaac-audio-sensors` provides reusable microphone-array data models,
deterministic audio sensing backends, and lazy Isaac Sim/Lab integration helpers
for robotics simulation.

Isaac Sim and Isaac Lab expose rich scene and robot simulation APIs, but they do
not currently provide a small open package that turns scene sound sources and
robot microphone arrays into robotics-style bearing, delay, RMS, and detection
records. This package fills that gap without requiring Isaac to be installed for
the pure Python core.

Showcase site: <https://isaac-audio-showcase-site.vercel.app>

Source repository: <https://github.com/PatrizioAcquadro/isaac-audio-sensors>

Current package release: `1.0.0`. The frame schema version remains separate at
`ias.audio_sensor_frame.v1`.

## Features

- Pure Python core models for scenes, sound sources, time windows, microphone
  arrays, detections, DOA estimates, and sensor frames.
- Stable `AudioSensorFrame` v1 trace contract with schema version, frame name,
  poses, units, provenance, max-event semantics, and JSON Schema export.
- `geometry_only` backend for deterministic source bearing and sector labels.
- `tdoa_synthetic` backend for per-microphone delay and RMS diagnostics.
- Explicit two-microphone front/back ambiguity reporting.
- Optional `room_acoustics` backend using `pyroomacoustics` for shoebox RIRs,
  generated microphone waveforms, and waveform-derived GCC-PHAT TDOA when
  installed.
- Public acoustic fidelity ladder documenting stable L0/L1, supported optional
  L2, provisional L3, and experimental/tooling L4 compatibility boundaries.
- Lazy Isaac Sim helpers for USD sound/listener/microphone-array metadata,
  live update-loop capture, USD-native world-pose reads, nested transform
  stacks, robot/base-mounted arrays, moving sources/arrays/microphone children,
  semantic array/source discovery, active sound windows, debug visualization
  records, JSONL writer output, and a reference Kit extension with optional
  extension-only Replicator recording.
- Lazy Isaac Lab integration that becomes a real `SensorBaseCfg`/`SensorBase`
  sensor when imported inside an initialized Isaac Lab runtime, with a public
  recovery API, vectorized multi-env RL buffers, GPU validation, USD transform
  stack stage binding, scene/env binding helpers, semantic cloned-stage
  discovery, and scene entity/articulation tensor binding for robot/link
  mounted arrays and source entities.
- CLI commands for config validation, simulation, schema export, and trace
  export.

## Architecture

The package is organized into four layers:

1. `isaac_audio_sensors.core`: stable data models, array geometry, backends,
   DOA helpers, TOML config loading, CLI trace IO. This layer imports no Isaac,
   Omniverse, room-acoustics, ROS 2, or project-specific modules.
2. `isaac_audio_sensors.isaac`: optional Isaac Sim and Omniverse helpers. These
   modules import Isaac packages lazily and raise clear errors when unavailable.
3. `isaac_audio_sensors.lab`: optional Isaac Lab sensor classes. In Lab mode
   they inherit `SensorBaseCfg`/`SensorBase`; outside Lab they stay import-safe
   and exercise the same tensor conversion path in tests.
4. Optional project adapters: downstream projects can convert
   `AudioSensorFrame` records into their own message or graph contracts outside
   the core package.

## V1 Scope

The canonical v1 scope is frozen in [V1 Public Scope](docs/v1_scope.md). V1
promises only the stable `AudioSensorFrame` v1 contract, stable L0
`geometry_only`, stable L1 `tdoa_synthetic`, supported optional L2
`room_acoustics`, supported Isaac Sim and Isaac Lab sensor paths, the Omniverse
extension as reference UX, stable JSON/JSONL export, and Replicator only as an
optional extension capability.

V1 does not promise SquadBot or Alex as release gates, sim-real calibration,
real hardware benchmarks, complete L3/L4 acoustic fidelity, realistic
occlusions or material acoustics, mandatory ROS 2 or downstream adapters, or
Alex/SquadBot validation before releasing the sensor package.

## Quick Install

For the local final wheel after `make build`:

```bash
python -m pip install dist/isaac_audio_sensors-1.0.0-py3-none-any.whl
python -m isaac_audio_sensors --version
```

For development from a checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Room-acoustics support is optional:

```bash
python -m pip install -e ".[room]"
```

Isaac Sim, Isaac Lab, and Omniverse packages are not PyPI dependencies. Use the
Python interpreter that comes with your Isaac installation for live smoke tests.
The pure core supports Python 3.10 or newer.

## Quickstart

```python
from isaac_audio_sensors import AudioSceneSnapshot, AudioSourceSpec, AudioTimeWindow
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.microphone_array import create_microphone_array

array = create_microphone_array(
    array_id="rig_front",
    prim_path="/World/Rig/AudioArray",
    layout_name="quad_front",
)
scene = AudioSceneSnapshot(
    stage_id="demo",
    timestamp_ms=0,
    sources=(
        AudioSourceSpec(
            source_id="speaker",
            prim_path="/World/Sources/Speaker",
            class_label="Speech",
            audio_asset_path="generated://impulse",
            position_world=(4.0, 2.0, 0.0),
            orientation_world_quat=None,
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
        ),
    ),
    arrays=(array,),
)
frame = TdoaSyntheticBackend().simulate(
    scene,
    array,
    AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=0,
        sample_rate_hz=array.sample_rate_hz,
    ),
)
print(frame.schema_version, frame.frame_name)
print(frame.detections[0].doa)
```

The frame serializes to the public v1 JSON shape. The JSON Schema is available
at `docs/schemas/audio_sensor_frame.v1.schema.json`, and example traces live
under `examples/traces/`. The public contract is documented in
[API Freeze](docs/api_freeze_0_1.md) and [API Reference](docs/api_reference.md):
`AudioSensorFrame.schema_version` is `ias.audio_sensor_frame.v1`, independent
from the Python package version, and covers the coordinate policy, units,
timestamps, provenance values, ambiguity fields, diagnostics namespaces, JSON
examples, and NDJSON trace corpus.

The acoustic fidelity ladder is documented in
[Acoustic Fidelity Ladder](docs/acoustic_fidelity.md). L0 `geometry_only` and
L1 `tdoa_synthetic` are stable v1 runtime levels, L2 `room_acoustics` is a
supported optional v1 runtime level, and L3/L4 are future-facing metadata
directions rather than complete v1 backends. The complete promise and
non-promise boundary is documented in [V1 Public Scope](docs/v1_scope.md).

## Isaac Sim Example

```bash
PYTHONPATH=src "$ISAAC_SIM_PYTHON" scripts/live_isaac_sim_audio_smoke.py
```

The script creates an in-memory USD stage, semantically discovers sources and a
robot-mounted array from `ias:*`, native sound attributes, names, and child
microphone prims, then starts `IsaacAudioArraySensor.from_discovered_stage`.
It reads time-coded live world poses between update ticks, runs `geometry_only`
and `tdoa_synthetic`, verifies changed frame output, records an inactive sound
window, and writes GPU, discovery, transform-provenance, config JSON, evidence
JSON, and JSONL frame traces under ignored `outputs/`.

Latest local final `1.0.0` live validation, rerun on 2026-05-24 local time
(`2026-05-25T03:34Z` Kit log timestamp) with the Isaac Python runtime selected
by `ISAAC_SIM_COMMAND`, passed on real Isaac Sim 5.1.0 / Kit
`107.3.3+production.229672.69cbf6ad.gl` with an NVIDIA GeForce RTX 4090,
driver `570.211.01`, and Torch `2.7.0+cu128`. It produced 6
`AudioSensorFrame` v1 JSONL records: 3 `geometry_only` and 3 `tdoa_synthetic`,
selected array `rig_front` at `/World/RobotBase/ArrayMount/AudioArray`, and
selected source `speaker_front` at `/World/MovingSource/Sound`. The evidence
records debug primitive labels for microphones, source, bearing rays, and
sector. `room_acoustics` skipped cleanly because `pyroomacoustics` was not
installed in that Isaac runtime. Artifacts:

- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.json`
- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.frames.jsonl`
- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.config.json`

The source distribution also includes a reference Kit extension at
`exts/isaac_audio_sensors.omni`. Add the repository `exts/` directory to Isaac
Sim's Extension Manager search paths and enable `Isaac Audio Sensors` to use a
panel for selected-prim binding, array/source `ias:*` metadata authoring,
backend selection, start/stop/update lifecycle controls, debug overlay
primitives, and latest-frame JSON, JSONL trace, and reusable binding/config
exports. The extension supports two recording paths:

- package-native JSON/JSONL records containing `AudioSensorFrame` v1 payloads;
- Omniverse-native Replicator writer payloads under a user-selected output
  directory, with lazy `omni.replicator.core` registration and readable
  missing-runtime/write/flush errors.

Beginner GUI walkthrough:
[Isaac Audio Sensors GUI Guide for Isaac Sim](docs/isaac_sim_gui_guide.md)
covers Extension Manager activation, every visible section/control, a first demo
pipeline, expected outputs, and troubleshooting.

Replicator is optional extension functionality only. The core package import,
`AudioSensorFrame`, JSON/JSONL export, Isaac Sim base sensor, and Isaac Lab
sensor do not depend on Replicator availability.

The live reference UX smoke is:

```bash
make live-omniverse-extension-ux ISAAC_SIM_COMMAND="$ISAAC_SIM_PYTHON"
```

It records real Kit version/runtime facts, selected-prim workflow status,
overlay primitive evidence, JSON/JSONL exports, config import/export,
Replicator registration/write/flush/stop status, and screenshot status under
`outputs/isaac_audio_sensors/`.

## Isaac Lab Example

```bash
PYTHONPATH=src "$ISAAC_LAB_PYTHON" scripts/live_isaac_lab_audio_smoke.py
```

The script launches Isaac Lab first, imports the sensor layer, verifies real
`SensorBaseCfg`/`SensorBase` inheritance through
`ensure_isaac_lab_sensor_classes()`, binds two environment-indexed scene
snapshots, discovers arrays and sources in two cloned USD stage environments
through authored Xform ops, binds a duck-typed Lab scene entity setup from
articulation and rigid-object tensors, and checks tensor buffer shapes/device
plus selected-env reset and update behavior.

Lab observations expose `event_presence`, `bearing_deg`, `confidence`,
`sector_onehot`, `per_mic_rms`, and `ambiguity_mask` as fixed-shape tensors
`[num_envs, max_events, ...]` suitable for RL pipelines.

GPU-required validation fails instead of passing on CPU:

```bash
make live-isaac-lab-audio-gpu ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
```

## Validation Status

Current core validation is reproducible without Isaac:

```bash
python -m pip install -e ".[dev]"
python -c "import isaac_audio_sensors; print(isaac_audio_sensors.__version__)"
python -m isaac_audio_sensors --version
python -m pytest
python -m ruff check .
python -m build
python scripts/audit_distribution.py --dist-dir dist
python -m isaac_audio_sensors.cli export-schema --out /tmp/audio_sensor_frame.v1.schema.json
git diff --check
```

Live Isaac Sim and Isaac Lab checks use user-managed NVIDIA runtimes, not PyPI
dependencies. The GPU Isaac Lab target is expected to fail with a concrete CUDA
blocker when no NVIDIA GPU is available to the Isaac Lab runtime.

## Local Live Evidence Report

The machine-local report source and PDF are generated from the canonical
ignored artifacts, including exact `python_executable` runtime paths that are
not repeated in tracked public docs:

```bash
make live-evidence-report
```

Inputs:

- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.json`
- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.frames.jsonl`
- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.config.json`
- `outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.json`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.frames.jsonl`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.config.json`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.replicator/`

Outputs:

- `outputs/isaac_audio_sensors/live_validation_evidence.md`
- `outputs/isaac_audio_sensors/live_validation_evidence.pdf`

The generator is `scripts/generate_live_evidence_report.py`. It records Isaac
Sim/Kit app and build fields, Isaac Lab version, exact Python executable paths,
GPU/CUDA/NVIDIA driver facts, pass/optional/blocker status, artifact paths, and
declared non-promises from the current JSON/JSONL artifacts. The PDF is written
with ReportLab when that dependency is available; if no PDF backend is
available, the Markdown source remains the reproducible report source.

## Known Limitations

- `geometry_only` is a deterministic geometric bearing model, not acoustic
  propagation.
- `tdoa_synthetic` computes direct-path synthetic delays and does not model
  reverberation or occlusion.
- `room_acoustics` is optional and depends on the `room` extra; it should be
  treated as an approximate shoebox-room simulation, not realistic occlusion,
  material behavior, directivity, microphone calibration, production
  beamforming, or sim-real transfer.
- L3 advanced realism and L4 sim-real calibration are not complete v1 runtime
  systems. They are documented extension directions for optional config,
  diagnostics, artifacts, and dependencies.
- Two microphones cannot resolve front/back ambiguity without an additional
  prior. Four or more non-collinear microphones are recommended for DOA.
- Isaac Sim pose extraction supports USD transform stacks, fallback attrs, and
  semantic discovery from common audio metadata, but full articulation semantic
  adapters remain task-specific.
- Isaac Lab entity binding supports common scene/entity tensor fields such as
  `root_state_w`, `root_pos_w`, `root_quat_w`, `body_state_w`, `body_pos_w`,
  and `body_quat_w` without requiring exact Isaac Lab classes at import time.
- The Isaac helpers include a reference extension wrapper, but this is not an
  official NVIDIA extension.
- Replicator recording is an Omniverse extension feature and is imported lazily
  inside Isaac Sim/Kit. The core package and extension import smoke do not
  require Replicator outside Isaac.

## Documentation

- [Installation](docs/installation.md)
- [Quickstart](docs/quickstart.md)
- [V1 Public Scope](docs/v1_scope.md)
- [Isaac Sim](docs/isaac_sim.md)
- [Isaac Lab](docs/isaac_lab.md)
- [Acoustic Fidelity Ladder](docs/acoustic_fidelity.md)
- [Backends](docs/backends.md)
- [Room Acoustics](docs/room_acoustics.md)
- [TDOA And DOA](docs/tdoa_doa.md)
- [API Freeze](docs/api_freeze_0_1.md)
- [Validation](docs/validation.md)
- [Limitations](docs/limitations.md)
- [Versioning](docs/versioning.md)
- [Open Source Release Checklist](docs/open_source_release_checklist.md)
- [Roadmap](docs/roadmap.md)
- [Showcase](docs/showcase.md)

## License And Citation

This repository is released under the Apache License 2.0. See `LICENSE`,
`NOTICE`, and `CITATION.cff`.
