# Phase R6 — Packaging and Release

## Objective

Provide audited GitHub source, PyPI source/wheel distributions, and an NVIDIA Kit archive without mixing temporary validation data or maintainer-only state into the product.

## Subphase R6.0 — Release Model

#### Implementation

The release model is locked to the public GitHub repository, one universal Python wheel, and one platform-compatible Kit extension zip. R6.0 records the decision; later subphases implement it.

#### Key Decisions

The original decision excluded a source archive and automated publication. R6.2 through R6.7 implemented and validated that local wheel and Kit-only model; the explicit R6.8 PyPI publication decision supersedes only the deferred sdist and publication boundaries.

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

The Python build step clears stale setuptools staging, builds the wheel from a clean version-synchronized commit, and runs one wheel-specific audit. The audit permits only the maintained package and matching distribution metadata, requires the schemas, console entry point, `LICENSE`, and `NOTICE`, and rejects source archives or repository-only content.

The same audit installs the wheel with `--no-deps` in a temporary virtual environment with repository import paths removed. It verifies the installed package version, CLI, schema resources, metadata, and the `room` extra declarations without downloading optional dependencies.

#### Key Decisions

`make build` and `audit-dist` have no compatibility aliases. GitHub remains the public source distribution, and an sdist remains deferred until a separate PyPI decision.

R6.8 is that separate PyPI decision. It retains this subphase as historical attribution and adds a narrowly audited source distribution without restoring the removed compatibility aliases.

The standard `room` extra still declares `pyroomacoustics`, `scipy`, and `soundfile`. R6.2 checks this installed metadata but does not repeat the real room-runtime gate.

#### Problems / Limitations

The host gate passes 418 unit/contract tests, 231 integration tests with two expected SoundFile skips, and 43 release tests. Version synchronization, Ruff, and the real wheel build and installed-artifact audit pass.

R6.2 changes packaging only. Isaac, GPU, physical-acoustics, and optional room-execution gates are not repeated; Python APIs, CLI behavior, and serialized schemas are unchanged.

## Subphase R6.3 — Standard Kit Archive

#### Implementation

The Kit build step creates `dist/PatrizioAcquadro-isaac-audio-sensors-linux-x86_64-v2.0.0.zip` through temporary staging. The archive contains only the Kit manifest, Extension Manager resources, entrypoint, direct `isaac_audio_sensors` package, and required licenses. It leaves no extracted tree, checksum, vendoring manifest, or build metadata in `dist/`.

The manifest declares the canonical package name and exact release target: Linux x86_64, CPython 3.12, Kit 110.1, and release configuration. The archive audit owns filename, target metadata, required content, and shared release policy. The entrypoint uses the included package, with one `src/` fallback for checkout development.

The unconsumed local installer, `_vendor` layout, development sentinel, duplicated runtime checks, and their test-only surfaces were removed. One real-build test plus one negative audit test now cover the archive contract. The live smoke accepts an extension path and verifies package origin, Extension Manager enable/disable, and shutdown.

The live smoke targets the declared Kit 110.1/CPython 3.12 APIs directly. Extension Manager verification uses the canonical enable, identity, and disable calls without scanning unrelated extensions; viewport capture uses the current viewport utility, while full-window UI capture retains the renderer swapchain. Generic object-attach evidence is written only under `object_attach_live_qa.generic_scene`, including its config roundtrip and screenshot records.

#### Key Decisions

The Community Registry archive is the installation surface; no custom installer remains. The builder returns only the archive path and preserves the Python wheel. Legacy top-level aliases in newly generated Kit smoke evidence are not maintained; existing ignored validation files are not migrated. Python APIs, CLI behavior, schemas, and optional room dependencies are unchanged.

#### Problems / Limitations

All host and release gates pass. Both the checkout extension and an isolated extraction of the archive pass the 37-step Kit workflow on the RTX 4090 with Kit 110.1.2; the packaged run resolves `isaac_audio_sensors` from the extracted archive and verifies disable and shutdown.

Direct Extension Manager discovery requires the extracted root to use the extension name `isaac_audio_sensors.omni`; the Community Registry provides that installation layout.

## Subphase R6.4 — Remove the Custom Acoustic Pack

#### Implementation

The separate dependency artifact and all of its source, installer, builder, audit, Make, version-sync, documentation, and test surfaces are removed. `isaac_audio_sensors.core.packs`, `active_pack`, pack artifact naming, and `discover_capabilities(pack_root=...)` have no compatibility shims. `discover_capabilities()` now reports only `bundled`, `external`, or `absent` origins.

The Kit build verifies one hash-locked wheel for pyroomacoustics 0.10.1, SciPy 1.18.0, SoundFile 0.14.0, CFFI 2.1.0, and pycparser 3.0. It extracts runtime and license content into `isaac_audio_sensors/_bundled` in the temporary Kit staging tree while discarding wheel records, tests, and benchmarks. The source tree and universal Python wheel never contain `_bundled`.

