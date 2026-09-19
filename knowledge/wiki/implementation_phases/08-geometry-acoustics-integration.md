# Implementation Plan 08 — Geometry Acoustics Integration

Status: **08.1 and 08.2 are complete within their documented bounds.**
08.3 operating integration is implemented; runtime/distribution closeout is in progress.
Phase 08 remains open until those checks pass.

## Objective

Deliver a reusable geometry-backed audio sensor for Isaac Sim, Isaac Lab and
robot learning. This page owns sequence; [[implementation_phases/r10-geometry-acoustics-integration|R10]]
owns implementation and [[decisions/robot-audition-fidelity|Robot-Audition Fidelity]]
owns acoustic/interface criteria and supported-domain limits. Robot policies,
visual search and navigation belong to downstream applications.

## Subphase 08.1 — Implement R10.1

#### Implementation

Completed prepared USD/native scene and shared authoring panel. Automatic scene
import, materials/proxies, selective updates and live PhysX poses are available.

#### Key Decisions

Preserve the shared scene preparation during propagation and operating integration.

#### Problems / Limitations

Preparation alone does not qualify propagated microphone signals.

## Subphase 08.2 — Implement R10.2

#### Implementation

Completed native selected-route NLOS, shared diffuse pressure and their integration
with direct/specular contributions in one continuous multichannel producer.
Native controls and actual RTX Isaac Sim/Lab checks cover timing, motion/doors,
source-stop tails, block continuity, reset/isolation and unchanged observations.
The [[experiments/geometry-acoustics-admission|admission record]] owns results.

| Completed step | Evidence and boundary |
| --- | --- |
| 1 — Prepare simulation inputs | Bounded Office/Hospital proxies, controlled fixtures, reference diagnostics and RTX cost pilot; preparation is separate from model qualification |
| 2 — Integrate Steam NLOS | Selected-route timing, visibility, ordinary motion/doors, non-duplication and actual RTX Isaac controls; pressure remains probe-sensitive and diffraction uncalibrated |
| 3 — Qualify PRA diffuse extension | Shared-field energy, persistence, visibility, lifecycle and selected motion/observation controls pass; full-room moving equivalence remains NOT VALIDATED |
| 4 — Qualify the combined producer | Native and actual RTX Sim/Lab composition, timing, tails, resets and environment isolation pass; public signal/observation contracts are unchanged |

#### Key Decisions

Retain Analytic and the working direct/specular defaults. Extended NLOS/diffuse
coverage is opt-in. Sensor qualification uses acoustic and interface evidence;
application performance and physical hardware calibration remain separate.
Reuse valid evidence and rerun affected checks when a model or interface changes.

#### Problems / Limitations

Full-room moving pressure/observation equivalence is NOT VALIDATED and non-blocking
within this bounded admission. Cube/mirror diagnostic mismatches, selected-route
coverage and measured runtime limits remain explicit. Passing stream integration
or scalar/CUDA parity does not establish absolute localization accuracy, physical
transfer or learning performance.

## Subphase 08.3 — Implement R10.3

#### Implementation

Implemented the shared Python/Kit configuration workflow, controller-owned prepared
scene, optional advanced native controls, capability failures and separate
material/path/coverage diagnostics. Binding import/export retains native settings
without handles; window teardown preserves the scene and stage changes close
borrowing producers first. Historical NLOS coverage is now captured per block.

Closeout in progress: bounded sensor-to-instrument runtime validation, native
consumer/build consolidation review, one/two-environment measurements and affected
native, scalar/CUDA, actual Sim/Lab/Kit and clean-source packaging checks.

#### Key Decisions

Slower-than-real-time simulation is permitted with coherent simulated clocks.
No acoustic GPU port, large-batch qualification, policy training or new physical
capture campaign is required. Use actual GPU execution for supported Isaac/CUDA paths.

#### Problems / Limitations

08.3 closeout is in progress. Phase 08 closes only after its operating and distribution
checks pass. [[topics/onr-video-production#Remaining ONR deliveries|ONR deliveries]]
retain their own scenario/media gates; SDK completion does not approve a video.

## Artifacts

[[experiments/geometry-acoustics-admission|Admission evidence]] owns measurements and
limitations; [[experiments/geometry-acoustics-trial-protocol|simulation fixtures]]
owns prepared inputs and their verified boundaries.

## Files

`knowledge/wiki/implementation_phases/r10-geometry-acoustics-integration.md`.
