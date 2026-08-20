# Validation

Core validation does not require Isaac Sim, Isaac Lab, Omniverse, or
`pyroomacoustics`.

## V1 Release Scope Gates

[V1 Public Scope](v1_scope.md) is the canonical source for release promises and
non-promises. A v1 release must validate the stable
`AudioSensorFrame` contract, JSON Schema parity, JSON and JSONL trace corpus,
stable L0 `geometry_only`, stable L1 `tdoa_synthetic`, supported optional L2
`room_acoustics` behavior, package JSON/JSONL export, import smoke, lint,
build, and distribution audit.

The supported Isaac Sim and Isaac Lab sensor paths have their own live smoke
gates when a user-managed runtime is available. The Omniverse extension UX
smoke is the gate for the reference UX when Kit is available. Replicator is only
an optional extension capability gate: absence of `omni.replicator.core` must
not block the core v1 package unless the release specifically claims
Replicator is enabled in that environment.

The following are non-gates for v1 package release: SquadBot, Alex,
ROS 2/downstream adapters, real hardware benchmarks, sim-real calibration,
complete L3/L4 acoustic fidelity, realistic materials or occlusion acoustics,
and Alex or SquadBot validation before releasing the sensor package.

Run:

```bash
python -m pip install -e ".[dev]"
python -c "import isaac_audio_sensors; print(isaac_audio_sensors.__version__)"
python -m isaac_audio_sensors --version
python -m pytest
python -m ruff check .
python -m build
python tools/release/audit_distribution.py --dist-dir dist
python -m isaac_audio_sensors.cli export-schema --out /tmp/audio_sensor_frame.v1.schema.json
python -m isaac_audio_sensors.cli export-trace examples/configs/isaac_audio_sensors_demo.toml --out /tmp/audio_sensor_frame.v1.json
git diff --check
```

The Makefile wraps the same release checks:

```bash
make test
make lint
make export-schema
git diff --check
make build
make audit-dist
make import-smoke
```

## Minimal External Consumer Smoke

The `1.0.0rc1` wheel was validated from an independent temporary consumer
workspace outside the repository on 2026-05-24 local time (Kit logs at
`2026-05-25T03:10Z`) before final `1.0.0` promotion. The install used
`pip --target`, not an editable install:

```bash
python -m pip install --no-deps --target /tmp/isaac-audio-sensors-rc-consumer/site \
  dist/isaac_audio_sensors-1.0.0rc1-py3-none-any.whl
cd /tmp/isaac-audio-sensors-rc-consumer
PYTHONPATH=/tmp/isaac-audio-sensors-rc-consumer/site \
  "$ISAAC_LAB_PYTHON" generic_isaac_sim_consumer.py \
  --out /tmp/isaac-audio-sensors-rc-consumer/evidence/generic_isaac_sim_consumer.evidence.json
PYTHONPATH=/tmp/isaac-audio-sensors-rc-consumer/site \
  "$ISAAC_LAB_PYTHON" generic_isaac_lab_consumer.py \
  --out /tmp/isaac-audio-sensors-rc-consumer/evidence/generic_isaac_lab_consumer.evidence.json
```

Both generated consumer scripts were run from
`/tmp/isaac-audio-sensors-rc-consumer`, and both imported package version
`1.0.0rc1` from
`/tmp/isaac-audio-sensors-rc-consumer/site/isaac_audio_sensors/__init__.py`.
The evidence recorded empty repo-source `sys.path` blocks and no downstream
module imports.

The generic Isaac Sim consumer created an in-memory USD stage named
`generic_external_consumer.usda` with generic array/source prims under
`/World/GenericAudioStage`, then emitted two valid `AudioSensorFrame` v1 JSONL
records: one `geometry_only` and one `tdoa_synthetic`.

The generic Isaac Lab consumer launched `isaaclab.app.AppLauncher` before
resolving the package Lab classes, recovered real `AudioArraySensorCfg` and
`AudioArraySensor` classes, and proved `SensorBaseCfg`/`SensorBase`
subclassing. It exposed a two-environment CPU observation surface with stable
keys `audio/event_presence`, `audio/bearing_deg`, `audio/confidence`,
`audio/sector_onehot`, `audio/per_mic_rms`, and `audio/ambiguity_mask`. This
external consumer smoke is not the live GPU gate; GPU placement remains covered
by `make smoke-isaac-lab`.

Final `1.0.0` does not add SquadBot, Alex, ROS 2, or downstream adapters as
release gates. The final wheel is still clean-install smoked separately from
the build artifact before tag publication.

Evidence files:

- `/tmp/isaac-audio-sensors-rc-consumer/evidence/generic_isaac_sim_consumer.evidence.json`
- `/tmp/isaac-audio-sensors-rc-consumer/evidence/generic_isaac_sim_consumer.frames.jsonl`
- `/tmp/isaac-audio-sensors-rc-consumer/evidence/generic_isaac_lab_consumer.evidence.json`

