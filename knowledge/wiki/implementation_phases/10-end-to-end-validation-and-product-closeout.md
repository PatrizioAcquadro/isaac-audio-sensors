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

Perform a repository-wide consumer, dependency, registry, configuration, schema, package-content, and documentation audit after the migration. Confirm that active code contains no remaining `AudioDetection`, `DetectionMode`, former `detection_mode` values, source-conditioned perception, obsolete frame-producing backend path, redundant DOA implementation, compatibility fallback, orphan adapter, or unused optional dependency unless a current supported consumer and distinct product role are documented.

Remove obsolete modules, types, fields, schema versions, serializers, configuration keys, registry entries, algorithms, dependencies, examples, fixtures, tests, generated tracked artifacts, and documentation after proving they are outside the maintained consumer and protected-evidence boundary. Keep the smallest clear implementation for each capability and consolidate repeated lifecycle, validation, and adaptation logic when doing so reduces ownership ambiguity without creating speculative abstraction.

Verify that production code contains no API, runtime switch, mock path, synthetic shortcut, or alternate implementation that exists only for tests. Tests may provide their own fixtures and fakes, but must exercise the same production contracts used by real consumers. Inspect built packages as well as the source tree so removed functionality is not retained accidentally through package data, optional extras, or stale generated resources.

#### Key Decisions

- Maintainability, clarity, and a minimal supported surface are release criteria, not optional cleanup work.
- Every retained file, public symbol, configuration option, dependency, and algorithm requires a current product responsibility or maintained consumer.
- One canonical implementation per semantic role is preferred; multiple implementations require distinct measured operating roles.
- Obsolete tests are updated or removed with obsolete behavior and never justify retaining dead production code.
- Frozen historical evidence is preserved when required but does not remain connected to current runtime contracts.

#### Problems / Limitations

Removal must remain consumer-first: apparent dead code may support packaging, external integration, or protected historical evidence. Verify those boundaries before deletion, record any intentionally retained exception, and do not use cleanup as authority to remove out-of-scope downstream artifacts.

## Artifacts

Expected artifacts are a consolidated validation report, supported operating boundaries, dataset integrity evidence, a repository-surface cleanup audit, and release-ready local packages. Publication is not implied.

## Files

Exact validation commands, fixtures, and reports are deferred to the implementation and closeout agents.
