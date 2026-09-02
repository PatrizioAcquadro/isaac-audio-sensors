# Implementation Plan 06 — Simulated and Real Signal Parity

Status: Planned after the observed frame and dataset boundaries exist.

## Objective

Make simulated propagation and physical microphone capture interchangeable producers of the same `MicrophoneSignalBlock` meaning. Reuse one perception pipeline for both paths so sim-to-real differences are measured at the signal boundary rather than hidden behind separate detector implementations.

Plan 06 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: parity must consolidate shared semantics rather than add permanent parallel simulation and hardware stacks.

## Subphase 06.1 — Common Signal Semantics

#### Implementation

Define identical channel ordering, sample-rate, timing, array identity, validity, discontinuity, clipping, and level conventions for simulated and captured blocks. Bind each producer to an explicit `MicrophoneArraySpec` or calibrated physical equivalent instead of inferring geometry from filenames or device order.

The shared contract describes observed microphone samples only. Simulator scene state and hardware-driver details remain producer-owned metadata outside perception inputs.

#### Key Decisions

- Simulation and hardware differ only before the signal-block boundary.
- Perception receives the same shape and semantics from both producers.
- Channel order and geometry identity fail closed because silent permutation can invalidate DOA.
- Signal provenance remains available for analysis without changing observation meaning.

#### Problems / Limitations

Hardware devices may expose clock drift, missing channels, unknown gain, or buffering behavior that does not exist in deterministic simulation. The common contract must represent these conditions rather than normalize them away silently.

## Subphase 06.2 — Physical Capture Adapter

#### Implementation

Add the smallest hardware capture boundary needed to emit validated signal blocks from a robot-mounted microphone array. Device discovery, stream lifecycle, clock continuity, channel health, and calibration lookup remain capture responsibilities. Activity and DOA continue to belong exclusively to `AudioPerceptionPipeline`.

#### Key Decisions

- No hardware-specific observation type is introduced.
- Physical capture does not bypass the shared activity and DOA plugins.
- Calibration is applied only when supported by a valid profile and is never invented from nominal metadata.
- Recoverable stream faults remain explicit reset or invalid-block events.

#### Problems / Limitations

Driver and operating-system latency can vary. A successful device read does not establish acoustic calibration or timing quality.

## Subphase 06.3 — Cross-Domain Comparison

#### Implementation

Compare simulated and physical blocks using shared scenarios and task-relevant features: level distributions, noise, clipping, temporal continuity, activity behavior, DOA error, ambiguity, and latency. Use the differences to guide bounded simulation randomization rather than claiming exact acoustic-twin equivalence.

#### Key Decisions

- Real recordings are required to evaluate transfer, even when simulation tests pass.
- Comparison targets downstream-relevant behavior, not exhaustive waveform identity.
- Mismatches inform [[implementation_phases/09-practical-realism-and-randomization|Plan 09]].

#### Problems / Limitations

A small physical dataset supports only the tested array, mounting, rooms, and noise conditions. Generalization claims remain bounded to collected evidence.

## Subphase 06.4 — Producer Consolidation and Cleanup

#### Implementation

After simulation and hardware share `MicrophoneSignalBlock`, consolidate common signal handling and remove superseded frame paths, hardware-specific perception, duplicate conversions, obsolete capture wrappers, and their unused supporting surfaces. Keep producer-specific code only for real provider or device differences, never only for tests.

#### Key Decisions

- Shared behavior has one owner and one downstream perception path.
- Producer-specific code and dependencies require a supported simulation or hardware role.

#### Problems / Limitations

Check supported devices and recorded-data consumers before consolidating driver-specific behavior.

## Artifacts

Expected artifacts are one common signal contract, a minimal hardware producer boundary, comparable simulated-versus-real perception outputs, and removal of duplicate domain-specific paths.

## Files

Exact capture and calibration integration files are deferred to implementation.
