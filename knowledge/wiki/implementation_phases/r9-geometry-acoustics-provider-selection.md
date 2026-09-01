# Phase R9 — Geometry Acoustics Provider Selection

## Objective

Select the existing acoustic engine that can satisfy the passive-audio requirements before building a maintained Isaac integration. This phase owns provider qualification and the final provider decision; R10 owns product integration.

## Subphase R9.1 — Required Provider Contract

#### Implementation

Require the provider to support:

- passive audible sources with arbitrary file-backed or generated content;
- separate phase-coherent raw output for every physical microphone;
- relevant scene geometry, materials, static objects, and dynamic objects;
- direct occlusion, reflections, transmission, indirect pathing, and approximate around-edge or around-corner propagation;
- connected rooms, corridors, doors, and openings without clamping remote sources into the array's room;
- physically coherent relative amplitudes without requiring universal dB SPL calibration;
- acoustic-partition or assembly semantics that do not multiply loss merely because one physical barrier uses several meshes or colliders;
- authored frequency-dependent assembly transmission without undocumented total-loss clipping;
- bounded optional path or ray diagnostics that can support review artifacts without becoming public sensor state;
- a viable Isaac runtime, packaging, licensing, and performance path.

Human-listener, binaural, device-speaker-mix, metadata-only, or active-ultrasound-only output does not satisfy the microphone-array contract.

#### Key Decisions

- Raw multichannel microphone output and passive audible content are non-negotiable gates.
- Approximate pathing/diffraction is required; a complete wave solver is not.
- The maintained product should select one primary passive provider.
- Native provider capabilities take precedence over repository-owned reimplementations when they satisfy the sensor contract and maintenance boundary.

#### Problems / Limitations

No provider is selected by this specification. Provider marketing or a plausible rendered signal is insufficient if the microphone-array contract cannot be met. A provider that cannot represent one acoustic assembly across fragmented geometry, or that silently changes authored transmission values, does not satisfy the material contract.

## Subphase R9.2 — Candidate Qualification

#### Implementation

Build only the temporary adapters needed to exercise each serious candidate in the intended Isaac runtime. Qualify provider behavior rather than recreating its propagation algorithms. Record runtime availability, license and distribution constraints, raw per-microphone output semantics, phase coherence, dynamic-scene update behavior, material inputs, and performance with diagnostics disabled and enabled.

Use a common fixture matrix. One acoustic partition represented by one mesh and by several meshes must produce equivalent transmission. Two independent sequential partitions must compound transmission. A double-leaf construction must accept one authored whole-assembly frequency curve without requiring the SDK to simulate structural coupling. Door and opening cases must preserve alternative propagation rather than forcing all energy through the blocking wall. Moving doors, sources, arrays, and large objects must update bounded state without rebuilding unrelated static geometry.

Verify that the candidate either exposes native path diagnostics or permits a thin optional adapter to the existing `DebugPrimitive` representation. Diagnostic absence is recorded explicitly and weighed against the complete provider contract; path data is never required in `AudioSensorFrame` or ordinary datasets. Reject hidden attenuation clamps, listener-only rendering, mixed-device output, non-phase-coherent channels, and any candidate that requires a permanent duplicate propagation implementation in this repository.

#### Key Decisions

- Qualification uses shared semantic fixtures and measurable outputs, not subjective audition or marketing claims.
- Existing provider geometry, pathing, transmission, reflection, scattering, and diffraction facilities are reused through the thinnest maintainable adapter.
- Temporary comparison adapters are deleted after the final provider decision unless they are part of the selected integration.
- Whole-assembly transmission data is preferred over a repository-owned double-leaf or structural wall solver.

#### Problems / Limitations

A provider may meet propagation requirements while lacking a useful diagnostic API; that limitation must remain visible in the decision rather than causing path reconstruction in Core. Nominal provider material tables do not establish measured truth for a specific construction, and qualification does not add real-world calibration scope.

## Subphase R9.3 — Candidate Decision

#### Implementation

Treat Steam Audio as the principal existing-engine candidate for passive geometry-aware propagation. Evaluate NVIDIA RTX Acoustic in the installed Isaac runtime, but select it for this role only if it supports arbitrary audible source content and raw per-microphone output rather than only active chirp or ultrasonic operation.

PyRoom remains the analytic provider and is not treated as the general arbitrary-geometry engine. Active acoustics, if added later, remains a separate backend.

Temporary candidate adapters may coexist during qualification, but the phase concludes with one documented primary provider or an explicit no-provider result. It must not leave multiple redundant experimental backends as permanent public surface.

#### Key Decisions

- Provider research and provider integration are separate phases.
- The selected engine owns the mathematically complex propagation algorithms; the repository does not recreate them.

#### Problems / Limitations

If no candidate meets passive, per-microphone, dynamic-geometry, and distribution requirements, R10 remains blocked rather than weakening the sensor semantics.

## Artifacts

This page is the R9 phase specification. No provider decision exists yet.

## Files

No source files are changed by this planning step.
