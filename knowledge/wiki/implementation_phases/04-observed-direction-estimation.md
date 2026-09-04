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

`PyroomacousticsSrpEstimator` is the primary general-purpose planar estimator for arrays with at least three non-collinear microphones. It remains a public, lazy optional plugin under registry ID `pyroomacoustics_srp`, keeps the 04.1 signature unchanged, and performs a stateless Hann-windowed STFT over only the supplied mixture block. Its qualified settings are a causal 250 ms block, 512-point FFT, 256-sample hop, observed-energy bin selection within 300–6000 Hz, a 2-degree azimuth grid, and estimator-local minimum reliability `0.06`. PyRoom remains constrained to `>=0.10.1,<0.11`; importing Core or the plugin surface does not import it.

The corrected `ias.doa.phase_04_2_qualification.v2` runner qualifies roles independently rather than ranking estimators. PyRoom alone owns the primary planar, robustness, planar-compute, and informational 3D evaluations. `tdoa_least_squares` is qualified separately for the physically distinct two-microphone role. Internal `srp_phat` and NormMUSIC are absent from all qualification gates; internal SRP remains present only until the planned 04.3 cleanup. Exact `pass`, `fail`, and `blocked` states distinguish observed gate violations from absent dependencies or insufficient evidence.

The real evaluation replays each of the 35 hash-verified ReSpeaker takes from its start as sequential, non-overlapping 250 ms blocks through `AuditokActivityDetector -> AudioPerceptionPipeline -> PyRoom SRP`. Active takes are scored only inside their canonically hash-verified authorized reference interval, while complete official silence takes are scored. Eleven calibration takes select the highest eligible 0.5 dB Auditok grid point and the lowest eligible 0.01 PyRoom reliability grid point; the resulting values are `-40.5 dBFS` and `0.06`. Twenty-four other takes remain held out. The report records per-take activity and resolved coverage, abstention, bearing median/p95/max, and per-take compute latency in the non-semantic performance section. No source audio or report is written into `evidence/`.

Primary planar PyRoom passes: synthetic resolved coverage is 100% with 1-degree p95; every frequency-band p95 is at most 1.45 degrees; every held-out nominal take has 100% resolved coverage with worst-take p95 10 degrees; held-out silence produces zero selected bearings; and replay is deterministic. The separate two-microphone role passes exact zero/intermediate/endpoint semantics, 95.83% synthetic candidate containment, and 7.48-degree candidate-error p95. Energetic identical channels now proceed through GCC-PHAT, so zero TDOA exposes the physical `(0, 180)` candidate pair without a selected bearing, sector, or confidence; silence remains `low_information`.

Robustness fails only its own role. Synthetic low-SNR, reflection, interference, clipping, and noise cases miss the 90% coverage gate, while resolved-error p95 remains below 9 degrees. Representative real noise takes pass, but occlusion reaches 178.3-degree worst-take p95 and 80% minimum take coverage, and low-level behavior reaches only 85% minimum take coverage. Planar composed compute passes 200 measured calls after 20 warmups: the two report runs record p95 5.25 ms and 5.23 ms, with maxima below 5.38 ms, separately from the 250 ms observation interval. End-to-end rolling 20 Hz integration remains blocked until 04.3. Optional 3D remains blocked because only 12 synthetic diagnostics exist; no representative real or realtime 3D evidence supports a product claim.

`bearing_confidence` remains explicitly estimator-local reliability, not a probability or cross-estimator comparable score. Below-threshold, insufficient-context, unsupported-geometry, and unobservable-azimuth outcomes remain explicit unresolved estimates when the input is structurally valid. Malformed arrays and non-finite input still fail. The Phase 04.1 interface, `DoaEstimate`, frame v3, registry IDs, mixture-only inputs, causal behavior, ambiguity fields, configuration, and consumer defaults remain unchanged.

#### Key Decisions

- PyRoom SRP passes the primary planar role independently; consumer selection and integration remain 04.3 work.
- Least-squares passes only the separate two-microphone ambiguity role; it is not a general planar competitor.
- The estimator is stateless. A later consumer must supply the selected causal 250 ms window without future look-ahead.
- Internal SRP has no qualification role and remains only until 04.3 removal.
- NormMUSIC is neither evaluated nor added.
- A robustness failure and optional 3D blocker do not invalidate the passed primary planar or two-microphone roles.
- Geometry and DOA providers remain independently replaceable.

#### Problems / Limitations

The selected 250 ms observation context can smear fast source or robot motion even though measured composed compute remains below 6 ms. Robustness is not qualified, specifically under low SNR, occlusion, and low-level coverage. Real placement has a ±5-degree tolerance and microphone centers are nominal rather than measured, so the real figures do not establish sub-degree physical accuracy. NSMRL-specific two-microphone hardware behavior and representative real/realtime 3D behavior remain blocked. The ignored local reports are reproducible evidence, not distributed benchmark fixtures.

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

Subphase 04.1 produced the exact mixture-only estimator boundary. Subphase 04.2 adds lazy PyRoom SRP, estimator-local reliability and abstention semantics, the corrected role-based qualification runner, and ignored v2 JSON reports under `build/qualification/doa/`. The retained v1 `phase-04.2-final-a.json` and `phase-04.2-final-b.json` reports are superseded historical evidence; their comparative conclusions are not current qualification authority. Subphase 04.3 must select and integrate the primary estimator and remove internal SRP while preserving any verified distinct two-microphone need.

## Files

- `src/isaac_audio_sensors/core/plugins/pyroomacoustics.py`
- `src/isaac_audio_sensors/core/plugins/adapters.py`
- `tools/qualification/doa/phase_04_2.py`
- `tests/unit/test_doa_qualification.py`

## Version Notes

- 2026-09-04: Completed the mixture-only DOA boundary without selecting an estimator, changing serialized contracts, or integrating DOA into maintained consumers.
- 2026-09-04: Qualified PyRoom SRP at a causal 250 ms observation context and estimator-local reliability threshold `0.034`; no maintained consumer or default estimator changed.
- 2026-09-04: Superseded the v1 comparative conclusion with role-based v2 evidence, recalibrated PyRoom reliability to `0.06`, qualified its primary planar and compute roles, qualified least-squares two-microphone ambiguity, isolated the robustness failure, and kept optional 3D blocked.
