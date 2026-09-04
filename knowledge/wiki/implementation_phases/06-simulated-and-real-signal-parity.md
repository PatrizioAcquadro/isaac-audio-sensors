# Phase 06 — Simulated and Real Signal Parity

Status: 06.1 complete. 06.2 and 06.3 remain planned.

## Objective

Make simulated propagation and physical capture interchangeable producers of the same `MicrophoneSignalBlock`. Reuse one perception pipeline across projects, robots, array layouts, sources, and environments so sim-to-real differences remain measurable at the signal boundary.

Proceed from common signal semantics (06.1), to external physical capture integration (06.2), to cross-domain comparison and consolidation (06.3). The first device exercises the general contract; it does not define the SDK's scope or gate 06.1.

Plan 06 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: parity consolidates shared semantics instead of creating parallel simulation and hardware stacks.

## Subphase 06.1 — Common Signal Semantics

#### Implementation

The runtime block now requires ordered local microphone geometry, a named sample-clock domain, explicit discontinuity, and per-channel clipping with an unknown state. Existing finite immutable float32 samples, nominal rate, validity, and exact-window semantics remain. Analytic propagation and dataset truth production populate the same contract, including exact-window electronics clipping and separate nominal gain, configured drift, applied correction, and unknown measured-calibration metadata. See [[topics/public-contracts-and-recording|Public Contracts and Recording]] for the common conventions.

`AudioPerceptionPipeline` validates the declared local geometry against the bound array before invoking plugins. One shared continuity check resets activity, estimator state, and rolling DOA context on a fault, an invalid block, changed identity/clock/rate/layout, or non-contiguous windows. Its first applicable reset reason is recorded once in perception diagnostics. Rigid pose changes and provenance-only changes preserve contiguous state. Isaac's duplicate geometry-signature reset path is removed; explicit lifecycle resets remain.

Common signal diagnostics survive frame recording and replay through the existing diagnostics extension. Frame v3, manifest v4, frame-record v2, and calibration v1 remain unchanged. Recorder reset markers and gap accounting retain their existing ownership. No capture adapter, device driver, automatic calibration, new dependency, or compatibility constructor is introduced.

Validation passes 612 unit/contract, 278 integration, and 58 release tests. Tests cover binding failures, exact-window clipping, fault reset equivalence with a fresh Auditok pipeline, rigid motion, large clock origins, and equal observations for identical samples supplied with different producer provenance. Parity cases use mono/8 kHz, stereo/16 kHz, and quad/48 kHz arrays. Recording preserves signal metadata and explicit reset markers. Optional PyRoom/SoundFile audio, the seven-frame fixture, and byte-identical regeneration of all three schemas pass. The supported Isaac interpreter passes 99 tests. Live Isaac Sim, Isaac Lab, and Kit smokes pass on the RTX 4090. Lab preserves zero-tensor parity and partial reset; its existing 4096-environment entity path measures 0.138 ms/step against a 20 ms budget, not parallel waveform perception. The source Isaac interpreter lacks Auditok, so runtime gates use an isolated copy of the installed exact 0.5.2 package without replacing Kit NumPy or changing the runtime.

The block contains observed microphone samples only. Simulator state and hardware-driver details remain producer-owned metadata outside perception.

#### Key Decisions

- Simulation and hardware differ only before the signal boundary.
- Perception receives the same shape and meaning from both.
- Channel order and geometry fail closed because silent permutation invalidates DOA.
- Provenance remains available without changing observation meaning.
- Nominal parameters, measured calibration, and applied corrections remain distinguishable.
- The public constructor is migrated directly without legacy defaults or aliases.
- Samples retain their original digital amplitude; perception does not normalize or infer SPL.
- Continuity belongs to the common pipeline; driver and calibration metadata cannot alter perception.

#### Problems / Limitations

Resolved: missing channels remain explicit invalid rows; unknown clipping and acquisition evidence remain null; nominal gains, configured drift, and applied channel corrections are distinct. Geometry mismatch fails instead of silently permuting samples.

Resolved during runtime validation: the Kit smoke previously accumulated repeated paused 50 ms windows as though they were new audio. It now advances and commits the timeline for genuine contiguous activity, then checks that repeated paused snapshots remain inactive while prior activity persists in UI history and Replicator.

Unresolved by design: producer declarations cannot prove physical channel mapping, clock quality, gain, or calibration. Unknown acquisition details stay unknown. The parity tests establish common semantics, not acoustic fidelity or measured sim-to-real transfer; physical integration and comparison remain 06.2 and 06.3.

## Subphase 06.2 — Physical Capture Integration

#### Implementation

Enable external acquisition producers to supply validated `MicrophoneSignalBlock` values to the SDK's shared perception and recording path. The SDK owns common contracts, validation, and reusable signal handling; hardware-specific drivers, device configuration, channel mapping, mounting geometry, calibration data, and acquisition campaigns remain in SquadBot or the consuming project. Activity and DOA remain exclusively in `AudioPerceptionPipeline`.

Use the user's four-microphone ReSpeaker XVF3800 to verify this boundary through downstream acquisition, reusing existing S-phase and SquadBot work without importing its hardware integration into the SDK. The shipped nominal calibration profile is a contract example, not measured calibration.

#### Key Decisions

- Do not introduce hardware-specific observations.
- Physical capture never bypasses the shared perception plugins.
- Apply calibration only from a valid profile.
- Stream faults produce explicit reset or invalid-block events.
- An SDK capture adapter requires a concrete reusable role across devices or projects; the ReSpeaker reference alone does not justify one.

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

06.1 delivers the common runtime contract, one shared continuity owner, migrated consumers, and maintained validation tests. Local ignored evidence is under `build/validation/phase06_1/` (host, optional-audio/schema, and runtime logs) and `build/validation/isaac_audio_sensors/` (live smoke JSON and media). No physical recording or transfer evidence is produced.

06.2–06.3 still target downstream acquisition integration and measured sim-versus-real comparisons with explicit limits.

## Files

Main 06.1 implementation files:

- `src/isaac_audio_sensors/core/types/_signal.py` — common signal declarations and validation.
- `src/isaac_audio_sensors/core/perception.py` — binding, common continuity, and frame diagnostics.
- `src/isaac_audio_sensors/core/backends/_analytic/block.py` — analytic signal projection.
- `src/isaac_audio_sensors/core/effects/electronics.py` — exact-window clipping evidence.
- `src/isaac_audio_sensors/isaac/sensor.py` — lifecycle integration without duplicate stream validation.
- `tools/smoke/live_omniverse_extension_ux.py` — contiguous activity and paused-snapshot runtime checks.

ReSpeaker-specific files remain downstream.

Existing reference material:

- `examples/calibration/respeaker_xvf3800_nominal.v1.json` — nominal contract example only.
- `../squadbot-av-phase1/implementation_phases/phase_6c/evidence/2026-07-28-operational-points-6-7.md` — local downstream ReSpeaker acquisition evidence; no dependency on SquadBot is introduced.
