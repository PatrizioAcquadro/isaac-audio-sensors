# Implementation Plan 08 — Geometry Acoustics Integration

Status: **08.1–08.3 and Phase 08 are complete within their documented bounds.**
Operating, runtime and clean-source distribution gates passed on 2026-09-19.

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

Completed the bounded sensor-to-instrument gate on actual RTX Kit, including
closed/open/closed screen motion with NLOS and diffuse together, source-stop/tail,
window recreation, failure recovery and stage replacement. Actual Sim, the shared
preparation panel and CUDA Lab pass. Base/combined one/two-environment measurements
cover preparation, warm-up, reset, mean/p95, host/GPU memory and simulated/wall time;
the [[experiments/geometry-acoustics-admission#08.3 operating runtime and cost (2026-09-19)|admission record]]
owns values and interpretation.

Host checks pass: 677 unit/contract, 336 integration and 58 release tests.
Affected native/stream and CUDA parity/isolation checks pass. Consumer/build review
confirmed one maintained production binding per capability; native patches,
installed providers and retained inputs remain intact. Clean committed source
produced audited sdist, its derived wheel and Kit ZIP. The extracted Kit archive
passes the actual GPU smoke, including bundled dependency origins and Geometry.

#### Key Decisions

Slower-than-real-time simulation is permitted with coherent simulated clocks.
No acoustic GPU port, large-batch qualification, policy training or new physical
capture campaign is required. Use actual GPU execution for supported Isaac/CUDA paths.

#### Problems / Limitations

No remaining 08.3 gate is blocked. Full-room fidelity, calibrated diffraction,
large-batch scaling and real-time performance remain outside this bounded closure.
[[topics/onr-video-production#Remaining ONR deliveries|ONR deliveries]]
retain their own scenario/media gates; SDK completion does not approve a video.

## Artifacts

[[experiments/geometry-acoustics-admission|Admission evidence]] owns measurements and
limitations; [[experiments/geometry-acoustics-trial-protocol|simulation fixtures]]
owns prepared inputs and their verified boundaries.

## Files

`knowledge/wiki/implementation_phases/r10-geometry-acoustics-integration.md`.
