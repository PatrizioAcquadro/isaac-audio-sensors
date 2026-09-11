# Implementation Plan 08 — Geometry Acoustics Integration

Status: 08.1 completed; 08.2 intermediate hybrid milestone completed; Milestone 2 native extensions blocked on dynamic diffuse pressure; full scope unchanged (2026-09-11); 08.3 remains planned. Bounded 07.2 admission follows the latest [[status|user sequencing decision]]; geometry integration does not imply perceptual qualification. R10 owns the propagation/perception boundary.

## Objective

Record the execution order of the R10 geometry-integration work. This page is a sequence reference only; [[implementation_phases/r10-geometry-acoustics-integration|R10]] is the sole authority for requirements, decisions, limitations, artifacts, acceptance semantics, and application of the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision.

## Subphase 08.1 — Implement R10.1

#### Implementation

Completed [[implementation_phases/r10-geometry-acoustics-integration#Subphase R10.1 — USD Acoustic Scene|R10.1 USD Acoustic Scene]], including automatic import and the shared Python/Kit preparation panel. Operational backend controls and propagation diagnostics remain in 08.3.

#### Key Decisions

- This plan defines only that R10.1 precedes R10.2; R10.1 remains authoritative for its execution.

#### Problems / Limitations

This reference adds no requirements beyond R10.1.

## Subphase 08.2 — Implement R10.2

#### Implementation

After R10.1 is complete, implement [[implementation_phases/r10-geometry-acoustics-integration#Subphase R10.2 — Passive Microphone-Array Propagation|R10.2 Passive Microphone-Array Propagation]]. Begin with its
[[implementation_phases/r10-geometry-acoustics-integration#Early complete-path and scaling decision gate (resume after blocker)|early complete-path and scaling decision gate]]:
after complete acoustic coverage passes, compare against the 07.2 practical baseline, locate bottlenecks, investigate
Linux/NVIDIA acceleration and prototype GPU work only when justified. Decide
whether to retain both backends after matched functional/performance checks;
CUDA support and analytic retirement are not assumed outcomes.

#### Key Decisions

- This plan defines only that R10.2 follows R10.1 and precedes R10.3; R10.2 remains authoritative for its execution.

#### Problems / Limitations

The original reflection and hybrid coverage failures remain historical evidence.
The user subsequently authorizes an intermediate direct/transmission/specular
milestone without reducing final R10 scope. Its bounded native corrections,
streaming adapter, common perception and actual Isaac qualification are tracked
in [[implementation_phases/r10-geometry-acoustics-integration#Intermediate coherent propagation milestone (2026-09-10)|R10's intermediate milestone]].
The subsequent [[implementation_phases/r10-geometry-acoustics-integration#Milestone 2 native extensions — dynamic-field blocker (2026-09-11)|Milestone 2 admission gate]] now has a bounded native NLOS timing extension but remains blocked on physically
consistent dynamic diffuse pressure and complete integration. Complete coverage must pass before final performance
qualification/scaling; the 32–256 matrix has not started.
A coherent diffuse field and complete final coverage remain required before
08.2 closure and 08.3 operating integration.
This reference adds no requirements beyond R10.2.

## Subphase 08.3 — Implement R10.3

#### Implementation

After R10.2 is complete, implement [[implementation_phases/r10-geometry-acoustics-integration#Subphase R10.3 — Operating Integration and Cleanup|R10.3 Operating Integration and Cleanup]].

#### Key Decisions

- This plan defines only that R10.3 follows R10.2; R10.3 remains authoritative for its execution.

#### Problems / Limitations

This reference adds no requirements beyond R10.3.

R10.3 also owns provider-specific occlusion/path diagnostics and the integrated signal/instrument behavior needed for the fuller geometry version of [[topics/onr-video-production|ONR Video 4]]. Its simpler direct-attenuation scope may be feasible after the pre-07.2 corrections; neither version is qualified by its position in the phase sequence alone.

## Artifacts

This reference produces no independent artifacts. R10 owns all geometry-integration artifacts.

## Files

- `knowledge/wiki/implementation_phases/r10-geometry-acoustics-integration.md`
