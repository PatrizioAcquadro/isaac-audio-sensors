# Phase 06 — Simulated and Real Signal Parity

Status: 06.1–06.3 complete. Software parity passes and 25 physical takes have nominal free-field comparisons. Raw remains enabled; no correction or absolute physical calibration is admitted.

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

The 06.2 controlled comparison contains initial silence and two eight-second takes at each of eight azimuths. The operator confirmed the same bench setup, a MacBook Pro source at 0.60 m and z = −0.135 m, volume 56%, and approximately ±5° angular placement uncertainty. SSH verified source model, original reference WAV hash, volume, and the ReSpeaker USB identity. Both independent pipelines use identical native samples, nominal geometry, Auditok threshold −40.5 dBFS, maintained DOA, windows, and resets. Raw correlation verifies each common 3–7 s analysis interval inside the reference noise segment. Each branch records exactly 2,720 processed blocks; native PCM, frame metadata, and reset replay pass exact checks. All 17 physical captures complete without faults or digital clipping.

The 06.2 gain decisions use take aggregates, with no block treated as an independent trial. Admission requires at least 10% median absolute relative-level improvement, p95 worsening no greater than 0.05 dB, signed median no farther from zero, and supporting uncertainty across takes.

| Candidate | Raw → corrected median absolute residual | Current decision |
| --- | --- | --- |
| ch1 gain −1.6021 dB | 1.838 → 1.875 dB | Rejected: median residual worsens. |
| ch2 gain −1.2796 dB | 1.517 → 1.635 dB | Rejected: median, p95, and signed bias worsen. |
| ch3 gain −1.2136 dB | 1.734 → 1.410 dB | Inconclusive: 18.7% improvement, but the 95% take-bootstrap benefit interval is −0.387 to 1.214 dB. |

The existing functional mapping orientation is supported: all raw per-take median angular errors, including declared placement uncertainty, remain within half the 45° target spacing. Raw median errors range from 1° to 12°, with a median across takes of 3.5°. Raw and gain branches have identical take error summaries, 100% activity and resolved-DOA coverage in the declared source windows, and no abstention there; initial silence has no detected activity. Positive relative polarity is supported on all current takes and all historical groups; +1 changes no waveform. No gain is admitted for live use. At 06.2 closure, raw remained the default and the corrected branch was assessment-only; 06.3 retires that executable branch. The shipped nominal profile remains a contract example.

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

SquadBot now owns one `scripts.compare_audio_domains` command accepting recorded real sessions, the array configuration, the original source WAV, and assessment-owned take references. It verifies native PCM against every recorded block, reprocesses the recorded observations exactly, and records corresponding `AnalyticAcoustics` sessions in `free_field`. Both domains use declared positions, nominal unity gains, original WAV amplitude, and no added effects, normalization, or fitted corrections. Acquisition and campaign orchestration stay downstream. `MicrophoneSignalBlock`, frame v3, manifest v4, and calibration v1 are unchanged.

The recorder and comparator construct `AudioPerceptionPipeline` through one downstream factory: Auditok at −40.5 dBFS, `MaintainedDoaEstimator`, and 50 ms blocks. Every take and domain has independent state with corresponding resets. The ch0/ch1 views retain the actual ordered pair geometry and run independent pipelines without new acquisition. Recording/replay equality uses exact samples and the canonical serialized observation content, including perception diagnostics. Assessment angles and intervals never enter perception.

The original 17 captures and eight new captures yield 5,440 real windows and 5,440 recorded four-channel simulated windows. All native/sample, observation, simulation round-trip, and continuity checks pass. Every physical take is complete, with no stream fault or digital endpoint clipping. No acquisition needed repetition or exclusion. The eight new takes comprise 8-second ambient silence before and after the campaign and three 20-second takes at each of 0° and 90°. The operator confirmed each position at the same 0.60 m radius, −0.135 m height, 56% MacBook volume, and ±5° placement uncertainty.

Each source take plays a 15-second sequence derived from the original reference noise: one second of silence, a one-second nominal marker, another second of silence, then four two-second segments at 0, −3, −6, and −12 dB separated by one-second silences. Correlation on the original raw PCM establishes one common received reference origin across channels; every new source take aligns on all four channels. The simulated emission schedule subtracts only nominal center propagation time to align received reference origins. This does not measure physical emission latency or correct individual channel delays.

