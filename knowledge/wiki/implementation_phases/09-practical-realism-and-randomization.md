# Implementation Plan 09 — Practical Realism and Randomization

Status: Planned after the observed pipeline works across analytic, geometry, and physical signal producers.

## Objective

Improve simulated audio only where it materially affects activity detection, DOA, or robot policy behavior, avoiding expensive detail without measurable application benefit.

Plan 09 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: realism increases only where evidence justifies implementation, runtime, and maintenance cost.

## Subphase 09.1 — Task-Relevant Realism Model

#### Implementation

Define realism through downstream behavior rather than maximum acoustic complexity. Prioritize relative propagation, phase coherence, SNR, reverberation, occlusion and alternative paths, microphone mismatch, motion, clipping, timing, and detector stability.

Build on the joint temporal count/direction work and correctness repairs requested before 07.2, the observed GUI consolidation in 07.3, and the geometry integration in Phase 08. Do not postpone those earlier correctness requirements to this phase or recreate a second occlusion model here. Evaluate what additional realism changes useful detection, localization or policy behavior in the completed producers.

Keep structural vibration, complete wave-equation simulation, exact material twins, and other expensive phenomena outside scope unless evidence shows material task value.

The completed [[implementation_phases/06-simulated-and-real-signal-parity|06.3 comparison]] supplies the first physical priorities. On one bench, the same fixed-threshold pipeline detects the −3 dB segment in nearly every real window and the −6 dB segment intermittently, while nominal free-field simulation detects neither. Strong-source DOA remains broadly consistent within declared placement limits, and measured processing p95 is below 6 ms for 50 ms blocks. Prioritize received level, ambient interference, and detector behavior near threshold before adding computationally expensive acoustics. These observations do not yet identify which physical contribution causes each difference.

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

Existing DSP already provides channel response, noise, clock variation, AGC, clipping and quantization capabilities. Their existence does not establish useful realistic parameter ranges or justify exposing every parameter in the GUI. Select coherent presets and controls only where they help users reproduce a supported condition. Keep dBFS distinct from calibrated sound pressure, mixture RMS distinct from per-event level, and estimated SNR distinct from privileged simulation ratios. Calibration data must not imply that a correction has been applied automatically.

Extract useful provider-versioned transmission, blocked-path, direct-to-indirect, indirect delay/level, door, and dynamic-occluder behavior from representative Geometry Acoustics scenarios. Transfer distributions, not provider internals or raw paths, into scalable analytic and Isaac Lab execution.

Use the 06.3 per-take level/noise and channel-relative reports to propose bounded, coherent source/receiver variation for a later validation campaign. Keep room/source effects separate from microphone sensitivity; the current data admits no gain correction. Preserve pair ambiguity and abstention when varying levels instead of forcing a unique bearing. The measured activity-offset tail motivates checking source-off interference and temporal behavior, but does not establish reverberation or absolute latency. No realism distribution is implemented or qualified by this documentation update.

#### Key Decisions

- Asset amplitude is not calibrated source level.
- Private truth may label audibility but never enter perception.
- Geometry Acoustics remains the high-fidelity reference; analytic training does not claim exact equivalence.

#### Problems / Limitations

Simulation evidence requires physical comparison, and transferred distributions apply only to the scenario family from which they were derived.

## Subphase 09.3 — Validation and Cleanup

#### Implementation

Validate each realism feature by its effect on a supported detector, DOA estimator, policy, or product claim. Retain only useful effects, parameters, profiles, and distributions; remove ineffective or redundant features, arbitrary knobs, overlapping formats, and their unused supporting surfaces. Do not keep expensive or test-only fidelity paths.

Consolidate the useful realism-facing GUI at the same time: active effect/preset state, signal level and clipping, available AGC/noise information, and explicit limits. Waveform and spectrogram previews already exist through exported sensor audio; consider direct live-buffer preview only if its value justifies the extra workflow. Preserve the distinction between sensor audio and the native Kit mix. Reuse existing RMS and freshness instruments rather than adding redundant displays, and do not color an event as unreliable merely because the received mixture is quiet.

#### Key Decisions

- Balance downstream value against implementation, runtime, and maintenance cost.
- Keep one clear representation per quantity and only distinct validated fidelity profiles.

#### Problems / Limitations

Preserve concise exclusion evidence so a concrete future requirement can justify reconsideration.

## Artifacts

Expected artifacts are a bounded realism profile, evidence-backed ranges, documented exclusions, and removal of realism surfaces without demonstrated value. Existing inputs are the 25-take comparison and recorded limitations in [[implementation_phases/06-simulated-and-real-signal-parity|Phase 06]]; all proposed transfer ranges remain future work.

## Files

Exact configuration and profile formats are deferred to implementation.