The Kit audit requires the five module and metadata payloads, native CFFI, libsndfile, pyroomacoustics, and SciPy libraries, plus their licenses. It rejects NumPy, `typing_extensions`, undeclared wheelhouse files, unsafe paths, collisions, and retired release members. `NOTICE` records the distributed dependencies; their complete shipped license payload remains in the zip.

The packaged entrypoint adds `_bundled` to `sys.path`. Because Kit's pip importer preloads CFFI, the entrypoint resolves CFFI and pycparser from their exact locked bundle paths during extension startup. There is no download or package installation.

#### Key Decisions

Standard Python continues to use `isaac-audio-sensors[room]`; Kit receives the same capability through its single archive. Kit remains authoritative for NumPy and `typing_extensions`, preventing duplicate numerical runtimes.

The public API removal is intentional. Backend, DSP, recording, schema, Isaac Lab, and valid-input numerical behavior are unchanged.

#### Problems / Limitations

Kit 110.1 preloads CFFI before third-party extensions start, so `sys.path` ordering alone did not satisfy the provenance gate. Exact-path loading at extension startup resolves the bundled copy without replacing Kit's NumPy or `typing_extensions`.

The gate passes 412 unit/contract tests, 230 integration tests with two expected SoundFile skips in the base venv, 39 release tests, and 88 Isaac tests on the RTX 4090. The packaged extension verifies all five dependency origins, bundled L2/room/FLAC capability, room waveform generation, FLAC export/read/replay, Extension Manager enable/disable, and shutdown. The unchanged SquadBot consumer subset passes 34 tests.

## Subphase R6.5 — Local Release Workflow

#### Implementation

The primary local workflow is `make clean`, `make check`, and `make release WHEELHOUSE=<path>`. The check command runs version synchronization, Ruff, Git whitespace checks, and the unit/contract, integration, and release lanes without requiring a GPU or clean worktree.

At R6.5 closeout, the release command validated the exact locked wheelhouse, synchronized versions, and one clean Git revision before removing existing artifacts. It recreated `dist/`, built the universal wheel and self-contained Kit archive, and audited both. The flat outbox retained only those two artifacts and performed no publication, tag, or push.

Redundant build, audit, version, source, and all-lane Make wrappers are removed. The Makefile no longer duplicates the package version. Clean-source logic now has one implementation, and the retired tar and nested-archive policy/test surfaces are gone. Focused host, Isaac, smoke, schema, and diagnostic targets remain available.

A later maintenance pass consolidates version synchronization, clean-source provenance, and locked-wheel validation behind `release_preflight.py`. The Kit builder exposes and reuses one wheelhouse validator, the publication workflow delegates pre-build validation to `make release`, and the builder and final artifact audit retain their independent boundary checks.

#### Key Decisions

`pyproject.toml` is the only package-version authority. The explicit R6.4 wheelhouse remains required; release orchestration never downloads or changes dependency versions. The dependency lock is also authoritative for versioned bundled metadata paths, while explicit runtime, native-library, and license requirements remain audit policy. Preflight failures preserve existing `dist/` contents.

`dist/python/` and `dist/kit/` were not introduced because the flat outbox matched the approved workflow. R6.8 retains the flat layout while adding the sdist. `make check` remains deterministic and CPU-only; GPU and live runtime gates remain separate.

#### Problems / Limitations

Release still requires a clean committed tree and an externally prepared wheelhouse matching all five locked hashes. At R6.5 closeout, the deterministic gate passed 412 unit/contract tests, 230 integration tests with two expected SoundFile skips, and 38 release tests; the clean-source release produced and audited the wheel and Kit ZIP.

## Subphase R6.6 — Exact Artifact Audits

#### Implementation

At R6.6 closeout, one final release auditor derived both artifact names and the package version from `pyproject.toml`. It required `dist/` to contain exactly the universal wheel and Kit ZIP, then compared their complete first-party inventories with the maintained source tree. R6.8 extends that same authority to the source distribution and three-artifact outbox.

The wheel audit also enforces the exact distribution metadata, entry point, schemas, licenses, and isolated offline installation behavior. The Kit audit reconstructs the expected `_bundled` inventory from the five locked wheels and compares it file-for-file while retaining target, native-library, license, contamination, and Kit-owned dependency checks.

#### Key Decisions

The existing `make release WHEELHOUSE=<path>` interface and dependency lock remain unchanged. The audit adds no artifact manifest, checksum file, installer, compatibility alias, or test-only runtime surface.

Only redundant release helpers and duplicate assertions were removed. Negative coverage for contamination, licenses, targets, collisions, and host-owned NumPy and `typing_extensions` remains.

