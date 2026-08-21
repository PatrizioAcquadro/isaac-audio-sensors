# Phase R6 — Packaging and Release

## Objective

Reduce local packaging and release workflows to the approved GitHub source, Python wheel, and NVIDIA Kit archive model without mixing temporary validation data or maintainer-only state into the product.

## Subphase R6.0 — Release Model

#### Implementation

The release model is locked to the public GitHub repository, one universal Python wheel, and one platform-compatible Kit extension zip. R6.0 records the decision; later subphases implement it.

#### Key Decisions

There is no target source archive, separate acoustics pack, checksum artifact, automated publication, tag, or push. The temporary source command is removed in R6.2; the pack command remains operational until R6.4.

#### Problems / Limitations

None. The model is decision-complete; later R6 subphases implement each artifact.

## Subphase R6.1 — Root and Local Workspace Cleanup

#### Implementation

Essential contribution, private security-reporting, data-handling, and safety limitations now live in `README.md`. Separate citation, conduct, contribution, and security policy files were removed, and `CHANGELOG.md` retains one concise entry per release.

Automatic smoke, diagnostic, and default Kit output now belongs under temporary `build/validation/isaac_audio_sensors/`. The old root output and run surfaces are no longer ignored or supported. `make clean` removes only regenerable build, distribution, cache, coverage, Python metadata, and validation files.

The removed citation surface also left version synchronization and the temporary source manifest. The archive content policy still rejects an `outputs` member because that gate prevents the retired surface from re-entering a distribution.

#### Key Decisions

`ISAAC_AUDIO_SENSORS_OUTPUT_ROOT` and explicit absolute Kit paths remain supported. The compatibility-only legacy output-prefix stripper and its dedicated assertion were removed.

`evidence/`, `AGENTS.md`, `TODO.md`, `.venv/`, and local assistant state are outside `make clean`. The authorized specification under `knowledge/raw/` remains byte-identical. No Python API, CLI, schema, sensor, recording, backend, or release-model behavior changed.

#### Problems / Limitations

Host tests, version synchronization, Ruff, and current wheel/source and Kit archive audits pass. The RTX 4090 confirms that generated diagnostics use only `build/validation/`.

The R6.1 run exposed two semantic blockers outside its cleanup diff. A subsequent reconciliation preserves static room configuration during live capture and aligns the Kit smoke with the composed controller and current renderer-capture namespace. On the RTX 4090, Isaac Sim now passes three frames for each maintained backend and Kit passes all 37 workflow steps, UI/config/instrument checks, audio output, and screenshots.

## Subphase R6.2 — Minimal Python Wheel

#### Implementation

Python packaging now produces only `isaac_audio_sensors-<version>-py3-none-any.whl`. `MANIFEST.in` and the source-distribution workflow are removed; package discovery and the three JSON Schema files are declared explicitly in `pyproject.toml`.

`make build-python` clears only prior root Python artifacts under `dist/`, preserves Kit and pack subdirectories, builds the wheel from a clean version-synchronized commit, and runs one wheel-specific audit. The audit permits only the maintained package and matching distribution metadata, requires the schemas, console entry point, `LICENSE`, and `NOTICE`, and rejects source archives or repository-only content.

The same audit installs the wheel with `--no-deps` in a temporary virtual environment with repository import paths removed. It verifies the installed package version, CLI, schema resources, metadata, and the `room` extra declarations without downloading optional dependencies.

#### Key Decisions

`make build` and `audit-dist` have no compatibility aliases. GitHub remains the public source distribution, and an sdist remains deferred until a separate PyPI decision.

The standard `room` extra still declares `pyroomacoustics`, `scipy`, and `soundfile`. R6.2 checks this installed metadata but does not repeat the real room-runtime gate. Kit and acoustic-pack builders, audits, and tests remain unchanged for R6.3 and R6.4.

#### Problems / Limitations

The host gate passes 418 unit/contract tests, 231 integration tests with two expected SoundFile skips, and 43 release tests. Version synchronization, Ruff, and the real wheel build and installed-artifact audit pass.

R6.2 changes packaging only. Isaac, GPU, physical-acoustics, and optional room-execution gates are not repeated; Python APIs, CLI behavior, and serialized schemas are unchanged.

## Artifacts

R6.1 retains no generated artifact. R6.2 leaves one ignored universal wheel under `dist/`; build, cache, and installed-audit environments remain temporary.

## Files

- `README.md`
- `Makefile`
- `src/isaac_audio_sensors/kit/paths.py`
- `pyproject.toml`
- `tools/release/audit_python_wheel.py`
