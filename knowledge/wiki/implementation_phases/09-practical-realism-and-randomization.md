# Implementation Plan 09 — Practical Realism and Randomization

Status: Planned after the observed pipeline works across analytic, geometry, and physical signal producers.

## Objective

Improve simulated audio only where it materially affects activity detection, DOA, or robot policy behavior, avoiding expensive detail without measurable application benefit.

Plan 09 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: realism increases only where evidence justifies implementation, runtime, and maintenance cost.

## Subphase 09.1 — Task-Relevant Realism Model

#### Implementation

Define realism through downstream behavior rather than maximum acoustic complexity. Prioritize relative propagation, phase coherence, SNR, reverberation, occlusion and alternative paths, microphone mismatch, motion, clipping, timing, and detector stability.

Keep structural vibration, complete wave-equation simulation, exact material twins, and other expensive phenomena outside scope unless evidence shows material task value.

#### Key Decisions

- Realism is judged by useful transfer and robustness, not feature count.
- Every effect needs a concrete failure mode or measured downstream benefit.
- Unsupported physical truth remains explicit.
- High-fidelity geometry and scalable analytic training serve different roles.

#### Problems / Limitations

Realism requirements are task-dependent and do not automatically transfer from dominant-direction sensing to classification or active acoustics.

## Subphase 09.2 — Evidence-Backed Distributions and Transfer

#### Implementation

Model bounded variation in source levels and interference, distance, microphone gain and response, self-noise, background noise, clipping, and received SNR. Derive ranges from geometry simulation and physical recordings where available, preserve plausible correlations, and distinguish source emission from received audibility.

Extract useful provider-versioned transmission, blocked-path, direct-to-indirect, indirect delay/level, door, and dynamic-occluder behavior from representative Geometry Acoustics scenarios. Transfer distributions, not provider internals or raw paths, into scalable analytic and Isaac Lab execution.

#### Key Decisions

- Asset amplitude is not calibrated source level.
- Private truth may label audibility but never enter perception.
- Geometry Acoustics remains the high-fidelity reference; analytic training does not claim exact equivalence.

#### Problems / Limitations

Simulation evidence requires physical comparison, and transferred distributions apply only to the scenario family from which they were derived.

## Subphase 09.3 — Validation and Cleanup

#### Implementation

Validate each realism feature by its effect on a supported detector, DOA estimator, policy, or product claim. Retain only useful effects, parameters, profiles, and distributions; remove ineffective or redundant features, arbitrary knobs, overlapping formats, and their unused supporting surfaces. Do not keep expensive or test-only fidelity paths.

#### Key Decisions

- Balance downstream value against implementation, runtime, and maintenance cost.
- Keep one clear representation per quantity and only distinct validated fidelity profiles.

#### Problems / Limitations

Preserve concise exclusion evidence so a concrete future requirement can justify reconsideration.

## Artifacts

Expected artifacts are a bounded realism profile, evidence-backed ranges, documented exclusions, and removal of realism surfaces without demonstrated value.

## Files

Exact configuration and profile formats are deferred to implementation.
