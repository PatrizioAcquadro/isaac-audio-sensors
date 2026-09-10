# Implementation Plan 07 — Isaac Lab Observation Integration

Status: Subphase 07.1 implemented on 2026-09-08; 07.2 is complete within the baseline scope agreed on 2026-09-10; 07.3 remains unimplemented. The 2026-09-09 admission retained the maintained reference and suspended temporal research. The 2026-09-10 closeout treats 4096 environments as exploratory, characterizes practical smaller batches and defers component changes. General temporal reliability remains unqualified. Confidence and bounded live occlusion are corrected. This supersedes the earlier general temporal prerequisite; the subsequent 07.2 causal-clock implementation is recorded below.

## Objective

Expose observed activity and direction to policies through fixed-shape Isaac Lab tensors without scheduled-source truth, source-conditioned RMS, or hidden direction choices. Preserve scale while keeping scalar waveform perception as the semantic reference.

Plan 07 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: the Lab migration directly replaces the source-conditioned contract and retains multiple execution paths only for distinct validated roles.

## Subphase 07.1 — Observation-to-Tensor Contract

#### Implementation

`AudioArraySensorData.from_observations()` converts ordered observation sequences into finite fixed-capacity tensors on the selected device. Explicit masks distinguish padding, absent scores, absent DOA, unresolved estimates, valid directions, and independent azimuth/elevation candidates. Observation and candidate truncation counts expose capacity loss without sorting or choosing an ambiguous direction. Defaults are one observation and two candidates; both capacities are configurable non-negative integers, not source-count assumptions. The exact fields and policy projection belong to [[topics/isaac-lab-integration|Isaac Lab Integration]].

The reference binding now projects actual scalar `simulate_frame()` observations instead of discarding them. Each environment keeps its own uncapped standard pipeline; only the Lab projection truncates. Reference windows align to the sample clock so ordinary float32 timestamp rounding does not repeatedly reset causal context. Allocation, selected writes, and partial reset cover every new field.

The maintained example requires an explicit reference threshold and exposes optional DOA. Its consumer uses masked fixed angle scaling, forwards all masks/counts, and applies no statistical normalization. The old six-tensor contract is directly replaced; per-event RMS and redundant sectors are absent, with no aliases. At the 07.1 closeout, the entity binding remained empty; 07.2 below replaces it. Core/recording schemas, package version, and lazy runtime imports are unchanged.

#### Key Decisions

- Observation-only projection excludes source truth, poses, identifiers, arbitrary diagnostics, and mixture RMS. Task-owned privileged channels remain separate.
- Masks define availability; padding is zero and all floating tensors are finite. Reliability is not reinterpreted as probability.
- Candidate directions are alternatives within one event, not simultaneous sources. Candidate elevation and bearing axes are independent.
- 07.1 initially projected one standard signal event. Subsequent [[implementation_phases/04-observed-direction-estimation|Subphase 04.4]] now supplies actual multisource events at 16 kHz and validates this tensor contract on the GPU.
- Only necessary consumer migration is completed here; scalable perception and remaining cleanup stay in 07.2–07.3.

#### Problems / Limitations

Fixed: reference perception was discarded, Lab direction padding contained NaN, and the tensor surface lacked score/DOA/candidate validity and truncation semantics. Fixed: sample-clock alignment prevents tiny float32 tick errors from masquerading as stream discontinuities.

**Completed correction before 07.2:** unavailable confidence now projects finite numeric padding with a false `bearing_confidence_mask`; a measured zero has a true mask. Direction and candidate masks remain independent. Frame-v4 recording/replay and actual CUDA projection pass the null/zero checks. The [[implementation_phases/02-signal-and-perception-architecture|observed contract]] owns the correction; general temporal reliability remains unqualified but is no longer a general prerequisite for beginning 07.2.

Resolved by 04.4: the common scalar localizer emits actual multiple events in its bounded direct-path role; GPU projection verifies them independently of slot capacity. Scalar waveform processing and packing remain host-side; CUDA validates tensor placement and sensor lifecycle, not a CUDA-native perception implementation. Arbitrary cadence, long-horizon timing, and scalable context remain 07.2 responsibilities. No learner, downstream task, or physical multisource campaign is validated here.

