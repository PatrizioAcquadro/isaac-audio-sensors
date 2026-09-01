# Phase R8 — Analytic Acoustics Backend

## Objective

Implement one fast, deterministic `AnalyticAcoustics` backend over the [[implementation_phases/r7-acoustic-environment-contract|R7 Acoustic Environment Contract]]. It is the pure-Core path for tests, non-Isaac use, and large Isaac Lab workloads.

The current public propagation surface contains only `AnalyticAcoustics`; future `GeometryAcoustics` remains outside R8. `geometry_only`, `tdoa_synthetic`, `room_acoustics`, and `room_acoustics_srp` were removed as runtime identifiers and implementations after active consumers migrated. Their useful direct-geometry, TDOA, and PyRoom behavior is internal `AnalyticAcoustics` logic, not compatibility aliases or duplicate backend paths.

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

The backend reuses the maintained source scheduler, gain, directivity, effects, GCC/SRP estimators, waveform writer, detection builder, and frame assembly. Every frame and detection reports `analytic_solver = {solver_id, provider, environment_kind}` without changing the v1 serialized schemas. `free_field` requires `max_order=0`; `half_space` accepts order zero or one; `air_absorption` and `ray_tracing` are reserved for the PyRoom routes. R8.1 temporarily reused `[audio.room_acoustics]`; R8.3 replaced it with `[audio.analytic_acoustics]` without a legacy parser.

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

R8.2 produces one phase-coherent received waveform per microphone while preserving relative timing, polarity, distance loss, air absorption, material effects, channel relationships, source gain, Doppler, and source/microphone directivity. The public output remains the combined multichannel waveform; direct and indirect stems are internal implementation state.

Core free field exposes its direct impulse as `D`; half space separates that impulse from the floor image-source reflection `R`. Each PyRoom shoebox or polygon-prism render computes both the configured full RIR and an order-zero direct RIR, pads them to one shape, and derives `R = full - D`. The same decomposition is assembled segment by segment for motion windows. PyRoom receives the requested sound speed before RIR computation through `Room.set_sound_speed()` when available; constructor-configured legacy providers are accepted only when `room.c` proves that they preserved the exact value, otherwise the backend fails explicitly.

For direct stem `D`, indirect stem `R`, and direct-path attenuation `a`, the backend computes `a * D + R`, never `a * (D + R)`. Broadband or banded loss is applied once to each affected source/microphone pair after source gain, Doppler, and `per_pair_direct_path` directivity. Microphone gain, channel response, source summation, noise/electronics, DOA estimation, and frame assembly follow recombination. With no attenuation, the original full premix is used directly; only actually attenuated pairs are replaced, preserving the previous no-occlusion waveform byte for byte. Geometry-only and synthetic-TDOA propagation remain direct-only, and retained PyRoom backends now use the same direct-stem rule when `SourceOcclusion` is present.

`SourceOcclusion` now requires `array_id`, `source_id`, exact `per_mic_blocked` and `per_mic_attenuation_db` maps, and `occlusion_model`. Optional aligned band attenuation, band centers, per-microphone hit paths, and hit-material provenance remain. Construction and scene assembly validate identifiers, exact microphone coverage, finite non-negative rows, unblocked zero state, path references, and material references. Aggregate `occlusion_factor`, `attenuation_db`, and `hit_prim_paths` fields and duplicate applied-gain diagnostics were removed without aliases. `AudioDetection.occluded` and the concise UI `occlusion_factor` diagnostic are derived from `per_mic_blocked`.

The live Isaac sensor accepts `analytic_acoustics` with enabled raycast occlusion. Its lifecycle evidence covers a blocked-to-clear transition after source/array motion, using the same public frame and Kit paths as ordinary captures.

Absolute SPL is not a package default. Source power, microphone sensitivity, measured materials, and absolute calibration remain optional user-owned extensions with explicit provenance.

#### Key Decisions

- Physically coherent relative signals are the maintained public target.
- `SourceOcclusion` is applied exactly once and only to the analytic direct stem.
- The unoccluded full-premix path remains the numerical compatibility authority.
- Nominal material fallback remains visible in diagnostics and is never presented as measured truth.
- Passive audible sources are the current scope; active acoustics is deferred to a separate future backend.
- Legacy public backend identifiers remain until R8.3 and downstream consumers are migrated; R8.2 does not add aliases or edit downstream repositories.

#### Problems / Limitations

Analytic surfaces cannot reproduce arbitrary objects, full scattering, general pathing, reflected-path occlusion, or diffraction. Those limitations are deliberate and handled by R10 rather than hidden. `surface_set` remains unsupported. R8.3 resolved the entity-batched Lab and room-specific backend-structure limitations described at the R8.2 cutoff.

## Subphase R8.3 — Isaac Lab Scale

