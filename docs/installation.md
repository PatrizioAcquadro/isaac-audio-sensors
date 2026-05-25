# Installation

## Core Install

Use Python 3.10 or newer for the pure package. After building the local final
release, install the wheel directly:

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

Verify that the core package imports without Isaac Sim or Isaac Lab:

```bash
python -c "import isaac_audio_sensors; print(isaac_audio_sensors.__version__)"
python -m isaac_audio_sensors --version
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

For external consumer validation without modifying the Isaac runtime
environment, install the wheel into a temporary target directory and point
`PYTHONPATH` only at that target:

```bash
python -m pip install --no-deps --target /tmp/isaac-audio-sensors-rc-consumer/site \
  dist/isaac_audio_sensors-1.0.0rc1-py3-none-any.whl
cd /tmp/isaac-audio-sensors-rc-consumer
PYTHONPATH=/tmp/isaac-audio-sensors-rc-consumer/site \
  "$ISAAC_LAB_PYTHON" generic_isaac_sim_consumer.py
PYTHONPATH=/tmp/isaac-audio-sensors-rc-consumer/site \
  "$ISAAC_LAB_PYTHON" generic_isaac_lab_consumer.py
```

The 2026-05-24 local-time `1.0.0rc1` external consumer smoke used this mode and
was reviewed before final `1.0.0` promotion. It imported `isaac_audio_sensors`
from
`/tmp/isaac-audio-sensors-rc-consumer/site/isaac_audio_sensors/__init__.py`,
not from an editable checkout.

If Isaac is unavailable, the pure core tests still run.