## Subphase 07.2 — Reference, Scalable, and Stateful Paths

#### Implementation

The scalar reference now consumes only elapsed audio with compensated float64 episode time and integer sample cursors. Time-zero and repeated reads do not process future or duplicate samples. Deferred reference reads consume intervening windows; reset clears only selected clocks, cursors, backend and perception state. The original 07.1 future-window behavior is corrected.

The entity binding now produces actual 16 kHz free-field microphone mixtures from explicit file sources and observed entity poses, then runs independent CUDA perception and unchanged observation projection. Acquisition follows physics updates even when policy reads are deferred. The producer alone owns source schedules, poses, polar gains and propagation; the detector/localizer accepts mixtures, microphone geometry and continuity only. Context is retained on the device, including the maintained 750 ms past window. Detector timing, unavailable confidence, event discovery, masks and capacity truncation retain their observable meaning. See [[topics/isaac-lab-integration|Isaac Lab Integration]] for configuration, file-loop semantics and lifecycle diagnostics.

The CUDA localizer reuses NARA-WPE primitives, Torch spectral/linear-algebra operations and the maintained WPE/group-sparse method. It does not introduce a learned surrogate, oracle observations, event smoothing, a source-count cap or a second acoustic research candidate. Geometry-only dictionaries are prepared once; runtime work is chunked across environments. Each environment has its own numerical floors and convergence state. This fixes the installed NARA Torch implementation's cross-batch floor dependence; exact reference grid-neighborhood boundaries are also preserved. The 2026-09-10 closeout additionally corrects CUDA bearings to Core's 0–360-degree convention and sorts by normalized bearing/elevation before truncation; the earlier signed-angle projection could retain a different event prefix despite equivalent physical directions.

#### Key Decisions

- Scalar waveform perception remains the semantic reference. The CUDA adaptation has a separate measured scale role and can be replaced behind the internal processing/reset boundary without redesigning policy tensors.
- Profile the whole path before simplifying. At 256 environments with one source, float64 WPE consumed about 456 ms of a 541 ms update. Float32 WPE reduced the complete update to 134 ms and peak allocation from about 3.44 GiB to 1.75 GiB, but was **rejected** after the randomized raised control exposed extra events. On the same 64 mixtures, count agreement fell to 78.125% and complete event sets to 79.6875%, versus 95.3125% for the reference. Restoring float64 restores count agreement to 100% and the reference's 95.3125% complete sets. Final WPE uses float64 on every geometry; spatial fitting retains the reference's float32 arithmetic. No geometry-specific precision switch is introduced.
- The paired stationary comparison covers 36 existing received-audio recordings / 1,440 updates across all four geometries and 0/1/2 speech/non-speech events. The controls measure activity, count, direction, misses, extras and response against the same scalar inputs. These controls preserve imperfect observations, not a new general-room qualification. The rejected float32 variant passed this bounded indoor subset; that success did not justify the wider numerical approximation. Final float64 validation has 100% count/activity agreement, with angular-difference p95 of 0.000015/0.000010/0.000174/0.000164 degrees for triangle/square/raised/tetrahedral. Reference/CUDA misses and extras are identical: 8/72, 1/8, 14/36 and 0/14 respectively.
- CUDA bulk data stays on the device; initialization prepares geometry/assets on the host. Small control synchronizations and chunk loops remain. There is no per-environment scalar perception loop or silent CPU fallback.
- The old 20 ms empty-entity budget is replaced by reporting complete active-perception cost; an explicit caller budget remains optional.
- The user clarified on 2026-09-10 that 4096 environments are an exploratory scale point, not a mandatory realtime requirement. Close 07.2 by characterizing practical smaller batches on the unchanged baseline. Moderate indoor reverberation remains a product objective; WPE, context, cadence and localizer comparisons are explicitly deferred.

#### Problems / Limitations

