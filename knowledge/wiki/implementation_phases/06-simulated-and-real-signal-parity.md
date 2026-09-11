# Phase 06 — Simulated and Real Signal Parity

Status: 06.1–06.3 complete; raw physical capture retained, no gain correction or absolute calibration admitted.

## Objective

Use the same PCM/perception/recording boundary for simulation and physical capture. Measure differences without fitting them away.

## Subphase 06.1 — Common Signal Semantics

#### Implementation

Added ordered local mic geometry, sample-clock identity, explicit discontinuity and per-channel clipping/unknown state. One common continuity owner validates binding and resets on faults, gaps, changed identity/rate/layout; rigid motion/provenance alone preserve context.

#### Key Decisions

Original digital amplitude is retained. Missing channels are invalid rows, unknown measurements stay unknown. Driver details remain outside perception.

#### Problems / Limitations

Software equivalence is checked on identical PCM; it does not prove physical equivalence. Actual Sim/Lab/Kit gates passed; original empty-entity timing was not active perception throughput.

## Subphase 06.2 — Physical Capture Integration

#### Implementation

SquadBot owns local/SSH ReSpeaker acquisition, raw PCM mapping, fault/reset handling and common pipeline recording. Eight-azimuth orientation review supports functional mapping.

#### Key Decisions

Hardware/campaign code stays downstream; a device example does not justify an SDK driver. Calibration must be explicitly justified.

#### Problems / Limitations

Microphone centers remain nominal; gain candidates were rejected/inconclusive. Raw is enabled; the assessment-only gain branch was retired in 06.3.

## Subphase 06.3 — Cross-Domain Validation and Cleanup

#### Implementation

Compared 25 physical takes and nominal free-field simulation: 5,440 windows per domain, exact sample/observation replay and continuity. Retired completed gain-campaign executables while preserving evidence and reusable comparison.

#### Key Decisions

No gain, threshold, angle or per-channel delay fitted to improve comparison. Received-origin alignment is common across channels.

#### Problems / Limitations

Strong-source directions are broadly consistent; weak-level activity differs materially. Analog saturation, calibrated SPL, measured drift and absolute acoustic latency remain unknown. Real transfer is bounded to this bench.

## Artifacts

[[experiments/physical-signal-comparison|Physical comparison]] owns key measurements, rejected gains and downstream evidence pointers. [[topics/public-contracts-and-recording|Common signal/recording contract]] owns runtime semantics.

## Files

`src/isaac_audio_sensors/core/types/_signal.py`, `core/perception.py`, `core/effects/electronics.py`, `tests/integration/test_signal_domain_parity.py`. Device code stays downstream.
