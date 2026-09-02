# Implementation Plan 10 — End-to-End Validation and Product Closeout

Status: Planned after the maintained signal producers, perception path, dataset boundary, Lab adapter, and realism profiles are complete.

## Objective

Establish that the redesigned system is correct, practical, maintainable, and honest across Core, Isaac Sim, Isaac Lab, Kit, recording, replay, packaging, and bounded physical comparison before closing the product milestone.

Plan 10 enforces the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision across the complete repository. Its final audit catches residual complexity but does not replace the cleanup required inside each earlier milestone.

## Subphase 10.1 — Semantic and Leakage Validation

#### Implementation

Verify that propagation produces only final microphone signals, perception consumes no source schedules or private stems, observations contain no oracle fields, ground truth remains dataset-owned, and policy adapters expose only configured observed inputs. Exercise silence, one dominant source, competing sources, inaudible emitted sources, invalid channels, ambiguity, resets, and discontinuities.

#### Key Decisions

- Contract correctness includes absence of privileged information.
- Observation and truth matching is evaluated outside sensor output.
- Silent frames and failed localization are first-class valid cases.
- Schema migrations are direct and do not preserve conflicting legacy aliases.

#### Problems / Limitations

Passing deterministic tests cannot by itself establish realistic detector behavior or sim-to-real transfer.

## Subphase 10.2 — Perception Quality and Runtime Boundary

#### Implementation

Evaluate activity errors, angular errors, ambiguity, stability, latency, CPU or GPU cost, memory, and reset behavior across representative analytic, geometry, and physical recordings. Establish separate supported boundaries for live waveform perception, high-fidelity geometry simulation, and mass-parallel Isaac Lab training.

#### Key Decisions

- Accuracy and runtime are assessed together at application-relevant operating points.
- External libraries are retained only when they pass their supported runtime and packaging paths.
- Real recordings are required for transfer claims.
- A blocked GPU or provider runtime is reported as blocked rather than replaced by weaker evidence.

#### Problems / Limitations

No finite evaluation proves universal acoustic robustness. Claims remain tied to tested arrays, environments, sources, motion, and noise.

## Subphase 10.3 — Dataset and Distribution Closeout

#### Implementation

Validate atomic alignment, schema consistency, replay, truth separation, split isolation, optional checksums, and loader behavior for the new learning dataset. Confirm that Python packages, Kit archives, optional perception dependencies, and selected provider assets remain installable and auditable through the intended distribution paths.

#### Key Decisions

- A release is blocked by ambiguous observation semantics or truth leakage.
- Packaging must preserve optional-runtime isolation and actionable capability reporting.
- Publication is a separate authorized action after local closeout.

#### Problems / Limitations

Provider licensing or redistribution limits may require user-managed installation even when runtime integration is complete.

## Subphase 10.4 — Repository Quality and Maintainability Closeout

#### Implementation

Perform the final repository-wide check. Verify consumers, remove or simplify remaining unused, obsolete, duplicate, compatibility-only, speculative, and test-only production surfaces, and confirm that source and built packages contain only the necessary maintained system.

#### Key Decisions

- Code quality, clarity, efficiency, elegance, and maintainability are completion criteria.
- Keep only necessary functionality and distinct justified implementations; obsolete tests do not preserve dead code.

#### Problems / Limitations

Verify packaging, external consumers, and protected evidence before removal.

## Artifacts

Expected artifacts are a consolidated validation report, supported operating boundaries, dataset integrity evidence, a repository-surface cleanup audit, and release-ready local packages. Publication is not implied.

## Files

Exact validation commands, fixtures, and reports are deferred to the implementation and closeout agents.
