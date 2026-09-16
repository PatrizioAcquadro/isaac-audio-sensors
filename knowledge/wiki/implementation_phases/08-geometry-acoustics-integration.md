# Implementation Plan 08 — Geometry Acoustics Integration

Status: 08.1 and the 08.2 intermediate complete; Milestone 2 and 08.3 open.

## Objective

Sequence reference for [[implementation_phases/r10-geometry-acoustics-integration|R10]]. Read [[decisions/robot-audition-fidelity|the approved domain/budgets]] first; both profiles remain required.

## Subphase 08.1 — Implement R10.1

#### Implementation

Completed prepared USD/native scene and shared authoring panel.

#### Key Decisions

Preserve it during propagation integration.

#### Problems / Limitations

Preparation is not signal qualification.

## Subphase 08.2 — Implement R10.2

#### Implementation

Complete native NLOS/diffuse extensions, combined streaming and AV then mobile task gates.

#### Key Decisions

Keep the working intermediate and Analytic; apply the approved provider stop rule.

#### Problems / Limitations

Experimental capabilities are not enabled by a scope decision.

## Subphase 08.3 — Implement R10.3

#### Implementation

Complete operating workflow, diagnostics, consolidation and bounded runtime/packaging closeout.

#### Key Decisions

Slower-than-real-time simulation is permitted; no large-batch or acoustic GPU-port requirement.

#### Problems / Limitations

ONR deliveries retain separate scenario/media gates.

## Phase 08 closeout status

Both profiles and all applicable gates must pass. Scope approval is not implementation.

### Remaining execution order

Step 1 [[experiments/geometry-acoustics-trial-protocol|simulation preparation is complete]]
under the user's clarified lean scope (2026-09-15). Concrete inputs, bounded
Office/Hospital acoustic representations, generic footprint/visibility checks,
static reference diagnostics and the RTX cost pilot are saved. The local USD
units/up-axis authoring error is fixed; 08.1 SDK behavior was not changed.
Full-field conditioning/DRR and moving-reference gaps still block affected later
comparisons and have explicit Step 2/3 owners. No later model or consumer was
implemented or qualified. Representative family sampling replaces blanket per-cell
repetition without changing domain/budgets or hiding unresolved difficult strata.

| Step | Work | Completion evidence |
| --- | --- | --- |
| 1 — Instantiate the approved matrix | Record concrete scenes, trajectories, DRR/bands, camera/array settings, valid references, scoring and trial counts before comparisons | Every mandatory condition/metric has concrete inputs, bounded controls and an explicit valid/unavailable reference entry with later qualification ownership; no full-model implementation inside preparation |
| 2 — Integrate Steam NLOS (selected-route transport complete) | Production selected-route timing, visibility, ordinary motion/door updates, non-duplication and explicit coverage limits | Native delay/geometry, continuous update and actual RTX Isaac controls pass; refinement measured, door pressure remains probe-sensitive and uncalibrated |
| 3 — Qualify PRA diffuse extension | Shared spatial/temporal statistics, energy partition, normalization, visibility and representative weak-direct motion | Binding physical/statistical controls and representative approximation-impact comparisons pass; the recorded cube late-response mismatch is diagnostic under the approved decision |
| 4 — Qualify the combined producer | Integrate admitted direct/specular/NLOS/diffuse contributions on one clock, retaining source-stop tails, block equivalence, resets and environment isolation | Focused continuous-stream and integration checks pass with unchanged signal/observation contracts |
| 5 — Demonstrate Profile 1 | Observed audio guides camera search with explicitly simulated reference visual confirmation | Measured audio benefit, approximation budgets and honest missing/false/unconfirmed results under mandatory AV conditions |
| 6 — Demonstrate Profile 2 | Moving-array/source trials and untrained homing; two-source goal is an audible source without supplied identity | Motion/door cues and matched audio-disabled navigation comparisons pass; collisions, switching and timeouts remain visible |
| 7 — Complete 08.3 operation | Existing Python/Kit configuration, actionable diagnostics, capability failures and consumer-safe consolidation | Usable geometry-backed sensor-to-instrument chain; provider truth stays separate from observations |
| 8 — Close Phase 08 | Run affected native, scalar/CUDA, actual Sim/Lab/Kit and packaging checks; measure one/few-environment runtime and memory | Supported domain, failures and runtime limits documented; checks pass; local validated commits, no push |

Step 3 was attempted on 2026-09-15: native transport preparation passes, but the
shared statistical candidate fails controlled temporal coherence during mirror
rotation after independent reference and ray-count refinement. The user then
authorized targeted observation comparisons before a provider decision. Those
comparisons now pass all observation-impact budgets for a controlled rotating
selected mixture on both arrays with weak direct; source-motion angular budgets
also pass, while several rates/p95 bounds remain inconclusive. The physical
failure is retained. The resumed work now implements the general shared field
and optional D producer, with native visibility, analytic plane/energy and
producer lifecycle checks. The conditioned smooth-room pressure-decay and RTX
observation-impact comparison fails the original criteria after order/ray refinement.
The user subsequently approved its
[[decisions/robot-audition-fidelity#Step 3 cube diagnostic decision (2026-09-16)|diagnostic role]]:
matching that late response is no longer a prerequisite for Step 3. The
2026-09-16 user-requested practical-impact
follow-up retains the candidate: late-response diagnostics and downstream software
replay are complete. Bounded geometric head/camera diagnostics now measure task
consequences; a fresh refined confirmation supports retaining PRA while keeping
individual-stratum and numerical/consumer limits explicit. Step 3 remains open
for binding field controls and representative C03/C04, room and two-source
observations. Address measurement defects before affected comparisons and reuse
episodes/PCM for field and observation checks. Complete profile usefulness belongs
to Steps 5–6; matched physical transfer is a separate claim. The
[[experiments/geometry-acoustics-admission|admission record]] records the measured
boundary and reusable native changes.

Steps 2 and 3 include focused native checks before wider integration. Carry
lifecycle checks through development rather than postponing them to Step 8.
**Steps 1–6 close Milestone 2 only if both profiles and the integrated producer
pass. Steps 7–8 then close the whole phase.** Reuse still-valid evidence and rerun
affected checks when integration changes their boundary.

A Profile 1-only result is an intermediate delivery. A material mandatory-domain
failure under the current decision, invalid reference or unresolved task-usefulness
gap stays open; do not remove a mandatory condition, change numerical margins or
substitute passing tensor checks. Report
perception/controller failures separately from acoustic failures. A larger PRA
fork or new provider evaluation requires the specific user decision in R10.

[[topics/onr-video-production#Remaining ONR deliveries after the R10 profile decision|ONR readiness]] remains separate per video. Existing-capability videos can proceed
through their own scene/media gates without waiting for all eight steps; this
plan update neither produces media nor approves an untested scene.

## Artifacts

R10 and its linked experiment record own evidence; this page owns sequence only.

## Files

`knowledge/wiki/implementation_phases/r10-geometry-acoustics-integration.md`.