The CUDA producer currently supports free-field file sources at 16 kHz. Stationary fractional-delay PCM agrees with Core. Moving paths interpolate reception-time distance and polar gain between physics observations: this is a quasi-static approximation, not Core's retarded-source trajectory integration. A physics interval above 100 ms explicitly drops unavailable pose history, clears acoustic context and reports a discontinuity rather than fabricating past samples. Ordinary smaller physics steps and deferred policy reads remain supported.

The four-geometry comparison validates CUDA perception on supplied indoor mixtures; it does not implement or qualify a CUDA indoor propagation model. Stereo and other rates remain scalar-reference roles. Weak-speech misses, extra events and roughly 1–1.5 s responses remain reference limitations; no general temporal, physical, downstream learner or sim-to-real qualification is added. GUI migration belongs to 07.3, and geometry/realism remain Phases 08–09.

#### Validation and Scale

Actual RTX 4090, active free-field mixtures from two independent file sources, seed-72 randomized azimuth/range, 100 ms simulated audio periods, 20 uninstrumented updates per planar batch after warm-up:

| Environments | Mean update (ms) | p95 (ms) | Peak Torch allocation (GiB) | Simulated / wall time | Complete nominal sets within 20 degrees |
| --- | --- | --- | --- | --- | --- |
| 256 | 465.1 | 466.4 | 3.44 | 0.2150 | 100.00% |
| 1024 | 1854.7 | 1857.7 | 3.62 | 0.0539 | 100.00% |
| 4096 | 6644.3 | 6654.3 | 4.35 | 0.0151 | 99.95% |

Repository checks pass 645 unit/contract, 338 integration, 58 release and 139 supported-runtime Isaac tests. The source distribution builds a wheel whose 167 Python modules exactly match current source; version sync, Ruff, whitespace and wiki boundary checks pass. Local reports are under `build/validation/phase07_2/`: `indoor-parity-final.json`, `double-256.json`, `double-1024.json`, `double-4096.json`, `double-raised-4096.json` and runtime/host logs. These regenerable run artifacts remain Git-ignored.

Every run also checks deferred reads, finite observation masks, causal warm-up and partial reset. Peak allocation includes the live smoke's other resident sensors; it is Torch allocation, not total driver-reserved VRAM. The 4096 result has two extra-event environments (4094 with two observations, two with three). Matched direction p95 is 1.17 degrees. This is a steady-state throughput measurement with stationary randomized geometry; startup, arbitrary motion and physical acoustics are separate claims.

A separate raised-array run uses five microphones, 642 spherical search directions and randomized elevations in [-30, 30] degrees. At 4096 environments, five uninstrumented updates average **12,979.3 ms**, p95 **12,986.9 ms** (the maximum of this short sample), peak Torch allocation **5.58 GiB**, and simulated/wall ratio **0.0077**. Complete nominal sets reach **96.48%**: 3952 environments have two observations and 144 have three; matched direction p95 is **5.60 degrees**. The fixed 95% nominal set gate passes without suppressing extra events. This does not establish uniform per-content 3D accuracy or qualify arbitrary dynamic scenes. The separate instrumented update spends about 6.17 s in transforms/WPE and 6.75 s in sparse fitting, so both dominate the 3D path.

An additional instrumented 256-environment update measures about 392.2 ms for transforms/WPE, 68.1 ms for sparse fitting, 3.0 ms for the detector, 3.8 ms for geometry, 0.8 ms for propagation, 0.7 ms for context-buffer operations, 1.8 ms for peaks and 0.3 ms for projection. Buffer ranges nest inside propagation and must not be added twice. These CUDA profiler durations are separate from uninstrumented wall timing. Initialization uploads reusable assets and dictionaries; steady-state PCM/context remain on CUDA. Scalar control synchronizations are included in wall time, but their individual transfer cost is not resolved by this runtime profiler.

The initial delivery left performance closure open because 4096 environments did not sustain realtime operation. The user clarified on 2026-09-10 that this was an exploratory measurement, not a mandatory closure gate. The measured limit remains valid: the planar 4096 workload takes about 66 wall seconds per simulated second. The float32 shortcut remains rejected.

#### Practical Baseline Closeout

