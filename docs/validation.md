# Validation

Core validation does not require Isaac Sim, Isaac Lab, Omniverse, or
`pyroomacoustics`.

Run:

```bash
python -m pip install -e ".[dev]"
python -c "import isaac_audio_sensors; print(isaac_audio_sensors.__version__)"
python -m pytest
python -m ruff check .
python -m build
git diff --check
```

Expected behavior:

- core import succeeds in a normal Python environment;
- optional room-acoustics tests skip when `pyroomacoustics` is unavailable;
- Isaac Sim and Isaac Lab unavailable-path tests raise clear optional-runtime
  errors rather than import failures;
- package build creates a source distribution and wheel without generated media.

Optional live checks:

```bash
PYTHONPATH=src "$ISAAC_SIM_PYTHON" scripts/live_isaac_sim_audio_smoke.py
PYTHONPATH=src "$ISAAC_LAB_PYTHON" scripts/live_isaac_lab_audio_smoke.py
```

Use `scripts/discover_isaac_runtimes.py` to print likely local runtime
candidates. The discovery script is a convenience probe; users should still set
their own `ISAAC_SIM_PYTHON` or `ISAAC_LAB_PYTHON` explicitly.

Before a public release, inspect the package contents:

```bash
python -m build
python -m tarfile -l dist/isaac_audio_sensors-0.1.0.tar.gz
python -m zipfile -l dist/isaac_audio_sensors-0.1.0-py3-none-any.whl
```

The archives should not contain `outputs/`, `runs/`, generated media, private
recordings, local environment files, or third-party scene assets.
