# Implementation Plan 06 — Simulated and Real Signal Parity

Status: Planned after the observed frame and dataset boundaries exist.

## Objective

Make simulated propagation and physical capture interchangeable producers of the same `MicrophoneSignalBlock`. Reuse one perception pipeline so sim-to-real differences remain measurable at the signal boundary.

Plan 06 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: parity consolidates shared semantics instead of creating parallel simulation and hardware stacks.

## Subphase 06.1 — Common Signal Semantics

#### Implementation

Define identical channel ordering, sample rate, timing, array identity, validity, discontinuity, clipping, and level conventions for simulated and captured blocks. Bind each producer to an explicit `MicrophoneArraySpec` or calibrated physical equivalent rather than filenames or device order.

The block contains observed microphone samples only. Simulator state and hardware-driver details remain producer-owned metadata outside perception.

#### Key Decisions

- Simulation and hardware differ only before the signal boundary.
- Perception receives the same shape and meaning from both.
- Channel order and geometry fail closed because silent permutation invalidates DOA.
- Provenance remains available without changing observation meaning.

#### Problems / Limitations

Clock drift, missing channels, unknown gain, and buffering must remain explicit rather than being silently normalized away.

## Subphase 06.2 — Physical Capture Adapter

#### Implementation

Add the smallest hardware boundary that emits validated blocks from a robot-mounted array. Device discovery, stream lifecycle, clock continuity, channel health, and calibration lookup remain capture responsibilities. Activity and DOA remain exclusively in `AudioPerceptionPipeline`.

#### Key Decisions

- Do not introduce hardware-specific observations.
- Physical capture never bypasses the shared perception plugins.
- Apply calibration only from a valid profile.
- Stream faults produce explicit reset or invalid-block events.

#### Problems / Limitations

A successful device read does not establish timing quality or acoustic calibration, and operating-system latency may vary.

## Subphase 06.3 — Cross-Domain Validation and Cleanup

#### Implementation

Compare simulated and physical blocks on downstream-relevant level, noise, clipping, continuity, activity, DOA, ambiguity, and latency behavior. Use measured differences to guide [[implementation_phases/09-practical-realism-and-randomization|Plan 09]] without claiming exact acoustic-twin equivalence.

Consolidate common signal handling and remove superseded frame paths, hardware-specific perception, duplicate conversions, obsolete capture wrappers, and their unused supporting surfaces. Keep producer-specific code only for real provider or device differences, never only for tests.

#### Key Decisions

- Real recordings are required for transfer claims.
- Shared behavior has one owner and one downstream perception path.
- Producer-specific code and dependencies require a supported role.

#### Problems / Limitations

Claims remain bounded to tested hardware and environments. Check device and recorded-data consumers before consolidating driver-specific behavior.

## Artifacts

Expected artifacts are one common signal contract, a minimal hardware producer, comparable sim-versus-real outputs, and removal of duplicate domain paths.

## Files

Exact capture and calibration integration files are deferred to implementation.
