# Phase R2 — Fast Test Architecture

Status: complete; current commands are maintained in Validation and Release.

## Objective

Organize validation by product responsibility and execution requirements rather than implementation phase or filename.

## Subphase R2.1 — Semantic Test Lanes

#### Implementation

Separated unit, contract, integration, Isaac, release and fixture responsibilities; optional behavior has explicit execution lanes.

#### Key Decisions

Host success cannot stand in for skipped native/GPU/runtime behavior.

#### Problems / Limitations

Host UI fakes do not establish actual Kit rendering, wiring or lifecycle.

## Subphase R2.2 — Public Command Surface

#### Implementation

Maintained focused Make targets; R6 later introduced `make check` as the deterministic umbrella.

#### Key Decisions

Use focused checks while iterating and relevant complete lanes before delivery.

#### Problems / Limitations

Actual GPU and packaged-runtime gates remain separate; release builders require clean Git source.

## Artifacts

[[topics/validation-and-release|Validation and Release]] owns commands, runtime requirements and artifact audits.

## Files

`tests/`, `Makefile`, `pyproject.toml`.
