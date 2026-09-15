# Robot-Audition Fidelity

Status: approved by the user on 2026-09-11; qualification is pending. This is the
canonical R10 scope/acceptance decision, not a claim of implemented capability.
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

## Provider stop rule and exclusions

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
