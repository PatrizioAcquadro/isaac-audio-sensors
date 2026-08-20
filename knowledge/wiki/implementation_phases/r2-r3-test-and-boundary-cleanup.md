# R2-R3 Test and Boundary Cleanup

Status: complete on 2026-08-20.

## Outcome

R2 replaced filename and history-based classification with tests organized by
responsibility:

- `tests/unit/` covers DSP, math, effects, and pure backend logic.
- `tests/contract/` covers public imports, frames, schemas, configuration,
  serialization, plugins, CLI, and lazy runtime imports.
- `tests/integration/` covers recording, replay, codecs, plugins, GUI/headless
  flows, and filesystem behavior.
- `tests/isaac/` covers Isaac Sim, Isaac Lab, Kit, Omnigraph, and GPU behavior.
- `tests/release/` covers wheel, source archive, Kit extension, optional pack,
  and archive-content policy.
- `tests/fixtures/` contains only small deterministic data.

The public command surface is `make test`, `make test-isaac`,
`make test-release`, and `make test-all`. Deterministic lanes do not depend on
skips for success.

R3 removed phase-coupled measurement code, CLI and orchestration, historical
repository reconstructions, project-specific tooling, and run output from the
active product. Generic recording code, packaged schemas, release tools,
runtime smokes, demo configuration, and Kit code moved to their owning
packages. Removed interfaces have no compatibility shims.

The final boundary audit replaced the built-in Alex and Unitree rig presets
with `quad_cross_120mm` and `stereo_y_100mm`. Custom rig profiles and optional
mount paths remain supported. The live Kit smoke now uses only its portable
in-memory scene and has no external showcase-fixture dependency.

## Release Boundary

One recursive policy inspects wheel, source archive, Kit, and pack artifacts,
including nested wheels. It rejects tests, local datasets and outputs,
measurement implementation, phase paths, project-specific implementation, and
absolute workstation paths. Schemas remain package resources and schema export
does not read from documentation.

## Evidence Boundary

The ignored local evidence archive retains the authoritative terminal indices,
active calibration handoff, decisive failed evaluation and recovery packages,
and every referenced raw artifact required by that closure. Its local manifest
records path, role, byte size, SHA-256, and source index. All 1,500 records were
reverified after the final boundary cleanup.

## Validation

- Host: 414 passed, no skips, 9.71 seconds during the parallel full gate.
- Integration: 366 passed.
- Release: 34 passed; real wheel, source archive, and Kit archives passed.
- Isaac: 116 passed on the RTX 4090 through the Isaac Lab interpreter.
- Live Kit: the generic scenario and all 37 workflow steps passed on the RTX
  4090; no CPU fallback or external scene was used.
- Ruff, version synchronization, configuration, schema export, fixture
  validation, consumer searches, and whitespace checks passed.
- The downstream SquadBot project owns its replay fixture; 38 focused audio
  contract, adapter, replay, and demo tests passed against this checkout.

## Commits

- `e2c27ce` in the downstream repository: owned replay fixture migration.
- `dab4d93`: semantic test suite and command surface.
- `6fbe19d`: phase-coupled implementation, tooling, and local-output cleanup.
