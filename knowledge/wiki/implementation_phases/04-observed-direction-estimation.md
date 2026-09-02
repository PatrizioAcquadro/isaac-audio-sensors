# Implementation Plan 04 — Observed Direction Estimation

Status: Planned after generic activity detection.

## Objective

Estimate direction from the final multichannel mixture only when acoustic activity is present. Preserve physically honest ambiguity and invalidity while making the dominant-source case useful for live robots and learning datasets.

Plan 04 applies the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision through explicit estimator qualification, role separation, consumer migration, and removal.

## Subphase 04.1 — Mixture-Only DOA Boundary

#### Implementation

Run every maintained DOA estimator through the existing array-local geometry and an observed `[microphone, sample]` signal. Remove private per-source stems, scene source count, true positions, and scheduled identities from estimator inputs.

Bind microphone geometry explicitly and preserve current bearing, elevation, candidate, and ambiguity meaning. `DoaEstimate` remains a reusable result and is optional on `AudioObservation` when localization is not attempted.

#### Key Decisions

- The initial problem is dominant-source localization, not blind source separation.
- The estimator never receives the true number of active sources.
- Geometry-derived ambiguity is preserved instead of resolved with hidden contextual priors.
- An invalid or low-information signal does not produce a fabricated direction.

#### Problems / Limitations

Mixtures, reverberation, low SNR, spatial aliasing, clipping, and moving sources can destabilize estimates even when array geometry is sufficient.

## Subphase 04.2 — Pyroomacoustics DOA Qualification

#### Implementation

Qualify `pyroomacoustics.doa.SRP` as the primary external SRP-PHAT candidate for waveform perception. Compare it with the maintained least-squares and internal SRP paths using the same mixture-only scenarios. Consider NormMUSIC only as an evidence-backed alternative, not as an automatic permanent option.

Evaluate angular accuracy, ambiguity behavior, frequency-band sensitivity, 2D and 3D support, latency, CPU cost, rolling-STFT requirements, coordinate adaptation, deterministic behavior, and packaging. Retain only implementations with a distinct supported operating role.

#### Key Decisions

- Prefer a proven external implementation when it improves accuracy or maintenance without violating the contract.
- Keep a lightweight baseline only when it provides a concrete dependency, interpretability, or scaling benefit.
- Avoid two permanent SRP implementations serving the same profile without evidence.
- The geometry provider and the DOA provider remain independently replaceable.

#### Problems / Limitations

Using PyRoom for both some simulated rooms and DOA evaluation can create overly correlated validation. Final selection must include independent simulated conditions and real multichannel audio.

## Subphase 04.3 — Temporal Context and Confidence

#### Implementation

Allow the perception pipeline to maintain a bounded rolling signal or STFT context across sensor updates. Record the observation time separately from algorithmic availability latency so downstream control and replay remain temporally honest.

Define confidence from observable estimator evidence. Peak prominence, geometric observability, and signal quality may contribute, but values from different estimators are not treated as interchangeable until calibrated.

#### Key Decisions

- Stateful context is allowed; hidden future look-ahead is not allowed in live mode.
- Estimator identity and confidence semantics remain recoverable.
- Low activity or invalid channels can suppress DOA without suppressing the underlying activity observation.

#### Problems / Limitations

Longer context improves stability but increases latency and can smear fast motion. The supported operating point must be chosen from application evidence rather than maximum offline accuracy alone.

## Subphase 04.4 — Estimator Consolidation and Removal

#### Implementation

After qualification, select one primary DOA estimator and remove non-selected or duplicate algorithms with their unused supporting surfaces. Retain a lightweight baseline only for a distinct necessary role. `DoaEstimate` remains the estimator-independent result contract.

#### Key Decisions

- Keep one implementation per supported DOA role.
- Tests and historical convenience do not justify a duplicate estimator.

#### Problems / Limitations

Verify any claimed scale or dependency distinction before retaining another estimator.

## Artifacts

Expected artifacts are a mixture-only DOA path, one selected waveform estimator plus any justified distinct baseline, explicit latency, ambiguity, and confidence semantics, and removal of redundant estimator surfaces.

## Files

Exact implementation and comparison artifacts are deferred to the implementation agent.
