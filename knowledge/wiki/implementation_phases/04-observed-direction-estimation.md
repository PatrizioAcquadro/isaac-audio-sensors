# Implementation Plan 04 — Observed Direction Estimation

Status: Planned after generic activity detection.

## Objective

Estimate direction from the final multichannel mixture only when acoustic activity is present. Preserve physically honest ambiguity and invalidity while making the dominant-source case useful for live robots and learning datasets.

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

After qualification, select one primary waveform DOA estimator and retain a lightweight baseline only when it has a distinct documented operating role and maintained consumer, such as dependency-free diagnostics or mass-parallel execution. Explicitly audit the existing least-squares, internal SRP-PHAT, PyRoom SRP, registry, configuration, adapter, and downstream consumer paths.

Delete every non-selected or behaviorally duplicate estimator together with its construction branches, registry values, configuration options, adapters, dedicated dependencies, tests, fixtures, examples, and documentation when no maintained role remains. Do not keep two implementations of the same SRP profile for historical convenience or test coverage alone. Shared geometry and ambiguity primitives may remain only when the selected implementation or another current consumer uses them.

`DoaEstimate` remains the estimator-independent result contract and is not tied to retaining any specific legacy algorithm. Tests must validate selected production estimators through their real public path; no estimator or runtime branch may exist only to make tests easier.

#### Key Decisions

- One primary implementation per supported DOA operating profile is the default.
- A baseline survives only with a concrete, non-overlapping product role and maintained consumer.
- Algorithm provenance remains visible without exposing redundant algorithms as permanent public surface.
- Removal includes configuration, registration, dependency, test, example, and documentation surfaces, not only the estimator module.

#### Problems / Limitations

An apparently duplicate estimator may serve a materially different scale or dependency boundary. Preserve it only after that difference is measured and documented; otherwise remove it after consumer migration.

## Artifacts

Expected artifacts are a mixture-only DOA path, one selected waveform estimator plus any justified distinct baseline, explicit latency, ambiguity, and confidence semantics, and removal of redundant estimator surfaces.

## Files

Exact implementation and comparison artifacts are deferred to the implementation agent.