#### Problems / Limitations

The exact audit requires all five locked wheels before replacing existing artifacts. Any missing or hash-mismatched wheel is a release failure; the workflow never downloads or substitutes dependencies.

## Subphase R6.7 — Validation and Closeout

#### Implementation

The final host gate, release build, artifact inventories, Isaac tests, live Isaac Sim and Lab smokes, optional room/FLAC smoke, packaged Kit workflow, and SquadBot consumer subset were validated locally. The packaged run starts from the extracted ZIP with offline pip settings and no checkout package path.

The RTX 4090 run verifies Extension Manager enable/disable, packaged first-party origin, all five bundled dependency origins, Kit-owned NumPy and `typing_extensions`, room waveform output, FLAC recording, and shutdown. No publication action was performed.

#### Key Decisions

R6.7 closed its scope with two ignored local artifacts built from the final documentation commit. R6.8 later reopens only publication readiness; neither subphase changes runtime APIs, CLI behavior, schemas, or audio semantics.

#### Problems / Limitations

The deterministic gate passes 412 unit/contract tests, 230 integration tests with two expected host SoundFile skips, and 37 release tests. The RTX gate passes 88 Isaac tests, three live Isaac Sim backends, and 50 Lab steps over 4096 environments at 1.934 ms/step mean against the 20 ms budget. The Isaac Lab interpreter passes pyroomacoustics 0.10.1, SciPy 1.18.0, and SoundFile 0.14.0; the unchanged SquadBot subset passes 34 tests.

## Subphase R6.8 — Publication Readiness

#### Implementation

The local release outbox now contains one safe source distribution, the universal wheel built from it, and the unchanged self-contained Kit ZIP. The exact audit validates the sdist root, package source, generated metadata, licenses, console entry point, long description, and shared content policy before retaining the existing wheel-install and Kit bundle gates.

GitHub Actions runs the deterministic host gate on Python 3.10–3.12 and the optional room/FLAC gate on Python 3.12. One non-reusable publication workflow builds and audits the complete outbox, passes only the sdist and wheel between jobs, and uses short-lived OIDC credentials with environment approval. No dependency installation occurs in the token-bearing upload jobs. Official actions are pinned to exact reviewed commits.

#### Key Decisions

Setuptools default discovery already creates the required minimal sdist, so no `MANIFEST.in` is restored. At R6.8 completion, TestPyPI was available only by manual dispatch from `main`; production PyPI was available only from a published GitHub release whose tag matched `pyproject.toml`. The Kit ZIP remains a GitHub Release asset and is never sent to a Python index.

#### Problems / Limitations

The final freeze at commit `583d66e` passes 412 unit/contract tests, 230 integration tests with two expected SoundFile skips, 45 release tests, `twine check`, isolated wheel installation, and isolated sdist build/installation. The clean-source release produces exactly the three audited artifacts. The RTX 4090 passes 88 Isaac tests, all live Sim/Lab and room/FLAC gates, and the extracted ZIP's 37-step packaged workflow; the unchanged SquadBot subset passes 34 tests.

The TestPyPI rehearsal and production workflow complete successfully through their protected environments and trusted publishers. The immutable GitHub release and tag target commit `583d66e`; the sole release asset is the validated Linux Kit ZIP. PyPI publishes exactly `isaac_audio_sensors-2.0.0.tar.gz` and `isaac_audio_sensors-2.0.0-py3-none-any.whl`, reports one provenance bundle for each, and passes clean base installations on Python 3.10–3.12 plus the Python 3.12 `room`/FLAC gate. Community Registry discovery remains pending the NVIDIA crawler; the public repository and release already satisfy the required topic and archive-name inputs.

#### Version Notes

On 2026-08-25, later maintenance removed manual TestPyPI publication and duplicate artifact rechecks. Production publishing remains isolated behind a matching non-prerelease GitHub Release and the protected `pypi` environment; one matrix now owns all public-index installation checks.

## Artifacts

R6.1 retains no generated artifact. R6.2 adds the ignored universal wheel and R6.3–R6.4 add the self-contained Community Registry ZIP. R6.8 supersedes the two-file outbox with the exact sdist, wheel, and Kit ZIP; all staging remains temporary.

## Files

- `README.md`
- `Makefile`
- `src/isaac_audio_sensors/kit/paths.py`
- `pyproject.toml`
- `tools/release/audit_release_artifacts.py`
- `exts/isaac_audio_sensors.omni/config/extension.toml`
- `tools/release/build_kit_extension.py`
- `tools/release/audit_kit_archive.py`
- `tools/release/release_preflight.py`
- `tools/release/content_policy.py`
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `tools/release/kit_dependencies.lock`
- `src/isaac_audio_sensors/core/capabilities.py`
- `NOTICE`
- `tools/smoke/live_omniverse_extension_ux.py`
