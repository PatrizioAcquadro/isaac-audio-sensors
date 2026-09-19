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

## 2026-09-15 — update: Trial preparation and selected-route NLOS

Completed bounded Phase 08 preparation and the RTX pilot. Integrated native Steam probes, route timing and immutable visibility; corrected coverage/weight/ordinary-opening failures. Step 2 closes selected-route transport with explicit probe-pressure limits, not calibrated diffraction or full-room admission.

## 2026-09-15 — experiment: Persistent PRA pressure and diagnostic failures

Implemented optional native shared pressure and corrected banded material phase. Rotating-mirror coherence and conditioned-cube decay/observation comparisons failed their original criteria. Targeted weak-direct impact evidence supported continued PRA work; no replacement provider was selected.

## 2026-09-16 — experiment: Motion, measurement reliability and bounded AV

Refined head/camera evidence supported PRA retention with rare false association and stratum limits. Corrected WPE conditioning/peak ties, then completed actual-producer C03/C04 confirmations, finite-field follow-ups and bounded room/property checks. Fixed the native door-jamb projection leak. Results and uncertainty are consolidated in [[experiments/geometry-acoustics-admission|admission evidence]].

## 2026-09-16 — update: Step 3 admission with explicit limitations

After a bounded reference-feasibility stop, the user declined a separate room-field reference and accepted full-room moving equivalence as NOT VALIDATED and non-blocking. Step 3 is PASS with cube/mirror diagnostic limits; combined producer and complete AV/mobile remain open. No new experiment accompanied this decision.

## 2026-09-16 — update: Consumer-safe workspace and wiki cleanup

The user explicitly authorized this one-time condensation of existing log entries. Current contracts, future requirements and decisive results now have separate canonical owners. Historical tracked detail remains at `9395b1c`; concluded ignored outputs are removed, not archived in Git. Retain future R10 inputs/controls, ONR regeneration/deliveries and active Lab parity recordings. Removed historical route re-exports and duplicate stream cleanup without changing public interfaces.

## 2026-09-16 — lint: Verify retained workspace and canonical links

All 42 wiki pages are indexed, internal links/anchors and active source references resolve.
Host checks pass (668 unit/contract, 336 integration, 58 release), as do 228 Isaac tests,
optional audio and real RTX Sim/Lab/Kit/NLOS gates. Retained inputs pass 104 episode
checks, 131 USD compositions, visibility, producer lifecycle and independent quadrature.
ONR frame metadata is migrated locally to v4 with unchanged PCM and observations;
current-source replay and bounded media recomposition validate retained paths.

## 2026-09-19 — update: Step 4 combined native stream

Enabled joint NLOS/diffuse configuration in the existing Geometry producer, retained
component diagnostics and made failed reads discard the environment's partially
advanced state. Thirteen combined controls plus affected native regressions pass
(61 native tests total); 14 convolution/route unit tests pass. Live Sim/Lab
qualification and Step 4 admission are pending. Defaults and public schemas are unchanged.

## 2026-09-19 — update: Combined Sim and Lab runtime controls

Extended existing smoke entrypoints with explicit combined modes. Actual RTX 4090
Sim passes dynamic door, tails and reset; square Lab passes two-environment
same-PCM scalar/CUDA parity, non-consuming reads, partial-reset continuation,
independent native replay and reordered/+60 dB-neighbour observation isolation.
Measurements and task-fidelity boundaries are recorded in the admission page.

## 2026-09-19 — update: Close Phase 08 Step 4

Step 4 is PASS for combined streaming and integration. Raised CUDA Lab also passes
same-PCM parity and lifecycle/isolation, with maximum angular difference 0.00854°
and independent PCM error below 2.8e-9. Updated sequence, status, technical contract
and admission evidence; Step 5 AV usefulness is next. Full-room moving equivalence
and the existing cube/mirror/NLOS limits remain explicit. No defaults, public
schemas, provider physics or acceptance budgets changed.

## 2026-09-19 — lint: Verify Step 4 closeout

All 42 wiki pages are indexed; internal links/anchors and new runtime/test
references resolve. Raw material is unchanged. `make check` passes (668/336/58),
61 affected native tests and 14 targeted stream/route tests pass, and actual RTX
Sim plus square/raised Lab gates pass. Documentation preserves component limits
and leaves Steps 5–8 open; whitespace and repository lint checks pass.

## 2026-09-19 — update: Complete 08.2 sensor propagation and integration

08.2 is complete within its documented acoustic and integration bounds. Current
status, phase plans, SDK criteria, fixture documentation and README agree on the
implemented producer, recorded native/RTX evidence and remaining limitations.
08.3 operating workflow, diagnostics and runtime/distribution closeout are next.

## 2026-09-19 — lint: Verify 08.2 documentation closeout

All 42 wiki pages are indexed; internal links/anchors and affected source references
resolve. Active documentation consistently identifies 08.3 as the next phase of
work. Existing Step 4 native, Sim/Lab and host-check records were inspected; no
runtime tests were rerun for these documentation-only changes. Raw material and
runtime code are unchanged; whitespace checks pass.


## 2026-09-19 — update: Implement Geometry operating integration

Documented controller-owned prepared scenes, Python/Kit native configuration,
capability checks, settings persistence and separate simulation diagnostics.
NLOS coverage now preserves the historical block snapshot. Runtime, cost and
clean-source distribution closeout remain explicitly in progress.

## 2026-09-19 — lint: Check operating integration documentation

All canonical pages remain indexed and internal wikilink targets resolve. Updated
source/API references exist; raw material is unchanged. Host checks pass
(677 unit/contract, 336 integration, 58 release); the focused controller/native
checks preserve configuration, session lifetime and historical diagnostics.
