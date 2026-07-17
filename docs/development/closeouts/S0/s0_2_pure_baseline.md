# S0.2 pure baseline closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S0.2` - Pure baseline |
| Closeout date | 2026-07-16 |
| Environment timestamp | `2026-07-16T19:51:12-04:00` |
| Entry revision | `e626ee2` (`e626ee23d7c828645b75df6345f4cb2b1d3eadd2`) |
| Closing revision | `5a388b5` (`5a388b5342ca71a69415c7c60273af585abd1a55`) |
| Package version | `1.7.0` |
| Host environment | Ubuntu 24.04.4 LTS; Linux `6.8.0-136-generic`; Python 3.12.3 in `.venv` |
| Dependency record | `outputs/isaac_audio_sensors/S0/S0.2/pip_freeze.txt` |

The host facts, entry revision, and timestamp are preserved in
`outputs/isaac_audio_sensors/S0/S0.2/environment.txt`. The adjacent
`pip_freeze.txt` is the full dependency record for the pure virtual
environment.

## Scope

This closeout records the pure gates required by Section 6.3 of
`docs/final_sensor_development_plan.md`: tests, lint, import and configuration
smokes, package build and distribution audit, generated-schema parity,
generated-trace parity, and direct source-distribution exclusion. These gates
do not load Isaac Sim or Isaac Lab, require a GPU, or constitute live-runtime
evidence.

## Gate results

`PYTHON` resolved to `.venv/bin/python`, `BUILD_FLAGS` to `--no-isolation`, and
`EXPECTED_VERSION` to `1.7.0` under the recorded Makefile defaults.

| Gate | Command and target expansion | Result | Recorded log |
| --- | --- | --- | --- |
| Tests | `make test` -> `.venv/bin/python -m pytest` | **Pass:** 383 passed, 67 skipped; 450 collected | `outputs/isaac_audio_sensors/S0/S0.2/gate_test.log` |
| Lint | `make lint` -> `.venv/bin/python -m ruff check .` | **Pass:** all checks passed | `outputs/isaac_audio_sensors/S0/S0.2/gate_lint.log` |
| Import smoke | `make import-smoke` -> `PYTHONPATH=$PWD/src:${PYTHONPATH} .venv/bin/python -c "import isaac_audio_sensors, sys; print(isaac_audio_sensors.__version__); sys.exit(0 if isaac_audio_sensors.__version__ == '1.7.0' else 1)"` | **Pass:** printed `1.7.0` | `outputs/isaac_audio_sensors/S0/S0.2/gate_import_smoke.log` |
| Configuration validation | `make validate-config` -> `PYTHONPATH=$PWD/src:${PYTHONPATH} .venv/bin/python -m isaac_audio_sensors.cli validate-config configs/isaac_audio_sensors_demo.toml` | **Pass:** demo configuration validated | `outputs/isaac_audio_sensors/S0/S0.2/gate_validate_config.log` |
| Build and distribution audit | `make build` -> `.venv/bin/python -c "import shutil; from pathlib import Path; shutil.rmtree('dist', ignore_errors=True); Path('dist').mkdir()"`; `.venv/bin/python -m build --no-isolation`; `.venv/bin/python scripts/audit_distribution.py --dist-dir dist` | **Pass:** sdist (210 files) and wheel (86 files) audited OK | `outputs/isaac_audio_sensors/S0/S0.2/gate_build.log` |
| Schema parity | `make export-schema && git diff --exit-code docs/schemas/` -> `PYTHONPATH=$PWD/src:${PYTHONPATH} .venv/bin/python -m isaac_audio_sensors.cli export-schema --out docs/schemas/audio_sensor_frame.v1.schema.json`, then the stated diff | **Pass:** generated schema matched | `outputs/isaac_audio_sensors/S0/S0.2/gate_schema_parity.log` |
| Example-trace parity | `make regenerate-traces && git diff --exit-code examples/` -> `PYTHONPATH=$PWD/src:${PYTHONPATH} .venv/bin/python scripts/regenerate_example_traces.py`, then the stated diff | **Pass:** three generated traces matched | `outputs/isaac_audio_sensors/S0/S0.2/gate_trace_parity.log` |
| Internal-doc sdist exclusion | <code>tar -tzf dist/isaac_audio_sensors-1.7.0.tar.gz &#124; grep -E '(^&#124;/)docs/(development/&#124;reference_rig_hardware_environment\.md$)'</code> | **Pass:** `grep` exited 1, meaning no matching archive members | `outputs/isaac_audio_sensors/S0/S0.2/gate_sdist_exclusion.log` |

