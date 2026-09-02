# Implementation Plan 04 — Observed Direction Estimation

Status: Planned after generic activity detection.

## Objective

Estimate direction from the final multichannel mixture only when activity is present. Preserve honest ambiguity and invalidity while making dominant-source localization useful for robots and learning datasets.

Plan 04 applies the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision through estimator qualification, selection, consumer migration, and removal.

## Subphase 04.1 — Mixture-Only DOA Boundary

#### Implementation

Run every maintained estimator from observed `[microphone, sample]` signals and explicit array-local geometry. Remove private per-source stems, true source count or positions, and scheduled identities from estimator inputs.

Preserve bearing, elevation, candidate, and ambiguity meaning. `DoaEstimate` remains reusable and optional on `AudioObservation`: `None` means localization was not run, while an unresolved estimate records an attempted but non-unique or invalid result.

#### Key Decisions

- The initial target is dominant-source localization, not source separation.
- The estimator never receives the true number of sources.
- Geometry ambiguity remains visible rather than being resolved by hidden priors.
- Invalid or low-information signals do not produce fabricated directions.

#### Problems / Limitations

Mixtures, reverberation, low SNR, aliasing, clipping, and motion can destabilize estimates even with sufficient array geometry.

## Subphase 04.2 — Estimator Qualification and Operating Semantics

#### Implementation

Qualify `pyroomacoustics.doa.SRP` as the primary external SRP-PHAT candidate and compare it with maintained least-squares and internal SRP paths on the same mixture-only scenarios. Consider NormMUSIC only as an evidence-backed alternative.

Evaluate angular accuracy, ambiguity, frequency sensitivity, 2D/3D support, deterministic behavior, packaging, CPU cost, latency, and bounded rolling-signal or STFT context. Record observation time separately from availability latency. Define confidence only from observable estimator evidence and do not treat scores from different estimators as interchangeable before calibration.

Use independent simulated conditions and real multichannel audio so PyRoom is not evaluated only on PyRoom-generated rooms.

#### Key Decisions

- Prefer a proven external implementation when it improves accuracy or maintenance.
- Stateful context is allowed; hidden future look-ahead is not allowed live.
- Low activity or invalid channels may suppress DOA without suppressing activity.
- Geometry and DOA providers remain independently replaceable.

#### Problems / Limitations

Longer context may improve stability while increasing latency and smearing motion; select the operating point from application evidence.

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

Expected artifacts are a mixture-only DOA path, one selected waveform estimator plus any justified distinct baseline, explicit latency, ambiguity, and confidence semantics, and removal of redundant estimator surfaces.

## Files

Exact implementation and comparison artifacts are deferred to the implementation agent.
