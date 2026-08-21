# Getting Started

## Choose the Runtime

The pure package supports Python 3.10 or newer and imports without Isaac Sim, Isaac Lab, Kit, CUDA, Torch, or room-acoustics dependencies.

Use the pure environment for contracts, configuration, deterministic backends, recording, replay, CLI operations, and host tests.

Use the official Isaac Lab launcher for Isaac Sim, Isaac Lab, Kit, GPU, and live-stage validation because those packages are user-managed NVIDIA runtime dependencies rather than PyPI dependencies of this project.

## Install the Core

Create a development environment from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Install approximate room-acoustics support only when needed:

```bash
python -m pip install -e ".[room]"
```

Install a built wheel with:

```bash
python -m pip install dist/isaac_audio_sensors-2.0.0-py3-none-any.whl
python -m isaac_audio_sensors --version
```

## First CLI Workflow

Validate the maintained example configuration:

```bash
isaac-audio-sensors validate-config examples/configs/isaac_audio_sensors_demo.toml
```

Generate a deterministic geometry frame:

```bash
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml --backend geometry_only --array-id rig_front
```

Export a synthetic TDOA trace and the public frame schema:

```bash
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml --backend tdoa_synthetic --array-id rig_front --out outputs/tdoa_trace.json
isaac-audio-sensors export-schema --out outputs/audio_sensor_frame.v1.schema.json
```

The CLI also exposes capability reporting, dataset validation/statistics/splitting, and the guided headless workflow; run `isaac-audio-sensors --help` and the relevant subcommand help for the current arguments.

## Examples

Run the pure examples from the repository root:

```bash
python examples/core/two_mic_ambiguity.py
python examples/recording/read_manifest.py
python examples/calibration/read_profile.py
```

Run the optional room recipe with the Isaac Lab interpreter or another environment that includes the `room` extra:

```bash
python examples/core/room_acoustics_demo.py
```

The pure examples use generated audio identifiers or small deterministic JSON fixtures, write no output, and require no private recordings.

Isaac examples under `examples/isaac_sim/` and `examples/isaac_lab/` are concise recipes for initialized compatible runtimes. The end-to-end GPU workflows remain under `tools/smoke/` and are invoked through the maintained commands below.

## Isaac Runtime Commands

The supported default launcher is `~/IsaacLab/isaaclab.sh -p`, selected by `ISAAC_LAB_PYTHON` when a different installation is required.

Run live gates from a shell without an activated venv or Conda environment so the launcher does not select an interpreter that lacks the Isaac packages.

```bash
make smoke-isaac-sim
make smoke-isaac-lab
make smoke-kit
```

The Isaac Lab smoke explicitly requires CUDA and fails instead of silently using CPU.

## Development Workflow

Use [[topics/validation-and-release|Validation and Release]] for the maintained test, lint, build, and archive gates.

Keep the pure core import-safe, keep optional dependencies lazy, update the canonical wiki for material public behavior changes, and do not add generated media, private recordings, absolute workstation paths, or downstream task policy to tracked product documentation.
