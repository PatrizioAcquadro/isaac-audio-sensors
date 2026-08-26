# Validation and Release

## Test Lanes

`make` requires an explicit target and fails without one, so validation, release, and cleanup work is never implicit.

`make check` is the deterministic host gate. It runs version synchronization, Ruff, `git diff --check`, and the unit/contract, integration, and release lanes without requiring a GPU or clean worktree.

`make test` remains the focused pure unit and contract lane. `.venv/bin/python -m pytest -q tests/integration` remains the focused recording, replay, codecs, workflows, filesystem, and cross-component lane.

`make test-release` remains the focused release content, versioning, Python sdist/wheel, Kit, and repository-boundary lane.

`make test-isaac` runs the Isaac lane through the configured Isaac Lab interpreter with `CUDA_VISIBLE_DEVICES=0`.

## Focused Checks

`make validate-config` validates the maintained TOML example; `make validate-fixture` validates the deterministic recording fixture; `make export-schema` regenerates all three public schemas.

`make lint` runs Ruff. The complete `make check` gate also rejects whitespace and conflict-marker damage.

`make clean` removes only regenerable build, distribution, coverage, Python metadata, and tool-cache files. It does not touch the virtual environment, local evidence, agent instructions, or the local implementation checklist.

Use focused tests during iteration, then run the complete relevant lane before committing a coherent milestone.

## Live Runtime Gates

`make smoke-isaac-sim` exercises live stage discovery, transforms, sensor updates, diagnostics, and output through the Isaac runtime.

`make smoke-isaac-lab` exercises real Lab inheritance, multi-environment bindings, fixed-shape tensors, selected reset/update, and CUDA placement; it fails when the GPU path is unavailable.

`make smoke-kit` exercises the real extension manager, UI/controller workflow, USD stage operations, frame output, optional services, and clean shutdown.

Automatic smoke and diagnostic artifacts use temporary paths under `build/validation/isaac_audio_sensors/`. `ISAAC_AUDIO_SENSORS_OUTPUT_ROOT` remains the explicit Kit override.

Runtime blockers must report the exact command and failure; sandbox restrictions are not evidence that the host lacks a GPU or Isaac installation.

## Version Authority

`pyproject.toml` is authoritative for the package version.

The version gate synchronizes the package `__version__`, Kit manifest, root README, canonical wiki status, root changelog, and extension-specific changelog.

The frame, dataset-manifest, and calibration-profile schema versions remain independent from the package version.

## Build and Audit

The `dev` extra installs the build frontend, Setuptools 77 or newer, and wheel, matching the default non-isolated source/wheel build and its PEP 639 license metadata.

`make release WHEELHOUSE=<path>` runs one preflight for version synchronization, clean Git source, and the locked wheelhouse before clearing `dist/`. It builds the source distribution, builds the universal wheel from that source distribution, creates the self-contained Kit ZIP, and requires those exact synchronized filenames as the complete flat outbox. It never publishes, tags, or pushes.

The source-distribution audit requires safe tar paths, exact source and generated-metadata inventories, matching root files, package metadata, licenses, console entry point, and README description. It rejects repository-only and project-specific content. The wheel audit derives the complete package and schema inventory from the maintained source tree, then installs the exact wheel without dependency downloads or checkout import paths and verifies the import, CLI, schemas, and `room` metadata.

The Kit build creates `PatrizioAcquadro-isaac-audio-sensors-linux-x86_64-v<version>.zip`. The explicit wheelhouse must match the hashes and exact five-distribution inventory in `tools/release/kit_dependencies.lock`. Acquisition verifies hashes while downloading; the preflight, builder, and post-build audit independently validate their input or artifact boundary.

Temporary staging contains the direct Python package, Kit configuration/resources/docs/entrypoint, licenses, and the locked room/FLAC dependencies under `isaac_audio_sensors/_bundled`. The audit derives the complete first-party inventory from source, reconstructs the complete bundled inventory from the five hash-locked wheels, and compares both file-for-file. It also verifies target metadata, licenses, native libraries, no bundled NumPy or `typing_extensions`, and no retired release surface.

The shared policy rejects first-party tests, tools, scripts, local datasets, evidence, outputs, phase paths/content, downstream project identifiers, and absolute workstation paths. Bundled third-party content receives safe-path and dedicated dependency/license audits instead of project-semantic filtering.

## Release Checklist

Run `make clean`, `make check`, and `make release WHEELHOUSE=<path>`. Add the runtime gates appropriate to changed behavior, regenerate schemas when contracts change, update `CHANGELOG.md`, and inspect all three artifacts before publication.

Builds must originate from one clean committed tree; do not publish, tag, or push based on uncommitted artifacts or skipped required lanes.

R6.2 originally deferred the source archive. R6.8 supersedes that temporary wheel-only decision for PyPI, adds the exact sdist contract, and keeps the GitHub repository as the public source tree. R6.3–R6.7 continue to own the Kit archive and validated runtime gates.

GitHub Actions runs the deterministic host gate on Python 3.10, 3.11, and 3.12 plus one Python 3.12 `room`/FLAC lane. Publishing a matching non-prerelease GitHub release builds and audits all three artifacts, runs `twine check` once, and transfers only the immutable sdist and wheel artifact to a protected PyPI upload job with `id-token: write`. One post-publication matrix verifies base installations on Python 3.10–3.12 and the Python 3.12 `room`/FLAC path.

After publication, verify the remote tag and immutable GitHub asset against the release commit and digest. Verify the PyPI JSON and Integrity APIs expose only the expected sdist and wheel with provenance, then repeat base and optional-extra installation checks from the public index. Community Registry closeout additionally requires discovery, installation, enable/disable, and launch from the registry; a valid GitHub release is only the crawler input, not proof of registry publication.

Before closeout, run the packaged Kit smoke from an extracted ZIP with offline pip settings, no checkout package path, and a precreated `ISAAC_AUDIO_SENSORS_OUTPUT_ROOT`. Verify Extension Manager enable/disable, first-party and bundled origins, Kit-owned NumPy and `typing_extensions`, room waveform, FLAC, and shutdown.

## Interpretation

Passing software gates establishes the implemented contract within their environments; it does not establish physical acoustic fidelity, hardware calibration, downstream policy quality, or sim-to-real behavior.

Current verified results and exact limitations belong in [[status|Current Status]], while release chronology belongs in the root `CHANGELOG.md`.
