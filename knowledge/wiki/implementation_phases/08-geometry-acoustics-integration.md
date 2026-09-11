# Implementation Plan 08 — Geometry Acoustics Integration

Status: 08.1 completed; 08.2 intermediate hybrid milestone completed; Milestone 2 qualification pending for priority AV attention/search and complementary mobile audition (2026-09-11); 08.3 remains planned. Bounded 07.2 admission follows the latest [[status|user sequencing decision]]; geometry integration does not imply perceptual qualification. R10 owns the propagation/perception boundary.

## Objective

Record the execution order of the R10 geometry-integration work. This page is a sequence reference only; [[implementation_phases/r10-geometry-acoustics-integration|R10]] is the sole authority for requirements, decisions, limitations, artifacts, acceptance semantics, and application of the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision.

The confirmed qualification order is **Profile 1: AV attention/search first**, then
**Profile 2: mobile robot audition as the complement**. Essential timing, joint
microphone statistics, visibility/energy accounting, streaming and truth separation
remain required. Advanced acoustic phenomena may use documented approximations
within measured task-error budgets. Perfect asynchronous path history is a stress
test, not a global phase blocker. The SDK remains general-purpose for robot
audition; R10 is not a general-purpose acoustic-engine qualification.

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
after the declared robot-task acoustic domain passes, compare against the 07.2 practical baseline, locate bottlenecks, investigate
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
The latest [[implementation_phases/r10-geometry-acoustics-integration#Active scope — Robot-audition fidelity (2026-09-11)|R10 scope revision]] explicitly supersedes the former absolute dynamic-coverage gate.
Bounded geometry updates and statistical reverberation are eligible for task-domain
qualification; neither physical imperfection alone nor passing tensor/PCM checks
establishes admission. Corrected NLOS integration, representative diffuse-motion
impact and practical-use/lifecycle checks remain open. Declared-domain coverage
must pass before final scaling; the 32–256 matrix has not started.
This reference adds no requirements beyond R10.2.

## Subphase 08.3 — Implement R10.3

#### Implementation

After R10.2 is complete, implement [[implementation_phases/r10-geometry-acoustics-integration#Subphase R10.3 — Operating Integration and Cleanup|R10.3 Operating Integration and Cleanup]].

#### Key Decisions

- This plan defines only that R10.3 follows R10.2; R10.3 remains authoritative for its execution.

#### Problems / Limitations

This reference adds no requirements beyond R10.3.

R10.3 also owns provider-specific occlusion/path diagnostics and the integrated signal/instrument behavior needed for the fuller geometry version of [[topics/onr-video-production|ONR Video 4]]. Its simpler direct-attenuation scope may be feasible after the pre-07.2 corrections; neither version is qualified by its position in the phase sequence alone.

## Phase 08 closeout status

The approved scope is actionable, but Phase 08 is not closed. 08.1 and the
operational intermediate are complete; corrected NLOS and joint diffuse production
integration, both profile gates and 08.3 operation remain open. Freeze the domain
and numerical error budgets, demonstrate profile-specific task utility, then
complete affected actual runtime/consumer checks and final declared-domain
performance qualification. Scaling stays outside Milestone 2.
[[implementation_phases/r10-geometry-acoustics-integration#Remaining Phase 08 closeout gates|R10 owns the detailed closeout table]].

ONR videos have separate scenario and media gates. In particular, a bounded
direct-occlusion Video 4 can precede full Phase 08; the richer Geometry version
targets 08.3. Videos 5/7/8/9 are not all automatically blocked on Phase 08.
[[topics/onr-video-production#Remaining ONR deliveries after the R10 profile decision|The ONR page owns their current readiness]].

## Artifacts

This reference produces no independent artifacts. R10 owns all geometry-integration artifacts.

## Files

- `knowledge/wiki/implementation_phases/r10-geometry-acoustics-integration.md`
