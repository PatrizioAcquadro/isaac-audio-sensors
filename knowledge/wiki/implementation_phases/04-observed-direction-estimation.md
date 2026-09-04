# Implementation Plan 04 — Observed Direction Estimation

Status: Subphases 04.1–04.2 complete on 2026-09-04. Subphase 04.3 is planned.

## Objective

Estimate direction from the final multichannel mixture only when activity is present. Preserve honest ambiguity and invalidity while making dominant-source localization useful for robots and learning datasets.

Plan 04 applies the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision through estimator qualification, selection, consumer migration, and removal.

## Subphase 04.1 — Mixture-Only DOA Boundary

#### Implementation

`DoaEstimator.estimate(samples, microphone_positions_m, sample_rate_hz)` is the exact public estimator boundary. `AudioPerceptionPipeline` accepts that protocol explicitly and passes only the final `MicrophoneSignalBlock` rows whose channels are valid, the corresponding array-local XYZ positions in the same order, and the block sample rate. The read-only sample matrix contains the combined microphone mixture after propagation, directivity, occlusion, gain, and enabled effects.

Scene snapshots, source count, source identity or position, schedules, private render stems, and producer diagnostics are absent from both the protocol and pipeline invocation. Private per-source state remains confined to signal producers. The two existing registry estimators, `tdoa_least_squares` and `srp_phat`, execute through this same mixture-only boundary; neither is selected for maintained consumers in 04.1.

`DoaEstimate` remains unchanged and reusable on `AudioObservation`. `None` means localization was not run, including inactive windows or fewer than two valid channels. A returned unresolved estimate preserves candidate and ambiguity evidence without inventing a selected bearing, elevation, sector, or confidence. Structurally invalid estimator returns fail explicitly.

#### Key Decisions

- The initial target is dominant-source localization, not source separation.
- The estimator never receives the true number of sources.
- Geometry ambiguity remains visible rather than being resolved by hidden priors.
- Invalid or low-information signals do not produce fabricated directions.

#### Problems / Limitations

Mixtures, reverberation, low SNR, aliasing, clipping, and motion can destabilize estimates even with sufficient array geometry. Subphase 04.1 establishes input and result boundaries only: it does not qualify an estimator, define a low-information threshold, compare confidence, add context, or integrate DOA into a default consumer. Those operating semantics remain 04.2 work.

## Subphase 04.2 — Estimator Qualification and Operating Semantics

#### Implementation

`PyroomacousticsSrpEstimator` is a public, lazy optional plugin candidate under registry ID `pyroomacoustics_srp`. It keeps the 04.1 signature unchanged and performs a stateless Hann-windowed STFT over only the supplied mixture block. Its qualified settings are a 512-point FFT, 256-sample hop, observed-energy bin selection within 300–6000 Hz, a 2-degree azimuth grid, a 5-degree elevation grid for rank-3 arrays, and estimator-local minimum reliability `0.034`. PyRoom is constrained to the qualified `>=0.10.1,<0.11` minor line; importing Core or the plugin surface still does not import PyRoom.

The qualification runner compares PyRoom SRP, internal SRP, and GCC-PHAT least-squares on 689 cases per estimator. Independent NumPy plane-wave mixtures cover planar and rank-3 geometry, four frequency bands, four SNRs, direct sound, early reflection, interference, clipping, silence, incoherent noise, common-mode ambiguity, and invalid channels. Real validation uses the 24 nominal, four noise/occlusion, four low-level, and three silence ReSpeaker takes from the opened S4 recovery evidence. All 35 selected WAV hashes are verified against their official producer records; one silence take calibrates the low-information threshold and two independent silence takes remain held out. No audio or report is written into `evidence/`.

The evidence selects the shortest acceptable context at 250 ms. PyRoom achieves 97.98% held-out active coverage, 6-degree overall bearing p95, 3-degree synthetic-planar p95, 6-degree real-nominal p95 with 2-degree median, and zero held-out null emissions. The limited rank-3 cells at that context have 0-degree p95 on the 2/5-degree grid. Two complete runs produce identical semantic results; four-channel availability-latency p95 is 5.06 ms and 5.00 ms, below the 50 ms live period. Observation interval and post-window compute latency are recorded separately.

`bearing_confidence` is now explicitly an estimator-local reliability ordering, not a probability or a cross-estimator comparable score. PyRoom combines normalized coherent excess with grid contrast; least-squares combines residual confidence with GCC peak strength; internal SRP retains its existing noise-aware score. Below-threshold, insufficient-context, unsupported-geometry, and unobservable-azimuth outcomes remain explicit unresolved estimates when the input is structurally valid. Malformed arrays and non-finite input still fail.

#### Key Decisions

- PyRoom SRP passes qualification as the primary external candidate; selection and consumer integration remain 04.3 work.
- The estimator is stateless. A later consumer must supply the selected causal 250 ms window without future look-ahead.
- Internal SRP and least-squares remain measured baselines but do not satisfy the complete threshold, coverage, held-out-null, and context gate.
- NormMUSIC is not evaluated because PyRoom SRP passes every essential gate.
- Geometry and DOA providers remain independently replaceable.

#### Problems / Limitations

The selected 250 ms observation context can smear fast source or robot motion even though compute availability remains below 6 ms. The 300–800 Hz synthetic band reaches 11-degree p95, and 800–2000 Hz coverage is 87.5%; these frequency limits remain visible instead of being hidden by the aggregate result. Real placement has a ±5-degree tolerance and the microphone centers are nominal rather than measured, so the real figures validate robustness and repeatability rather than sub-degree physical accuracy. The ignored local report is reproducible evidence, not a distributed benchmark fixture.

## Subphase 04.3 — Selection, Integration, and Cleanup

#### Implementation

Integrate one primary estimator into the perception pipeline and retain a lightweight baseline only for a distinct necessary role such as dependency-free diagnostics or mass-parallel execution. Keep estimator identity, confidence meaning, and latency recoverable.

Remove non-selected or duplicate algorithms and their unused configuration, registry, adapter, dependency, test, example, and documentation surfaces. Tests and historical convenience do not justify a duplicate estimator; shared geometry and ambiguity utilities remain only when still used.

#### Key Decisions

- Keep one implementation per supported DOA role.
- Every additional estimator requires a verified non-overlapping purpose and maintained consumer.
- `DoaEstimate` remains independent of the selected algorithm.

#### Problems / Limitations

Verify claimed scale or dependency distinctions before retaining another estimator.

## Artifacts

Subphase 04.1 produced the exact mixture-only estimator boundary. Subphase 04.2 adds the lazy PyRoom SRP candidate, estimator-local reliability and abstention semantics, a reproducible independent/real qualification runner, and ignored JSON reports under `build/qualification/doa/`. Subphase 04.3 must select and integrate one estimator and remove any baseline without a distinct maintained role.

## Files

- `src/isaac_audio_sensors/core/plugins/pyroomacoustics.py`
- `tools/qualification/doa/phase_04_2.py`
- `tests/unit/test_doa_qualification.py`

## Version Notes

- 2026-09-04: Completed the mixture-only DOA boundary without selecting an estimator, changing serialized contracts, or integrating DOA into maintained consumers.
- 2026-09-04: Qualified PyRoom SRP at a causal 250 ms observation context and estimator-local reliability threshold `0.034`; no maintained consumer or default estimator changed.
