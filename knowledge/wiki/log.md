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

## 2026-09-15 — update: Save Phase 08 Step 1 preparation

Preserve the approved domain and budgets. Record local Office/Hospital composition,
eight generic-rig USD layers, normalized existing stimuli, expanded workload counts
and a bounded native specular reference diagnostic that fails the target decay
bands. Keep unvalidated scene conditions and moving-room reference gaps explicit.
Actual Isaac validation and cost pilot await the user-selected manual reboot for
NVIDIA loaded/on-disk version mismatch. Step 1 remains incomplete; no Step 2+ work,
long campaign, physical acquisition or GPU-to-CPU workload substitution.

## 2026-09-15 — lint: Validate saved Step 1 checkpoint

Nine documentation/version tests pass. Wiki page links/index, ten finite 16 kHz
source files and fixed reference levels, 154 unique unready workload entries and
Markdown whitespace checked. Eight saved USD layers reopen with the camera forward
axis verified. Native PRA diagnostic outputs are retained as failed conditioning
evidence. GPU rendering, collision/trajectory validation and cost pilot remain
unexecuted; no model or task admission is claimed.

## 2026-09-15 — update: Phase 08 Step 1 after driver recovery

Verified recovered RTX 4090 CUDA/Isaac runtime after the user reboot. Saved controlled
USD layers, Office/Hospital queries, exact episode inputs and bounded reference
diagnostics. Completed 24 intermediate-only cost episodes and enumerated additional
mode/replay resource envelopes. Scene acoustic representation, banded decay/DRR and
reference gates remain open; rejected closed-door scalar energy is retained. No
model comparison, later-step implementation or broad campaign was performed.

## 2026-09-15 — lint: Post-reboot Step 1 preparation

All 42 wiki pages are indexed; internal targets and heading anchors resolve. Nine
documentation/version tests pass. Episode inputs, scorer/background controls, USD
composition and reference-overlay imports pass their bounded checks. Diff review
preserves approved decisions, raw assets, historical evidence and Step 2+ boundaries.

## 2026-09-15 — update: Lean Step 1 preparation closeout

Completed bounded Office/Hospital acoustic inputs through the existing 08.1 API,
corrected local USD overlay units/up-axis and checked native world coordinates.
Saved essential visibility/static path and direct/scattering diagnostics. Preserved
reference failures; assigned full-field conditioning and model-specific refinements
once to their later steps. Replaced blanket per-cell repetition with representative
family comparisons and conditional cost envelopes, retaining domain/budgets and
unresolved difficult strata. Step 1 preparation is complete under clarified scope;
no later model implementation, candidate comparison or extended campaign ran.

## 2026-09-15 — lint: Lean preparation and execution ownership

All 42 wiki pages are indexed and internal links/anchors resolve. Nine
documentation/version tests and 104 episode-input checks pass. All 131 affected USD
overlay roots have explicit meters/Z-up; proxy world coordinates and required
clear/blocked/open links pass. Diff review preserves raw/original assets, approved
numerical budgets and later-step gates; historical cost envelopes are superseded.

## 2026-09-15 — update: Step 2 native probe preparation

Recorded automatic Steam probe preparation, coverage errors, native interpolation and focused component controls; dynamic producer admission remains open.

## 2026-09-15 — update: Opt-in causal NLOS producer

Documented automatic probes, ABI 2 interpolation identity, surface-endpoint shortcut corrections, causal transport and live RTX lifecycle evidence. Step 2 motion/refinement qualification remains in progress.

## 2026-09-15 — update: Consistent native NLOS corridor visibility

Recorded the corner/weight-loss regression, centered native probe preparation and shared graph/export visibility bounds; retained failed evidence and the open refinement gate.

## 2026-09-15 — update: Native NLOS neighborhood selection

Recorded the traversal-order cutoff that omitted one side of a screen, native nearest-visible probe selection and added motion/identity/directivity regressions.

## 2026-09-15 — update: Step 2 selected-route transport closeout

Closed bounded NLOS transport controls, documented causal opening recovery, total
path bounds, native query caches and actual RTX Isaac evidence. Recorded probe
refinement sensitivity without claiming converged or calibrated door pressure;
diffuse, combined-model, reference and consumer gates remain separate.

