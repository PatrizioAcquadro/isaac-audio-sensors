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

## Features

- Pure Python core models for scenes, sound sources, time windows, microphone
  arrays, detections, DOA estimates, and sensor frames.
- `geometry_only` backend for deterministic source bearing and sector labels.
- `tdoa_synthetic` backend for per-microphone delay and RMS diagnostics.
- Explicit two-microphone front/back ambiguity reporting.
- Optional `room_acoustics` backend using `pyroomacoustics` when installed.
- Lazy Isaac Sim helpers for USD sound/listener/microphone-array metadata.
- Lazy Isaac Lab wrapper classes for observation-style sensor data.
- CLI commands for config validation, simulation, and trace export.

## Architecture

The package is organized into four layers:

1. `isaac_audio_sensors.core`: stable data models, array geometry, backends,
   DOA helpers, TOML config loading, CLI trace IO. This layer imports no Isaac,
   Omniverse, room-acoustics, ROS 2, or project-specific modules.
2. `isaac_audio_sensors.isaac`: optional Isaac Sim and Omniverse helpers. These
   modules import Isaac packages lazily and raise clear errors when unavailable.
3. `isaac_audio_sensors.lab`: optional Isaac Lab wrapper classes that expose
   deterministic sensor observations from a bound scene snapshot.
4. Optional project adapters: downstream projects can convert
   `AudioSensorFrame` records into their own message or graph contracts outside
   the core package.

## Quick Install

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
print(frame.detections[0].doa)
```

## Isaac Sim Example

```bash
PYTHONPATH=src "$ISAAC_SIM_PYTHON" scripts/live_isaac_sim_audio_smoke.py
```

The script creates an in-memory USD stage, authors a sound source and
microphone array metadata, captures a synthetic TDOA frame, and writes optional
evidence under ignored `outputs/`.

## Isaac Lab Example

```bash
PYTHONPATH=src "$ISAAC_LAB_PYTHON" scripts/live_isaac_lab_audio_smoke.py
```

The script imports the active Isaac Lab runtime, builds a small scene snapshot,
and updates `AudioArraySensor` once.

## Validation Status

Current core validation is reproducible without Isaac:

```bash
python -m pip install -e ".[dev]"
python -c "import isaac_audio_sensors; print(isaac_audio_sensors.__version__)"
python -m pytest
python -m ruff check .
python -m build
git diff --check
```

Live Isaac Sim and Isaac Lab checks are optional manual checks because the
NVIDIA runtimes are large environment installs, not package dependencies.

## Known Limitations

- `geometry_only` is a deterministic geometric bearing model, not acoustic
  propagation.
- `tdoa_synthetic` computes direct-path synthetic delays and does not model
  reverberation or occlusion.
- `room_acoustics` is optional and depends on `pyroomacoustics`; it should be
  treated as an approximate shoebox-room simulation.
- Two microphones cannot resolve front/back ambiguity without an additional
  prior. Four or more non-collinear microphones are recommended for DOA.
- The Isaac helpers do not make this an official NVIDIA extension.

## Documentation

- [Installation](docs/installation.md)
- [Quickstart](docs/quickstart.md)
- [Isaac Sim](docs/isaac_sim.md)
- [Isaac Lab](docs/isaac_lab.md)
- [Backends](docs/backends.md)
- [Room Acoustics](docs/room_acoustics.md)
- [TDOA And DOA](docs/tdoa_doa.md)
- [API Freeze 0.1](docs/api_freeze_0_1.md)
- [Validation](docs/validation.md)
- [Limitations](docs/limitations.md)
- [Showcase](docs/showcase.md)

## License And Citation

This repository is released under the Apache License 2.0. See `LICENSE`,
`NOTICE`, and `CITATION.cff`.
