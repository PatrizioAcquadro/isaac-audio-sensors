# Implementation Plan 07 — Isaac Lab Observation Integration

Status: Planned after the scalar observed-perception contract and learning dataset boundary stabilize.

## Objective

Expose observed activity and direction to robot policies through fixed-shape Isaac Lab tensors without reintroducing scheduled-source truth, source-conditioned RMS, or hidden contextual direction choices. Preserve a scalable training path while retaining scalar waveform perception as the semantic reference.

Plan 07 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: the Lab migration replaces the source-conditioned contract directly and retains multiple execution paths only for distinct validated scale roles.

## Subphase 07.1 — Observation-to-Tensor Contract

#### Implementation

Adapt variable-length `AudioObservation` values into fixed-capacity tensors with explicit validity, optional-DOA, ambiguity, and truncation semantics. Start with one dominant observation per environment so the tensor contract reflects the maintained perception capability rather than pretending to support resolved multi-source audition.

Policy tensors derive only from observations. Truth events are available to rewards, curricula, and evaluation only through explicit privileged channels owned by the training task.

#### Key Decisions

- `max_observations = 1` is the initial practical contract.
- Padding and masks represent missing observations and missing DOA separately.
- Ground truth never appears in ordinary sensor observation tensors.
- Any privileged training input is named and configured explicitly outside the sensor observation.

#### Problems / Limitations

The existing Lab tensors are source-conditioned and include per-source RMS. They require a breaking semantic migration rather than a field rename.

## Subphase 07.2 — Reference and Scalable Paths

#### Implementation

Use scalar waveform perception as the reference path for semantic correctness. Maintain a CUDA-native scalable path only where it approximates the same observed contract and is required for thousands of environments. Geometry-derived or real-data-derived bounded distributions may substitute for expensive online waveform propagation, but they must not provide exact source truth as if it were sensed.

#### Key Decisions

- Reference parity compares observable meaning, not internal algorithms.
- A scalable approximation is acceptable when its limits and randomized inputs are explicit.
- CPU fallback does not establish the supported GPU training path.
- Geometry Acoustics is not required to run independently in every parallel environment.

#### Problems / Limitations

Mass-parallel feature synthesis may never reproduce the full waveform detector. The policy claim must distinguish feature-domain training from waveform-domain evaluation.

## Subphase 07.3 — Stateful Reset and Temporal Context

#### Implementation

Carry activity and DOA context per environment while preserving partial reset. Reset noise-floor estimates, rolling windows, and detector state only for selected environments. Keep update latency, device placement, and environment independence explicit.

#### Key Decisions

- Perception state follows Isaac Lab episode lifecycle.
- One environment cannot contaminate another environment's detector context.
- Temporal buffers remain on the intended device when the scalable implementation supports them.

#### Problems / Limitations

Stateful signal processing increases memory pressure at scale. Supported context length must balance policy value, latency, and GPU cost.

## Subphase 07.4 — Lab Migration and Cleanup

#### Implementation

Migrate maintained Isaac Lab tasks, adapters, configuration, data containers, reset handling, examples, and tests to the observed-only tensor contract. Then remove source-conditioned tensors, per-source RMS observation fields, scheduled-source bindings used only for sensing, obsolete configuration and registry entries, compatibility aliases, duplicate conversion kernels, fixtures, documentation, and dependencies without a remaining Lab role.

Retain scalar reference and CUDA-native scalable implementations only because they serve distinct correctness and mass-parallel roles. They must share one observable semantic contract and common validation where practical; any additional CPU, fallback, mock, or synthetic runtime path requires a supported deployment role rather than test convenience.

#### Key Decisions

- The old and new Lab observation contracts do not coexist after consumer migration.
- Reference and scalable paths may differ internally but cannot duplicate public meaning or drift semantically.
- A path survives only with a current task, validation, or deployment role.
- Test-only kernels, sensor modes, and runtime branches are not part of the maintained package.

#### Problems / Limitations

Downstream tasks may depend on privileged source information for rewards or curricula. Preserve that data only through explicitly privileged task-owned channels; it does not justify retaining the obsolete sensor observation path.

## Artifacts

Expected artifacts are an observed-only fixed tensor contract, scalar reference semantics, a justified scalable approximation with correct reset behavior, migrated consumers, and removal of the source-conditioned Lab sensor surface.

## Files

Exact Lab data, configuration, and adapter files are deferred to implementation. Current behavior is documented in [[topics/isaac-lab-integration|Isaac Lab Integration]].
