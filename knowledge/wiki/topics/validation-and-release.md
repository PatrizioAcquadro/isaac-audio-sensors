# Validation and Release

## Test Lanes

`make check` is the deterministic host gate. It runs version synchronization, Ruff, `git diff --check`, and the unit/contract, integration, and release lanes without requiring a GPU or clean worktree.

`make test` remains the focused pure unit and contract lane. `.venv/bin/python -m pytest -q tests/integration` remains the focused recording, replay, codecs, workflows, filesystem, and cross-component lane.

`make test-release` remains the focused release content, versioning, Python-wheel, Kit, and repository-boundary lane.

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

`make release WHEELHOUSE=<path>` validates the locked wheelhouse, version synchronization, and clean Git source before clearing `dist/`. It builds and audits the universal wheel and self-contained Kit ZIP, leaves only those two flat artifacts, and never publishes, tags, or pushes.

The wheel audit enforces the minimal package, schema, metadata, entry-point, and license inventory, then installs the wheel without dependency downloads in a temporary environment and verifies the installed import, CLI, schemas, and `room` metadata.

The Kit build creates `PatrizioAcquadro-isaac-audio-sensors-linux-x86_64-v<version>.zip`. The explicit wheelhouse must match the hashes and exact five-distribution inventory in `tools/release/kit_dependencies.lock`.

Temporary staging contains the direct Python package, Kit configuration/resources/docs/entrypoint, licenses, and the locked room/FLAC dependencies under `isaac_audio_sensors/_bundled`. The audit verifies target metadata, runtime modules, distribution metadata, licenses, native libraries, no Kit-owned NumPy or `typing_extensions`, and no retired release surface.

The shared policy rejects first-party tests, tools, scripts, local datasets, evidence, outputs, phase paths/content, downstream project identifiers, and absolute workstation paths. Bundled third-party content receives safe-path and dedicated dependency/license audits instead of project-semantic filtering.

## Release Checklist

Run `make clean`, `make check`, and `make release WHEELHOUSE=<path>`. Add the runtime gates appropriate to changed behavior, regenerate schemas when contracts change, update `CHANGELOG.md`, and inspect both artifacts before publication.

Builds must originate from one clean committed tree; do not publish, tag, or push based on uncommitted artifacts or skipped required lanes.

R6.2 removes the source archive and treats the GitHub repository as the public source. R6.3 standardizes the Kit archive, R6.4 makes it self-contained, and R6.5 owns the three-command local workflow.

## Interpretation

Passing software gates establishes the implemented contract within their environments; it does not establish physical acoustic fidelity, hardware calibration, downstream policy quality, or sim-to-real behavior.

Current verified results and exact limitations belong in [[status|Current Status]], while release chronology belongs in the root `CHANGELOG.md`.
