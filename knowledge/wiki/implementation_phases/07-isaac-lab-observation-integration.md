# Implementation Plan 07 — Isaac Lab Observation Integration

Status: Subphase 07.1 implemented on 2026-09-08. Subphases 07.2–07.3 remain planned. On 2026-09-09 the user reopened joint temporal count/direction improvement and placed it, confidence availability and live occlusion correctness before 07.2. This supersedes the earlier permission to proceed while motion research was paused. The bounded 04.4 reference remains implemented; the renewed prerequisite is not yet satisfied.

## Objective

Expose observed activity and direction to policies through fixed-shape Isaac Lab tensors without scheduled-source truth, source-conditioned RMS, or hidden direction choices. Preserve scale while keeping scalar waveform perception as the semantic reference.

Plan 07 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: the Lab migration directly replaces the source-conditioned contract and retains multiple execution paths only for distinct validated roles.

## Subphase 07.1 — Observation-to-Tensor Contract

#### Implementation

`AudioArraySensorData.from_observations()` converts ordered observation sequences into finite fixed-capacity tensors on the selected device. Explicit masks distinguish padding, absent scores, absent DOA, unresolved estimates, valid directions, and independent azimuth/elevation candidates. Observation and candidate truncation counts expose capacity loss without sorting or choosing an ambiguous direction. Defaults are one observation and two candidates; both capacities are configurable non-negative integers, not source-count assumptions. The exact fields and policy projection belong to [[topics/isaac-lab-integration|Isaac Lab Integration]].

The reference binding now projects actual scalar `simulate_frame()` observations instead of discarding them. Each environment keeps its own uncapped standard pipeline; only the Lab projection truncates. Reference windows align to the sample clock so ordinary float32 timestamp rounding does not repeatedly reset causal context. Allocation, selected writes, and partial reset cover every new field.

The maintained example requires an explicit reference threshold and exposes optional DOA. Its consumer uses masked fixed angle scaling, forwards all masks/counts, and applies no statistical normalization. The old six-tensor contract is directly replaced; per-event RMS and redundant sectors are absent, with no aliases. The entity binding remains empty pending 07.2. Core/recording schemas, package version, and lazy runtime imports are unchanged.

#### Key Decisions

- Observation-only projection excludes source truth, poses, identifiers, arbitrary diagnostics, and mixture RMS. Task-owned privileged channels remain separate.
- Masks define availability; padding is zero and all floating tensors are finite. Reliability is not reinterpreted as probability.
- Candidate directions are alternatives within one event, not simultaneous sources. Candidate elevation and bearing axes are independent.
- 07.1 initially projected one standard signal event. Subsequent [[implementation_phases/04-observed-direction-estimation|Subphase 04.4]] now supplies actual multisource events at 16 kHz and validates this tensor contract on the GPU.
- Only necessary consumer migration is completed here; scalable perception and remaining cleanup stay in 07.2–07.3.

#### Problems / Limitations

Fixed: reference perception was discarded, Lab direction padding contained NaN, and the tensor surface lacked score/DOA/candidate validity and truncation semantics. Fixed: sample-clock alignment prevents tiny float32 tick errors from masquerading as stream discontinuities.

**Completed correction before 07.2:** unavailable confidence now projects finite numeric padding with a false `bearing_confidence_mask`; a measured zero has a true mask. Direction and candidate masks remain independent. Frame-v4 recording/replay and actual CUDA projection pass the null/zero checks. The [[implementation_phases/02-signal-and-perception-architecture|observed contract]] owns the correction; the temporal prerequisite remains unsatisfied.

Resolved by 04.4: the common scalar localizer emits actual multiple events in its bounded direct-path role; GPU projection verifies them independently of slot capacity. Scalar waveform processing and packing remain host-side; CUDA validates tensor placement and sensor lifecycle, not a CUDA-native perception implementation. Arbitrary cadence, long-horizon timing, and scalable context remain 07.2 responsibilities. No learner, downstream task, or physical multisource campaign is validated here.

## Subphase 07.2 — Reference, Scalable, and Stateful Paths

#### Implementation

