# Phase R2 — Fast Test Architecture

## Objective

Replace phase- and filename-oriented validation with deterministic test lanes owned by product responsibility, so a successful command cannot hide unsupported behavior behind skips.

## Subphase R2.1 — Semantic Test Lanes

#### Implementation

The test tree is divided into `unit`, `contract`, `integration`, `isaac`, `release`, and `fixtures` responsibilities.

`tests/unit/` checks pure DSP, geometry, acoustic effects, motion, DOA, and backend mathematics without optional simulator runtimes.

`tests/contract/` checks public imports, frame and schema compatibility, calibration, manifests, configuration, capabilities, plugins, CLI behavior, security redaction, and lazy optional-runtime imports.

`tests/integration/` checks recording, replay, codecs, plugins, filesystem behavior, guided/headless workflows, and cross-component acoustic behavior.

`tests/isaac/` checks Isaac Sim, Isaac Lab, Kit, OmniGraph, visualization, stage motion, cache invalidation, and GPU/runtime behavior through the supported Isaac interpreter.

`tests/release/` checks wheel and Kit artifacts, version synchronization, repository boundaries, and forbidden release content.

#### Key Decisions

`make test` is the fast host gate and runs only unit and contract tests.

Optional runtime behavior has explicit lanes instead of being reported as a skipped host success.

The same public contracts are exercised from focused tests before broader integration and runtime gates.

#### Problems / Limitations

Isaac tests require a compatible installed runtime and visible GPU; the suite fails with a concrete blocker instead of falling back to CPU.

Release builders require a clean Git source because their provenance is bound to one commit.

## Subphase R2.2 — Public Command Surface

#### Implementation

The focused entry points are `make test`, `make test-release`, and `make test-isaac`. R6.5 adds `make check` as the deterministic host umbrella; live smoke and release behavior are documented in [[topics/validation-and-release|Validation and Release]].

#### Key Decisions

Test commands express ownership and runtime requirements directly.

#### Problems / Limitations

Isaac validation remains a separate GPU/runtime lane and is not part of the portable host check.

## Artifacts

The maintained artifacts are the semantic test directories, deterministic fixtures under `tests/fixtures/`, and the Make targets that invoke them.

## Files

- `tests/`
- `Makefile`
- `pyproject.toml`
