# Phase R8 — Analytic Acoustics Backend

Status: completed on 2026-09-01.

## Objective

Provide one deterministic `AnalyticAcoustics` propagation backend over the [[implementation_phases/r7-acoustic-environment-contract|R7 Acoustic Environment Contract]] for pure Core, Isaac Sim, Kit, and scalable Isaac Lab use.

`analytic_acoustics` is the only current runtime propagation identifier. `geometry_only`, `tdoa_synthetic`, `room_acoustics`, and `room_acoustics_srp` were removed after active consumers migrated; their useful algorithms are internal implementation, not compatibility aliases. TDOA least-squares and SRP-PHAT remain independent DOA estimators selected after propagation.

## Solver Routing

The environment selects exactly one solver:

| Environment | Solver ID | Provider |
|---|---|---|
| `free_field` | `free_field_direct` | Core |
| `half_space` | `half_space_image_source` | Core |
| `shoebox` | `pyroom_shoebox` | PyRoom |
| `polygon_prism` | `pyroom_polygon_prism` | PyRoom |

Core implements fractional direct delay, spherical spreading, and the optional half-space floor image source. Closed rooms use lazy `pyroomacoustics` loading, exact local-frame containment, authored materials, and requested sound speed. A Core-only installation therefore runs `free_field` and `half_space`; requesting a closed topology without the `room` extra fails actionably. `surface_set` fails closed because it requires a future geometry provider.

Every frame and detection reports `{solver_id, provider, environment_kind}`. TOML owns solver options under `[audio.analytic_acoustics]`; the removed room table has no parser.

## Relative Waveform and Occlusion

Analytic propagation preserves relative timing, polarity, distance, air absorption, material response, gain, Doppler, directivity, and channel relationships. The public result is one combined multichannel waveform; direct and indirect stems remain private.

For direct stem `D`, indirect stem `R`, and direct-path attenuation `a`, propagation computes `a * D + R`. Broadband or banded attenuation is applied once per source/microphone pair after source gain, Doppler, and pair directivity. Microphone gain, channel response, summation, effects, DOA estimation, and frame assembly follow recombination. An unattenuated pair reuses the original full premix byte-for-byte.

`SourceOcclusion` contains only `array_id`, `source_id`, exact per-microphone blocked and broadband-loss maps, plus optional aligned band losses and centers. In the current observed pipeline, attenuation changes the waveform and its measured RMS; the blocked map is not a detection or a perceived occlusion label. Model, geometry, material, and fallback provenance are owned once by Isaac frame diagnostics rather than duplicated in each Core record.

Isaac groups collision hits by optional `ias:acoustic_partition_id`, or by collider path when no partition is authored. Fragmentation cannot duplicate loss; conflicting curves and exceeded hit limits fail closed; distinct sequential partitions add in dB without a total-loss clamp. `unknown_material_loss_db` is an explicit nominal fallback, not measured truth. Optional `debug_draw` emits transient ray/hit review data outside snapshots, stable frames, and datasets.

## Isaac Lab

At the R8 closeout, entity binding was a Torch-native, free-field, feature-only path computing scheduling, gain/directivity, direct delay, TDOA least-squares, confidence and six fixed-shape observations on `sensor.device`. Phase 07.1 subsequently removed that source-conditioned observation contract; current entity output remains empty pending 07.2. [[topics/isaac-lab-integration|Isaac Lab Integration]] owns the current executable surface.

That historical entity mode required explicit free-field state, at least three microphones, order zero, identity effects and non-degenerate TDOA geometry. It did not generate waveforms, reverberation, occlusion, calibrated SPL or closed-room behavior. Current scalar reference sensing consumes actual waveform observations rather than those historical features.

## Historical Subphases

- R8.1 introduced `AnalyticAcoustics`, topology routing, lazy PyRoom, and solver diagnostics while legacy identifiers still existed at that staging boundary.
- R8.2 introduced private direct/indirect stems and direct-only broadband or spectral occlusion. Its larger temporary `SourceOcclusion` shape was subsequently reduced.
- R8.3 removed the four legacy runtimes and configuration paths, added the CUDA-native Lab route, migrated SquadBot, and introduced the then-current `ias.omni_extension_binding.v4`; R9.1.2 later replaced it directly with v5.
- R8.4 finalized the minimal occlusion record, partition-based uncapped transmission, explicit unknown-material fallback, and optional transient debug traces.

At the R8 closeout, historical frame identifiers remained readable replay data but could not select a runtime backend, and all three schemas remained v1. R9.1.1 later removed frame v1 reading and replaced only the frame contract with v2.

## Final Validation

