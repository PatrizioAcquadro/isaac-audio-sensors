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
python scripts/audit_distribution.py --dist-dir dist
python -m isaac_audio_sensors.cli export-schema --out /tmp/audio_sensor_frame.v1.schema.json
python -m isaac_audio_sensors.cli export-trace configs/isaac_audio_sensors_demo.toml --out /tmp/audio_sensor_frame.v1.json
git diff --check
```

The Makefile wraps the same release-candidate checks:

```bash
make test
make lint
make build
make import-smoke
make validate-config
make export-schema
make audit-dist
git diff --check
```

Expected behavior:

- core import succeeds in a normal Python environment;
- optional room-acoustics tests skip when `pyroomacoustics` is unavailable;
- Isaac Sim and Isaac Lab unavailable-path tests raise clear optional-runtime
  errors rather than import failures;
- Isaac Lab fallback tests allocate torch buffers and cover one-env,
  multi-env, padding/truncation, sector one-hot, per-mic RMS ordering,
  ambiguity masks, selected `env_ids` update, selected reset, lazy update
  periods, cloned-env binding, semantic array/source discovery, and discovered
  transform diagnostics;
- Isaac Lab entity tests use fake scene/entity objects to cover dict/attribute
  lookup, body/link index lookup, robot-mounted array pose composition, source
  root/body pose tensors, multiple sources, active windows, selected `env_ids`
  reads, CUDA buffer/device behavior when available, env-origin application,
  error paths, and stage-binding compatibility;
- package build creates a source distribution and wheel, then audits both
  archives for required public files and forbidden generated/private paths.
- JSON Schema and trace exports include `schema_version`, poses, units,
  provenance, and `max_events`.

Optional live checks:

```bash
make live-isaac-sim-audio ISAAC_SIM_COMMAND="$ISAAC_SIM_PYTHON"
make live-isaac-lab-audio ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
make live-isaac-lab-audio-gpu ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
```

The Isaac Lab smoke launches AppLauncher before importing
`isaac_audio_sensors.lab`, resolves classes through
`ensure_isaac_lab_sensor_classes()`, checks that `AudioArraySensorCfg`
subclasses `SensorBaseCfg` and `AudioArraySensor` subclasses `SensorBase`, then
binds a two-environment setup and a two-env cloned stage. It verifies tensor
shapes, device, reset, USD Xform stage binding, semantic array/source
discovery, transform provenance, moving-stage updates, entity binding from
articulation/rigid-object tensors, entity binding provenance, selected
`env_ids` update, and before/after bearing changes after moving a source
entity.

The Isaac Sim smoke requires an Isaac Python runtime with visible CUDA/GPU
support. It authors an in-memory USD stage with nested robot/base, source
parent, array, and microphone child transform stacks; discovers the stage
entities semantically; reads time-coded poses with
`IsaacAudioArraySensor.from_discovered_stage`; and writes evidence for selected
array, discovery reasons, before/after source pose, array pose, bearing,
transform provenance, stage time code, and frame traces in
`outputs/isaac_audio_sensors/isaac_sim_live_smoke.json`.

The GPU target fails if CUDA is unavailable or if any audio tensor, timestamp
tensor, or outdated-mask tensor is allocated on CPU. It records `torch.cuda`
and `nvidia-smi` evidence in
`outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json`.

Use `scripts/discover_isaac_runtimes.py` to print likely local runtime
candidates. The discovery script is a convenience probe; users should still set
their own `ISAAC_SIM_PYTHON` or `ISAAC_LAB_PYTHON` explicitly.

Before a public release, inspect the package contents:

```bash
make build
make audit-dist
python -m tarfile -l dist/isaac_audio_sensors-0.1.0.tar.gz
python -m zipfile -l dist/isaac_audio_sensors-0.1.0-py3-none-any.whl
```

The archives should not contain `outputs/`, `runs/`, generated media, private
recordings, local environment files, local goal files, caches, build artifacts,
or third-party scene assets.

Public naming hygiene:

```bash
grep -RInE '<legacy project-specific token pattern>' \
  README.md CHANGELOG.md Makefile pyproject.toml configs examples docs src tests exts
```

Ignored build artifacts such as `dist/`, `*.egg-info/`, `.pytest_cache/`, and
`.ruff_cache/` should be absent or regenerated before public release checks.
