# Implementation Plan 10 — End-to-End Validation and Product Closeout

Status: Planned after the maintained signal producers, perception path, dataset boundary, Lab adapter, and realism profiles are complete.

## Objective

Establish that the redesigned system is correct, practical, maintainable, and honest across Core, Isaac Sim, Isaac Lab, Kit, recording, replay, packaging, and bounded physical comparison.

Plan 10 enforces the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision repository-wide. Its final audit catches residual complexity but does not replace cleanup inside earlier milestones.

## Subphase 10.1 — Semantic and Leakage Validation

#### Implementation

Verify that propagation produces only microphone signals, perception consumes no schedules or private stems, observations contain no oracle fields, truth remains dataset-owned, and policy adapters expose only configured observed inputs. Cover silence, dominant and competing sources, inaudible emissions, invalid channels, ambiguity, reset, and discontinuity.

#### Key Decisions

- Contract correctness includes absence of privileged information.
- Observation-to-truth matching remains outside sensor output.
- Silent frames and failed localization are valid cases.
- Schema migrations do not preserve conflicting legacy aliases.

#### Problems / Limitations

Deterministic correctness alone cannot establish realistic perception or sim-to-real transfer.

## Subphase 10.2 — Perception, Dataset, and Runtime Validation

#### Implementation

Evaluate activity, joint audible-event count/direction, missing/extra events, angular errors, ambiguity, stability, latency, compute, memory, and reset across representative analytic, geometry, and physical recordings. Establish separate supported boundaries for live perception, high-fidelity geometry, and mass-parallel Lab training.

The user's bounded 07.2 admission is a sequencing decision, not a waiver of perceptual qualification. Retain the failed temporal experiments and qualify every claimed capability against its declared robot behaviors and domain. General temporal reliability remains unqualified until supported by new evidence. If a claimed behavior requires reliable dynamic multisource listening, its qualification must address the joint count/direction and response failures; scaling, GUI completeness and improved geometric realism cannot substitute for that evidence. A narrower validated product scope must explicitly exclude unsupported claims.

Carry forward [[implementation_phases/r10-geometry-acoustics-integration#Confirmed profiles and ownership|R10's priority AV attention/search and complementary mobile audition profiles]].
For Profile 1, report useful camera acquisition, missed/spurious search cues,
false confirmation, loss/reacquisition and added latency, separating acoustic
processing from robot turning and visual processing. For Profile 2, report
motion-dependent cue quality and observed-only navigation success, collisions,
timeouts and efficiency. A source remaining physically hidden is not expected to
be visually confirmed; an NLOS arrival is not automatically the source bearing.

Use predeclared domain/error budgets and paired trial-level uncertainty. Retain
independent physical-cue checks, hard signal/lifecycle invariants and the truth
boundary even if one consumer improves. Exact asynchronous path history and
unqualified extreme motion remain explicit stress limits unless material
in-domain impact makes them necessary. Do not turn this product closeout into
universal acoustic-engine qualification or reopen deferred algorithms solely
to pass an unrelated edge case. Record simulated utility and physical transfer
as separate outcomes.

Validate dataset alignment, schema consistency, replay, truth separation, split isolation, required integrity checks, and loader behavior. Real recordings are required for transfer claims, and blocked GPU or provider runtime remains blocked rather than being replaced with weaker evidence.

#### Key Decisions

- Accuracy and runtime are evaluated together at application-relevant operating points.
- External libraries remain only when supported runtime and packaging paths pass.
- Claims stay bounded to tested arrays, environments, sources, motion, and noise.
- Ambiguous observation semantics or truth leakage blocks closeout.

#### Problems / Limitations

No finite evaluation proves universal acoustic robustness, and provider redistribution limits may constrain the supported installation path.

## Subphase 10.3 — Product and Repository Closeout

#### Implementation

Confirm that Python packages, Kit archives, optional perception dependencies, and selected provider resources are installable and auditable. Perform the final repository-wide check: verify consumers, remove or simplify remaining unused, obsolete, duplicate, compatibility-only, speculative, and test-only production surfaces, and ensure source and built packages contain only the necessary maintained system.

#### Key Decisions

- Code quality, clarity, efficiency, elegance, and maintainability are completion criteria.
- Keep only necessary functionality and distinct justified implementations.
- Obsolete tests do not preserve dead production code.
- Publication remains a separate authorized action.

#### Problems / Limitations

Verify packaging, external consumers, licensing, and protected evidence before removal or release claims.

## Artifacts

Expected artifacts are a consolidated validation report, supported operating boundaries, dataset evidence, a repository cleanup audit, and release-ready local packages. Publication is not implied.

## Files

Exact validation commands, fixtures, and reports are deferred to the implementation and closeout agents.
