# Implementation Plan 03 — Audio Activity Detection

Status: Planned after the signal and perception boundary is established.

## Objective

Detect generic acoustic activity from the final multichannel microphone signal without using source schedules, private stems, scene identities, or oracle audibility. Provide a practical, stateful gate that decides when downstream localization should run.

Plan 03 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: qualification must end with one maintained detector path and no rejected, duplicate, or test-only production surface.

## Subphase 03.1 — Activity Detector Contract

#### Implementation

Introduce an activity-detector plugin contract that consumes ordered microphone samples and sample-rate information, maintains explicit streaming state, and returns a bounded decision with a stable non-empty `detector_id` and explicit score semantics. Reset behavior must cover episode changes, time discontinuities, array changes, and replay boundaries.

The detector operates after propagation, mixing, sensor noise, and relevant electronics. Its output describes acoustic activity rather than speech, source identity, class, or direction.

#### Key Decisions

- Activity detection and DOA estimation are separate capabilities.
- Detection presence is meaningful even when DOA is unavailable.
- The detector identifies its implementation or supported profile through `detector_id`; it never identifies a scene source.
- The contract supports multichannel evidence without assuming that all channels remain valid.
- Temporal smoothing and event boundaries belong to detector state, not frame assembly.

#### Problems / Limitations

Energy depends on source level, distance, microphone gain, noise, and clipping. A fixed threshold alone cannot represent the intended range of simulated and real conditions.

## Subphase 03.2 — Auditok Qualification

#### Implementation

Qualify `auditok` as the primary generic activity-detector candidate. Evaluate its energy validation, automatic threshold strategies, temporal tokenization, multichannel policy, streaming latency, state reset, score access, NumPy interoperability, licensing, packaging, and behavior under changing noise floors.

Use a thin IAS adapter around the useful detector and tokenizer primitives rather than exposing file-oriented or device-oriented library APIs. If qualification reveals a material contract mismatch, retain the plugin boundary and document the smallest justified alternative instead of silently forking the library logic.

#### Key Decisions

- External implementation is preferred when it provides maintained, tested behavior that fits the contract.
- Library adoption depends on runtime and semantic evidence, not merely on algorithm availability.
- Speech-only validators remain optional future work and do not define generic activity.
- The adapter owns IAS types, timestamps, origin, and diagnostics; `auditok` owns its activity algorithm and event-state behavior.

#### Problems / Limitations

`auditok` is energy-based and may degrade in far-field or non-stationary noise. Automatic initial calibration may also be contaminated when a source is active immediately. These limitations must shape configuration and realism evaluation.

## Subphase 03.3 — Observation Emission

#### Implementation

Emit no `AudioObservation` when activity is absent. When activity is present, create an observation with `origin=signal_derived`, the selected detector's `detector_id`, and optional `detection_score` only if its unit and interpretation are explicit. Energy, threshold, and margin may remain diagnostics when they are more honest than a normalized confidence value.

Do not recreate `signal_energy` as a detection mode. Energy may be an implementation detail or diagnostic of the selected detector, while `origin` and `detector_id` preserve the separate evidence-path and producer meanings defined by Plan 02.

Initially support one dominant acoustic event per update. Activity detection does not invent source identity or class and does not use the number of active simulated sources.

#### Key Decisions

- Absence of an observation is the normal inactive result.
- Detector score and DOA confidence are separate quantities.
- `detection_score` is optional and remains meaningful only together with `detector_id`.
- Generic activity is useful without classification.
- The first maintained behavior prioritizes reliable dominant-event operation over unsupported multi-source claims.

#### Problems / Limitations

Short impulses and continuous background machinery may require different temporal settings. One universal configuration is not expected to fit every application.

## Subphase 03.4 — Detector Consolidation and Cleanup

#### Implementation

After qualification, retain `auditok` only if it satisfies the supported activity contract; otherwise retain the smallest qualified alternative. Keep multiple detectors only when each has a distinct measured operating role and maintained consumer.

Remove rejected or duplicate detector adapters, algorithms, configuration choices, registry entries, dependencies, examples, tests, fixtures, and documentation after migrating consumers to the selected path. Do not retain a legacy energy detector, a second threshold path, or a runtime shortcut solely for comparison or test convenience. Shared signal utilities remain only when another maintained component uses them.

#### Key Decisions

- Generic activity has one canonical maintained detector path by default.
- Additional detectors require non-overlapping product roles and evidence.
- Qualification scaffolding does not become permanent runtime surface.
- Tests validate the selected production detector rather than preserving obsolete implementations.

#### Problems / Limitations

A detector that performs differently under a genuinely distinct latency, dependency, or noise regime may justify a separate profile. That role must be measured and documented before retaining another implementation.

## Artifacts

Expected artifacts are one qualified activity-detector path, documented operating limits, signal-derived observations with no scene leakage, and removal of rejected or redundant detector surfaces.

## Files

Exact implementation and validation files are deferred to the implementation agent.
