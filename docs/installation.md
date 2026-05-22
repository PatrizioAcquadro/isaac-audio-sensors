# Installation

## Core Install

Use Python 3.10 or newer for the pure package:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Verify that the core package imports without Isaac Sim or Isaac Lab:

```bash
python -c "import isaac_audio_sensors; print(isaac_audio_sensors.__version__)"
```

## Optional Extras

Install room-acoustics support only when you need the approximate
`pyroomacoustics` backend:

```bash
python -m pip install -e ".[room]"
```

Install docs tooling when editing docs:

```bash
python -m pip install -e ".[docs]"
```

## Isaac Runtime Policy

Isaac Sim 5.1, Isaac Lab 5.1, Omniverse, and NVIDIA runtime packages are
optional environment dependencies. They are not listed as PyPI dependencies
because their installation is platform-specific and usually comes from NVIDIA's
Isaac distribution.

For live smoke tests, run the scripts with the Python interpreter from your
Isaac environment:

```bash
PYTHONPATH=src "$ISAAC_SIM_PYTHON" scripts/live_isaac_sim_audio_smoke.py
PYTHONPATH=src "$ISAAC_LAB_PYTHON" scripts/live_isaac_lab_audio_smoke.py
```

If Isaac is unavailable, the pure core tests still run.
