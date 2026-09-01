# Getting Started

## Choose the Runtime

The pure package supports Python 3.10 or newer and imports without Isaac Sim, Isaac Lab, Kit, CUDA, Torch, or room-acoustics dependencies.

Use the pure environment for contracts, configuration, deterministic backends, recording, replay, CLI operations, and host tests.

Use the official Isaac Lab launcher for Isaac Sim, Isaac Lab, Kit, GPU, and live-stage validation because those packages are user-managed NVIDIA runtime dependencies rather than PyPI dependencies of this project.

## Install the Core

Create a clean environment and install the published package:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install isaac-audio-sensors
```

Install approximate room-acoustics support only when needed:

```bash
python -m pip install "isaac-audio-sensors[room]"
```

For repository development, replace the package install with:

```bash
python -m pip install --editable ".[dev]"
```

Install an audited local wheel with:

```bash
python -m pip install dist/isaac_audio_sensors-3.0.0-py3-none-any.whl
python -m isaac_audio_sensors --version
```

## First CLI Workflow

Validate the maintained example configuration:

```bash
isaac-audio-sensors validate-config examples/configs/isaac_audio_sensors_demo.toml
```

Generate a deterministic analytic frame:

```bash
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml --backend analytic_acoustics --array-id rig_front
```

The maintained configuration uses `free_field`, so neither command needs Isaac, a GPU, or the optional `room` extra.

Export an analytic trace and the public frame schema:

```bash
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml --backend analytic_acoustics --array-id rig_front --out build/validation/isaac_audio_sensors/analytic_trace.json
isaac-audio-sensors export-schema --out build/validation/isaac_audio_sensors/audio_sensor_frame.v1.schema.json
```

The CLI also exposes capability reporting, dataset validation/statistics/splitting, and the guided headless workflow; run `isaac-audio-sensors --help` and the relevant subcommand help for the current arguments.

## Examples

Run the maintained pure Core example from the repository root:

```bash
python examples/core/two_mic_ambiguity.py
```

Run the optional room recipe with the Isaac Lab interpreter or another environment that includes the `room` extra:

```bash
python examples/core/room_acoustics_demo.py
```

The Core examples use generated audio identifiers, write no persistent output, and require no private recordings.

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
