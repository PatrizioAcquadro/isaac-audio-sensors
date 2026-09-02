# Implementation Plan 09 — Practical Realism and Randomization

Status: Planned after the observed pipeline works across analytic, geometry, and physical signal producers.

## Objective

Improve the aspects of simulated audio that materially affect activity detection, DOA, and robot policy behavior while avoiding expensive physical detail that does not provide measurable application benefit.

Plan 09 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: realism increases only where evidence justifies its implementation, configuration, runtime cost, and maintenance burden.

## Subphase 09.1 — Task-Relevant Realism Model

#### Implementation

Define practical realism through observable downstream behavior rather than maximum acoustic complexity. Prioritize relative propagation, phase coherence, source-to-noise ratios, reverberation, occlusion and alternative paths, microphone mismatch, motion, clipping, timing, and detector stability because these directly influence the maintained perception outputs.

Keep structural vibration, complete wave-equation simulation, exact material twins, and other expensive phenomena outside scope unless evidence shows that they materially affect the target application.

#### Key Decisions

- Realism is judged by useful transfer and robustness, not feature count.
- Every added effect needs a concrete failure mode or measured downstream benefit.
- Unsupported physical truth remains explicit.
- High-fidelity geometry and scalable analytic training serve different purposes.

#### Problems / Limitations

The value of a simulated effect is task-dependent. A model useful for dominant speech direction may not be sufficient for machinery classification or active ultrasonics.

## Subphase 09.2 — Level, Noise, and Audibility Distributions

#### Implementation

Model bounded variation in source amplitude, source-to-source interference, distance, microphone gain mismatch, frequency response, self-noise, background noise, clipping, and received SNR. Derive useful ranges from geometry simulations and physical recordings where available instead of choosing convenient arbitrary constants.

Represent source emission and received audibility separately. Use private simulation evidence to label audibility without feeding it into perception.

#### Key Decisions

- Energy-detector evaluation requires meaningful level and noise variation.
- Asset amplitude is not treated as a calibrated source level.
- Randomization preserves plausible correlations rather than sampling every parameter independently.
- Impossible-to-observe truth is not a required positive detection target.

#### Problems / Limitations

Simulation-derived distributions remain simulation evidence until compared with physical recordings. Sparse real data limits the supported range.

## Subphase 09.3 — Geometry-to-Analytic Transfer

#### Implementation

Extract bounded, provider-versioned acoustic behavior from representative Geometry Acoustics scenarios and transfer only useful distributions into the scalable analytic or Isaac Lab paths. Candidate quantities include transmission, blocked-path fraction, direct-to-indirect ratio, dominant indirect delay and level, and changes caused by doors or dynamic occluders.

#### Key Decisions

- Transfer distributions and behavior, not provider internals or raw path traces.
- Geometry Acoustics remains the high-fidelity reference path.
- Analytic training does not claim exact geometry-provider equivalence.

#### Problems / Limitations

Transferred behavior applies only to the scenario family used to derive it and must not be presented as universal acoustic calibration.

## Subphase 09.4 — Realism Surface Consolidation and Cleanup

#### Implementation

After evaluating downstream value, retain only acoustic effects, randomization parameters, profiles, samplers, calibration inputs, and geometry-derived distributions that improve a supported detector, DOA, policy, or validation claim. Give each retained control one clear owner, unit, provenance, range, and consumer.

Remove effects with no measurable application benefit, redundant parameterizations, overlapping profile formats, arbitrary knobs, obsolete defaults, duplicate samplers, unused configuration, dependencies, assets, generated data, examples, tests, fixtures, and documentation. Do not keep expensive fidelity branches, hidden heuristics, or synthetic production shortcuts solely to increase feature count or satisfy isolated tests.

#### Key Decisions

- Practical realism optimizes downstream value per implementation, runtime, and maintenance cost.
- One canonical representation owns each retained physical or randomized quantity.
- Multiple fidelity profiles remain only for distinct validated operating regimes.
- Excluded effects stay documented as boundaries rather than partially implemented dormant code.

#### Problems / Limitations

Absence of measured benefit in a narrow dataset does not prove universal irrelevance. Remove unsupported production machinery while preserving concise evidence and reconsider the effect only when a concrete application supplies new requirements.

## Artifacts

Expected artifacts are a bounded realism profile, evidence-backed randomization ranges, documented exclusions tied to downstream relevance, and removal of realism surfaces without demonstrated value.

## Files

Exact configuration and profile formats are deferred to implementation.