Expected behavior:

- core import succeeds in a normal Python environment;
- optional room-acoustics tests skip when `pyroomacoustics` is unavailable;
- contract-lock tests fail if `AudioSensorFrame` v1 field names, required
  schema keys, stable backend ids, unit values, provenance values, diagnostics
  namespaces, timestamp semantics, ambiguity fields, or bearing-sector
  semantics drift;
- the distribution audit fails if active `docs/api_freeze_0_1.md` no longer
  documents the v1 breaking-change policy, stable backend identifiers, separate
  frame schema version, compatible additive extension path, and corrected
  bearing-sector behavior;
- fake-pyroom tests still exercise supported L2 RIR, waveform, GCC-PHAT
  diagnostics, deterministic multi-source scheduling, and lazy dependency
  behavior when the real dependency is unavailable;
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
- the checked-in `src/isaac_audio_sensors/schemas/audio_sensor_frame.v1.schema.json` exactly
  matches the schema generated by code.
- JSON and NDJSON trace corpus files under `examples/traces/` use
  `schema_version = "ias.audio_sensor_frame.v1"`, parse as complete public
  frame objects, preserve stable fields through trace round-trip, and cover a
  minimal frame, a multi-detection frame, an ambiguity case, and diagnostics or
  provenance-rich frame sequences.
- tests enforce the v1 coordinate policy, stable unit values, allowed
  provenance values, timestamp ordering, ambiguity fields, and stable
  diagnostics namespaces.
- tests enforce the public acoustic fidelity ladder metadata: L0/L1 stable
  backend ids, L2 supported optional backend id, and L3/L4 represented without
  being selectable v1 runtime backends.
- L2 room-acoustics diagnostics include stable optional names for room config,
  `pyroomacoustics_version`, RIR length/peak delay, GCC-PHAT peaks, estimated
  TDOA matrix, direct-path delay comparison, per-mic RMS, waveform sample
  counts, and source/microphone room positions.

Optional live checks:

```bash
make live-isaac-sim-audio
make smoke-kit
make live-isaac-lab-audio
make smoke-isaac-lab
```

