# Implementation Plan 08 — Geometry Acoustics Integration

Status: 08.1 completed; 08.2 intermediate hybrid milestone completed; Milestone 2 qualification pending for priority AV attention/search and complementary mobile audition (2026-09-11); 08.3 remains planned. Bounded 07.2 admission follows the latest [[status|user sequencing decision]]; geometry integration does not imply perceptual qualification. R10 owns the propagation/perception boundary.

## Objective

Record the execution order of the R10 geometry-integration work. This page is a sequence reference only; [[implementation_phases/r10-geometry-acoustics-integration|R10]] is the sole authority for requirements, decisions, limitations, artifacts, acceptance semantics, and application of the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision.

Qualification follows [[implementation_phases/r10-geometry-acoustics-integration#Confirmed profiles and ownership|R10's confirmed profiles]]: AV attention/search first,
then complementary mobile audition. R10 owns physical invariants, approximation
budgets and stress-test boundaries.

## Subphase 08.1 — Implement R10.1

#### Implementation

Completed [[implementation_phases/r10-geometry-acoustics-integration#Subphase R10.1 — USD Acoustic Scene|R10.1 USD Acoustic Scene]], including automatic import and the shared Python/Kit preparation panel. Operational backend controls and propagation diagnostics remain in 08.3.

#### Key Decisions

- This plan defines only that R10.1 precedes R10.2; R10.1 remains authoritative for its execution.

#### Problems / Limitations

This reference adds no requirements beyond R10.1.

## Subphase 08.2 — Implement R10.2

#### Implementation

Implement [[implementation_phases/r10-geometry-acoustics-integration#Subphase R10.2 — Passive Microphone-Array Propagation|R10.2]] under the
[[implementation_phases/r10-geometry-acoustics-integration#Approved operating domain and ambition (2026-09-11)|approved domain, budgets, reference consumers and exclusions]].
Both profiles use the same producer: qualify AV attention/search first, then mobile
audition. Retain Analytic and the working intermediate configuration. Milestone 2
ends with integrated acoustic/lifecycle evidence and both task profiles; final
bounded runtime measurement follows. Real-time execution, acoustic GPU porting,
32–256 scaling and Analytic retirement are not Phase 08 completion requirements.

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
precedes final bounded runtime measurements; the larger scaling campaign is deferred.
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

Phase 08 remains open. The user has approved the scope and budgets; this is not
implementation or admission evidence. R10's [[implementation_phases/r10-geometry-acoustics-integration#Remaining Phase 08 closeout gates|closeout table]] owns requirements and status.

### Remaining execution order

| Step | Work | Completion evidence |
| --- | --- | --- |
| 1 — Instantiate the approved matrix | Record concrete scenes, trajectories, DRR/bands, camera/array settings, valid references, scoring and trial counts before comparisons | Every mandatory condition and metric has a justified test/reference; no new approval needed for routine choices inside the approved scope |
| 2 — Integrate Steam NLOS | Production selected-route timing, visibility, ordinary motion/door updates, non-duplication and explicit coverage limits | Native delay/geometry controls and continuous update tests pass; no impossible shortcut arrivals |
| 3 — Qualify PRA diffuse extension | Shared spatial/temporal statistics, energy partition, normalization, visibility and representative weak-direct motion | Independent physical/statistical controls and approximation-impact comparisons pass; otherwise apply the approved blocker/decision rule |
| 4 — Qualify the combined producer | Integrate admitted direct/specular/NLOS/diffuse contributions on one clock, retaining source-stop tails, block equivalence, resets and environment isolation | Focused continuous-stream and integration checks pass with unchanged signal/observation contracts |
| 5 — Demonstrate Profile 1 | Observed audio guides camera search with explicitly simulated reference visual confirmation | Measured audio benefit, approximation budgets and honest missing/false/unconfirmed results under mandatory AV conditions |
| 6 — Demonstrate Profile 2 | Moving-array/source trials and untrained homing; two-source goal is an audible source without supplied identity | Motion/door cues and matched audio-disabled navigation comparisons pass; collisions, switching and timeouts remain visible |
| 7 — Complete 08.3 operation | Existing Python/Kit configuration, actionable diagnostics, capability failures and consumer-safe consolidation | Usable geometry-backed sensor-to-instrument chain; provider truth stays separate from observations |
| 8 — Close Phase 08 | Run affected native, scalar/CUDA, actual Sim/Lab/Kit and packaging checks; measure one/few-environment runtime and memory | Supported domain, failures and runtime limits documented; checks pass; local validated commits, no push |

Steps 2 and 3 include focused native checks before wider integration. Carry
lifecycle checks through development rather than postponing them to Step 8.
**Steps 1–6 close Milestone 2 only if both profiles and the integrated producer
pass. Steps 7–8 then close the whole phase.** Reuse still-valid evidence and rerun
affected checks when integration changes their boundary.

A Profile 1-only result is an intermediate delivery. A material mandatory-domain
failure, invalid reference or unresolved task-usefulness gap stays open; do not
remove the case, change the budget or substitute passing tensor checks. Report
perception/controller failures separately from acoustic failures. A larger PRA
fork or new provider evaluation requires the specific user decision in R10.

[[topics/onr-video-production#Remaining ONR deliveries after the R10 profile decision|ONR readiness]] remains separate per video. Existing-capability videos can proceed
through their own scene/media gates without waiting for all eight steps; this
plan update neither produces media nor approves an untested scene.

## Artifacts

This reference produces no independent artifacts. R10 owns all geometry-integration artifacts.

## Files

- `knowledge/wiki/implementation_phases/r10-geometry-acoustics-integration.md`
