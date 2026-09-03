# Implementation Plan 03 — Audio Activity Detection

Status: 03.1 completed on 2026-09-03; 03.2–03.3 remain planned.

## Objective

Detect generic acoustic activity from the final multichannel microphone signal without source schedules, private stems, scene identities, or oracle audibility. Provide a practical stateful gate for downstream localization.

Plan 03 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: qualification ends with one maintained detector path and no rejected, duplicate, or test-only production surface.

## Subphase 03.1 — Activity Detector Contract

#### Implementation

`ActivityDetector` is the public stateful plugin protocol. It owns a stable non-empty `detector_id`, consumes ordered valid-channel samples plus sample rate through `detect()`, returns one `ActivityDecision`, and provides a required `reset()` method. `activity_detector` is a validated registry kind with scalar `ActivityDecision` output; a resolved instance must use the same identifier as its declaration.

`ActivityDecision` contains an exact Boolean `active`, an optional `activity_probability` constrained to `[0, 1]`, and copied diagnostics. The probability means confidence that the current window contains generic acoustic activity. A detector without a justified probability returns `None` and keeps energy, threshold, margin, or other algorithm-specific values in diagnostics.

`AudioPerceptionPipeline` now accepts the detector object without a parallel identifier, calls `detect()` only with valid channels in original array order, and maps `activity_probability` to signal-derived `detection_score`. The pipeline retains no continuity heuristic: lifecycle owners must call `reset()` before a new episode or replay stream, after gaps, overlaps, or rewind, and when array, sample rate, or valid-channel layout changes. Existing Isaac and Lab lifecycle reset ownership remains intact.

No concrete activity detector is registered in 03.1. Default Core, Isaac, Lab, Kit, and CLI consumers therefore continue to emit valid zero-observation output. The detector runs after propagation, mixing, sensor noise, and relevant electronics and detects activity, not speech, source identity, class, or direction.

#### Key Decisions

- Activity detection and DOA estimation are separate capabilities.
- Detection remains meaningful when DOA is unavailable.
- `detector_id` identifies an implementation or supported profile, never a scene source.
- Temporal smoothing and event boundaries belong to detector state.
- Signal-derived score semantics are fixed to optional activity probability; unnormalized algorithm values remain diagnostics.
- Stream-boundary reset is explicit rather than inferred by frame assembly.

#### Problems / Limitations

The contract does not select an algorithm, threshold, temporal profile, or automatic reset policy. Energy varies with level, distance, microphone gain, noise, and clipping; one fixed threshold cannot cover all simulated and physical conditions.

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

Subphase 03.1 produced the public decision/protocol contract, registry validation, and typed pipeline seam. Expected later artifacts remain one qualified detector path, documented operating limits, signal-derived observations without scene leakage, and removal of redundant detector surfaces.

## Files

- `src/isaac_audio_sensors/core/types/_frame.py`
- `src/isaac_audio_sensors/core/plugins/protocols.py`
- `src/isaac_audio_sensors/core/perception.py`

## Version Notes

- 2026-09-03: Implemented Subphase 03.1 with a bounded activity-probability decision, stateful detector plugin protocol, registry validation, typed pipeline integration, explicit reset ownership, and no concrete default detector or schema change.
