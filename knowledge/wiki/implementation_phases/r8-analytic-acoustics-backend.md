# Phase R8 — Analytic Acoustics Backend

Status: original R8 complete; later continuous-clock and bounded live-occlusion corrections integrated.

## Objective

Maintain one AnalyticAcoustics backend over explicit environments, with propagation separate from DOA. Retain it alongside Geometry for its supported simple/reference and Lab roles.

## Subphase R8.1 — Solver Routing

#### Implementation

Core handles direct free-field and half-space image reflection; optional PRA handles shoebox/polygon-prism rooms. Configuration/containment fails explicitly; legacy backend aliases were removed in R8.3.

#### Key Decisions

Topology chooses the solver; raw source amplitude and configured relative effects remain meaningful.

#### Problems / Limitations

No arbitrary mesh, connected-room, shared diffuse or calibrated wall/SPL claim.

## Subphase R8.2 — Relative Waveform and Occlusion

#### Implementation

Private direct/indirect stems combine as `a * D + R`, with direct loss once per source/mic pair and common response/effects afterward.

#### Key Decisions

Blocked geometry remains diagnostics, never inferred event identity or reliability.

#### Problems / Limitations

Analytic attenuation does not model reflected-path blocking, diffraction or structural transmission.

## Subphase R8.3 — Consumer Migration

#### Implementation

Migrated Core/Isaac/Kit/Lab/downstream consumers to one analytic identifier and explicit environment contract.

#### Key Decisions

Old runtime names have no compatibility selectors.

#### Problems / Limitations

The original Lab feature/six-tensor implementation was superseded by Phase 07 observed PCM/CUDA.

## Subphase R8.4 — Partition Semantics

#### Implementation

Reduced SourceOcclusion to pair losses and grouped fragments by authored partition identity; explicit nominal unknown-material fallback and optional debug traces remain.

#### Key Decisions

One loss per physical partition; distinct analytic losses add in dB without an arbitrary clamp.

#### Problems / Limitations

This analytic approximation does not qualify Steam sequential-construction transmission.

## Later Update — Continuous Propagation (2026-09-09)

Fixed per-window loss of earlier emissions: at 10 m it had inserted ~29 ms silence
per block, and at 40 m a 100 ms block could be silent. Persistent emission history,
retarded sampling and filter history preserve motion, Doppler and source-stop tails;
Isaac owns persistent backends and Lab reference environments isolate state.
[[decisions/continuous-acoustic-clock|Continuous Acoustic Clock]] owns model choice,
reset semantics and remaining approximations. Fast DOA remains separately unqualified.

## Pre-07.2 Follow-up — Live Occlusion Correctness

Replaced failing closest-hit recasts with one PhysX `raycast_all` segment query,
both mesh sides, copied/sorted hits and collider/partition deduplication. Invalid,
partial or unavailable requested queries fail capture and clear current state;
Kit finalizes an active recording as incomplete, never emits an unoccluded fallback.

Actual RTX/PhysX controls pass solid primitives/meshes, 1 mm–50 cm boxes, sequential
solids, selective 20 dB pair attenuation and recovery. Maximum recomposition error
<1.9e-9; actual Kit shows independent observed confidence and geometric path counts.
Evidence: `local/pre72/live_one/`, `live_two/`, `live_final/`. Sub-window moving edges,
arbitrary instancing, reflected obstruction and robot-housing acoustics remain
unqualified. General perceptual misses/extras are not solved by correct attenuation.

## Artifacts

Original host, optional-room, actual RTX Sim/Lab/Kit, downstream and clean-source archive gates passed. Later evidence is summarized below; current algorithms/limits are in [[topics/acoustic-modeling|Acoustic Modeling]].

## Files

`src/isaac_audio_sensors/core/backends/analytic.py`, `core/backends/_analytic/`, `isaac/occlusion.py`.