#### Implementation

`AudioArraySensorCfg` now defaults to `analytic_acoustics`. Entity binding requires one explicit `AcousticEnvironmentSpec` and initially accepts only `free_field`. It resolves array, microphone, and source poses from the official scene tensors and computes direct delay as `distance / speed_of_sound_mps`, `1/d` spreading, source and microphone gain/directivity, TDOA least-squares, confidence, scheduling, active-event compaction, and the six fixed-shape public tensors entirely with Torch on `sensor.device`. There are no per-environment loops or device-to-host transfers in this path.

`per_mic_rms` is a relative direct-path feature; it is not waveform RMS, calibrated SPL, reverberation, or occlusion output. Entity mode requires at least three microphones, `doa_estimator="tdoa_least_squares"`, identity effects, order-zero free-field options, and valid non-degenerate TDOA geometry. Two-microphone ambiguity, `srp_phat`, PyRoom, half-space, shoebox, and polygon-prism execution remain available through scalar `bind_reference`.

`AudioArraySensorCfg` exposes `speed_of_sound_mps`, `doa_estimator`, and analytic solver options shared with reference binding. Entity/reference parity covers presence, bearing, confidence, sectors, ambiguity, and per-microphone RMS ratios; scheduling, truncation, directivity/gain, device placement, partial reset, and failure modes remain deterministic.

Runtime consolidation leaves only `analytic_acoustics` in the propagation registry. The four legacy classes, modules, registry entries, capability records, validation branches, and runtime configuration identifiers were removed without aliases. Maintained PyRoom implementation lives under `core/backends/_analytic/`; direct geometry and TDOA are internal Core/Lab computation. DOA selection is independent through `doa_estimator = "tdoa_least_squares" | "srp_phat"`.

TOML uses `[audio.analytic_acoustics]` for `max_order`, `air_absorption`, and `ray_tracing`; the old room table fails clearly. Core, CLI, Isaac, Kit, examples, and live smokes use the analytic backend. Python and Kit room-prefixed fields were renamed to analytic equivalents, and Kit configuration is `ias.omni_extension_binding.v4` with no v3 parser. The three v1 serialized schemas are unchanged: historical frames and manifests retain their recorded backend identifiers for replay, but those identifiers cannot select a runtime backend.

SquadBot migrated its active code, configuration, and deterministic tests to `AnalyticAcoustics.simulate(scene, array_id, window)`. Its Phase 6A oracle is now a project-owned canonical-geometry oracle with identity `squadbot_phase6a_geometry_oracle`; the sensor remains `AnalyticAcoustics`. Authenticated artifacts, historical phase documents, and the unrelated downstream `TODO.md` were not changed.

#### Key Decisions

- Large-batch training and high-fidelity geometry simulation are separate operating paths.
- Geometry-derived parameterization is not absolute hardware or room calibration.
- Propagation backend and DOA estimator are independent choices.
- Historical serialized identifiers are replay data, not runtime aliases.

#### Problems / Limitations

The scalable analytic model is intentionally free-field and feature-only. It does not generate waveforms, reverberation, occlusion, calibrated SPL, half-space reflections, closed-room propagation, or per-environment acoustic randomization. Future geometry-derived distributions must be motivated and bounded before they are added.

## Subphase R8.4 — Occlusion Contract and Transmission Closeout

#### Implementation

Complete the analytic occlusion cleanup after R8.3 has stabilized the scalable backend and migrated the legacy consumers. Keep `SourceOcclusion` limited to `array_id`, `source_id`, exact `per_mic_blocked` and `per_mic_attenuation_db` maps, plus optional aligned band attenuation and band centers. Remove `per_mic_hit_prim_paths`, `hit_materials`, and per-record `occlusion_model` without aliases. Report the producing model and material-resolution provenance once in frame or sensor diagnostics instead of repeating geometry-internal state in every Core record.

Replace hit-path persistence with an optional Isaac-internal trace. The normal path emits only the minimal `SourceOcclusion`; debug or artifact capture may additionally collect source, microphone, ray endpoints, hit points, acoustic-partition ids, resolved materials, and applied losses. Convert that trace to the existing `DebugPrimitive` surface for live overlays, sidecar JSON, or review video. Do not add it to `AudioSceneSnapshot`, the stable `AudioSensorFrame` schema, or ordinary datasets, and do not allocate or serialize it when debug capture is disabled.

Define accumulation over acoustic partitions rather than arbitrary visual or collision prims. Multiple prims assigned to one partition contribute one authored assembly transmission curve; distinct sequential partitions multiply transmission and therefore add their losses in dB. Alternative direct, reflected, diffracted, or around-opening paths remain separate waveform contributions and are never represented by summing obstacle losses. The analytic model accepts an authored whole-assembly curve for constructions such as double-leaf walls and does not implement structural wall physics.

