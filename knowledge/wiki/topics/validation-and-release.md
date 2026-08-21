# Validation and Release

## Test Lanes

`make test` runs the pure unit and contract lane and is the fast required gate.

`.venv/bin/python -m pytest -q tests/integration` runs recording, replay, codecs, workflows, filesystem, and cross-component integration tests.

`make test-release` runs release content, versioning, distribution, Kit, pack, and repository-boundary tests.

`make test-isaac` runs the Isaac lane through the configured Isaac Lab interpreter with `CUDA_VISIBLE_DEVICES=0`.

`make test-all` runs host, integration, release, and Isaac lanes in dependency order.

## Focused Checks

`make validate-config` validates the maintained TOML example; `make validate-fixture` validates the deterministic recording fixture; `make export-schema` regenerates all three public schemas.

`make lint` runs Ruff and `git diff --check` catches whitespace and conflict-marker damage.

Use focused tests during iteration, then run the complete relevant lane before committing a coherent milestone.

## Live Runtime Gates

`make smoke-isaac-sim` exercises live stage discovery, transforms, sensor updates, diagnostics, and output through the Isaac runtime.

`make smoke-isaac-lab` exercises real Lab inheritance, multi-environment bindings, fixed-shape tensors, selected reset/update, and CUDA placement; it fails when the GPU path is unavailable.

`make smoke-kit` exercises the real extension manager, UI/controller workflow, USD stage operations, frame output, optional services, and clean shutdown.

Runtime blockers must report the exact command and failure; sandbox restrictions are not evidence that the host lacks a GPU or Isaac installation.

## Version Authority

`pyproject.toml` is authoritative for the package version.

The version gate synchronizes the package `__version__`, Kit manifest, optional pack manifest/artifact name, Makefile expected version, root README, canonical wiki status, citation metadata, root changelog, and extension-specific changelog.

The frame, dataset-manifest, and calibration-profile schema versions remain independent from the package version.

## Build and Audit

`make build` creates the wheel and source archive after version and clean-source checks, then audits both formats.

`make build-kit` creates a deterministic self-contained Kit archive with the maintained package vendored under `_vendor`, source revision metadata, and a canonical tree hash.

`make build-pack WHEELHOUSE=<path>` creates the optional acoustics pack from an explicit wheelhouse and verifies its locked content.

The shared recursive policy rejects tests, tools, scripts, local datasets, evidence, outputs, phase paths/content, downstream project identifiers, absolute workstation paths, and nested archive leaks.

## Release Checklist

Run the deterministic and runtime gates appropriate to the changed behavior, regenerate schemas when contracts change, update `CHANGELOG.md`, and inspect the actual wheel, source, Kit, and pack inventories before publication.

Builds must originate from one clean committed tree; do not publish, tag, or push based on uncommitted artifacts or skipped required lanes.

R4 documentation-only work does not require GPU gates because it does not change runtime behavior, but it must rebuild and audit the source and Kit archives after the clean commit.

## Interpretation

Passing software gates establishes the implemented contract within their environments; it does not establish physical acoustic fidelity, hardware calibration, downstream policy quality, or sim-to-real behavior.

Current verified results and exact limitations belong in [[status|Current Status]], while release chronology belongs in the root `CHANGELOG.md`.
