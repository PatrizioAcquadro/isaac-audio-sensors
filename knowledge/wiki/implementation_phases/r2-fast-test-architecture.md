# Phase R2 — Fast Test Architecture

## Objective

Replace phase- and filename-oriented validation with deterministic test lanes owned by product responsibility, so a successful command cannot hide unsupported behavior behind skips.

## Subphase R2.1 — Semantic Test Lanes

#### Implementation

The test tree is divided into `unit`, `contract`, `integration`, `isaac`, `release`, and `fixtures` responsibilities.

`tests/unit/` checks pure configuration, DSP, geometry, acoustic effects, motion, DOA, backend mathematics, Kit instruments, profiles, validation, and room/USD utilities without optional simulator runtimes.

`tests/contract/` checks public imports, frame and schema compatibility, calibration, manifests, capabilities, plugins, Kit architecture, CLI behavior, security redaction, and lazy optional-runtime imports.

`tests/integration/` checks real cross-component composition: room acoustics, multi-source and dynamic scenes, motion, waveform and codec I/O, recording/replay/splits/validation, CLI, headless workflows, and Kit services. Simulated Omni UI coverage is limited to one host build/refresh smoke plus failure and cleanup semantics that the live happy path does not prove.

`tests/isaac/` checks Isaac and real-USD integration, visualization, stage motion, cache invalidation, lifecycle behavior, and Isaac Lab parity through the supported Isaac interpreter.

`tests/release/` checks wheel and Kit artifacts, version synchronization, repository boundaries, and forbidden release content.

#### Key Decisions

`make test` is the fast host gate and runs only unit and contract tests.

Optional runtime behavior has explicit lanes instead of being reported as a skipped host success.

The same public contracts are exercised from focused tests before broader integration and runtime gates.

#### Problems / Limitations

Isaac tests require a compatible installed runtime. Live CUDA placement, parity, reset, and performance remain explicit GPU smoke gates rather than hardware sentinels in the deterministic suite.

Release builders require a clean Git source because their provenance is bound to one commit.

## Subphase R2.2 — Public Command Surface

#### Implementation

The focused entry points are `make test`, `make test-integration`, `make test-release`, and `make test-isaac`. R6.5 adds `make check` as the deterministic host umbrella; live smoke and release behavior are documented in [[topics/validation-and-release|Validation and Release]].

#### Key Decisions

Test commands express ownership and runtime requirements directly.

#### Problems / Limitations

Isaac validation remains a separate runtime lane and is not part of the portable host check. GPU behavior belongs to the live Isaac Lab smoke.

Real Kit rendering, widget wiring, instruments, OmniGraph, audio output, device-mix capture, and cleanup belong to `make smoke-kit`; host fakes are not runtime evidence.

## Artifacts

The maintained artifacts are the semantic test directories, deterministic fixtures under `tests/fixtures/`, and the Make targets that invoke them.

## Files

- `tests/`
- `Makefile`
- `pyproject.toml`
