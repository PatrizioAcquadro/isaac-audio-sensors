# Phase 06 — Simulated and Real Signal Parity

Status: 06.1 and 06.2 complete. Raw remains the default; current gain candidates are rejected or inconclusive. 06.3 remains planned.

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

External acquisition now supplies validated `MicrophoneSignalBlock` values through the existing shared perception and recording APIs. Frame v3 and its generated schema add the generic `physical_capture` provenance value without changing field shape or schema version. Older readers with the closed provenance enumeration must upgrade before reading physical frames. Manifest v4 uses its existing `monotonic` time base; the distinct sample-clock domain remains in signal diagnostics and session configuration.

SquadBot owns native ReSpeaker acquisition, explicit device/configuration checks, six-channel PCM16 WAV replay, and the capture/assessment commands. Acquisition runs locally or through SSH to the Raspberry, with the same native ALSA settings and workstation SDK pipeline. Raw USB channels 2–5 become four immutable float32 rows at 16 kHz, in contiguous 800-sample windows. Native PCM is retained beside the SDK dataset. No capture driver or hardware dependency is added to this package. Auditok and optional maintained DOA run only through `AudioPerceptionPipeline`.

The consumer stops on ALSA errors, timeout, or truncated reads; it resets perception, retains an explicit fault report and incomplete verified recording, and gives each reopening a new sample clock. The raw WAV retains completed native windows; recorder cancellation retains only published shards and reports accepted versus published frame counts. Digital endpoint clipping is measured before corrections. Unknown drift, absolute delivery latency, and analog clipping remain unknown.

The first native five-second live smoke passes with 100 accepted/published frames, exact PCM-to-dataset sample equality, one recorded reset, no stream fault, and no raw endpoint clipping. Activity and DOA execute through the shared pipeline. This is acquisition evidence, not a controlled accuracy test. The SDK host gate passes 613 unit/contract, 278 integration, and 58 release tests; the downstream suite passes 408 tests, including 26 focused capture/assessment tests. A second native smoke through Raspberry SSH also passes 100 frames. CPU is the supported DSP path; these checks require no new Isaac/GPU qualification.

The S4.5 audit recovered all 102 authorized original Fit A/Fit B WAVs from the Raspberry and verified their inventory hashes and sizes. Reference validation, active windows, clipping exclusions, and group aggregation reproduce 85 admitted attempts and 32 independent groups (16 per partition), including the original gain, delay, polarity, and selected-mapping observations. Three reference-validation failures, six silence takes, and eight audio/video takes retain their original roles. Frozen decision checks agree with retained/rejected parameters. No holdout audio was opened, no hypothesis selection was repeated, and no parameter was refitted. The Fit A estimates evaluated on Fit B retain their historical level benefit; S4.6 verified application to simulation configuration, not current physical accuracy.

The current controlled comparison contains initial silence and two eight-second takes at each of eight azimuths. The operator confirmed the same bench setup, a MacBook Pro source at 0.60 m and z = −0.135 m, volume 56%, and approximately ±5° angular placement uncertainty. SSH verified source model, original reference WAV hash, volume, and the ReSpeaker USB identity. Both independent pipelines use identical native samples, nominal geometry, Auditok threshold −40.5 dBFS, maintained DOA, windows, and resets. Raw correlation verifies each common 3–7 s analysis interval inside the reference noise segment. Each branch records exactly 2,720 processed blocks; native PCM, frame metadata, and reset replay pass exact checks. All 17 physical captures complete without faults or digital clipping.

Current gain decisions use take aggregates, with no block treated as an independent trial. Admission requires at least 10% median absolute relative-level improvement, p95 worsening no greater than 0.05 dB, signed median no farther from zero, and supporting uncertainty across takes.

| Candidate | Raw → corrected median absolute residual | Current decision |
| --- | --- | --- |
| ch1 gain −1.6021 dB | 1.838 → 1.875 dB | Rejected: median residual worsens. |
| ch2 gain −1.2796 dB | 1.517 → 1.635 dB | Rejected: median, p95, and signed bias worsen. |
| ch3 gain −1.2136 dB | 1.734 → 1.410 dB | Inconclusive: 18.7% improvement, but the 95% take-bootstrap benefit interval is −0.387 to 1.214 dB. |

The existing functional mapping orientation is supported: all raw per-take median angular errors, including declared placement uncertainty, remain within half the 45° target spacing. Raw median errors range from 1° to 12°, with a median across takes of 3.5°. Raw and gain branches have identical take error summaries, 100% activity and resolved-DOA coverage in the declared source windows, and no abstention there; initial silence has no detected activity. Positive relative polarity is supported on all current takes and all historical groups; +1 changes no waveform. No gain is admitted for live use. Raw remains the default, the corrected branch remains assessment-only, and the shipped nominal profile remains a contract example.

#### Key Decisions

- Do not introduce hardware-specific observations.
- Physical capture never bypasses the shared perception plugins.
- Apply calibration only from a valid profile.
- Stream faults produce explicit reset or invalid-block events.
- An SDK capture adapter requires a concrete reusable role across devices or projects; the ReSpeaker reference alone does not justify one.

#### Problems / Limitations

A successful device read does not establish timing quality or acoustic calibration, and operating-system/network latency may vary. The eight-azimuth review supports the orientation of the existing functional association; microphone centers remain nominal, without traced wiring or measured geometry. The orientation criterion distinguishes the declared directions; it is not an acoustic-accuracy qualification.

Relative-level residuals include source directivity, placement, and room paths; they do not isolate microphone sensitivity. The bootstrap describes variation among these takes, while declared placement uncertainty is separate. No gain-level benefit becomes a claim of improved DOA. Delays, angular offsets, frequency response, confidence calibration, SPL, absolute latency, measured drift, and analog saturation receive no new correction or calibration claim. Historical evidence stays unchanged; recovered authorized WAVs and current acquisitions are downstream ignored outputs.

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

06.2 evidence is downstream under `outputs/phase06_2/`: local/SSH raw smokes, `recovered_fit/`, the two S4.5 audit reports, `reference_campaign/`, `paired_assessment/`, sample/metadata/reset verification, and `orientation_review.json`. Operational commands and current results are in SquadBot `docs/respeaker-capture.md`. The SDK host gate is under `build/validation/phase06_2/`. Acquisition, shared perception, recording, replay, and fault handling close 06.2 independently of correction admission. Full sim-versus-real comparison remains 06.3.

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
