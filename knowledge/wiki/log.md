# Knowledge Log

Compacted on 2026-09-11 at the user's explicit request. Routine lint entries and
repeated run narratives are consolidated; canonical pages retain decisions,
results and evidence pointers. The full earlier log is recoverable at `5cfe48d`.
Future entries should remain short and append-only; this compaction is not a
standing authorization to rewrite history.

## 2026-08-20 — update: Product and knowledge boundaries

[[implementation_phases/r2-fast-test-architecture|R2]] separated test lanes;
[[implementation_phases/r3-product-boundary-cleanup|R3]] removed campaign payload;
[[implementation_phases/r4-documentation-consolidation|R4]] established canonical wiki ownership.

## 2026-08-21 — update: Runtime ownership and release

[[implementation_phases/r5-semantic-component-refactor|R5]] consolidated subsystem
APIs/lifecycle. [[implementation_phases/r6-packaging-and-release|R6]] delivered
clean-source Python/Kit and historical v2.0.0 publication (`583d66e`).

## 2026-08-27 — update: Maintainable consumers and acoustic contracts

Aug 24–27 cleanup aligned native Kit audition, source organization, release tools,
gain/directivity and snapshot ownership. Current behavior lives in
[[topics/system-architecture|Architecture]], [[topics/acoustic-modeling|Acoustic Modeling]]
and [[topics/validation-and-release|Validation and Release]].

## 2026-09-01 — update: Explicit environments and analytic propagation

[[implementation_phases/r7-acoustic-environment-contract|R7]] made environment
resolution explicit/fail-closed; [[implementation_phases/r8-analytic-acoustics-backend|R8]]
consolidated analytic solvers and direct-only partition attenuation.

## 2026-09-03 — update: Provider selection and observed-only boundary

[[implementation_phases/r9-geometry-acoustics-provider-selection|R9]] selected bounded
Steam capabilities; R9.4 ran between 02.1 and 02.2. [[implementation_phases/02-signal-and-perception-architecture|02]]
separated PCM/perception and removed the legacy bridge. Later R10 withdrew stronger
reflection/NLOS timing interpretations; archived reports remain unchanged.

## 2026-09-04 — update: Activity, direction and datasets

[[implementation_phases/03-audio-activity-detection|03]] integrated fixed-threshold
Auditok; [[implementation_phases/04-observed-direction-estimation|04.1–04.3]] qualified
nominal DOA roles but failed robustness. [[implementation_phases/05-ground-truth-and-learning-datasets|05]]
separated truth/learning inputs; 06.1 established common signal continuity.

## 2026-09-07 — experiment: Physical signal comparison

[[experiments/physical-signal-comparison|25-take real/sim comparison]] passed software
parity but exposed weak-level activity mismatch. Gains were rejected/inconclusive;
raw capture retained, no general physical transfer claim.

## 2026-09-08 — experiment: Stable multisource reference and Lab projection

07.1 projected observed events. [[experiments/04-4-multisource-localization|04.4]]
recorded failed candidates, then two fresh 24-group confirmations for the maintained
stable-source WPE/group-sparse reference. General temporal behavior stayed open.

## 2026-09-09 — update: Continuous timing, runtime correctness and ONR

[[decisions/continuous-acoustic-clock|Continuous propagation]] fixed per-window
arrival loss. Confidence null/zero and PhysX solid occlusion were corrected.
Temporal candidates failed; user admitted bounded 07.2 and suspended that research.
[[topics/onr-video-production|ONR revised videos 1–3]] completed with saved scope/QA.

## 2026-09-10 — update: Lab/GUI closeout and Geometry intermediate

[[experiments/lab-perception-runtime|07.2 practical batches]] retained float64 WPE;
07.3 completed observed GUI and consumer cleanup. R10 scene preparation completed;
[[experiments/geometry-acoustics-admission|native failures/corrections]] admitted only
Steam direct/transmission + PRA specular streaming, with actual Isaac/CUDA checks.

## 2026-09-11 — experiment: Native route and diffuse motion limits

[[experiments/geometry-acoustics-admission|Selected-route timing and interception]]
passed bounded controls; NLOS arrival direction improved. PRA shared pressure still
biased weak-direct moving observations; first-scatter anchors did not solve later
persistence. No replacement provider was evaluated in these extension runs.

## 2026-09-11 — update: Approved task-domain ambition

[[decisions/robot-audition-fidelity|Approved both profiles, domain, budgets and stop rule]]
(`5cfe48d`). Exact dynamic completeness became stress scope; retain Analytic,
allow slower-than-real-time simulation, defer large-batch/GPU-port work. Maintenance
through `523695c` preserved the intermediate with host/native/actual packaged Kit gates.

## 2026-09-11 — update: Compact implementation knowledge

At user request, compact all plans/status/log; move binding fidelity decisions,
reusable Geometry contract and decisive provider/physics/physical/Lab evidence to
canonical owner pages. Preserve unresolved requirements and original local artifacts;
full prior prose remains in Git. No code, raw material, AGENTS.md or media changes.

## 2026-09-11 — lint: Validate compact knowledge

All 41 pages indexed; page/heading links and approved-scope/evidence checks pass.
Five documentation-boundary tests, version sync and whitespace pass. Documentation
only; no acoustic/runtime/media qualification rerun. Raw and local evidence untouched.

## 2026-09-15 — update: Define Phase 08 trials

Record the user's preferences in the canonical Geometry trial protocol. Primary
IHMC sources motivate building-exploration scenes and signals; manufacturer RGB
specifications motivate a generic 90-degree camera with 70/110-degree sensitivity.
Declare geometry, trajectories, sources, levels, both consumers, scoring, reference
validity gates and a cost-first sample plan. Preserve the approved domain/budgets.
Scene realization, acoustic conditioning, full reference validity and cost pilot
remain open; no production, native, perception or runtime qualification changes.

## 2026-09-15 — lint: Validate trial protocol

Nine documentation/version tests pass. Wiki page/heading links, 23 matrix row IDs,
maintained array coordinates, existing signal paths, L-corridor geometry, 10 m
range, pinhole FOV and binary-interval examples checked. Whitespace passes.
No simulation, reference qualification, statistical campaign or media run performed.
