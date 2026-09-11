# Implementation Plan 03 — Audio Activity Detection

Status: 03.1–03.3 complete (2026-09-04).

## Objective

Detect generic activity from the final valid-channel microphone mixture; never infer source identity, speech class or scheduled audibility.

## Subphase 03.1 — Activity Detector Contract

#### Implementation

Added stateful `ActivityDetector.detect/reset` and `ActivityDecision(active, optional probability, diagnostics)`, with validated registry identity.

#### Key Decisions

Only valid channels enter detection; unjustified probability remains absent.

#### Problems / Limitations

Lifecycle discontinuities require reset; Phase 06 later centralizes common continuity.

## Subphase 03.2 — Auditok Qualification

#### Implementation

Selected Auditok 0.5.2 through public `split()`: explicit stream-fixed dBFS threshold, 50 ms analysis, 100 ms minimum activity and maximum silence; bounded past-only context. Float32 interleaved input uses the audited 32768 energy-reference conversion.

#### Key Decisions

Auditok owns energy/tokenization; IAS owns PCM/dBFS mapping and state. Any-channel policy; `activity_probability=None`.

#### Problems / Limitations

Fixed thresholds can miss weak/short signals or respond to noise. No automatic calibration/readiness state. Qualification p95 ~0.359 ms over 500 four-channel 48 kHz blocks, not a universal latency guarantee.

## Subphase 03.3 — Observation Integration and Cleanup

#### Implementation

Integrated one explicit-threshold detector into standard Core/CLI/Isaac/Kit and scalar Lab reference. Injected pipelines cannot also request standard activation.

#### Key Decisions

Threshold is application-owned runtime configuration; example -60 dBFS is not a global default. No alternate legacy-energy path.

#### Problems / Limitations

Warm-up/inactivity can produce no observation. Phase 04 later adds event localization and Phase 07 actual CUDA perception; original empty entity tensors are superseded.

## Artifacts

Focused conversion/state tests, optional dependency packaging, host and actual Isaac/Kit/consumer gates passed. [[topics/public-contracts-and-recording|Current contracts]] and [[topics/acoustic-modeling|operating semantics]] own active behavior.

## Files

`src/isaac_audio_sensors/core/plugins/auditok.py`, `core/perception.py`, `core/simulation.py`, `kit/configuration.py`.