The sdist-exclusion log preserves the `grep` result rather than its shell
invocation. The table and reproduction section give the exact equivalent
command that checks both exclusions represented by that result.

The pytest skips were intentional missing-optional-dependency branches in the
pure virtual environment, not failures:

| Missing dependency | Skipped tests | Capability category |
| --- | ---: | --- |
| `torch` | 43 | Isaac Lab and batched tensor paths |
| `soundfile` | 15 | Optional waveform input/output paths |
| `pyroomacoustics` | 6 | Optional room-acoustics backend paths |
| `scipy` | 2 | Optional signal and waveform paths |
| `pxr` | 1 | USD/Isaac integration path |
| **Total** | **67** | Optional-dependency skips by design |

## Initial failures and resolution

The first `make test` run had one failure:
`test_public_files_use_neutral_demo_names`. Its summary was 382 passed, 67
skipped, and 1 failed. The guard traversed `docs/` as public content and
rejected the `SquadBot` project token in
`docs/reference_rig_hardware_environment.md`. The failing record is
`outputs/isaac_audio_sensors/S0/S0.2/initial_run/gate_test.log`.

The first `make build` completed the sdist and wheel construction, then failed
in the unchanged `scripts/audit_distribution.py`. The sdist had included
`docs/reference_rig_hardware_environment.md`; the audit reported its `Purdue`
text as a forbidden public-package token and its `SquadBot` text as a project
token outside the permitted scope documentation. The failing record is
`outputs/isaac_audio_sensors/S0/S0.2/initial_run/gate_build.log`.

Both failures had the same boundary error: tracked execution and reference-rig
documentation was being treated as public distribution content. Closing commit
`5a388b5` (`S0.2: keep internal docs out of public artifacts`) resolved that
boundary:

- `MANIFEST.in` explicitly excludes
  `docs/reference_rig_hardware_environment.md` and recursively excludes
  `docs/development/` from the sdist.
- `tests/test_isaac_audio_core.py` treats `docs/development/` as
  development-internal for the project-token context guard and permits the
  tracked reference-rig document in that internal context. The universal
  forbidden-token checks remain in force.
- `scripts/audit_distribution.py` was not changed or weakened. The rebuilt
  artifacts passed the same audit.

The policy decision is therefore explicit: `docs/development/` and
`docs/reference_rig_hardware_environment.md` remain tracked source and review
evidence, but are internal and excluded from public package artifacts.

## Reproduction

From a checkout of closing revision `5a388b5`, activate or provide the recorded
pure environment so that Make resolves `PYTHON` to `.venv/bin/python`, then run:

```bash
make test
make lint
make import-smoke
make validate-config
make build
make export-schema && git diff --exit-code docs/schemas/
make regenerate-traces && git diff --exit-code examples/
```

After `make build`, independently confirm that the internal documents are not
members of the sdist:

```bash
tar -tzf dist/isaac_audio_sensors-1.7.0.tar.gz \
  | grep -E '(^|/)docs/(development/|reference_rig_hardware_environment\.md$)'
test "$?" -eq 1
```

The expected `grep` status is 1 because no forbidden archive member should
match. A matching path is a gate failure.

## Boundary and follow-on gates

This closeout establishes only the no-Isaac-runtime, no-GPU pure baseline.
Live Isaac Sim, Isaac Lab, extension GUI, GPU, driver, and supported live
optional-backend gates belong to S0.3. Performance observation belongs to
S0.4. Tests skipped here for missing `torch`, `pyroomacoustics`, `soundfile`,
`scipy`, or `pxr` are exercised only in environments that provide those
dependencies; this pure result does not claim those paths passed.

## Verification record

This closeout was prepared from the preserved logs without rerunning tests,
builds, or live gates. Every repository and evidence path cited above was
checked for existence. The final summary, all skip-category counts, artifact
member counts, initial failures, exit statuses, revisions, and host facts were
cross-checked against their recorded files. Git status and a no-index diff
statistic were then checked to confirm that the only write for this closeout is
under `docs/development/`.
