# Phase R8 — Analytic Acoustics Backend

## Objective

Implement one fast, deterministic `AnalyticAcoustics` backend over the [[implementation_phases/r7-acoustic-environment-contract|R7 Acoustic Environment Contract]]. It is the pure-Core path for tests, non-Isaac use, and large Isaac Lab workloads.

The target public propagation surface contains only `AnalyticAcoustics` and `GeometryAcoustics`. After active consumers migrate, `geometry_only`, `tdoa_synthetic`, `room_acoustics`, and `room_acoustics_srp` are removed as backend identifiers and implementations; their useful direct-geometry, TDOA, and PyRoom behavior becomes internal `AnalyticAcoustics` solver logic, not compatibility aliases or duplicate backend paths.

GCC-PHAT, TDOA least-squares, and SRP-PHAT remain separate DOA-estimation algorithms selected after propagation. They are not propagation backends and are not removed by the two-backend consolidation.

## Subphase R8.1 — Solver Routing

#### Implementation

R8.1 adds the public `AnalyticAcoustics` class and `analytic_acoustics` backend identifier. The backend selects exactly one internal solver from `scene.environment.kind`:

| Environment kind | Diagnostic solver ID | Provider |
|---|---|---|
| `free_field` | `free_field_direct` | Core |
| `half_space` | `half_space_image_source` | Core |
| `shoebox` | `pyroom_shoebox` | PyRoom |
| `polygon_prism` | `pyroom_polygon_prism` | PyRoom |

The Core solvers implement fractional direct-path delay and spherical spreading; half-space order one adds the floor image source with the authored floor absorption. They transform all points into environment-local coordinates, including rotated or inclined environment poses, and reject points below the local floor instead of clamping.

The closed-room paths use `pyroomacoustics.ShoeBox` or `Room.from_corners(...).extrude(...)`. They preserve per-surface materials, validate the complete prism footprint, wall-edge mapping, vertical extrusion, and containment before simulation, and never clamp an out-of-bounds source or microphone. PyRoom is imported only after a closed topology is selected, so `free_field` and `half_space` work with the Core install; a missing `room` extra fails actionably only for `shoebox` and `polygon_prism`.

The backend reuses the maintained source scheduler, gain, directivity, effects, GCC/SRP estimators, waveform writer, detection builder, and frame assembly. Every frame and detection reports `analytic_solver = {solver_id, provider, environment_kind}` without changing the v1 serialized schemas. `free_field` requires `max_order=0`; `half_space` accepts order zero or one; `air_absorption` and `ray_tracing` are reserved for the PyRoom routes. Existing `[audio.room_acoustics]` settings remain the temporary configuration surface.

The caller chooses the environment, not the solver. The selected solver is reported in diagnostics. Unsupported topology fails clearly and directs the caller to `GeometryAcoustics`; it is never silently approximated by an invented enclosure.

#### Key Decisions

- PyRoom remains the maintained provider for closed analytic rooms.
- Small project-owned formulas are limited to direct and bounded simple-surface propagation.
- The backend does not grow into an arbitrary-mesh acoustic engine.
- `geometry_only`, `tdoa_synthetic`, `room_acoustics`, and `room_acoustics_srp` remain unchanged public identifiers during this staged subphase; no downstream migration is part of R8.1.
- `SourceOcclusion` is rejected by `analytic_acoustics` until R8.2 can apply it to the direct stem without attenuating reflections.
- CLI, TOML, Isaac, Kit, and scalar Isaac Lab reference binding recognize the new backend. Entity-batched Isaac Lab execution remains excluded until R8.3.

#### Problems / Limitations

`surface_set` fails closed and points to the future `GeometryAcoustics` provider. Complex topology, connected rooms, robust around-corner propagation, direct/reflected stem separation, and mass-parallel analytic execution remain outside R8.1.

## Subphase R8.2 — Relative Propagation and Occlusion

#### Implementation

Produce a separate phase-coherent received waveform for every microphone. Preserve relative timing, phase, distance loss, air absorption, material effects, channel relationships, and source/microphone directivity.

Keep direct and indirect propagation as distinct stems. `SourceOcclusion` has authority only over the analytic direct path: for direct stem `D`, reflected stem `R`, and direct-path attenuation `a`, the result is `a * D + R`, not `a * (D + R)`. Occlusion remains per source and microphone and may depend on the hit object, acoustic material, frequency band, and multiple blocking surfaces. Obstacle loss is not multiplied by an arbitrary source-obstacle distance factor.

Retain `SourceOcclusion` only for this necessary direct-path contract and meaningful public state. Audit its fields and consumers during the migration, remove duplicate or unused diagnostic-only data, and do not expand it into a container for reflected paths, diffraction, provider impulse responses, or general geometry propagation.

Absolute SPL is not a package default. Source power, microphone sensitivity, measured materials, and absolute calibration remain optional user-owned extensions with explicit provenance.

#### Key Decisions

- Physically coherent relative signals are the maintained public target.
- `SourceOcclusion` is applied exactly once and only to the analytic direct stem.
- Nominal material fallback remains visible in diagnostics and is never presented as measured truth.
- Passive audible sources are the current scope; active acoustics is deferred to a separate future backend.

#### Problems / Limitations

Analytic surfaces cannot reproduce arbitrary objects, full scattering, general pathing, or diffraction. Those limitations are deliberate and handled by R10 rather than hidden. The old room-specific backend structure is not retained merely for compatibility after equivalent maintained behavior moves to `AnalyticAcoustics`.

## Subphase R8.3 — Isaac Lab Scale

#### Implementation

Use `AnalyticAcoustics` as the scalable path for mass-parallel Isaac Lab workloads. Geometry-backend results may later define bounded parameter distributions and domain randomization for the analytic model without making the high-fidelity geometry provider run in every environment.

#### Key Decisions

- Large-batch training and high-fidelity geometry simulation are separate operating paths.
- Geometry-derived parameterization is not absolute hardware or room calibration.

#### Problems / Limitations

The scalable analytic model approximates the distribution of geometry-aware behavior; it does not reproduce every advanced scene path per environment.

## Artifacts

R8.1 includes deterministic routing and propagation tests, fake-provider coverage for both closed-room routes, real PyRoom 0.10.1 smoke execution for shoebox and a concave prism, CLI/config and Isaac reference coverage, legacy-backend regression coverage, and an updated live Isaac Sim smoke requirement for the Core free-field route.

R8.2 and R8.3 remain future work.

## Files

- `src/isaac_audio_sensors/core/backends/analytic.py`
- `src/isaac_audio_sensors/core/backends/room_acoustics/`
- `src/isaac_audio_sensors/core/plugins/registry.py`
- `src/isaac_audio_sensors/core/config.py`
- `src/isaac_audio_sensors/isaac/sensor.py`
- `src/isaac_audio_sensors/lab/reference_backend.py`
- `tests/integration/test_analytic_acoustics.py`

## Version Notes

- 2026-09-01: Implemented R8.1 solver routing while retaining the four legacy backend identifiers and all three serialized v1 schemas.