Reports contain per-take dBFS and relative channel levels, source-off noise, declared clipping/unknown clipping, validity and resets, activity, resolved DOA coverage, candidate errors, ambiguity, and abstention. Aggregates use takes, not consecutive blocks, as the unit of comparison. The nearest-rank p95 and full ranges are descriptive; at six takes the p95 is the observed maximum.

| Source analysis | Real take-median angular error: median / p95 [range] | Simulated: median / p95 [range] |
| --- | --- | --- |
| Original 16 source takes, eight azimuths | 3.5° / 12° [1–12°] | 0.5° / 1° [0–1°] |
| New six source takes, nominal segment | 2° / 2° [2–2°] | 0° / 0° [0–0°] |

The original source intervals have 100% activity and resolved DOA in both four-channel domains. New activity coverage equals resolved DOA coverage within the assessed source segments:

| New segment | Real coverage: median / p95 [take range] | Simulated coverage: median / p95 [take range] |
| --- | --- | --- |
| 0 dB | 100% / 100% [97.4–100%] | 98.7% / 100% [97.4–100%] |
| −3 dB | 97.4% / 100% [97.4–100%] | 0% / 0% [0–0%] |
| −6 dB | 25.6% / 38.5% [17.9–38.5%] | 0% / 0% [0–0%] |
| −12 dB | 0% / 0% [0–0%] | 0% / 0% [0–0%] |

Across the original source takes, median real-minus-simulated channel levels are +0.17, +2.04, +0.24, and +1.93 dB for ch0–ch3; the respective p95 values are +3.29, +4.29, +2.92, and +5.47 dB. The reports retain the signed ranges and relative-to-ch0 measurements. New before/after ambient levels have channel medians −48.37, −46.84, −48.49, and −47.28 dBFS; the corresponding p95 values are −48.19, −46.67, −48.34, and −47.11 dBFS. Both ambient takes have no detected activity. Nominal simulation has digital silence and therefore no finite noise dBFS; it does not model measured microphone self-noise.

The pair replay preserves ambiguity: the original source windows have no selected pair bearing, and median ambiguous coverage is 100% in both domains. New nominal segments likewise have no selected pair bearing; real median ambiguous coverage is 98.7%. Candidate errors and abstention remain separate from a resolved angular error. The public two-microphone example now executes the maintained estimator and shows its two candidates.

Host-monotonic timing stays in capture/comparison reports, outside sensor frames. It separates `process()`, delivered-block-to-frame response, and delivery intervals, excluding the first five blocks. In the six new source takes, processing medians range from 0.58 to 0.62 ms and processing p95 from 5.71 to 5.90 ms. There are zero processing overruns among all 2,680 post-initialization blocks, including ambient captures; the largest processing duration is 12.66 ms against the 50 ms period. Source-take delivery-to-frame p95 ranges from 5.84 to 6.10 ms; delivery-interval p95 ranges from 50.13 to 50.18 ms. Offline processing measurements remain explicitly separate from live delivery.

Relative to the aligned received reference, nominal-segment activity onset has real median/p95 96/108 ms [73–108 ms] and simulated 100/123 ms [90–123 ms]. These are sample-timeline responses with 50 ms frame resolution, not acoustic latency. The real activity-offset p95 reaches 500 ms; source-off intervals can include continued activity and elevated ambient energy. Arbitrary historical analysis-window boundaries produce no onset/offset measurement. At weaker levels, intermittent or absent detection remains explicit rather than becoming a fixed latency estimate.

SDK equivalence tests cover mono/8 kHz, stereo/16 kHz, and four-microphone planar arrays at 16 and 48 kHz, including identical-sample producers, recording/replay, known and unknown clipping, discontinuities, invalid channels, and reset recovery. `make check` passes 614 unit/contract, 282 integration, and 58 release tests; optional audio passes with PyRoom 0.10.1, SciPy 1.18.1, and SoundFile 0.14.0. The downstream suite passes 410 tests, including local UDP checks outside the sandbox. DSP/Core uses its supported CPU path; no Isaac consumer changed and no new GPU qualification is claimed.