The gates default to the official installs (`~/isaacsim/python.sh` and
`~/IsaacLab/isaaclab.sh -p`) when present; for non-default installs override
with `ISAAC_SIM_COMMAND=<isaac-python>` or
`ISAAC_LAB_PYTHON="$HOME/IsaacLab/isaaclab.sh -p"` style values. Run them from
a shell without an activated venv/conda environment (see
[Isaac Runtime Policy](installation.md#isaac-runtime-policy)).

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
`IsaacAudioArraySensor.from_discovered_stage`; runs `geometry_only` and
`tdoa_synthetic`; and writes evidence for selected array, discovery reasons,
before/after source pose, array pose, bearing, transform provenance, stage time
code, backend diagnostics, movement diagnostics, writer diagnostics, config,
and frame traces in:

- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.json`
- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.frames.jsonl`
- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.config.json`

The 2026-05-24 local-time final `1.0.0` live run (`2026-05-25T03:34Z` Kit log
timestamp) passed. The artifact's `isaacsim_version` and `kit_version` fields
were `unavailable`, while `kit_app_version` recorded Isaac Sim app `5.1.0` and
`kit_build_version` recorded `107.3.3+production.229672.69cbf6ad.gl`. CUDA saw
one NVIDIA GeForce RTX 4090, `nvidia-smi` reported driver `570.211.01`, and
Torch was `2.7.0+cu128`. It emitted 6 valid
`AudioSensorFrame` v1 JSONL records: 3 `geometry_only` and 3
`tdoa_synthetic`. Semantic discovery selected array `rig_front` at
`/World/RobotBase/ArrayMount/AudioArray` and source `speaker_front` at
`/World/MovingSource/Sound`. The evidence recorded debug primitive labels for
microphones, source, bearing rays, and sector. `room_acoustics` was skipped
cleanly because `pyroomacoustics` was absent from that Isaac runtime.

The Omniverse extension entrypoint also has a pure Python import smoke:

```bash
PYTHONPATH=src:exts/isaac_audio_sensors.omni python - <<'PY'
import isaac_audio_sensors_omni

ext = isaac_audio_sensors_omni.Extension()
ext.on_startup("test.ext")
ext.on_shutdown()
print("extension import smoke ok")
PY
```

This smoke verifies that extension import/startup/shutdown does not require
`omni`, `pxr`, Isaac Sim, Replicator, a display, CUDA, or a GPU. Fake
`omni.ui`, `omni.usd`, and fake Replicator tests cover import-safe UI,
selection binding, authoring, discovery, errors, config import/export,
serialized overlays, writer registration, payload shape, write, flush, stop,
and missing-runtime errors.

The live extension UX smoke is:

```bash
make smoke-kit
```

It starts or attaches to real Kit, records Isaac/Kit/GPU/runtime facts, enables
`isaac_audio_sensors.omni` through Kit's extension manager, starts the extension
entrypoint, creates a real USD stage, exercises selected-prim array/source/base
binding, authors array/source metadata, discovers and binds the stage, selects
a backend, starts and updates the sensor, records overlay primitive kinds,
writes package JSON/JSONL traces, starts/writes/flushes/stops the Replicator
writer, exports and imports config JSON, attempts viewport screenshot capture,
and stops cleanly. Evidence is written to:

- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.json`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.frames.jsonl`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.config.json`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.replicator/`

The 2026-05-24 local-time final `1.0.0` extension UX run
(`2026-05-25T03:38Z` Kit log timestamp) passed on the host-visible Isaac
runtime. The artifact's
`isaacsim_version` and `kit_version` fields were `unavailable`, while
`kit_app_version` recorded Isaac Sim app `5.1.0` and `kit_build_version`
recorded `107.3.3+production.229672.69cbf6ad.gl`. It also records Torch
`2.7.0+cu128`, CUDA visibility for `NVIDIA GeForce RTX 4090`, `nvidia-smi`
driver `570.211.01`, extension-manager status `enabled`, enabled extension id
`isaac_audio_sensors.omni-1.0.0`, `omni_usd_context_stage`, three real
`omni.usd` selection updates, 16 passed workflow steps, one valid
`AudioSensorFrame` v1 JSONL record, 7 overlay primitives, Replicator writer
registration/write/flush/stop, and readable error messages for no stage, no
selection, invalid prim path, invalid backend, and invalid Replicator output.
The Replicator writer passed with `omni.replicator.core`; annotator registration
was recorded as unavailable because that Kit shape has no supported simple
Python annotator registration API. Viewport screenshot capture records either a
captured PNG path/dimensions/method or the exact blocker; the strict screenshot
gate is `make smoke-kit-screenshots`.

The GPU target fails if CUDA is unavailable or if any audio tensor, timestamp
tensor, or outdated-mask tensor is allocated on CPU. It records `torch.cuda`
and `nvidia-smi` evidence in
`outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json`.

The 2026-05-24 local-time live Lab GPU run passed with:

```bash
make smoke-isaac-lab ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
```

The evidence artifact was
`outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json`. It records Isaac
Lab `0.54.2`, Isaac Sim `5.1.0`, Kit
`107.3.3+production.229672.69cbf6ad.gl`, Torch `2.7.0+cu128`, CUDA device
`cuda:0`, and `NVIDIA GeForce RTX 4090`. It also records real
`SensorBaseCfg`/`SensorBase` subclass checks, `fallback_classes_used_in_lab:
false`, two-env shapes for fixed RL buffers, all tensor/bookkeeping devices on
`cuda:0`, selected update/reset/repopulate passing for explicit, stage, and
entity paths, stable RL observation keys, and `pxr.Usd.Stage` binding inside
Kit/Lab. The live entity path uses CUDA tensor-backed scene/entity objects; the
full real `InteractiveScene`/`RigidObject` probe remains a documented local
runtime blocker because the GPU SimulationContext path raised PhysX CUDA
illegal-memory errors and the CPU SimulationContext path hung during Kit
shutdown.

Use `tools/smoke/discover_isaac_runtimes.py` to print likely local runtime
candidates. Official installs (`~/isaacsim`, `~/IsaacLab`) are listed first and
are what the Makefile gates auto-detect; legacy custom setups appear last. The
discovery script is a convenience probe; for non-default installs set
`ISAAC_SIM_COMMAND`/`ISAAC_LAB_PYTHON` (make overrides) or
`ISAAC_SIM_PYTHON`/`ISAAC_LAB_PYTHON` (discovery hints) explicitly.

Before a public release, inspect the package contents:

```bash
make build
make audit-dist
python -m tarfile -l dist/isaac_audio_sensors-1.0.0.tar.gz
python -m zipfile -l dist/isaac_audio_sensors-1.0.0-py3-none-any.whl
```

The archives should not contain `outputs/`, `runs/`, generated media, private
recordings, local environment files, local goal files, caches, build artifacts,
or third-party scene assets.

Public naming hygiene:

```bash
grep -R -n -E '<legacy project-specific and private-path token pattern>' \
  README.md docs examples src tests Makefile pyproject.toml
git ls-files | grep -E '<tracked generated-cache-or-local-env path pattern>'
```

Use the same legacy and private-path tokens enforced by
`tools/release/audit_distribution.py` and the same tracked path classes listed in the
release goal. These checks should produce no relevant tracked public-package
leaks. Ignored build artifacts such as `dist/`, `*.egg-info/`, `.pytest_cache/`,
and `.ruff_cache/` should be absent from tracked files and regenerated only for
local validation.