Remove the fixed `60 dB` total-loss clamp. Retain `max_hits_per_ray` only as a bounded-work guard. Rename `occlusion_max_attenuation_db` to `unknown_material_loss_db`, use it only as an explicit nominal fallback for unresolved materials, and report every fallback application without presenting it as measured behavior. Exact authored losses remain unchanged by undocumented clipping.

#### Key Decisions

- R8.3 closed before this contract cleanup begins; its scale and consolidation work is not reopened or expanded.
- Core stores the attenuation needed by analytic propagation, while Isaac owns transient ray, hit, and material-resolution detail.
- One acoustic partition may own many visual or collision prims; fragmentation must not increase attenuation.
- Sequential partition losses add in dB, while alternative propagation paths remain separate signals.
- There is no default total attenuation cap and no missing-microphone fallback.
- Debug rays are optional review data outside stable frames and ordinary datasets.
- No compatibility aliases are retained for the removed unreleased v3 Python fields.

#### Problems / Limitations

Nominal unknown-material loss remains an explicit approximation rather than calibrated material truth. Assembly curves must be authored or resolved from a qualified source; R8.4 does not infer thickness, cavity resonance, structural coupling, or coincidence behavior from rendered meshes. Analytic occlusion remains direct-path-only and does not acquire general geometry pathing or diffraction.

## Artifacts

R8.1 includes deterministic routing and propagation tests, fake-provider coverage for both closed-room routes, real PyRoom 0.10.1 smoke execution for shoebox and a concave prism, CLI/config and Isaac reference coverage, legacy-backend regression coverage, and a live Isaac Sim Core free-field route.

R8.2 adds deterministic `a * D + R` coverage for all four supported analytic topologies, broadband and banded attenuation, no-attenuation byte equality, timing, polarity, distance, air absorption, materials, directivity, motion segmentation, multiple sources, multi-hit caps/provenance, and clear/partial/full occlusion. The closure gate passes 551 host tests, 216 focused integration tests, 57 release tests, 111 Isaac tests, real optional PyRoom/SciPy/SoundFile execution, and live RTX 4090 Isaac Sim, Isaac Lab, and 38-step Kit workflows. Live analytic evidence records `occlusion_factor` changing from `1.0` blocked to `0.0` clear. Temporary source, wheel, and Kit artifacts pass the release audit; all three serialized v1 schemas remain byte-identical. The unchanged SquadBot suite has the exact same 31-test failure set as baseline `3a8b078`.

R8.3 adds deterministic host coverage, 90 Isaac-runtime tests, optional PyRoom/SciPy/SoundFile execution, and RTX 4090 live gates. Isaac Sim passes three analytic lifecycle frames; Isaac Lab passes entity/reference parity, partial reset, CUDA tensor contracts, and 50 steps over 4096 environments at 2.213 ms/step mean against the 20 ms budget; Kit passes all 38 workflow steps with binding v4, a four-channel analytic waveform, and a non-silent qualitative device mix. The migrated SquadBot suite passes 373 tests with 10 expected skips and no removed-API failures. Clean-source `3.0.0` sdist, universal wheel, and Kit ZIP pass their local audit. The three serialized v1 schemas and authenticated downstream artifacts remain unchanged. R8.4 remains future work.

## Files

- `src/isaac_audio_sensors/core/backends/analytic.py`
- `src/isaac_audio_sensors/core/backends/_analytic/`
- `src/isaac_audio_sensors/core/types.py`
- `src/isaac_audio_sensors/core/acoustics/occlusion.py`
- `src/isaac_audio_sensors/core/plugins/registry.py`
- `src/isaac_audio_sensors/core/config.py`
- `src/isaac_audio_sensors/isaac/sensor.py`
- `src/isaac_audio_sensors/isaac/occlusion.py`
- `src/isaac_audio_sensors/lab/audio_array_sensor_cfg.py`
- `src/isaac_audio_sensors/lab/entity_binding.py`
- `src/isaac_audio_sensors/lab/batched_backend.py`
- `src/isaac_audio_sensors/lab/reference_backend.py`
- `tests/integration/test_analytic_acoustics.py`
- `tests/isaac/test_occlusion.py`

## Version Notes

- 2026-09-01: Implemented R8.1 solver routing while retaining the four legacy backend identifiers and all three serialized v1 schemas.
- 2026-09-01: Implemented R8.2 direct/indirect propagation and direct-path-only occlusion while preserving the public combined waveform and all three serialized v1 schemas.
- 2026-09-01: Implemented R8.3 mass-parallel free-field Isaac Lab execution, consolidated runtime propagation on `AnalyticAcoustics`, migrated SquadBot, introduced Kit binding v4, and preserved historical v1 replay contracts without runtime aliases.
