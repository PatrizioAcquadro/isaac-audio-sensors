# Phase R7 — Geometry-Aware Acoustic Realism

## Objective

Replace implicit or scene-inconsistent acoustic approximations with two clear propagation levels: one explicit, fast, simulator-independent analytic environment for tests and large Isaac Lab workloads, and one geometry-aware Isaac backend for the main high-fidelity passive-audio workflow.

The phase targets physically coherent relative multichannel signals, not universal dB SPL. Absolute calibration remains an optional user-owned layer because source power, room materials, microphone sensitivity, and hardware response depend on each deployment.

## Subphase R7.1 — Explicit Analytic Environments

#### Implementation

Introduce one pure-data analytic environment contract instead of a public hierarchy of room classes. It stores one world pose and a set of acoustically meaningful surfaces in environment-local coordinates. Source and microphone positions are transformed from the world frame into that local frame before propagation.

The same contract represents the maintained fast cases:

- `free_field`: explicitly no surfaces;
- `half_space`: a floor plane with no enclosing walls or ceiling;
- `shoebox`: a closed rectangular enclosure;
- `polygon_prism`: a closed extruded floor polygon, including L-shaped rooms;
- `surface_set`: an explicit bounded set of floor, wall, or ceiling surfaces for simple open environments.

Common cases use concise builders rather than manual vertex authoring. The contract has three equivalent entry paths:

- TOML is the text/configuration path used by the CLI and headless workflows. The environment belongs in the configuration file; geometry is not duplicated across many command-line flags.
- Python builders construct the same contract directly for library use and focused tests.
- The Isaac adapter derives the contract from a selected or uniquely resolved USD acoustic volume, a floor, or an explicit manual configuration.

The analytic backend selects its internal solver deterministically from validated topology. Explicit free field uses direct propagation, one floor uses a half-space model, a rectangular enclosure uses `pyroomacoustics.ShoeBox`, and a supported closed polygon uses the general PyRoom room construction. A small supported open surface set may use bounded direct and early-specular propagation. Unsupported topology fails clearly and directs the caller to the geometry-aware backend; it is never silently approximated by an invented room.

An analytic environment is always explicit. Missing environment data is an error, including when USD room discovery fails. Free field must be requested explicitly. A floor resolves to half-space, not free field.

In Isaac, room containment considers the complete microphone array with a geometric tolerance. One containing acoustic volume is selected automatically. Multiple valid volumes use explicit priority and then the smallest valid containing volume; unresolved ambiguity requires manual selection. Sources in other rooms are not clamped into the array's room and remain a geometry-aware propagation case.

#### Key Decisions

- Public configuration exposes one analytic environment contract and a small set of composable presets, not separate backends for every room shape.
- Environment orientation is represented by its world pose; analytic geometry remains simple in local coordinates.
- A room inferred from a USD prim remains an approximation of that prim's acoustic volume. Arbitrary unmarked stage geometry is not guessed to be a room.
- The current implicit Kit shoebox centered on the array must be removed rather than retained as fallback behavior.
- Solver selection is automatic but reported in diagnostics for reproducibility.

#### Problems / Limitations

The current room backend requires a shoebox and the current Kit workflow can invent a default enclosure when no anchor is selected. R7.1 replaces that behavior when implemented. The analytic backend remains intentionally bounded: it does not become an arbitrary-mesh ray tracer or a multi-room pathing engine.

## Subphase R7.2 — Physically Coherent Analytic Propagation

#### Implementation

Keep PyRoom and small analytic formulas for the bounded environment model, while correcting the current hybrid behavior where necessary. Direct and indirect propagation must remain distinguishable so a direct-path obstruction does not blindly attenuate every reflected contribution in the same way.

Occlusion continues to be evaluated per source and microphone and may depend on the hit object, acoustic material, frequency band, and multiple blocking surfaces. Distance attenuation and air absorption remain propagation effects; obstacle loss is not multiplied by an arbitrary source-obstacle distance factor. Material fallback remains explicit in diagnostics rather than masquerading as measured behavior.