## 2026-09-15 — lint: Step 2 closeout documentation

Verified wiki links/index coverage, repository references, whitespace and scope
against current tests and saved evidence. Final host checks pass 668 unit/contract,
336 integration and 58 release tests; native/producer checks pass 30 tests.
The clean-source wheel matches 183 Python modules and imports NLOS independently.

## 2026-09-15 — update: PRA native diffuse transport preparation

Documented checked pre-histogram band-energy capture, disjoint receiver ownership,
two-sided stochastic transport and the remaining shared-pressure qualification.
The existing specular producer and installed native providers remain preserved.

## 2026-09-15 — update: Step 3 diffuse statistical candidate stop

Recorded improvements in controlled source-motion and mirror-translation fields,
then the failed finite-rotation temporal-coherence gate. Independent quadrature
and native image-length checks pass; 12 fresh realizations at 1048576 rays retain
mean error 0.17045, 95% interval [0.16783, 0.17321], above 0.1. Applied the approved
stop rule; native preparation remains usable, while diffuse pressure, full energy,
producer, weak-direct observation and later consumer qualification remain open.
No replacement evaluation or broader transport solver was started.

## 2026-09-15 — lint: Step 3 bounded closeout

Wiki index/link checks and whitespace checks pass. The new native library passes
22 transport/specular/Geometry tests in the Isaac interpreter; 58 release and
three convolution tests plus repository Ruff checks pass. No live diffuse
simulation or CUDA observation qualification is claimed. New failed candidates
and reproduction reports remain in ignored local evidence; raw and historical
provider assets are unchanged.

## 2026-09-15 — update: Authorize targeted Step 3 observation impact

Record the user's decision to measure the current PRA candidate's bounded PCM
and observation impact before deciding on provider replacement. Preserve the
failed rotating-mirror diagnostic, domain, observation budgets and essential
physical/interface invariants. R10 and status now distinguish the authorized
follow-up from public diffuse admission and the earlier moving-ray failure.

## 2026-09-15 — experiment: Measure current PRA candidate observation impact

Preserve the native/statistical candidate and its failed rotating-mirror field
diagnostic. A separate scalar PCM harness supplies independent Lambertian/image
references, synthesis/energy/persistence checks, selected ray/update refinements
and actual RTX 4090 observations. Fresh confirmation uses 24 motion/two-source
episodes and 96 rotating/held-mirror episodes per condition, with both arrays.
The controlled rotating selected mixture passes all observation-impact budgets
at DRR about -15.7 dB; moving-source angular budgets pass, while several rates/p95
bounds remain inconclusive. No thresholds, budgets, provider or public SDK behavior
changed. Full D/room/energy/causal and AV/mobile utility qualification remain open.
The admission page owns the measured intervals, explicit reference limits and
consumer limitations; local evidence preserves 2304 multichannel streams.

## 2026-09-15 — lint: Targeted observation-impact evidence

Wiki links/index, changed-path scope, whitespace and evidence consistency checks
pass. The reference sampling replay reproduces its saved report; local scoring
tests, synthesis checks and Ruff pass. Scalar/CUDA parity and environment
independence use the actual RTX 4090. The confidence-interval plot was inspected.
Only canonical wiki files are tracked changes; experimental code/PCM remains in
the new ignored evidence directory. Raw, historical evidence and the existing
Obsidian metadata are preserved. No public provider admission or push is implied.

## 2026-09-15 — update: General PRA surface connection boundary

Added the checked private PRA segment-visibility binding for persistent surface
projection. Seven focused native tests pass, including both-sided closed/open/closed
partitions and a floor segment crossing a partition. General pressure qualification
is still in progress; the public diffuse option is not enabled.

## 2026-09-15 — lint: PRA surface connection documentation

Internal-link/index boundary checks and Markdown whitespace checks pass. The
native interface is documented separately from unqualified pressure synthesis.

## 2026-09-15 — update: Optional persistent PRA pressure candidate

Implemented native first-scatter quadrature, persistent object-local statistical
surface pressure and the opt-in D producer. Documented disjoint energy ownership,
filter power normalization and explicit approximation limits. Focused native,
analytic field and producer lifecycle checks pass; room and observation admission
remain pending. Historical prototypes and new general-field evidence are separate.

