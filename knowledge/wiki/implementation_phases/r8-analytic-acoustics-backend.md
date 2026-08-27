# Phase R8 — Analytic Acoustics Backend

## Objective

Implement one fast, deterministic `AnalyticAcoustics` backend over the [[implementation_phases/r7-acoustic-environment-contract|R7 Acoustic Environment Contract]]. It is the pure-Core path for tests, non-Isaac use, and large Isaac Lab workloads.

## Subphase R8.1 — Solver Routing

#### Implementation

Select the internal solver deterministically from validated environment topology. Explicit free field uses direct propagation, one floor uses a half-space model, a rectangular enclosure uses `pyroomacoustics.ShoeBox`, and a supported closed polygon uses the general PyRoom room construction. A small supported open surface set may use bounded direct and early-specular propagation.

The caller chooses the environment, not the solver. The selected solver is reported in diagnostics. Unsupported topology fails clearly and directs the caller to `GeometryAcoustics`; it is never silently approximated by an invented enclosure.

#### Key Decisions

- PyRoom remains the maintained provider for closed analytic rooms.
- Small project-owned formulas are limited to direct and bounded simple-surface propagation.
- The backend does not grow into an arbitrary-mesh acoustic engine.

#### Problems / Limitations

Open surface collections receive only explicitly supported bounded behavior. Complex topology, connected rooms, and robust around-corner propagation remain outside this backend.

## Subphase R8.2 — Relative Propagation and Occlusion

#### Implementation

Produce a separate phase-coherent received waveform for every microphone. Preserve relative timing, phase, distance loss, air absorption, material effects, channel relationships, and source/microphone directivity.

Keep direct and indirect propagation distinguishable so direct-path obstruction does not blindly attenuate all reflected energy. Occlusion remains per source and microphone and may depend on the hit object, acoustic material, frequency band, and multiple blocking surfaces. Obstacle loss is not multiplied by an arbitrary source-obstacle distance factor.

Absolute SPL is not a package default. Source power, microphone sensitivity, measured materials, and absolute calibration remain optional user-owned extensions with explicit provenance.

#### Key Decisions

- Physically coherent relative signals are the maintained public target.
- Nominal material fallback remains visible in diagnostics and is never presented as measured truth.
- Passive audible sources are the current scope; active acoustics is deferred to a separate future backend.

#### Problems / Limitations

Analytic surfaces cannot reproduce arbitrary objects, full scattering, general pathing, or diffraction. Those limitations are deliberate and handled by R10 rather than hidden.

## Subphase R8.3 — Isaac Lab Scale

#### Implementation

Use `AnalyticAcoustics` as the scalable path for mass-parallel Isaac Lab workloads. Geometry-backend results may later define bounded parameter distributions and domain randomization for the analytic model without making the high-fidelity geometry provider run in every environment.

#### Key Decisions

- Large-batch training and high-fidelity geometry simulation are separate operating paths.
- Geometry-derived parameterization is not absolute hardware or room calibration.

#### Problems / Limitations

The scalable analytic model approximates the distribution of geometry-aware behavior; it does not reproduce every advanced scene path per environment.

## Artifacts

This page is the R8 phase specification. No R8 implementation artifacts exist yet.

## Files

No source files are changed by this planning step.
