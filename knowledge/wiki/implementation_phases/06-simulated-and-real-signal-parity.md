# Implementation Plan 06 — Simulated and Real Signal Parity

Status: Planned after the observed frame and dataset boundaries exist.

## Objective

Make simulated propagation and physical capture interchangeable producers of the same `MicrophoneSignalBlock`. Reuse one perception pipeline across projects, robots, array layouts, sources, and environments so sim-to-real differences remain measurable at the signal boundary.

Proceed from common signal semantics (06.1), to a first physical adapter (06.2), to cross-domain comparison and consolidation (06.3). The first device exercises the general contract; it does not define the SDK's scope or gate 06.1.

Plan 06 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: parity consolidates shared semantics instead of creating parallel simulation and hardware stacks.

## Subphase 06.1 — Common Signal Semantics

#### Implementation

Define common conventions for channel ordering, sample rate, timing, array identity, validity, discontinuity, clipping, and levels across simulated and captured blocks. Bind each producer to an explicit `MicrophoneArraySpec` or physical equivalent, with configurable geometry and acquisition parameters rather than assumptions tied to one device.

The block contains observed microphone samples only. Simulator state and hardware-driver details remain producer-owned metadata outside perception.

#### Key Decisions

- Simulation and hardware differ only before the signal boundary.
- Perception receives the same shape and meaning from both.
- Channel order and geometry fail closed because silent permutation invalidates DOA.
- Provenance remains available without changing observation meaning.
- Nominal parameters, measured calibration, and applied corrections remain distinguishable.

#### Problems / Limitations

Clock drift, missing channels, unknown gain, and buffering must remain explicit rather than being silently normalized away.

## Subphase 06.2 — Physical Capture Adapter

#### Implementation

Add the smallest capture boundary that emits validated blocks from a standalone or robot-mounted array. Keep device-specific acquisition separate from shared signal handling so other devices can integrate without a separate perception stack. Activity and DOA remain exclusively in `AudioPerceptionPipeline`.

Use the user's four-microphone ReSpeaker XVF3800 as the first reference device, reusing existing S-phase and SquadBot hardware and acquisition evidence. The shipped nominal calibration profile is a contract example, not measured calibration.

#### Key Decisions

- Do not introduce hardware-specific observations.
- Physical capture never bypasses the shared perception plugins.
- Apply calibration only from a valid profile.
- Stream faults produce explicit reset or invalid-block events.
- Support the concrete reference device without building speculative driver abstractions or fixing the common contract to its layout.

#### Problems / Limitations

A successful device read does not establish timing quality or acoustic calibration, and operating-system latency may vary.

## Subphase 06.3 — Cross-Domain Validation and Cleanup

#### Implementation

Establish contract generality across representative supported configurations and physical behavior on the reference hardware. Compare level, noise, clipping, continuity, activity, DOA, ambiguity, and latency without making one device, task, or estimator the definition of realism.

Use measured differences to guide [[implementation_phases/09-practical-realism-and-randomization|Plan 09]]. Practical realism preserves relevant physical relationships and multichannel coherence through the simplest useful representation; added detail must justify its benefit and cost. This principle guides the earlier subphases, while realism implementation remains in Plan 09.

Consolidate common signal handling and remove superseded frame paths, hardware-specific perception, duplicate conversions, obsolete capture wrappers, and their unused supporting surfaces. Keep producer-specific code only for real provider or device differences, never only for tests.

#### Key Decisions

- Real recordings are required for transfer claims.
- Shared behavior has one owner and one downstream perception path.
- Producer-specific code and dependencies require a supported role.

#### Problems / Limitations

An extensible contract does not establish universal hardware compatibility or acoustic accuracy. Physical claims remain bounded to tested conditions. Check device and recorded-data consumers before consolidating driver-specific behavior.

## Artifacts

Expected artifacts are one general signal contract, a first physical producer, comparable sim-versus-real outputs with explicit limits, and removal of duplicate domain paths.

## Files

Exact capture and calibration integration files are deferred to implementation.

Existing reference material:

- `examples/calibration/respeaker_xvf3800_nominal.v1.json` — nominal contract example only.
- `../squadbot-av-phase1/implementation_phases/phase_6c/evidence/2026-07-28-operational-points-6-7.md` — local downstream ReSpeaker acquisition evidence; no dependency on SquadBot is introduced.