## 2026-09-15 — lint: Persistent PRA candidate documentation

Canonical wiki links/index, affected Ruff checks and whitespace checks pass.
The optional implementation is explicitly separated from pending admission.

## 2026-09-15 — update: Scale-invariant banded specular material filters

Independent room-reference conditioning exposed scalar-gain-dependent material
phase and lost negative directivity in banded specular synthesis. Normalize the
material spectrum, preserve the low-band DC endpoint and apply signed scalar gain
after minimum-phase conversion. Native polarity, half-gain and distance-scaling
regression checks pass; unchanged flat-material behavior retains its controls.

## 2026-09-15 — lint: Banded specular correction

The canonical documentation boundary, affected Ruff checks and whitespace checks
pass. The banded fix is separate from still-pending diffuse admission.

## 2026-09-15 — experiment: General PRA D candidate remains unadmitted

Completed the optional general field/producer and retained 36 passing focused
controls. Corrected surface projection visibility and banded specular material
phase. Conditioned an independent E0 room-pressure reference, then measured
pressure decay and actual RTX 4090 observations through orders 3/5/7 and targeted
4096/16384/65536-ray refinement. The final fixed-scene 96-episode comparison fails
spurious-update budgets on both arrays, with a separate raised-reference consumer
parity/count limit. Applied the approved stop rule; broader motion/room/two-source
qualification stays open. New evidence is isolated from historical prototypes.

## 2026-09-15 — lint: General Step 3 admission closeout

Canonical links/index, affected Ruff and whitespace checks pass. Current status,
R10, Phase 08, diagnostics and the admission record consistently distinguish the
implemented candidate from failed qualification. Historical evidence is preserved;
new confidence intervals are explicitly conditional on the frozen scene/field.

## 2026-09-16 — experiment: Step 3 practical significance before alternatives

Reanalyzed absolute extra-update rates and directional persistence, then replayed
four artificial late-response interventions with unchanged RTX 4090 perception.
Correcting 1 kHz decay alone has little effect; coherent late substitution recovers
most reference extras. Actual SquadBot adapter/search replay retains posterior
orienting cues, but does not measure physical turns or AV/mobile success. Corrected
the earlier task-easiness wording to distinguish observation impact from robot
outcomes. Retained failed/open qualification, assessed independent measured-data
options, and recorded the user-requested practical-impact continuation before any
provider decision. Historical evidence and the implementation remain unchanged.

## 2026-09-16 — lint: Practical-significance evidence

All five documentation-boundary checks, local diagnostic Ruff/compilation and
Markdown whitespace checks pass. Saved baseline binary outcomes match the original
GPU evidence; every intervention preserves the first 80 ms, and both decay changes
meet the original per-microphone tolerance. Raw/historical inputs are preserved;
new episode statistics, software decisions and prospective physical/closed-loop
validation are explicitly separated.

## 2026-09-16 — experiment: Bounded PRA head/camera diagnostics

Recorded the prospective less symmetric weak-direct comparison, sixteen geometric
AV episodes, targeted numerical refinements, direct-only consumer controls and
auxiliary MeshRIR measurements. Retained all failed/open limits; no provider,
localizer or acceptance-budget change. Refined confirmation is separately declared.

## 2026-09-16 — lint: Bounded AV diagnostic evidence links

Five documentation-boundary tests pass; canonical links, retained local evidence,
index coverage and diff whitespace checks pass. No raw knowledge material changed.

## 2026-09-16 — experiment: Refined AV confirmation supports retaining PRA

Recorded 192 fresh independent episodes on one refined native field, actual RTX
perception, whole-episode intervals, rare-event batch reproduction and measured
resumption benefit. Preserved the raised-only inconclusive interval, original
physical/observation counterexample and remaining domain/reference limits.
Recommendation: retain PRA; no provider evaluation or budget change.

## 2026-09-16 — lint: Refined AV confirmation closeout

Eight documentation/evaluator checks pass. All local study scripts pass Ruff;
canonical links, evidence paths, index coverage and diff whitespace are checked.
The Italian result figure was visually inspected; no raw knowledge changed.

## 2026-09-16 — update: Approved diagnostic role for the Step 3 cube failure

