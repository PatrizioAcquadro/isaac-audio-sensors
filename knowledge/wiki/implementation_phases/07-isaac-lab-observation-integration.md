# Implementation Plan 07 — Isaac Lab Observation Integration

Status: 07.1–07.3 complete within the agreed 2026-09-10 baseline; general temporal/physical qualification remains open.

## Objective

Project actual observed activity/events/directions into finite fixed-shape policy tensors, preserving uncertainty and isolation. Keep scalar perception as semantic reference and CUDA as a measured execution role.

## Subphase 07.1 — Observation-to-Tensor Contract

#### Implementation

`AudioArraySensorData.from_observations()` replaces the old six-tensor source-conditioned surface. Separate masks cover scores, DOA/confidence, azimuth/elevation alternatives and padding; explicit counts report truncation.

#### Key Decisions

Capacity is not source-count knowledge. No source truth, arbitrary diagnostics or mixture RMS in policy projection. Confidence null differs from zero.

#### Problems / Limitations

Warm-up/unavailable/ambiguous observations remain valid states. Initial empty entity output was superseded by 07.2.

## Subphase 07.2 — Reference, Scalable, and Stateful Paths

#### Implementation

Reference uses elapsed audio, compensated episode time and sample cursors. Entity mode renders explicit 16 kHz free-field file mixtures, maintains 750 ms context on CUDA and runs observed-only WPE/group-sparse perception. Acquisition continues between policy reads; partial reset affects selected environments only.

#### Key Decisions

Float64 WPE retained: float32 improved speed but failed raised-array count parity. Per-environment floors and convergence prevent cross-batch coupling. Normalize/sort bearings before truncation.

#### Problems / Limitations

CUDA propagation uses quasi-static pose interpolation, not Core retarded trajectories. Physics gaps >100 ms clear unavailable history explicitly. Indoor supplied-PCM parity does not qualify GPU indoor propagation; weak speech and 1–1.5 s response remain.

#### Practical Baseline Closeout

07.2 closes with measured active-audio limits, not 4096-copy real-time operation.
At 16 copies audio-only p95 is ~64 ms planar/~99 ms raised per 100 ms update;
128 copies are a measured collection starting point (~250/~472 ms mean). Physics,
rendering and learning add cost. WPE/context/cadence changes remain deferred.
See [[experiments/lab-perception-runtime|the matched workload and full results]].

#### Later numerical maintenance (2026-09-16)

R10 measurement work exposed finite but unstable WPE solutions on symmetric direct
channels and precision-dependent peak selection. Scalar and CUDA now use weighted
QR/pseudoinverse WPE and float64 peak sums/centroids with stable ties. Perception
parameters and public float32 tensors are unchanged; this was not part of the
original 07.2 closeout. All 27 affected RTX tests and 15 scalar tests pass, including
direct symmetry, equal-score plateaus, batch independence and selective reset.
[[experiments/lab-perception-runtime#Measurement reliability correction (2026-09-16)|Later replay and cost evidence]]
owns the refreshed measurements; the above throughput describes the earlier solver.

## Subphase 07.3 — Lab Migration and Cleanup

#### Implementation

Consolidated observed Kit presentation, simultaneous frame-local events, dashed ambiguity candidates, independent confidence availability and truncation. Reset/failure clears current data; history/freshness differs from perceptual latency. New GUI arrays default to 16 kHz.

#### Key Decisions

Keep all observed events, no arbitrary first-source selection or persistent track identity. Retain scalar/CUDA roles; remove rejected temporal injection/campaign code.

#### Problems / Limitations

GUI correctness cannot improve acoustic recall. Geometry path diagnostics belong to 08.3; realism controls to 09.

## Artifacts

Actual RTX Sim/Lab/Kit, package audits and 36-input/1,440-update same-PCM preservation pass (100% activity/count agreement, direction p95 <0.00018 degrees). [[experiments/lab-perception-runtime|Runtime evidence]] owns practical batches, float32 rejection and replay. [[topics/isaac-lab-integration|Lab Integration]] owns configuration and tensor fields.

## Files

`src/isaac_audio_sensors/lab/`, `kit/`, `tools/validation/lab_perception.py`, `tools/smoke/live_isaac_lab_audio_smoke.py`.
