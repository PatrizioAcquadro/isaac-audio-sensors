# Implementation Plan 08 — Geometry Acoustics Integration

Status: Planned after provider selection and the signal/perception architecture migration.

## Objective

Integrate the provider selected by [[implementation_phases/01-geometry-provider-qualification|Plan 01]] as the primary high-fidelity simulated signal producer for one or a few Isaac environments. Feed its final microphone signals into the same observed perception path used by `AnalyticAcoustics` and physical capture.

This plan is the ordered high-level entry point for the detailed geometry scope already recorded in [[implementation_phases/r10-geometry-acoustics-integration|R10]].

## Subphase 08.1 — USD Acoustic Scene

#### Implementation

Translate acoustically relevant USD geometry, assemblies, materials, openings, rooms, robot structure, source poses, and array poses into the selected provider. Preserve one acoustic meaning for one physical partition even when visual or collision geometry is fragmented.

Reuse provider-native scene, material, cache, and dynamic-update capabilities. Do not rebuild a second geometry engine inside IAS.

#### Key Decisions

- USD remains scene authority; visual appearance is not acoustic calibration.
- Acoustic assemblies, not mesh count, determine transmission behavior.
- Static geometry is reused while bounded dynamic state is updated.
- Technical source and sensor prims are excluded unless they represent physical obstacles.

#### Problems / Limitations

Visual geometry may contain irrelevant detail, while simplified collision geometry may omit acoustically meaningful structure. Selection must preserve task-relevant propagation without importing every triangle.

## Subphase 08.2 — Geometry Signal Producer

#### Implementation

Produce one phase-coherent final waveform per physical microphone through the common `MicrophoneSignalBlock` boundary. The provider owns supported direct, reflected, transmitted, scattered, and diffracted paths; IAS owns source content, microphone semantics, sensor effects not owned by the provider, lifecycle, and signal provenance.

Apply occlusion and transmission exactly once. Provider-native path diagnostics remain optional review artifacts and do not enter observations or learning datasets.

#### Key Decisions

- Geometry Acoustics emits signals, not `AudioObservation` values.
- Activity and DOA remain backend-independent.
- Private provider stems or paths are optional and never required by perception.
- Absolute SPL calibration is not implied by phase-coherent relative output.

#### Problems / Limitations

Provider limitations define the high-fidelity ceiling. Unsupported physics remain explicit instead of being approximated with undocumented heuristics.

## Subphase 08.3 — Operational Integration

#### Implementation

Integrate provider lifecycle, caching, updates, configuration, Kit workflow, diagnostics, and packaging without exposing redundant backends or provider-specific scene state through Core observation contracts. Keep `AnalyticAcoustics` as the scalable analytic producer and Geometry Acoustics as the high-fidelity Isaac producer.

#### Key Decisions

- One selected geometry provider becomes the maintained integration.
- Provider-specific controls stay behind the provider capability boundary.
- The public perception and dataset contracts remain producer-independent.
- Geometry-derived distributions may later inform mass-parallel analytic training.

#### Problems / Limitations

The high-fidelity provider may be suitable for a small number of scenes but not thousands of simultaneous environments. This is an accepted product boundary rather than a reason to weaken signal fidelity.

## Artifacts

Expected artifacts are a provider-backed signal producer, USD acoustic mapping, bounded lifecycle and diagnostics, and unchanged perception semantics across analytic, geometry, and hardware inputs.

## Files

Detailed affected areas remain owned by the existing R10 specification and the selected provider's final adapter design.
