# Implementation Plan 04 — Observed Direction Estimation

Status: 04.1–04.3 complete; 04.4 has a maintained bounded stable-source result, while general temporal/robust multisource qualification remains open.

## Objective

Estimate directions and observable event count from microphone mixtures alone. Keep unavailable, ambiguous, missing and extra events explicit; distinguish instantaneous DOA, tracking and separation.

## Subphase 04.1 — Mixture-Only DOA Boundary

#### Implementation

Defined `DoaEstimator.estimate(samples, microphone_positions_m, sample_rate_hz)` and independent `DoaEstimate` semantics.

#### Key Decisions

No source count, poses, IDs, schedules or private stems enter estimation.

#### Problems / Limitations

Array geometry and signal quality constrain observability; a contract does not qualify an algorithm.

## Subphase 04.2 — Estimator Qualification and Operating Semantics

#### Implementation

Qualified PyRoom SRP for nominal planar arrays and least-squares for two-mic ambiguity independently. SRP: 250 ms causal context, 512 FFT/256 hop, 300–6000 Hz, 2-degree grid, reliability 0.06. Nominal synthetic p95 1 degree; worst physical take p95 10 degrees.

#### Key Decisions

Reliability is estimator-local, not calibrated probability. Stereo candidates are alternatives, not separate sources.

#### Problems / Limitations

Robustness failed: degraded synthetic coverage 62.5–68.75% vs 90% gate; real occlusion yielded near-180-degree flips. Physical evidence was one campaign (11 calibration/24 validation takes), not session-independent accuracy. Optional 3D was not qualified at this stage.

## Subphase 04.3 — Selection, Integration, and Cleanup

#### Implementation

Integrated lazy, default-off standard DOA and 250 ms causal context; removed internal SRP. Stereo/retained single-event paths use explicit instability/confirmation semantics.

#### Key Decisions

No silent estimator fallback. Current 16 kHz multisource routing is the later 04.4 extension.

#### Problems / Limitations

Short compute time does not remove context-induced motion lag; nominal qualification is not occlusion robustness.

## Subphase 04.4 — Multi-Source Localization Qualification

#### Implementation

After 07.1, WPE plus group-sparse covariance fitting passed 24 stable-source geometry/condition groups on two fresh confirmation blocks. `EventLocalizer` produces multiple frame-local events from 750 ms past PCM at 16 kHz for planar/rank-3 arrays. Stereo and other planar rates retain their single-event roles.

#### Key Decisions

Unknown count must be inferred; no two-source cap, tracking IDs, ensemble or scene-specific selector. Keep physical and simulated claims separate.

#### Problems / Limitations

Weak speech, misses/extras and ~1–1.5 s response persist. The original combined 45-degree separation/6 dB imbalance/10 dB SNR/0.3 s RT60 domain is not generally qualified; planar elevation remains unobservable. Detailed accepted/failed candidates and motion results belong to the experiment record.

## Pre-07.2 Follow-up — Joint Count and Direction over Time

Motion/front-end candidates failed broad joint quality and were not integrated.
The user suspended general temporal research and admitted 07.2 on the maintained
bounded reference. 07.3 retired unshipped candidate interfaces while preserving
failures. Continuous acoustic timing is corrected separately; it does not qualify
fast moving-source DOA. Reopen perception research only for a concrete authorized task.

## Artifacts

[[experiments/04-4-multisource-localization|04.4 evidence]] owns protocols, numerical gates, rejected DP-RTF/weighted-SRP/ODAS/OnlineWPE and temporal controls. The maintained localizer passed actual RTX scalar/reference projection; CUDA adaptation belongs to Phase 07. Original 04.2 details remain in this path at `5cfe48d`.

## Files

`src/isaac_audio_sensors/core/plugins/`, `core/perception.py`, `lab/torch_perception.py`; the experiment record owns replay locations.
