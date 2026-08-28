# Phase R10 — Geometry Acoustics Integration

## Objective

Integrate the provider selected by [[implementation_phases/r9-geometry-acoustics-provider-selection|R9]] as the primary high-fidelity Isaac backend for one or a few passive-audio environments.

## Subphase R10.1 — USD Acoustic Scene

#### Implementation

Make Isaac own acoustic-geometry selection, room and array containment, material mapping, static-scene caching, and dynamic-object updates. Visual materials are not treated as calibrated acoustic truth; relevant surfaces use explicit absorption, scattering, and transmission properties with provenance.

Include acoustically relevant room surfaces, doors, openings, large objects, robot body, and microphone housing while excluding technical source and sensor prims that are not physical obstacles. Static geometry is reusable; moving doors, robots, and objects update without rebuilding unrelated scene state.

#### Key Decisions

- USD remains the scene authority, while acoustic inclusion and material meaning are explicit.
- Multiple rooms form one connected acoustic problem when sound can travel between them.
- A selected local room aids containment and diagnostics but does not discard external sources.

#### Problems / Limitations

Arbitrary visual detail may be acoustically irrelevant or too expensive. Geometry selection and simplification must preserve meaningful propagation without treating every rendered triangle as necessary acoustic input.

## Subphase R10.2 — Passive Microphone-Array Propagation

#### Implementation

Map arbitrary passive source content, source pose and directivity, every microphone pose and response, and the selected acoustic scene into the provider. Preserve direct and reflected paths, material transmission, indirect pathing, and approximate diffraction, then return one phase-coherent waveform per microphone through the existing `AudioSensorFrame` contract.

Isaac Audio Sensors owns provider lifecycle, source and array translation, per-channel effects, diagnostics, frame assembly, and public sensor semantics. The external engine owns mesh acceleration, ray traversal, multi-bounce reflection, scattering, indirect path search, and approximate diffraction.

The provider owns geometry-path occlusion and transmission exactly once. Isaac therefore does not run the legacy `SourceOcclusion` raycast-and-attenuation path for `GeometryAcoustics`, and the backend does not accept a precomputed `SourceOcclusion` record as another gain stage. Conflicting external attenuation input fails validation rather than being ignored or double-applied.

Do not reconstruct `SourceOcclusion` solely to mirror legacy diagnostics. Expose only concise provider-derived occlusion state that remains meaningful to the public frame contract or an active consumer; do not duplicate provider path data without a concrete use. Legacy occlusion machinery remains only where R8 still needs direct-path analytic attenuation, and geometry-path wrappers or duplicate material resolution are removed after consumer migration.

#### Key Decisions

- The backend simulates a robot-mounted microphone array, not a human listener or qualitative device mix.
- Geometry-provider occlusion is applied once; `SourceOcclusion` is neither an additional attenuation stage nor a mandatory diagnostic artifact.
- Relative physical coherence is required; absolute calibration remains deployment-specific and optional.
- Structural vibration, a complete wave-equation solver, and active ultrasound are outside this phase.

#### Problems / Limitations

The provider's supported physics define the advanced-fidelity ceiling. Unsupported effects must remain explicit rather than being replaced with undocumented heuristics. Diagnostics retain only actionable provenance, limitations, and observable sensor state; they do not preserve obsolete internal structures for their own sake.

## Subphase R10.3 — Operating Boundary

#### Implementation

Target high-quality operation for one or a few Isaac environments. Expose geometry-derived acoustic statistics or bounded parameters that can inform R8 randomization for mass-parallel Isaac Lab training without requiring the geometry provider in every environment.

#### Key Decisions

- `GeometryAcoustics` is the primary daily high-fidelity Isaac path.
- `AnalyticAcoustics` remains the scalable Isaac Lab path.
- Both paths preserve the same frame and downstream consumer boundary.

#### Problems / Limitations

The geometry backend is not required to scale directly to thousands of simultaneous Isaac Lab environments.

## Artifacts

This page is the R10 phase specification. No R10 implementation artifacts exist yet.

## Files

No source files are changed by this planning step.
