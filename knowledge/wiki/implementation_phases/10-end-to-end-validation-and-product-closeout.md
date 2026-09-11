# Implementation Plan 10 — End-to-End Validation and Product Closeout

Status: planned after maintained producers and intended realism profiles.

## Objective

Validate the complete supported product across Core, Isaac, Lab, Kit, datasets and distribution, enforcing [[decisions/minimal-maintained-repository-surface|minimal maintained scope]].

## Subphase 10.1 — Semantic and Leakage Validation

#### Implementation

Verify mixture-only perception, independent truth, masks/ambiguity, recording/replay and task-owned privileged channels across silence, competing/inaudible sources, faults and resets.

#### Key Decisions

No source schedules, private stems or hidden associations in observations/policies.

#### Problems / Limitations

Passing deterministic contracts does not prove acoustic usefulness or transfer.

## Subphase 10.2 — Perception, Dataset, and Runtime Validation

#### Implementation

Validate each claimed behavior using [[decisions/robot-audition-fidelity|approved profiles/budgets]], paired trial uncertainty and independent physical-cue checks. Validate dataset alignment, splits/loaders, compute/memory and lifecycle.

#### Key Decisions

Separate simulated utility, physical transfer, live use and mass-parallel execution. R10 permits bounded slower-than-real-time geometry.

#### Problems / Limitations

Known joint-motion/localization failures remain open for claims that need them. Reuse valid earlier evidence; GUI/scaling cannot substitute for perception. Physical transfer needs real comparison; no general solver or unrequested algorithm research.

## Subphase 10.3 — Product and Repository Closeout

#### Implementation

Verify clean-source Python/Kit packages, optional/native dependency boundaries and active consumers; remove unused/duplicate speculative source and tooling after evidence review.

#### Key Decisions

Clarity and maintainability are completion criteria. Publication is separately authorized.

#### Problems / Limitations

Inspect licensing, downstream consumers and protected evidence before removal.

## Artifacts

Expected: bounded capability/validation report, dataset evidence, repository audit and locally installable release artifacts. [[topics/validation-and-release|Validation and Release]] owns commands.

## Files

Current source/tests, package builders and actual consumer smokes; no speculative new framework.
