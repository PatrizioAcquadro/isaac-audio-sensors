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

`SourceOcclusion` contains only `array_id`, `source_id`, exact per-microphone blocked and broadband-loss maps, plus optional aligned band losses and centers. Detection and UI state derive from the blocked map. Model, geometry, material, and fallback provenance are owned once by Isaac frame diagnostics rather than duplicated in each Core record.

Isaac groups collision hits by optional `ias:acoustic_partition_id`, or by collider path when no partition is authored. Fragmentation cannot duplicate loss; conflicting curves and exceeded hit limits fail closed; distinct sequential partitions add in dB without a total-loss clamp. `unknown_material_loss_db` is an explicit nominal fallback, not measured truth. Optional `debug_draw` emits transient ray/hit review data outside snapshots, stable frames, and datasets.

## Isaac Lab

Entity binding is a Torch-native, free-field, feature-only path. It computes scheduling, gain/directivity, direct delay, TDOA least-squares, confidence, and the six fixed-shape observations on `sensor.device`, without per-environment loops or host transfers.

Entity mode requires explicit free-field environment state, at least three microphones, order zero, identity effects, and non-degenerate TDOA geometry. It does not generate waveforms, reverberation, occlusion, calibrated SPL, or closed-room behavior. Two-microphone ambiguity, SRP-PHAT, half-space, and PyRoom remain available through scalar `bind_reference`.

## Historical Subphases

- R8.1 introduced `AnalyticAcoustics`, topology routing, lazy PyRoom, and solver diagnostics while legacy identifiers still existed at that staging boundary.
- R8.2 introduced private direct/indirect stems and direct-only broadband or spectral occlusion. Its larger temporary `SourceOcclusion` shape was subsequently reduced.
- R8.3 removed the four legacy runtimes and configuration paths, added the CUDA-native Lab route, migrated SquadBot, and introduced `ias.omni_extension_binding.v4`.
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
- `src/isaac_audio_sensors/lab/batched_backend.py`