The final cleanup passes the complete Core-only host gate on Python 3.10 and 3.12, the real optional-room lane, 100 tests in the supported Isaac runtime, and live Isaac Sim/Lab/Kit execution on the RTX 4090. Lab preserves parity and partial reset across 4096 environments at 2.336 ms/step mean against the 20 ms budget; Kit passes all 38 maintained steps. The unchanged SquadBot suite passes 373 tests with 10 expected skips, release artifacts pass the clean-source audit, and all three v1 schemas regenerate byte-identically.

## Decisions and Limits

- Propagation backend and DOA estimator are separate choices.
- Scalar acoustic waveforms and vectorized Lab features remain separate contracts.
- Relative acoustic behavior is maintained; absolute SPL requires explicit measured calibration.
- Analytic occlusion affects only the direct path and does not model diffraction, reflected-path blocking, structural wall physics, or arbitrary geometry.
- `GeometryAcoustics` qualification belongs to R9/R10 rather than a second project-owned analytic path.

## Current Implementation

- `src/isaac_audio_sensors/core/backends/analytic.py` and `_analytic/`
- `src/isaac_audio_sensors/isaac/occlusion.py`
- `src/isaac_audio_sensors/lab/entity_binding.py`

## Later Update — Continuous Propagation (2026-09-09)

A subsequent pre-07.2 correction replaces window-local convolution and Doppler resampling with continuous emission history and retarded path sampling. This was not part of the original R8 validation: earlier tests could pass while each capture lost arrivals from preceding emissions. At 10 m, about 29 ms of artificial silence recurred per block; at 40 m, 100 ms blocks could remain entirely silent.

The shared backend now retains delayed sound and room tails, reuses bounded motion/room state, and supplies filter history. Isaac persists backend instances; Lab reference environments isolate propagation state. The public signal and plugin contracts are unchanged. Numerical tests cover static and moving arrivals, source stop/removal, loops, overlap, rewind/reset, room/half-space reflections, and channel processing. Frequency/level and passing-source intermicrophone waveforms are checked against independent closed forms.

The dependency decision, lifecycle, and remaining physical approximations are canonical in [[decisions/continuous-acoustic-clock|Continuous Acoustic Clock]]. Fast multisource DOA remains unresolved; see [[experiments/04-4-multisource-localization|the bounded comparison]]. Current validation is recorded in [[status|Current Status]].

## Pre-07.2 Follow-up — Live Occlusion Correctness

Status: implemented and validated on 2026-09-09 for the bounded direct-path model.

The former closest-hit recast loop failed on 10/20/50 cm solid boxes. The native adapter now uses one PhysX `raycast_all` segment query with both mesh sides enabled, copies native hit data, sorts distances and deduplicates collider paths before whole-partition material resolution. Injected raycasters implement `raycast_all`; the obsolete recast budget is removed. Invalid hits, inconsistent query completion and the distinct-collider limit fail explicitly instead of returning partial attenuation.

Requested-but-unavailable occlusion raises an actionable capture error. The sensor stops and resets current output/state; Kit clears current instruments, reports the error and finalizes an active guided recording as incomplete. No unoccluded replacement frame is emitted. The GUI displays aggregate blocked/total direct paths in a separate simulation-geometry diagnostic; confidence and RMS continue to derive from their observed contracts.

Actual RTX 4090/PhysX checks pass solid boxes from 1 mm through 50 cm, sphere, capsule, cylinder, closed triangle mesh, convex mesh and sequential solids. One- and two-source 160-window runs pass selective 20 dB loss, partial-channel attenuation, unchanged other-source contribution and recovery. Maximum linear recomposition difference is below 1.9e-9. Real Kit widget checks show `N/A` confidence and independent path counts; a controlled unavailable-service injection clears current output and displays the capture error. Local evidence is `local/pre72/live_one/`, `live_two/` and `live_final/`. Full host checks pass 1,041 tests and the supported Isaac suite passes 123 tests, including CUDA masks; all three live Isaac Sim, Kit and Isaac Lab lifecycle smoke checks also pass. The Kit smoke now inspects instruments before deliberate object removal and verifies cleared current state after the resulting capture failure.

This is direct-path attenuation, not advanced geometry acoustics or physical material qualification. Transforms settle before capture; moving-edge sub-window transitions, reflected-path obstruction, arbitrary instancing/meshes, diffraction and robot-housing acoustics remain unqualified. Full GUI event/candidate presentation remains 07.3 and geometric acoustics remains [[implementation_phases/r10-geometry-acoustics-integration|R10 / Phase 08]]. Perceptual extra/missed directions persist independently of correct attenuation and keep the temporal pre-07.2 objective open.
