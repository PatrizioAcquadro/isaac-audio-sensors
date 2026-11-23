# Getting Started

## Choose the Runtime

The pure package supports Python 3.10 or newer and imports without Isaac Sim, Isaac Lab, Kit, CUDA, Torch, or room-acoustics dependencies.

Use the pure environment for contracts, configuration, deterministic backends, recording, replay, CLI operations, and host tests.

Use the official Isaac Lab launcher for Isaac Sim, Isaac Lab, Kit, GPU, and live-stage validation because those packages are user-managed NVIDIA runtime dependencies rather than PyPI dependencies of this project.

## Install the Stable Package

Install version 3.0.0 from PyPI:

```bash
python -m pip install "isaac-audio-sensors==3.0.0"
```

Use `python -m pip install "isaac-audio-sensors[room]==3.0.0"` when room acoustics or planar DOA is required. Isaac runtimes and optional native Geometry providers remain separate installations.

Version 3 breaks the 2.0 contracts; follow [[decisions/product-boundary-and-compatibility|migration guidance]] before upgrading. Older installations need the documentation at their release tag.

## Install the Checkout

The examples target the matching 3.0 source checkout. Create an environment from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --editable ".[dev]"
```

Install approximate room-acoustics support only when needed:

```bash
python -m pip install --editable ".[room]"
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
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml --backend analytic_acoustics --array-id rig_front --energy-threshold-dbfs -60
```

The maintained configuration uses `free_field`, so neither command needs Isaac, a GPU, or the optional `room` extra.

Export an analytic trace and the public frame schema:

```bash
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml --backend analytic_acoustics --array-id rig_front --energy-threshold-dbfs -60 --out build/validation/isaac_audio_sensors/analytic_trace.json
isaac-audio-sensors export-schema --out build/validation/isaac_audio_sensors/audio_sensor_frame.v4.schema.json
```

The selected array sets the sample rate. Choose an activity threshold for your signal level. Here `-60` dBFS works for the generated example. Auditok requires 100 ms of activity, so an initial 50 ms block can be empty. Use `--enable-doa` for direction estimates. The optional `--max-observations` limits reported events after perception.

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

Record generated signals, split acquisitions, and collate a supervised NumPy batch:

```bash
python examples/core/learning_samples.py
```

The Core examples use generated audio identifiers, write no persistent output, and require no private recordings. The learning example creates and removes temporary sessions. See [[topics/public-contracts-and-recording|Public Contracts and Recording]] for policy inputs, masks, and split identity requirements.

Isaac examples under `examples/isaac_sim/` and `examples/isaac_lab/` are concise recipes for initialized compatible runtimes. The end-to-end GPU workflows remain under `tools/smoke/` and are invoked through the maintained commands below.

## Isaac runtime and development

The live Sim, Lab, and Kit workflows run through the Isaac Lab launcher. Follow [validation and release](validation-and-release.md#live-runtime-gates) for commands, GPU checks and required working directories. For API changes, consult the [architecture](system-architecture.md) and [compatibility guide](../decisions/product-boundary-and-compatibility.md).