The agreed closeout measures smaller batches without changing WPE, the 750 ms context, 16 kHz sample rate or 10 Hz observation cadence. Moderate indoor reverberation remains an intended domain; no component exclusion, shorter context, new backend, tracking study or policy training is introduced. This stage establishes practical audio cost, not the number of environments needed for a particular learner to succeed.

The small-batch workload uses 60 Hz acquisition (six calls per 100 ms observation update), two continuously active independent file sources, diversified fixed source poses, 30 synchronized uninstrumented updates after warm-up, and the actual RTX 4090. Robot dynamics, rendering, policy inference/optimization, setup and the separate scalar verification are outside these timings. The measured path includes microphone-mixture generation, context maintenance, detector, WPE, localization and observation projection. The free-field producer does not add room reverberation; the separate four-geometry indoor PCM qualification remains the evidence for indoor perception, not scalable room propagation.

Baseline verification compares the same final received PCM with the scalar localizer and preserves its false events. All reports retain nominal two-source quality separately. A diagnostic requiring a maximum difference of one degree failed on one 128-environment raised batch at 3.41 degrees, despite identical counts. That extra maximum-only diagnostic is not the established 07.2 paired criterion: the maintained baseline checks require count agreement of at least 97% and direction-difference p95 at most five degrees. The report exposes both p95 and maximum; the stricter diagnostic and its failed report remain local evidence. No localizer parameter was adjusted in response.



**Planar (four microphones)**

| Copies | Mean / p95 update (ms) | Peak Torch allocation (GiB) | Aggregate audio updates / wall second | Estimated wall minutes for 10 simulated minutes per copy |
| --- | --- | --- | --- | --- |
| 2 | 40.2 / 41.4 | 0.07 | 50 | 4.0 |
| 16 | 62.7 / 63.9 | 0.44 | 255 | 6.3 |
| 32 | 86.9 / 87.8 | 0.87 | 368 | 8.7 |
| 64 | 140.4 / 142.6 | 1.71 | 456 | 14.0 |
| 128 | 250.1 / 253.4 | 3.41 | 512 | 25.0 |
| 256 | 462.3 / 481.5 | 3.44 | 554 | 46.2 |

**Raised 3D (five microphones)**

| Copies | Mean / p95 update (ms) | Peak Torch allocation (GiB) | Aggregate audio updates / wall second | Estimated wall minutes for 10 simulated minutes per copy |
| --- | --- | --- | --- | --- |
| 2 | 42.4 / 44.0 | 0.17 | 47 | 4.2 |
| 16 | 90.9 / 99.1 | 0.64 | 176 | 9.1 |
| 32 | 142.6 / 144.4 | 1.18 | 224 | 14.3 |
| 64 | 252.6 / 253.7 | 2.25 | 253 | 25.3 |
| 128 | 471.7 / 475.9 | 4.39 | 271 | 47.2 |
| 256 | 935.6 / 965.3 | 4.43 | 274 | 93.6 |

The 64/128-copy planar measurements were repeated because their initial p95 values showed more variability while host checks were running; the table uses the repeat after those checks finished, with both reports retained. All batches preserve reference counts on their final PCM: 996/996 environment comparisons. The maximum direction differences are 0.254 degrees planar and 4.143 degrees raised. The 128/256-copy raised runs have p95 differences of 0.014/0.018 degrees; the isolated larger differences are not hidden by that statistic. Nominal raised complete-set fractions range from 92.19% to 100%, and the scalar reference reproduces the extra-event counts. No successful-detection or new room-qualification claim follows from throughput. Every accepted run verifies deferred reads, finite padding and partial reset; one-row reset costs 2.8–4.0 ms, measured separately without an episode-length assumption. Reset warm-up remains part of the sensor behavior.

**Practical starting points:** use 16 copies for short interactive development runs, and 128 copies as the first batch setting for collecting simulated experience. These are guidance for this audio workload, not changed SDK defaults. At 16 copies, audio-only p95 is about 64 ms planar and 99 ms raised; the latter leaves almost no realtime margin for additional robot/learning work. At 128 copies, aggregate throughput is about 92% of the 256-copy planar result and 99% of the raised result, while each copy advances almost twice as fast. Larger batches remain available but are not automatically a better practical choice.