This backend owns deterministic fast propagation, environment-local transforms, simple image-source paths, material application, per-microphone waveform assembly, and diagnostics. It does not implement general mesh acceleration, arbitrary multi-bounce ray tracing, geometric path finding, or diffraction from scratch.

#### Key Decisions

- Relative timing, phase, level changes, material effects, and channel relationships are the maintained physical quantities.
- User-specific source level, microphone sensitivity, measured materials, and absolute SPL calibration remain optional extensions.
- Analytic acoustics is the scalable path for large Isaac Lab workloads and may be parameterized or randomized from geometry-backend results.

#### Problems / Limitations

Simple surfaces and early reflections cannot reproduce arbitrary object geometry, connected rooms, or robust around-corner propagation. Those are explicit geometry-backend responsibilities rather than reasons to expand the analytic backend into a second general acoustic engine.

## Subphase R7.3 — Geometry-Aware Passive Audio

#### Implementation

Add one provider-neutral `GeometryAcoustics` integration as the primary high-fidelity Isaac path for one or a few environments. Isaac owns USD acoustic-geometry selection, room and array containment, material mapping, static-scene caching, dynamic-object updates, source and microphone transforms, provider lifecycle, diagnostics, and conversion to the existing `AudioSensorFrame` contract.

The selected external provider owns the mathematically complex propagation machinery: mesh acceleration, ray traversal, multi-bounce reflections, scattering, transmission, indirect path search, and approximate diffraction. The repository must integrate an existing engine instead of creating a general acoustic solver.

The backend requirements are:

- passive audible sources with arbitrary file-backed or generated content;
- a separate phase-coherent received waveform for every physical microphone;
- room, corridor, doorway, and multi-room propagation without clamping remote sources into the array's room;
- acoustically selected USD surfaces and large relevant objects, including static and dynamic geometry;
- explicit acoustic absorption, scattering, and transmission properties rather than treating visual materials as calibrated acoustic truth;
- direct occlusion, reflections, indirect pathing, and approximate around-edge or around-corner propagation, without requiring a complete wave solver;
- physically coherent relative amplitudes with extension points for deployment-specific absolute calibration.

PyRoom remains the analytic provider. Steam Audio is the principal existing-engine candidate for passive geometry-aware propagation. NVIDIA RTX Acoustic must be evaluated in the installed Isaac runtime, but it can become the passive backend only if it supports arbitrary audible source content and raw per-microphone output rather than only active chirp/ultrasonic operation. Active acoustics, if added later, remains a separate backend.

Provider evaluation may retain more than one experimental adapter temporarily, but the maintained product should select one primary passive geometry provider rather than permanently expose redundant advanced backends.

GeometryAcoustics targets quality for one or a few Isaac environments. It is not required to scale directly to thousands of Isaac Lab environments. Its outputs may instead define distributions or parameters used to randomize and improve the scalable analytic model.

#### Key Decisions

- The advanced backend simulates a robot-mounted microphone array, not a human-listener or device-speaker mix.
- Raw multichannel microphone output and compatibility with `AudioSensorFrame` are non-negotiable provider gates.
- Approximate pathing/diffraction is required so sound does not disappear unrealistically whenever the direct ray is blocked.
- Passive audible sensing is the current scope; active ultrasound or echolocation is deferred to a separate future backend.
- Absolute calibration is not a repository-wide default and must never be invented from nominal values.

#### Problems / Limitations

The final external provider is unresolved until its passive-audio, multichannel, dynamic-geometry, runtime, packaging, licensing, and performance fit is established. The phase does not target structural vibration, detailed edge-wave physics, or a complete wave-equation solver.

## Artifacts

This page is the phase specification. No R7 implementation artifacts exist yet.

## Files

No source files are changed by this planning step.
