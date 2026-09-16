# Robot-Audition Fidelity

Status: approved by the user on 2026-09-11, with explicit Step 3 admission revisions
on 2026-09-16. Step 3 is PASS under the current decision below; combined-producer
and AV/mobile qualification remain pending. This is the canonical R10
scope/acceptance decision; the admission record owns implementation evidence.
It supersedes historical requirements for complete dynamic acoustic physics.

## Purpose and profiles

Qualify a scientifically useful robot-audition signal producer for localization,
AV perception and robot learning. Both profiles are required, in this order:

| Profile | Required consumer evidence |
| --- | --- |
| 1 — AV attention/search | Fixed base, rotating head/array, stationary/moving and intermittent sources, distractors: useful search direction, camera acquisition, false/unconfirmed association and reacquisition |
| 2 — Mobile audition | Translating/rotating receiver, moving sources, connected rooms, corridors and ordinary doors: cue quality and untrained audio-guided homing/navigation |

They use one acoustic implementation. Profile 1 alone is an intermediate result.
SquadBot's fixed-Alex003 scope motivates priority 1; robot adapters, graph semantics
and hardware acceptance remain downstream. The approved downstream source is
[Alex003 Purdue/IHMC scope](https://github.com/PatrizioAcquadro/squadbot-av/blob/0de1e40aa50a1781bc61b4be4deb6bc04c55b8e8/implementation_phases/_program/alex003_purdue_ihmc_integration_scope.md).
Out-of-FOV and physically hidden are
different: turning need not reveal a source behind a wall. NLOS arrival direction
may point toward an opening; score it separately from hidden-source bearing.

## Approved operating domain

| Dimension | Mandatory representative coverage | Stress / separate qualification |
| --- | --- | --- |
| Geometry | Rooms with characteristic sizes around 3–10 m; connected rooms/corridors | Arbitrary large/complex spaces |
| Source–array distance | Approximately 0.5–10 m; indirect paths may be longer | Near-contact and longer-range extensions |
| Source speed | Stationary through 1.5 m/s | Faster motion |
| Receiver motion | Fixed/rotating in Profile 1; translation through 1 m/s in Profile 2; rotation through 90 degrees/s | Faster motion |
| Doors/obstacles | Ordinary moving obstacles; opening/closing over roughly 0.5–3 s | Extreme asynchronous openings during sound flight |
| Sources | One and two, sustained/intermittent, including distractors | Three sources |
| Reverberation | Target banded decay around 0.2–0.8 s | Around 1.2 s |
| Conditions | Dominant direct, weak direct, reverberation, physical occlusion and changing/sustained NLOS | Never silently omit weak-direct motion |
| Arrays | Maintained four- and five-microphone layouts as initial references | Other layouts need evidence, not API restrictions |

These are approved engineering test bounds, not partner specifications or measured
capabilities. Use a compact matrix with interior/boundary cases and meaningful
interactions, not every Cartesian combination. Before candidate comparisons,
record exact geometry/trajectories, DRR, banded decay, source content/levels, array
spacing, perception bands, camera FOV/joint limits, scoring, reference validity and
independent trial counts. Routine choices inside this scope need no new approval.
Changing the domain or budget requires the user; never tune them after a failure.

The [[experiments/geometry-acoustics-trial-protocol|2026-09-15 trial protocol]]
instantiates the user's scene/rig/content preferences and representative operating
values within this scope. It owns exact scenarios, camera selection, scoring and
sample planning; these choices do not change the budgets below or admit a provider.
The current preparation is simulation-only on the local machine, reuses existing
NVIDIA Office/Hospital before considering new environments, and requires no physical
measurement, new recording, purchase or hardware work. Reference gaps stay explicit;
trial preparation does not authorize subsequent model implementation/qualification.
The user's lean follow-up assigns bounded fixture checks to Step 1 and full-field
qualification once to its later owning step. The protocol now uses representative
family comparisons, retaining difficult strata and explicit per-cell uncertainty;
family pooling does not claim every cell meets a 5-point bound. Numerical budgets
and domain stay unchanged, and unavailable references still block affected claims.

## Physical and interface invariants

- One causal emission/reception clock; meaningful dominant-path delays and TDOA.
  Apply physical delay once; never substitute Euclidean distance for a detour.
- Sustained visibility and declared transmission; no unexplained opaque-wall
  leakage. Direct/transmitted, reflected/scattered and deviation contributions
  have disjoint ownership and no duplicate energy, attenuation or directivity.
- A valid shared microphone field: co-location, spatial/temporal statistics,
  physical energy normalization and convergence. No independent-mic noise followed
  by covariance repair, fitted gain, or smoothing that hides incorrect timing.
- Finite PCM, source-stop tails, block continuity, unchanged refresh reproducibility,
  reset/partial reset and independent environments; coherent AV timestamps.
- Public PCM, observations, recordings and Lab schemas stay unchanged. Provider
  paths, source IDs, schedules and hidden bearings remain diagnostic/scoring-only.
- Explicit material, coverage and numerical limits; unavailable requested features
  fail visibly. Nominal materials are not measured physical calibration.

Quasi-static geometry, finite reflection order and statistical late reverb are
eligible approximations, not automatic passes. Exact late phase and full moving-
boundary wave physics are unnecessary if the relevant cues/statistics survive.
One-sample exported-route timing and 0.1 controlled isotropic complex-coherence
checks keep their specific meanings. Neither alone certifies task fidelity;
arbitrary rooms must not be forced to have isotropic covariance.

## Approved approximation-impact budgets

| Quantity | Allowed change from a valid matched reference |
| --- | --- |
| Mean direction error | Within 5 degrees |
| 95th-percentile direction error | Within 10 degrees |
| Missing and spurious observation rates, separately | Within 5 percentage points |
| Visual-acquisition success | Within 5 percentage points |
| Added acoustic/perceptual latency | At most one observation update; about 100 ms at the maintained 10 Hz |
| Navigation success | Within 5 percentage points |
| Navigation time and path length | Within 10 percent |

These are approximation effects, not absolute DOA or total reaction-time promises.
Use paired independent trials, 95% confidence intervals and predeclared latency/
timeout handling. Negligible-impact intervals must fit the budget; inconclusive
precision is not a pass. Inspect both signs of change: an artifact can make a task
artificially easier. Keep weak-direct/occluded strata, misses, extras, ambiguity,
collisions and false confirmations visible. Do not treat adjacent frames as
independent trials or average away a failed mandatory condition.

The Step 3 cube decision below changes the admission role of one recorded
late-response comparison. It preserves these numerical margins and their
application to the remaining representative conditions.

References must be valid for the property: use controlled geometry/native or
analytic references, independent delay/spatial checks and sampling/update
refinement. Neither another provider nor the intermediate implementation is a
universal room oracle. Missing reference validity remains an evidence gap.

Task utility is a separate gate: predeclare a primary endpoint, compare the same
consumer with/without audio, report benefit magnitude, uncertainty and tradeoffs.
There is no universal absolute success percentage; two equally failing variants
do not prove usefulness. Greater realism need not improve every localization score.

## Reference consumers

Profile 1 uses observed audio to orient, then a clearly labeled simulated visual
reference constrained by FOV, visibility and declared latency. Visual annotations
cannot guide acoustic search or become audio estimates. No learned recognizer,
semantic tracker or complete SquadBot graph is required.

Profile 2 uses an untrained scripted direction follower, geometric collision
avoidance and exploration when cues are absent. Start with single-source homing;
with two sources, reach an audible source without supplied semantic identity.
Score switching/indecision as well as success, collisions, timeouts and efficiency.
The audio-disabled control has the same non-audio information and constraints.

Keep the maintained localizer. If physics passes but perception/controller limits
prevent benefit, identify that cause and leave the usefulness gate open; do not
silently start general perception research.

## Step 3 full-room limitation and admission decision (2026-09-16)

After the bounded reference-feasibility stop, the user explicitly declined a new
independent full-room moving reference and changed this property's admission role.
This decision supersedes the earlier instruction below to retain it as a blocker.

**Representative full-room pressure/observation equivalence is a known,
non-blocking limitation: NOT VALIDATED, never PASS.** This includes the unresolved
joint moving-room reference, its dependent room conditioning and complete matched
full-D route comparisons. Their absence is documented, not replaced by a claim
that static integration, geometry visibility or controlled-plane results validate
the complete moving field. The intended domain stays recorded; demonstrated
coverage remains bounded by the evidence.

| Requirement | Current Step 3 admission role |
| --- | --- |
| Shared field/persistence, causal timing and lifecycle, opaque visibility, disjoint energy ownership and native/filter normalization | Binding; structural defects remain blockers |
| Qualifiable controlled spatial/temporal statistics, band energy/decay, numerical refinement and observation impact | Binding within property-valid references and the approved representative allocation |
| Representative full-room pressure/observation equivalence | Known limitation, NOT VALIDATED; non-blocking for Step 3 |
| Recorded cube late-response failure and earlier selected rotating-mirror discrepancy | Retain their separately accepted diagnostic roles and original failed measurements |
| Material errors demonstrated in representative scenarios | Binding; new failures do not inherit either limitation's non-blocking status |
| Combined producer, AV and mobile usefulness | Separate Steps 4–6; unaffected by Step 3 admission |

No numerical tolerance, perception parameter or previously applicable observation
budget changes: retain complex error 0.1 where applicable, decay tolerance
`max(0.03 s, 15% of target)`, omitted energy below 0.1%, and independent-episode
95% intervals for mean/p95 angles (5/10 degrees), separate miss/extra rates
(5 percentage points each) and added latency (100 ms). An unconditioned room
recipe is not evidence of meeting its nominal decay target. This decision does
not waive energy-accounting defects or turn unresolved measurements into passes.

The user authorizes formal Step 3 PASS if the retained evidence leaves no other
binding requirement open. The
[[experiments/geometry-acoustics-admission#Step 3 formal admission (2026-09-16)|closeout review]]
records that outcome and the exact qualified scope. Reopen affected qualification
for a demonstrated structural defect or confirmed material representative error;
do not infer harmlessness throughout the domain from this acceptance decision.
No new tests, reference development or provider evaluation are authorized for
this closeout unless another actual blocker emerges. Diffuse remains opt-in;
this decision neither enables defaults nor admits the combined producer.

## Step 3 cube diagnostic decision (2026-09-16)

The user approved retaining the conditioned cube failure as a documented model
limit and diagnostic, without requiring its correction to continue or close
Step 3. This supersedes the earlier automatic stop on that result. It does not
by itself admit the renderer or establish that its tail is harmless throughout the
approved domain.

**Scope:** the general D candidate's smooth, symmetric 3 m E0/C02 room, centered
source/receiver axis, zero scattering, S0 Gaussian stimulus and R05 target. The
recorded late pressure decay/energy differences and spurious-update differences
on both arrays remain **FAIL under the original criteria; diagnostic for current
admission**. Neither the data nor the original thresholds are rewritten. The
room and its results stay in the evidence inventory; the 3 m domain boundary,
smooth surfaces and weak direct are not removed from supported-domain coverage.

### Requirements at the cube decision

The later full-room decision above governs current admission. This table records
the narrower revision made at the cube decision.

| Check | Current admission role |
| --- | --- |
| Causal delays/TDOA, visibility, disjoint energy ownership, native/filter normalization, shared microphone field and lifecycle | Binding, including in the cube; useful task behavior cannot excuse a structural defect |
| Controlled spatial/temporal statistics and representative band energy/decay | Binding under property-valid references; retain the controlled isotropic 0.1 check and the earlier separate rotating-mirror impact decision |
| Late pressure and extra-update agreement in the recorded cube comparison | Diagnostic; meeting the original tolerances in this comparison is not required for Step 3 admission or PRA retention |
| Representative motion, rooms, both arrays, one/two sources and weak-direct observations | Binding; retain the mean/p95 angle, separate miss/spurious and added-latency budgets with independent-episode 95% intervals |
| Combined producer and full AV/mobile utility | Separate Steps 4–6; bounded AV diagnostics do not close these gates or add them to Step 3 |

The pressure-energy difference from a coherent reference is distinct from an
energy-accounting or synthesis-normalization defect. The latter remains blocking.
Keep the decay tolerance `max(0.03 s, 15% of target)` when claiming a target and
retain representative 0.2–0.8 s coverage. Report the cube's actual decay and failed
target; do not relabel it as a successful 0.5 s room. No global decay/coherence
tolerance or observation budget is increased.

### Basis and reopening rule

The [[experiments/geometry-acoustics-admission|recorded investigation]] shows that
correcting 1 kHz decay alone does not recover the reference's extra estimates.
Replacing the entire late response changes several properties together, so it
does not isolate a single correction. Refined speech/head-motion evidence in a
less symmetric room preserves bounded AV benefit and does not reproduce the large
cube discrepancy. This supports accepting a bounded approximation, not declaring
the cube reference invalid or claiming physical transfer. The rare false
association and raised-only inconclusive interval remain visible.

Do not spend open-ended effort matching that late response. Reopen correction
when a structural defect is demonstrated or the approximation causes a
reproducible failure of a binding budget in required representative conditions.
Keep artificially beneficial changes visible as well as harmful ones. New
failures do not automatically inherit diagnostic status: record scenarios,
references, scoring and confirmation allocation before their new outcomes, and
keep failed or inconclusive representative gates open.

Next, resolve evaluation defects that could affect those measurements, then use
one compact set of shared episodes/PCM for the remaining movement and observation
checks. Reuse valid structural controls and restrict refinement or confirmation
to a concrete gap; this decision requires no blanket rerun or new physical capture.
At that point Step 3 remained `not_admitted` pending its other applicable controls.
The later formal closeout uses the full-room decision above. A larger solver or
provider evaluation still requires a separate user decision.

### Bounded full-room reference instruction (2026-09-16)

Historical instruction, superseded by the full-room limitation decision above.
After the targeted C04/field-seed closeout, the user explicitly retained the
current full-room admission criterion. It does not inherit the cube's diagnostic
exception. Define the minimum practical reference for a few complete existing
room paths, reusing current code/evidence and without expanding the matrix or
repeating qualified controls. If reference validity requires disproportionate
investment or a second complete engine, stop with the precise missing capability
before implementation; then reconsider the requirement explicitly with the user.
No other-provider evaluation is authorized. The
[[experiments/geometry-acoustics-admission#Bounded full-room reference feasibility (2026-09-16)|bounded audit]]
owns the resulting capability inventory and stop finding. That finding does not
change the domain, budgets, Step 3's then-OPEN status or PRA retention.

## Provider stop rule and exclusions

The dated follow-ups below retain their original decision context. The full-room
and cube decisions above govern their respective current admission roles.

### Step 3 targeted impact decision (2026-09-15)

The user authorized a bounded PCM/observation follow-up on the current persistent
PRA candidate before deciding on provider replacement. The failed rotating-mirror
temporal-coherence control remains a measured physical discrepancy, with its 0.1
criterion unchanged. Its failure alone does not establish a material robot-audition
error. Use it to select a sensitivity case and measure its energy and effect on the
maintained perception, including weak direct; do not infer current-candidate task
failure from the earlier moving-ray prototype.

This authorizes an isolated experimental renderer and valid controlled references,
not public diffuse admission or a larger propagation engine. Keep causal timing,
visibility, energy ownership/normalization, shared microphone pressure and lifecycle
requirements binding. Preserve the domain, approximation-impact budgets, independent
episode confidence intervals and consumer parameters. A refinement or ablation is
not model validation; missing references and inconclusive intervals stay open.
Full Step 3 qualification still requires its other applicable controls. A bounded
impact pass cannot establish arbitrary-room fidelity, learning transfer or AV/mobile
usefulness. Retain both harmful and artificially beneficial changes in scoring.

The executed follow-up supports retaining PRA: a controlled weak-direct selected
mixture passes the observation-impact budgets despite the retained field-statistic
failure. Other comparisons and full producer/room qualification remain open. This
is a bounded continuation decision, not public diffuse admission or proof of
SquadBot utility. The [[experiments/geometry-acoustics-admission|admission record]]
owns the results, reference limits and outstanding controls.

The subsequent general D implementation was stopped after a conditioned
smooth-room pressure-decay and observation-impact failure. Its current role is
governed by the cube decision above; the earlier rotating-mirror discrepancy is
also not an automatic rejection by itself. The admission record distinguishes
the acoustic counterexample from an additional raised-array consumer-parity limit.

On 2026-09-16 the user requested a practical-significance investigation before
considering alternatives. Retain the implemented renderer and examine absolute
false-update rates, directional persistence, causal late-response interventions,
downstream decisions and reference independence. This permits bounded diagnostic
follow-up, not an automatic budget waiver or a provider evaluation. A failed
observation budget does not establish failure of robot-task usefulness; conversely,
usefulness and physical-transfer claims require their own evidence. The admission
record owns the completed replays and remaining closed-loop/reference gaps. The
user subsequently authorized the bounded head/camera comparison and independent
reference audit. A coarse false association that changes under refinement, or a
direct-only consumer failure, does not establish a provider-replacement need.
Retain the implemented PRA work while separating those causes; all existing
physical, task-usefulness and transfer limits still require their own evidence.
The completed refined confirmation supports retaining PRA for bounded AV work:
acquisition and resumption benefit survive, while a rare false association and
raised-only precision limit remain recorded. This is an evidence-based retention
recommendation, not public diffuse admission, a budget waiver or proof that every
mandatory-domain failure is harmless.

Extend Steam/PRA first with the smallest general maintainable changes. If a
material mandatory-domain gap cannot be closed with simpler native/statistical
extensions and requires a repository-owned multibounce engine, stop with working
changes and reproducible failures. Ask whether to evaluate a replacement for the
whole reflection subsystem or revise the domain. Do not automatically add a third
provider or begin replacement evaluation. One failed prototype is not proof of
universal impossibility. [[experiments/geometry-acoustics-admission|Prior failures]]
remain evidence under this task-domain interpretation.

Retain Analytic and the working intermediate. Defer exact asynchronous path-history
search, a general wave solver, exact material twins, new perception/tracking,
semantic target selection, policy training, new physical recordings and Analytic
retirement. Simulation utility is not a physical-transfer claim.

Complete the existing Python/Kit workflow and actionable diagnostics, not an
advanced analysis GUI. Consumer-justified randomization distributions belong to
[[implementation_phases/09-practical-realism-and-randomization|Phase 09]].

After Milestone 2, measure one/few actual Isaac environments: wall-time mean/p95,
memory, warm-up/reset and simulated/wall ratio. Slower-than-real-time is allowed
with coherent simulated clocks and explicit limits. This does not qualify live
real-time use or mass-parallel learning. Acoustic GPU porting and 32–256 scaling
are deferred; supported Isaac/CUDA perception still uses the actual GPU, native
CPU-only engines remain on CPU. No real-time threshold closes Phase 08.

## Execution

[[implementation_phases/r10-geometry-acoustics-integration|R10]] owns implementation;
[[implementation_phases/08-geometry-acoustics-integration|Phase 08]] owns sequence.
Approved numerical scope: local commit `5cfe48d`; no new qualification accompanied it.
