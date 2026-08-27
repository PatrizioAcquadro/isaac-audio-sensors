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
- a viable Isaac runtime, packaging, licensing, and performance path.

Human-listener, binaural, device-speaker-mix, metadata-only, or active-ultrasound-only output does not satisfy the microphone-array contract.

#### Key Decisions

- Raw multichannel microphone output and passive audible content are non-negotiable gates.
- Approximate pathing/diffraction is required; a complete wave solver is not.
- The maintained product should select one primary passive provider.

#### Problems / Limitations

No provider is selected by this specification. Provider marketing or a plausible rendered signal is insufficient if the microphone-array contract cannot be met.

## Subphase R9.2 — Candidate Decision

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
