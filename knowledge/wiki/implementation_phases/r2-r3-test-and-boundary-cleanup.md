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
records path, role, byte size, SHA-256, and source index; every retained byte
was verified before the old data and output roots were removed.

## Validation

- Host: 414 passed, no skips, 6.87 seconds wall time.
- Integration: 366 passed.
- Release: 27 passed; real wheel, source archive, and Kit archives passed.
- Isaac: 116 passed on the RTX 4090 through the Isaac Lab interpreter.
- Ruff, version synchronization, configuration, schema export, fixture
  validation, consumer searches, and whitespace checks passed.
- The downstream SquadBot project now owns its replay fixture; its focused
  audio contract, replay, and demo checks passed without this repository's
  removed output tree.

## Commits

- `e2c27ce` in the downstream repository: owned replay fixture migration.
- `dab4d93`: semantic test suite and command surface.
- `6fbe19d`: phase-coupled implementation, tooling, and local-output cleanup.