The waiting-time column is an extrapolation from steady-state measurements, not a completed ten-minute simulation or training run. For example, 128 copies each advancing ten simulated minutes cost about 25 wall minutes planar or 47 minutes raised for audio alone. They represent 1280 aggregate simulated minutes; they do not establish independent learning samples, task success or a required training dataset size. At the same rates, 100,000 environment audio updates cost about 3.3/6.1 wall minutes. Robot physics, rendering and learning add cost and must be measured in their eventual task. Intermittent activity and episode resets may change the average.

Reproduce a selected batch with the maintained runtime, the existing isolated optional dependencies and the flags below (replace the layout/count to sweep the table):

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
PYTHONPATH=src:build/validation/phase06_1/runtime_deps:build/validation/continuity_runtime_deps \
"$HOME/IsaacLab/isaaclab.sh" -p tools/smoke/live_isaac_lab_audio_smoke.py \
  --perf-envs 128 --perf-layout raised --perf-steps 30 --perf-substeps 6 \
  --perf-reference-check --out build/validation/phase07_2/practical/recheck.json
```

Reports and the derived CSV/JSON table remain in ignored `build/validation/phase07_2/practical/`. The sensor's angle/order correction passes all 141 Isaac runtime tests; `make check` passes 645 unit/contract, 338 integration and 58 release tests. The unchanged paired indoor recordings remain the bounded indoor preservation evidence.

**Closure: 07.2 is complete within the scope agreed on 2026-09-10.** It supplies causal independent environment state, explicit audio content, mixture-only CUDA perception, the common observation contract, measured scale limits and practical baseline settings. Neither 4096-copy realtime operation nor a fast complete policy-training run is a closure requirement. Moderate indoor usefulness remains an objective with the documented reference limits. WPE removal, precision changes, context/cadence changes, alternative components and tracking research are deferred. The next implementation phase is 07.3 consumer/GUI migration; it does not erase these acoustic or performance limits.


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

07.1 delivers the observed-only tensor contract, scalar-reference projection, finite masked consumer, and updated contract/runtime tests. The live smoke records local evidence under `build/validation/isaac_audio_sensors/isaac_lab_live_smoke.json`. 04.4 subsequently supplies the qualified bounded multisource perceiver and its own GPU smoke; the scalable implementation and current measurements are recorded under 07.2.

The historical 07.1 validation passed 614 unit/contract, 282 integration, 58 release, and 116 supported-runtime Isaac tests, plus version synchronization, Ruff, and whitespace. The live RTX 4090 smoke passes independent scalar/reference tensor parity, activity and DOA warm-up, resolved direction, silence, and partial reset. Fifty updates across 4096 empty entity environments average 0.212 ms/step against the existing 20 ms budget. Runtime checks use the existing isolated Auditok 0.5.2 path without replacing Kit NumPy or installing dependencies. These results do not qualify multisource perception or a downstream learner.

## Files

Main implementation: `src/isaac_audio_sensors/lab/` (reference, entity PCM, CUDA perception and observation projection) and the maintained Lab example. Lifecycle/configuration, Isaac tests, and the existing live Lab smoke consume the same contract. See [[topics/isaac-lab-integration|Isaac Lab Integration]] for the public interface.

## Version Notes

- 2026-09-10: Close 07.2 within the agreed baseline scope after small-batch measurements; correct CUDA angle/order projection. Preserve moderate-indoor objectives and defer component studies.

- 2026-09-09: Deliver bounded 07.2 clocks, entity PCM and CUDA perception; reject float32 WPE after a raised-array regression. Active 4096-environment processing is verified, with realtime throughput still unmet.

- 2026-09-09: Reopened pre-07.2 joint temporal perception and correctness prerequisites; assigned observed GUI consolidation to 07.3. No runtime implementation changed.

- 2026-09-09: User admits 07.2 on the maintained verified reference and suspends temporal improvement research. General temporal reliability remains unqualified; preserve imperfect observations and avoid excessive localizer-specific optimization. No implementation started.