First complete the renewed [[implementation_phases/04-observed-direction-estimation#Pre-07.2 Follow-up — Joint Count and Direction over Time|joint temporal perception work]]. The [[implementation_phases/02-signal-and-perception-architecture|confidence-availability correction]] and bounded [[implementation_phases/r8-analytic-acoustics-backend|live occlusion corrections]] are implemented and validated. No particular custom cardinality algorithm is prescribed. Preserve the resulting reference's remaining missed/spurious events, response delay and moving-direction limits; scalar parity is not evidence of accurate perception. Start from its explicitly supported sample rate and operating domain rather than assuming the old qualification covers a replacement. The existing reference remains bounded at 16 kHz until a change is actually qualified.

Use scalar waveform perception as the semantic reference. Maintain a CUDA-native scalable approximation only where thousands of environments require it, with explicit limits and randomized inputs. Geometry- or real-data-derived distributions may replace expensive online propagation but never appear as exact sensed truth. Phase 08 need not run in every environment, and full Phase 09 realism is not a prerequisite for this integration.

Carry detector and DOA context per environment with correct partial reset. Reset only selected environments, prevent cross-environment state leakage, keep latency explicit, and retain temporal buffers on the intended device.

#### Key Decisions

- Reference parity compares observable meaning, not internal algorithms.
- CPU fallback does not validate the supported GPU path.
- Geometry Acoustics need not run in every parallel environment.
- Stateful context follows episode lifecycle independently per environment.

#### Problems / Limitations

Feature-domain scale may not reproduce full waveform perception. Context length must balance policy value, memory, latency, and GPU cost.

## Subphase 07.3 — Lab Migration and Cleanup

#### Implementation

After 07.2, finish migration of maintained Lab consumers and remove obsolete bindings, duplicate conversions, compatibility paths, and unused supporting surfaces. The tensor contract and maintained example were already migrated in 07.1, including removal of per-event RMS and the old tensor fields. Retain scalar and CUDA-native paths only for their distinct correctness and scale roles.

Consolidate the shared observed GUI with this consumer migration. Represent all simultaneous events and distinguish them from alternative directions of one ambiguous event. Show current activity, warm-up, unavailable localization and capacity truncation separately from historical events. Make the active localization role, sample rate and context understandable: the current 48 kHz GUI default does not enable the maintained 16 kHz multisource role merely by increasing observation capacity. Preserve frame-age warnings and distinguish frame freshness from perceptual response delay. This GUI work is planned; the immediate confidence and unavailable-occlusion indications belong to the pre-07.2 corrections.

The present compass hides bearings when there is more than one observation, and hides ambiguous candidates when no primary bearing exists. Correct those presentations without inventing event identities or carrying stale directions as fresh observations. Keep the RMS of the complete microphone mixture separate from individual event estimates. Geometry-derived occlusion/path displays belong to 08.3, and optional realism controls belong to Phase 09.

#### Key Decisions

- Old and new Lab observation contracts do not coexist.
- Additional kernels, fallbacks, or sensor modes require a real deployment role, not test convenience.

#### Problems / Limitations

Keep privileged reward or curriculum data only in explicit task-owned channels.

## Artifacts

07.1 delivers the observed-only tensor contract, scalar-reference projection, finite masked consumer, and updated contract/runtime tests. The live smoke records local evidence under `build/validation/isaac_audio_sensors/isaac_lab_live_smoke.json`. 04.4 subsequently supplies the qualified bounded multisource perceiver and its own GPU smoke; the scalable path remains 07.2 work.

Validation passes 614 unit/contract, 282 integration, 58 release, and 116 supported-runtime Isaac tests, plus version synchronization, Ruff, and whitespace. The live RTX 4090 smoke passes independent scalar/reference tensor parity, activity and DOA warm-up, resolved direction, silence, and partial reset. Fifty updates across 4096 empty entity environments average 0.212 ms/step against the existing 20 ms budget. Runtime checks use the existing isolated Auditok 0.5.2 path without replacing Kit NumPy or installing dependencies. These results do not qualify multisource perception or a downstream learner.

## Files

Main implementation: `src/isaac_audio_sensors/lab/audio_array_sensor_data.py`, `src/isaac_audio_sensors/lab/reference_backend.py`, and the maintained Lab example. Lifecycle/configuration, Isaac tests, and the existing live Lab smoke consume the same contract. See [[topics/isaac-lab-integration|Isaac Lab Integration]] for the public interface.

## Version Notes

- 2026-09-09: Reopened pre-07.2 joint temporal perception and correctness prerequisites; assigned observed GUI consolidation to 07.3. No runtime implementation changed.
