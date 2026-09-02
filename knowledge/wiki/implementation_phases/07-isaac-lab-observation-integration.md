# Implementation Plan 07 — Isaac Lab Observation Integration

Status: Planned after the scalar observed-perception contract and learning dataset boundary stabilize.

## Objective

Expose observed activity and direction to policies through fixed-shape Isaac Lab tensors without scheduled-source truth, source-conditioned RMS, or hidden direction choices. Preserve scale while keeping scalar waveform perception as the semantic reference.

Plan 07 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: the Lab migration directly replaces the source-conditioned contract and retains multiple execution paths only for distinct validated roles.

## Subphase 07.1 — Observation-to-Tensor Contract

#### Implementation

Adapt variable-length `AudioObservation` values into fixed-capacity tensors with explicit validity, optional-DOA, ambiguity, and truncation semantics. Start with `max_observations = 1` so the tensor reflects dominant-event perception rather than unsupported multi-source resolution.

Policy tensors derive only from observations. Truth may reach rewards, curricula, or evaluation only through explicit task-owned privileged channels.

#### Key Decisions

- Padding and masks distinguish absent observations from absent DOA.
- Ground truth never enters ordinary sensor observation tensors.
- Privileged training inputs are explicit and outside the sensor observation.

#### Problems / Limitations

Existing source-conditioned Lab tensors require a breaking semantic migration, not a field rename.

## Subphase 07.2 — Reference, Scalable, and Stateful Paths

#### Implementation

Use scalar waveform perception as the semantic reference. Maintain a CUDA-native scalable approximation only where thousands of environments require it, with explicit limits and randomized inputs. Geometry- or real-data-derived distributions may replace expensive online propagation but never appear as exact sensed truth.

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

Migrate maintained Lab consumers to the observed-only contract. Remove source-conditioned tensors, per-source sensing fields, obsolete bindings, duplicate conversions, compatibility paths, and their unused supporting surfaces. Retain scalar and CUDA-native paths only for their distinct correctness and scale roles.

#### Key Decisions

- Old and new Lab observation contracts do not coexist.
- Additional kernels, fallbacks, or sensor modes require a real deployment role, not test convenience.

#### Problems / Limitations

Keep privileged reward or curriculum data only in explicit task-owned channels.

## Artifacts

Expected artifacts are an observed-only tensor contract, scalar reference semantics, a justified scalable path with correct reset, migrated consumers, and removal of the source-conditioned sensor surface.

## Files

Exact Lab data, configuration, and adapter files are deferred to implementation. Current behavior is documented in [[topics/isaac-lab-integration|Isaac Lab Integration]].
