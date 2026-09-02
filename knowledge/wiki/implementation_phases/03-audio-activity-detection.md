# Implementation Plan 03 — Audio Activity Detection

Status: Planned after the signal and perception boundary is established.

## Objective

Detect generic acoustic activity from the final multichannel microphone signal without source schedules, private stems, scene identities, or oracle audibility. Provide a practical stateful gate for downstream localization.

Plan 03 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: qualification ends with one maintained detector path and no rejected, duplicate, or test-only production surface.

## Subphase 03.1 — Activity Detector Contract

#### Implementation

Define a detector plugin that consumes ordered microphone samples and sample rate, maintains explicit streaming state, and returns a bounded decision with stable non-empty `detector_id` and explicit score semantics. Reset behavior covers episode changes, time discontinuities, array changes, and replay boundaries.

The detector runs after propagation, mixing, sensor noise, and relevant electronics. It detects acoustic activity, not speech, source identity, class, or direction.

#### Key Decisions

- Activity detection and DOA estimation are separate capabilities.
- Detection remains meaningful when DOA is unavailable.
- `detector_id` identifies an implementation or supported profile, never a scene source.
- Temporal smoothing and event boundaries belong to detector state.

#### Problems / Limitations

Energy varies with level, distance, microphone gain, noise, and clipping; one fixed threshold cannot cover all simulated and physical conditions.

## Subphase 03.2 — Auditok Qualification

#### Implementation

Qualify `auditok` as the primary generic activity-detector candidate. Evaluate energy validation, threshold adaptation, temporal tokenization, multichannel behavior, latency, reset, score access, NumPy interoperability, licensing, packaging, and changing noise floors.

Use a thin IAS adapter around useful detector primitives. If `auditok` materially fails the contract, preserve the plugin boundary and select the smallest justified alternative rather than forking its logic. Speech-only validation remains future optional work.

#### Key Decisions

- Adopt an external implementation only when runtime and semantic evidence support it.
- IAS owns its contracts, timestamps, origin, and diagnostics; the library owns its activity algorithm.
- Realistic far-field and non-stationary-noise limitations shape the supported configuration.

#### Problems / Limitations

Energy-based detection can degrade at low SNR or during contaminated initial calibration, so qualification must cover those cases.

## Subphase 03.3 — Observation Integration and Cleanup

#### Implementation

Emit no `AudioObservation` when inactive. When active, emit `origin=signal_derived`, the selected `detector_id`, and optional `detection_score` only when its interpretation is explicit. Energy, threshold, and margin may remain diagnostics. Initially support one dominant event without inventing source identity, class, or simulated source count.

Do not recreate `signal_energy` as a mode. After integration, remove rejected, duplicate, legacy-energy, and test-only detector paths with their unused supporting surfaces. Keep another detector only for a distinct verified role.

#### Key Decisions

- Absence of an observation is the normal inactive result.
- Detection score and DOA confidence are separate.
- Generic activity has one canonical detector path by default.

#### Problems / Limitations

Short impulses and continuous machinery may need different supported profiles; a second implementation requires measured non-overlapping value.

## Artifacts

Expected artifacts are one qualified detector path, documented operating limits, signal-derived observations without scene leakage, and removal of redundant detector surfaces.

## Files

Exact implementation and validation files are deferred to the implementation agent.
