# Installation

## Core Install

Use Python 3.10 or newer for the pure package. After building the local final
release, install the wheel directly:

```bash
python -m pip install dist/isaac_audio_sensors-1.8.0-py3-none-any.whl
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

Isaac Sim, Isaac Lab, Omniverse, and NVIDIA runtime packages are optional
environment dependencies. They are not listed as PyPI dependencies because
their installation is platform-specific and usually comes from NVIDIA's Isaac
distribution.

The canonical runtimes are the official installs:

- Isaac Sim (for example 6.0.x) at `~/isaacsim`, launched through
  `~/isaacsim/python.sh <script>` for Python workloads.
- Isaac Lab (for example 3.0.x) at `~/IsaacLab`, launched through
  `~/IsaacLab/isaaclab.sh -p <script>`.

For live smoke tests, run the scripts through those launchers:

```bash
PYTHONPATH=src ~/isaacsim/python.sh scripts/live_isaac_sim_audio_smoke.py
PYTHONPATH=src ~/IsaacLab/isaaclab.sh -p scripts/live_isaac_lab_audio_smoke.py
```

The Makefile auto-detects the same installs: `make live-*` gates default to
`$(HOME)/isaacsim/python.sh` and `$(HOME)/IsaacLab/isaaclab.sh -p` when they
exist. Point `ISAAC_SIM_ROOT`/`ISAAC_LAB_ROOT` at other install locations, or
override the full commands with `ISAAC_SIM_COMMAND`/`ISAAC_LAB_PYTHON`, for
example `make live-isaac-lab-audio ISAAC_LAB_PYTHON="$HOME/IsaacLab/isaaclab.sh -p"`.

Headless vs GUI conventions:

- The live smoke scripts run headless by default (Isaac Sim scripts create
  `SimulationApp({"headless": True})`; the Isaac Lab smoke launches
  `AppLauncher` headless). No extra flag is needed for headless gates.
- For an Isaac Lab GUI run, append `--viz kit` (Isaac Lab 3.x: headless is the
  default when `--viz` is omitted; the old `--headless` flag is deprecated but
  still accepted):

  ```bash
  PYTHONPATH=src ~/IsaacLab/isaaclab.sh -p scripts/live_isaac_lab_audio_smoke.py --viz kit
  ```

- For the Isaac Sim GUI, launch `~/isaacsim/isaac-sim.sh --ext-folder <repo>/exts`
  or use the persistent installer described in
  [isaac_sim_gui_guide.md](isaac_sim_gui_guide.md).

Run live gates from a shell without an activated virtualenv or conda
environment: `isaaclab.sh` prefers `$VIRTUAL_ENV`/`$CONDA_PREFIX` interpreters,
so an activated repo `.venv` would silently swap in a Python without the Isaac
packages.

Legacy/custom runtimes (for example a self-managed conda env with the Isaac
packages) remain usable through the same `ISAAC_SIM_COMMAND`/`ISAAC_LAB_PYTHON`
overrides, but they are legacy-only; the official installs above are the
supported path.

For external consumer validation without modifying the Isaac runtime
environment, install the wheel into a temporary target directory and point
`PYTHONPATH` only at that target:

```bash
python -m pip install --no-deps --target /tmp/isaac-audio-sensors-rc-consumer/site \
  dist/isaac_audio_sensors-1.0.0rc1-py3-none-any.whl
cd /tmp/isaac-audio-sensors-rc-consumer
PYTHONPATH=/tmp/isaac-audio-sensors-rc-consumer/site \
  ~/IsaacLab/isaaclab.sh -p generic_isaac_sim_consumer.py
PYTHONPATH=/tmp/isaac-audio-sensors-rc-consumer/site \
  ~/IsaacLab/isaaclab.sh -p generic_isaac_lab_consumer.py
```

The 2026-05-24 local-time `1.0.0rc1` external consumer smoke used this mode and
was reviewed before final `1.0.0` promotion. It imported `isaac_audio_sensors`
from
`/tmp/isaac-audio-sensors-rc-consumer/site/isaac_audio_sensors/__init__.py`,
not from an editable checkout.

If Isaac is unavailable, the pure core tests still run.
