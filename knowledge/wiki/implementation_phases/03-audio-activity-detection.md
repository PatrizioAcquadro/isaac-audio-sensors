# Implementation Plan 03 — Audio Activity Detection

Status: 03.1–03.2 completed on 2026-09-03; 03.3 remains planned.

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

`AuditokActivityDetector` is the maintained generic detector and wraps the public `auditok.split()` API from `auditok==0.5.2`. Its required `energy_threshold_dbfs` is fixed for a stream; 50 ms analysis, 100 ms minimum activity, and 100 ms maximum silence are the initial temporal defaults. The detector retains bounded past context, replays only that context plus the current block, and returns active only when an emitted token overlaps the current block. No future samples or retroactive frame changes enter the decision. `reset()` clears context, layout, and stream position while preserving configuration.

IAS `[channel, sample]` values are converted to native-endian IEEE-754 `float32` bytes in sample-major/channel-interleaved order. Auditok 0.5.2 interprets `sample_width=4` as float samples, converts them to `float64`, and multiplies them by 32768. The adapter therefore converts IAS dBFS thresholds to Auditok's scale by adding `20 log10(32768)` and subtracts the same reference from reported energy. The payload is not described as integer PCM. Diagnostics contain the fixed profile, Auditok version, current-block energy, threshold and margin in dBFS, temporal parameters, and the explicit `any`-channel policy; `activity_probability` remains `None`.

The built-in registry exposes `auditok` for both runtime profiles and requires factory kwargs containing the threshold. Importing `core.plugins` does not import Auditok. Standard Python declares `auditok>=0.5.2,<0.6` as a Core dependency; the Kit archive locks and audits the exact 0.5.2 pure-Python wheel, metadata, and MIT license as its sixth bundled distribution. No Core, Isaac, Lab, Kit, CLI, or configuration default selects the detector before 03.3.

Fixed threshold and initial calibration received separate verdicts. `fixed_threshold` passes the blocking current-block, causality, reset, multichannel, determinism, float-format/scale, packaging, and supported-runtime gates. `initial_calibration` is not admitted as an in-band detector mode: the Boolean contract cannot represent “not ready,” and `active=False` would incorrectly mean inactive. An explicit pre-stream experiment may estimate a number and then construct a fresh fixed-threshold detector, but percentile 10, 6 dB margin, -50 dBFS floor, and 3 s duration remain unconfirmed initial values rather than runtime defaults.

#### Key Decisions

- Auditok is accepted through the fixed profile; an alternative is considered only for a fundamental blocking incompatibility.
- IAS owns block semantics, dBFS conversion, state bounds, identity, and diagnostics; Auditok owns energy validation and tokenization.
- “Not ready” is not encoded as inactivity. Calibration stays outside `detect()` until a separate readiness contract is justified.
- A fixed threshold is explicit because one default cannot represent arbitrary microphone gain and noise floor.

#### Problems / Limitations

Low SNR can remain below the threshold, a noise-floor increase can produce sustained activity, contaminated calibration can raise the estimate, and impulses shorter than the temporal profile can be suppressed. These are operating limits, not automatic rejection conditions.

The deterministic synthetic calibration probe produced -53.96 dBFS before applying the provisional -50 dBFS floor under stable background and -20.02 dBFS under heavily contaminated calibration. A post-calibration floor increase crossed the fixed threshold after the minimum-duration window; a low-SNR case and a 25 ms impulse remained inactive. These measurements demonstrate sensitivity to the candidate parameters and do not establish physical calibration.

For 500 four-channel, 48 kHz, 50 ms blocks, the host qualification run measured 0.312 ms median, 0.359 ms p95, 0.379 ms p99, and 0.754 ms maximum detector-call latency. The provisional 5 ms p95 target is satisfied in this run but remains informational and must be confirmed on target workloads.

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

Subphase 03.1 produced the public decision/protocol contract, registry validation, and typed pipeline seam. Subphase 03.2 adds one qualified fixed-threshold Auditok adapter, focused qualification coverage, exact Python and Kit dependency boundaries, and documented calibration and operating limits. Signal-derived default integration and final detector cleanup remain in 03.3.

## Files

- `src/isaac_audio_sensors/core/types/_frame.py`
- `src/isaac_audio_sensors/core/plugins/protocols.py`
- `src/isaac_audio_sensors/core/plugins/auditok.py`
- `src/isaac_audio_sensors/core/perception.py`

## Version Notes

- 2026-09-03: Implemented Subphase 03.1 with a bounded activity-probability decision, stateful detector plugin protocol, registry validation, typed pipeline integration, explicit reset ownership, and no concrete default detector or schema change.
- 2026-09-03: Qualified Auditok 0.5.2 for explicit fixed-threshold use, kept initial calibration outside the Boolean streaming contract, added exact float32/dBFS adaptation and Core/Kit packaging, and preserved zero-observation defaults until 03.3.
