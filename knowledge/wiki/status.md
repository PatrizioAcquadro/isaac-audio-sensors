# Current Status

Updated: 2026-08-20. Package version: `2.0.0`.

## Product Boundary

`isaac-audio-sensors` is a reusable robot-audition SDK that owns pure audio contracts and backends, calibration, generic recording/replay, optional Isaac Sim and Isaac Lab integration, the Kit extension, examples, and release tooling.

Robot-specific assets and mounts, downstream adapters and policies, task orchestration, measurement campaigns, holdouts, acceptance criteria, and experiment evidence remain outside the distributed product.

## Verified Capabilities

- Stable frame, calibration, manifest, serialization, configuration, plugin, capability, CLI, and packaged JSON Schema contracts.
- Deterministic geometry and synthetic TDOA backends plus optional room acoustics, SRP-PHAT, motion, Doppler, channel response, noise, electronics, directivity, and material/occlusion behavior.
- Atomic generic recording, verified sharded sessions, codecs, validation, statistics, deterministic splits, and read-only replay.
- Generic `quad_cross_120mm` and `stereo_y_100mm` stage rig profiles; robot-specific profiles remain downstream configuration.
- Lazy Isaac Sim stage discovery, pose and cache handling, sensor lifecycle, visualization, OmniGraph, Replicator, and Kit workflows.
- Lazy Isaac Lab sensor recovery, cloned-stage and scene/entity binding, scalar/batched fixed-shape observations, selected update/reset, and explicit GPU validation.
- Wheel, source archive, Kit extension, and optional acoustics-pack version, provenance, determinism, and content policy.
- Enforced R5.0 semantic imports, metadata-only package root, subsystem-owned public APIs, and fresh-process optional-runtime isolation.
- R5.1 core root limited to eleven fundamental models, simulator-independent config, quaternion-authoritative array pose, one propagation protocol, and generator-authoritative schemas.
- R5.2 single-path backend resolution and declaration-derived inventory, separated effects parsing/validation, and modular room-acoustics orchestration with unchanged valid-input numerical results.
- R5.3 minimal recording API, strict canonical manifests, one streaming session authority, composed recorder internals, structured corruption findings, and consolidated black-box coverage with compatible v1 artifacts.

## Documentation State

The canonical documentation is this wiki; the root README is the concise public landing page and the root `CHANGELOG.md` owns product and release chronology.

The root `docs/` directory is not part of the maintained repository boundary; the applied R0 specification is retained only as authorized raw material under `knowledge/raw/docs/`.

The Kit extension keeps a narrow standalone README and extension-specific changelog because an installed archive cannot depend on repository-relative documentation.

## Validation

The R3 runtime baseline passed 116 Isaac tests on the RTX 4090 and the complete generic live Kit workflow.

The R4 deterministic gate passed 414 host tests in 9.58 seconds, 366 integration tests in 10.36 seconds, and 40 release tests in 0.36 seconds, including six documentation-boundary tests.

The R5.0 host gate passes 417 unit/contract tests, 343 integration tests, and 40 release tests after removing redundant test-only coverage.

The R5.1 gate passes 416 unit/contract tests, 343 integration tests, 40 release tests, and 115 Isaac tests on the RTX 4090. The known SquadBot audio contract, replay, live-bridge, and adapter selection passes 34 downstream tests without consumer changes.

The R5.2 gate passes 409 unit/contract tests in 6.26 seconds, 342 integration tests in 8.24 seconds, 40 release tests, and 112 Isaac tests on the RTX 4090. Geometry, TDOA, fake-room GCC, and fake-room SRP frames remain byte-identical to the pre-refactor baselines; the maintained real-room example renders with pyroomacoustics 0.10.1. The same 34 SquadBot tests pass without consumer changes.

The R5.3 gate passes 413 unit/contract tests, 223 host integration tests, 40 release tests, and 112 Isaac tests on the RTX 4090. The optional FLAC lane passes 5 tests with SoundFile in the Isaac Lab interpreter; the host-only environment skips that one optional roundtrip. The same 34 SquadBot tests pass without consumer changes, and wheel/source plus Kit archives pass their audits.

Ruff, version synchronization, the executable README quickstart, internal wikilinks, index coverage, authorized R0 hash preservation, removed-root-doc references, Kit metadata, and whitespace checks passed.

R4 changes documentation, packaging metadata, version checks, and release-boundary tests without changing Python, CLI, schema, or runtime behavior; clean-source wheel, source, and Kit builds are verified after the implementation commit and reported in the phase handoff.

See [[implementation_phases/r2-fast-test-architecture|R2 Fast Test Architecture]], [[implementation_phases/r3-product-boundary-cleanup|R3 Product Boundary Cleanup]], [[implementation_phases/r4-documentation-consolidation|R4 Documentation Consolidation]], and [[implementation_phases/r5-semantic-component-refactor|R5 Semantic Component Refactor]].

## Maintained Commands

- `make test` — pure unit and contract tests.
- `.venv/bin/python -m pytest -q tests/integration` — host integration tests.
- `make test-release` — repository and archive release policy.
- `make test-isaac` — Isaac tests through the Isaac Lab interpreter.
- `make test-all` — all lanes in dependency order.
- `make build`, `make build-kit`, and `make build-pack` — audited release artifacts.

## Limits

- Isaac tests require a compatible user-managed runtime and visible GPU; required GPU checks do not use CPU fallback.
- Room acoustics requires the optional `room` dependencies and remains an approximate shoebox model.
- Raycast occlusion and nominal transmission do not model diffraction or establish measured material behavior.
- Simulation correctness does not establish hardware calibration, physical acoustic fidelity, downstream policy quality, or sim-to-real validity.
- Retained scientific evidence is local, ignored, protected, and excluded from distributions.

## Next Work

Later R5 work may simplify another semantic subsystem within the established boundaries. General packaging and release cleanup remains R6 work.
