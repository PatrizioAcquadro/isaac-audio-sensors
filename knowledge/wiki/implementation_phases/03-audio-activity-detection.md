# Implementation Plan 03 — Audio Activity Detection

Status: complete. Subphases 03.1–03.2 completed on 2026-09-03 and 03.3 completed on 2026-09-04.

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

The built-in registry exposes `auditok` for both runtime profiles and requires factory kwargs containing the threshold. Importing `core.plugins` does not import Auditok. Standard Python declares `auditok>=0.5.2,<0.6` as a Core dependency; the Kit archive locks and audits the exact 0.5.2 pure-Python wheel, metadata, and MIT license as its sixth bundled distribution. At the 03.2 boundary, no Core, Isaac, Lab, Kit, CLI, or configuration default selected the detector; 03.3 later integrated it into maintained scalar consumers.

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

`simulate_from_config()` and CLI `simulate` now require an explicit runtime `energy_threshold_dbfs`. They resolve `auditok` through the built-in registry and compose the standard scalar perception pipeline without adding a detector or threshold to `AudioSensorConfig`, TOML, frame schema v3, `simulate_frame()`, or the low-level `AudioPerceptionPipeline`. The maintained examples and safe deterministic Kit presets use `-60 dBFS` because their generated signal measures about `-55.3 dBFS`; this is demonstration configuration, not a package-wide threshold for arbitrary scenes.

`IsaacAudioArraySensor` and both stage factories use the same fail-closed ownership rule. A sensor constructing the standard pipeline requires `energy_threshold_dbfs`; a caller injecting a custom pipeline must omit it. Reset and close retain their previous lifecycle ownership, and a live change to the selected array's stream-defining identity, sample rate, convention, or microphone layout resets perception before the next frame.

The Isaac Lab configuration adds optional `energy_threshold_dbfs` only as binding-owned state. `bind_reference()` requires it and creates one independent Auditok detector and perception pipeline per environment, including selective reset. `bind_entities()` rejects it because that path has no microphone signal. Both bindings intentionally preserve the existing six public tensors and zero-filled results until [[implementation_phases/07-isaac-lab-observation-integration|Phase 07]]; running the reference detector does not project source truth or prematurely change the learning interface.

Kit state, UI, maintained presets, headless summaries, validation, sensor construction, import, and export carry the explicit threshold. The configuration contract is now `ias.omni_extension_binding.v6`, with an exact required `activity_detection` object containing `detector_id="auditok"` and finite real `energy_threshold_dbfs`; v5 and older inputs are rejected. Export, JSONL, guided recording, Replicator, OmniGraph, and live instruments retain the resulting frame observations.

Inactive and warm-up frames emit no `AudioObservation`. Once Auditok's default 100 ms minimum activity has been met, an active frame emits at most one observation with `origin=signal_derived`, `detector_id="auditok"`, and `detection_score=None`; threshold, energy, and margin remain diagnostics. No source identity, class, simulated source count, DOA, or oracle state is invented. `max_observations=0` still runs the detector and preserves waveform and aggregate RMS while suppressing the final observation sequence.

`auditok` is the only maintained generic detector. No `signal_energy`, alternate default, compatibility alias, legacy-energy path, or test-only production detector was added or retained.

#### Key Decisions

- Absence of an observation is the normal inactive result.
- Detection score and DOA confidence are separate.
- Generic activity has one canonical detector path in maintained scalar runtimes.
- The threshold is application-owned runtime state, not TOML or a universal package default.
- Low-level pipeline composition remains explicit so downstream detectorless consumers preserve their contract.
- Isaac Lab tensor semantics remain a Phase 07 responsibility even though the scalar reference path now executes the detector.

#### Problems / Limitations

The default 50 ms analysis, 100 ms minimum activity, and 100 ms maximum silence can suppress a first active block and short impulses. Low SNR and changing noise floors can still cause misses or sustained activity, and a fixed threshold requires scenario-specific tuning. A second implementation or temporal profile requires measured non-overlapping value.

The official Isaac runtime does not inherit the project's Python dependencies by default. Source validation therefore exposes the project environment's site-packages to the official launcher so its registered Auditok dependency is available; a bare launcher correctly fails closed when Auditok is absent.

## Artifacts

Subphase 03.1 produced the public decision/protocol contract, registry validation, and typed pipeline seam. Subphase 03.2 added one qualified fixed-threshold Auditok adapter, focused qualification coverage, exact Python and Kit dependency boundaries, and documented calibration and operating limits. Subphase 03.3 integrated that one detector into maintained scalar consumers, advanced the Kit binding to v6, preserved the Lab tensor contract for Phase 07, and closed live GPU and downstream compatibility gates.

The 03.3 closeout passes `make check` with 579 unit/contract tests, 221 integration tests, and 58 release tests; optional audio; 96 tests in the supported Isaac runtime; and live Isaac Sim, Isaac Lab, and Kit gates on the RTX 4090. The Lab smoke preserves zero-filled entity/reference tensor parity and selective reset over 4096 environments at 0.131 ms/step mean against the 20 ms budget. Seventy focused SquadBot consumer tests pass with one skip and no downstream changes.

## Files

- `src/isaac_audio_sensors/core/types/_frame.py`
- `src/isaac_audio_sensors/core/plugins/protocols.py`
- `src/isaac_audio_sensors/core/plugins/auditok.py`
- `src/isaac_audio_sensors/core/perception.py`
- `src/isaac_audio_sensors/core/simulation.py`
- `src/isaac_audio_sensors/isaac/sensor.py`
- `src/isaac_audio_sensors/lab/reference_backend.py`
- `src/isaac_audio_sensors/kit/configuration.py`

## Version Notes

- 2026-09-03: Implemented Subphase 03.1 with a bounded activity-probability decision, stateful detector plugin protocol, registry validation, typed pipeline integration, explicit reset ownership, and no concrete default detector or schema change.
- 2026-09-03: Qualified Auditok 0.5.2 for explicit fixed-threshold use, kept initial calibration outside the Boolean streaming contract, added exact float32/dBFS adaptation and Core/Kit packaging, and preserved zero-observation defaults until 03.3.
- 2026-09-04: Completed Subphase 03.3 with explicit-threshold Auditok integration across maintained scalar runtimes, Kit binding v6, detector state per Lab reference environment, unchanged Phase 07 tensor semantics, live RTX 4090 validation, and focused downstream compatibility.