Cleanup retires the completed S4.5 gain adapter, assessment command, recorder correction argument, and campaign-only tests. Reusable comparison metrics and necessary SSH, PCM, fault, and replay checks remain. The historical corrected-branch evidence described in 06.2 is preserved, but its executable campaign path is no longer maintained. [[implementation_phases/09-practical-realism-and-randomization|Plan 09]] receives priorities from these measured differences; its realism implementation remains planned.

#### Key Decisions

- Real recordings are required for transfer claims.
- Shared behavior has one owner and one downstream perception path.
- Producer-specific code and dependencies require a supported role.
- Software acceptance requires exact controlled equivalence. Physical acceptance requires valid acquisitions and verifiable differences, not numerical equality between reality and nominal simulation.
- Raw amplitude and geometry remain unchanged; no gain, threshold, timing, or angle is fitted to improve the comparison.

#### Problems / Limitations

Physical claims remain bounded to this bench and campaign. ±5° placement uncertainty and nominal microphone centers limit interpretation of angular differences; the new 2° result does not establish a 2° accuracy specification. Received levels mix source directivity, room paths, ambient sound, and device response. They do not isolate microphone sensitivity or calibrate source SPL. Quiet ambient recording does not isolate self-noise; source-off energy does not by itself identify reverberation or detector delay.

Positive clipping remains verified deterministically because none occurred physically. Analog saturation, absolute acoustic/transport latency, measured clock drift, and calibrated SPL remain unknown. Correlation alignment is a common time origin, not measured clock synchronization. Timing p95 supports this host pipeline under the observed workload, not a hard real-time or transport guarantee. Pair ambiguity is retained evidence; no contextual direction selection is added. More detailed acoustics or corrections require new evidence of useful benefit.

## Artifacts

06.1 delivers the common runtime contract, one shared continuity owner, migrated consumers, and maintained validation tests. Local ignored evidence is under `build/validation/phase06_1/` (host, optional-audio/schema, and runtime logs) and `build/validation/isaac_audio_sensors/` (live smoke JSON and media). No physical recording or transfer evidence is produced.

06.2 evidence is downstream under `outputs/phase06_2/`: local/SSH raw smokes, `recovered_fit/`, the two S4.5 audit reports, `reference_campaign/`, `paired_assessment/`, sample/metadata/reset verification, and `orientation_review.json`. Operational commands and current results are in SquadBot `docs/respeaker-capture.md`. The SDK host gate is under `build/validation/phase06_2/`. Acquisition, shared perception, recording, replay, and fault handling close 06.2 independently of correction admission.

06.3 evidence is downstream under `outputs/phase06_3/`: `reference_campaign/` retains the stimulus, protocol, eight original captures, playback/alignment reports, and take references; `existing_comparison_final/` and `targeted_comparison/` retain the authoritative JSON reports and simulated sessions. `summary.md` links the results and validation logs. The earlier `existing_comparison/` report is superseded because historical analysis boundaries are not source onsets. SDK gate logs are under `build/validation/phase06_3/`. All acquisition and generated evidence stays ignored; protected historical/raw material remains unchanged.

## Files

Main 06.1 implementation files:

- `src/isaac_audio_sensors/core/types/_signal.py` — common signal declarations and validation.
- `src/isaac_audio_sensors/core/perception.py` — binding, common continuity, and frame diagnostics.
- `src/isaac_audio_sensors/core/backends/_analytic/block.py` — analytic signal projection.
- `src/isaac_audio_sensors/core/effects/electronics.py` — exact-window clipping evidence.
- `src/isaac_audio_sensors/isaac/sensor.py` — lifecycle integration without duplicate stream validation.
- `tools/smoke/live_omniverse_extension_ux.py` — contiguous activity and paused-snapshot runtime checks.

ReSpeaker-specific files remain downstream.

Main 06.3 SDK files are `tests/integration/test_signal_domain_parity.py`, `tests/contract/test_simulation.py`, and `examples/core/two_mic_ambiguity.py`. The downstream comparator and capture timing do not add a device-specific SDK surface.

Existing reference material:

- `examples/calibration/respeaker_xvf3800_nominal.v1.json` — nominal contract example only.
- `../squadbot-av-phase1/implementation_phases/phase_6c/evidence/2026-07-28-operational-points-6-7.md` — local downstream ReSpeaker acquisition evidence; no dependency on SquadBot is introduced.
