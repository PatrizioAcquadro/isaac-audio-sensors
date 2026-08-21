# Phase R6 — Packaging and Release

## Objective

Reduce local packaging and release workflows to the approved GitHub source, Python wheel, and NVIDIA Kit archive model without mixing temporary validation data or maintainer-only state into the product.

## Subphase R6.0 — Release Model

#### Implementation

The release model is locked to the public GitHub repository, one universal Python wheel, and one platform-compatible Kit extension zip. R6.0 records the decision; later subphases implement it.

#### Key Decisions

There is no target source archive, separate dependency artifact, checksum artifact, automated publication, tag, or push. R6.2 through R6.4 implement the final wheel and Kit-only model.

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

`make build-python` clears prior Python artifacts and stale setuptools staging, preserves the Kit zip, builds the wheel from a clean version-synchronized commit, and runs one wheel-specific audit. The audit permits only the maintained package and matching distribution metadata, requires the schemas, console entry point, `LICENSE`, and `NOTICE`, and rejects source archives or repository-only content.

The same audit installs the wheel with `--no-deps` in a temporary virtual environment with repository import paths removed. It verifies the installed package version, CLI, schema resources, metadata, and the `room` extra declarations without downloading optional dependencies.

#### Key Decisions

`make build` and `audit-dist` have no compatibility aliases. GitHub remains the public source distribution, and an sdist remains deferred until a separate PyPI decision.

The standard `room` extra still declares `pyroomacoustics`, `scipy`, and `soundfile`. R6.2 checks this installed metadata but does not repeat the real room-runtime gate.

#### Problems / Limitations

The host gate passes 418 unit/contract tests, 231 integration tests with two expected SoundFile skips, and 43 release tests. Version synchronization, Ruff, and the real wheel build and installed-artifact audit pass.

R6.2 changes packaging only. Isaac, GPU, physical-acoustics, and optional room-execution gates are not repeated; Python APIs, CLI behavior, and serialized schemas are unchanged.

## Subphase R6.3 — Standard Kit Archive

#### Implementation

`make build-kit` now creates `dist/PatrizioAcquadro-isaac-audio-sensors-linux-x86_64-v2.0.0.zip` through temporary staging. The archive contains only the Kit manifest, Extension Manager resources, entrypoint, direct `isaac_audio_sensors` package, and required licenses. It leaves no extracted tree, checksum, vendoring manifest, or build metadata in `dist/`.

The manifest declares the canonical package name and exact release target: Linux x86_64, CPython 3.12, Kit 110.1, and release configuration. The archive audit owns filename, target metadata, required content, and shared release policy. The entrypoint uses the included package, with one `src/` fallback for checkout development.

The unconsumed local installer, `_vendor` layout, development sentinel, duplicated runtime checks, and their test-only surfaces were removed. One real-build test plus one negative audit test now cover the archive contract. The live smoke accepts an extension path and verifies package origin, Extension Manager enable/disable, and shutdown.

#### Key Decisions

The Community Registry archive is the installation surface; no custom installer remains. The builder returns only the archive path and preserves the Python wheel. Python APIs, CLI behavior, schemas, and optional room dependencies are unchanged.

#### Problems / Limitations

All host and release gates pass. Both the checkout extension and an isolated extraction of the archive pass the 37-step Kit workflow on the RTX 4090 with Kit 110.1.2; the packaged run resolves `isaac_audio_sensors` from the extracted archive and verifies disable and shutdown.

Direct Extension Manager discovery requires the extracted root to use the extension name `isaac_audio_sensors.omni`; the Community Registry provides that installation layout.

## Subphase R6.4 — Remove the Custom Acoustic Pack

#### Implementation

The separate dependency artifact and all of its source, installer, builder, audit, Make, version-sync, documentation, and test surfaces are removed. `isaac_audio_sensors.core.packs`, `active_pack`, pack artifact naming, and `discover_capabilities(pack_root=...)` have no compatibility shims. `discover_capabilities()` now reports only `bundled`, `external`, or `absent` origins.

`make build-kit WHEELHOUSE=<path>` verifies one hash-locked wheel for pyroomacoustics 0.10.1, SciPy 1.18.0, SoundFile 0.14.0, CFFI 2.1.0, and pycparser 3.0. It extracts runtime and license content into `isaac_audio_sensors/_bundled` in the temporary Kit staging tree while discarding wheel records, tests, and benchmarks. The source tree and universal Python wheel never contain `_bundled`.

The Kit audit requires the five module and metadata payloads, native CFFI, libsndfile, pyroomacoustics, and SciPy libraries, plus their licenses. It rejects NumPy, `typing_extensions`, undeclared wheelhouse files, unsafe paths, collisions, and retired release members. `NOTICE` records the distributed dependencies; their complete shipped license payload remains in the zip.

The packaged entrypoint adds `_bundled` to `sys.path`. Because Kit's pip importer preloads CFFI, the entrypoint resolves CFFI and pycparser from their exact locked bundle paths during extension startup. There is no download or package installation.

#### Key Decisions

Standard Python continues to use `isaac-audio-sensors[room]`; Kit receives the same capability through its single archive. Kit remains authoritative for NumPy and `typing_extensions`, preventing duplicate numerical runtimes.

The public API removal is intentional. Backend, DSP, recording, schema, Isaac Lab, and valid-input numerical behavior are unchanged.

#### Problems / Limitations

Kit 110.1 preloads CFFI before third-party extensions start, so `sys.path` ordering alone did not satisfy the provenance gate. Exact-path loading at extension startup resolves the bundled copy without replacing Kit's NumPy or `typing_extensions`.

The gate passes 412 unit/contract tests, 230 integration tests with two expected SoundFile skips in the base venv, 39 release tests, and 88 Isaac tests on the RTX 4090. The packaged extension verifies all five dependency origins, bundled L2/room/FLAC capability, room waveform generation, FLAC export/read/replay, Extension Manager enable/disable, and shutdown. The unchanged SquadBot consumer subset passes 34 tests.

## Artifacts

R6.1 retains no generated artifact. R6.2 leaves one ignored universal wheel under `dist/`. R6.3 and R6.4 leave one self-contained Community Registry zip beside it; all Kit and dependency staging remains temporary.

## Files

- `README.md`
- `Makefile`
- `src/isaac_audio_sensors/kit/paths.py`
- `pyproject.toml`
- `tools/release/audit_python_wheel.py`
- `exts/isaac_audio_sensors.omni/config/extension.toml`
- `tools/release/build_kit_extension.py`
- `tools/release/audit_kit_archive.py`
- `tools/release/kit_dependencies.lock`
- `src/isaac_audio_sensors/core/capabilities.py`
- `NOTICE`
- `tools/smoke/live_omniverse_extension_ux.py`