Recorded the user's acceptance revision: retain the smooth E0/C02/R05 late-response
and extra-update FAIL results as diagnostics without requiring their correction
for Step 3 admission. Structural invariants, representative conditions and
numerical margins remain binding. Synchronized the decision, protocol, R10/08,
status, evidence interpretation, index and producer diagnostic wording; diffuse
remains experimental and not_admitted. No acoustic algorithm or historical data
changed. The next qualification work addresses material measurement defects before
shared motion/observation checks, reusing valid evidence.

## 2026-09-16 — lint: Cube diagnostic decision consistency

Five documentation-boundary tests and all 19 wiki heading links pass. Checked
index coverage, allowed scope/tree, append-only history and diff whitespace.
Historical measurement tables, domain and numerical-budget tables are unchanged.
The producer's only code change is diagnostic text, verified by syntax-tree
comparison, compilation and Ruff; no acoustic qualification was rerun or claimed.

## 2026-09-16 — update: Compact Geometry Acoustics experiment pages

Condensed the trial protocol and admission record without changing scenarios,
acceptance criteria or measured outcomes. Added section navigation, consolidated
correction/preparation prose into tables, distinguished historical milestones from
current admission, and moved the replay index to the end. Superseded per-cell cost
expansions remain in the saved pilot report. Updated index descriptions; contracts,
phase plans, SDK code and original evidence are unchanged.

## 2026-09-16 — lint: Geometry editorial preservation checks

All 42 wiki pages, 237 wikilinks, 29 heading links and index coverage pass checks.
Preserved all original scenario/result tables except the superseded cost expansion
and the summary wording that now distinguishes intermediate from later NLOS
qualification. Checked 22 explicit evidence paths, replay directories, headings,
allowed scope, append-only history and diff whitespace. No runtime qualification
was rerun or implied by this editorial change.

## 2026-09-16 — update: Stable scalar and CUDA perception measurements

R10 diagnostics isolated ill-conditioned WPE normal equations and equal-score
peak selection. Documented weighted QR/pseudoinverse and float64 peak arithmetic,
unchanged perception parameters/public tensors, 27 actual RTX tests and 15 scalar
tests. Earlier observation intervals and throughput retain their historical solver
scope; focused replay is recorded separately from physical admission.

## 2026-09-16 — lint: Numerical correction documentation

Five documentation-boundary tests, 42-page index coverage, 240 wikilinks and
31 heading links pass. Checked whitespace and kept the numerical correction
separate from historical performance, physical fidelity and Step 3 admission.

## 2026-09-16 — experiment: R10 measurement reliability

Recorded the corrected scalar/CUDA direct and cube replay, maintained same-PCM
parity, targeted angular-cache/early-response isolation and focused AV replay.
The cache's full-pressure isolation check remains failed; actual producer positions
or separately qualified sampling govern future motion comparisons. Historical
observation intervals retain the preceding consumer. Updated R10/08, current status,
Lab runtime and the replay index without changing physical budgets or cube status.

## 2026-09-16 — lint: Measurement evidence and current limitations

Five documentation-boundary tests, all 42 indexed pages, 245 wikilinks and
36 heading links pass. Verified final replay/cost artifacts, unchanged task metrics
in the four selected AV programs, evidence directory references and whitespace.
Kept the failed cache-isolation result, historical interval scope, expensive stable
runtime and still-open physical admission explicit. Raw and historical evidence
were not edited; no complete acoustic-matrix or 192-episode rerun is claimed.

## 2026-09-16 — experiment: Actual-producer motion controls

Recorded the predeclared C03/C04 panel, analytic retarded-plane transport and
independent dense-quadrature checks, dynamic lifecycle and exact-pose replay,
corrected RTX diagnostic observations and targeted 10/5/2.5 ms refinement.
Native room cost limits the allocation before full routes without valid moving-
room references. The fresh confirmation and room closeout remain separate from
this validated checkpoint; no admission or provider change is claimed.

## 2026-09-16 — lint: Joint-control checkpoint

Five documentation-boundary checks, 40 canonical indexed pages, 247 wikilinks and
38 heading targets pass. Verified new evidence paths, quantitative control values,
reference independence boundaries and whitespace. Raw and historical evidence,
physical budgets and the cube diagnostic decision remain unchanged.
