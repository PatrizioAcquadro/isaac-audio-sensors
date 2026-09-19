# Robot-Audition Fidelity

Status: **08.2 is complete within its documented acoustic and integration bounds.**
This is the canonical R10 scope/acceptance decision; the
[[experiments/geometry-acoustics-admission|admission record]] owns implementation evidence.
08.3 owns remaining operating integration and runtime/distribution closeout.

## Purpose and ownership

Qualify a reusable simulated microphone-array signal producer for robot audition
and robot learning. The SDK owns multichannel acoustic behavior, observed-only
perception contracts and Isaac Sim/Lab integration. Correct timing, microphone
coherence, motion/obstacle response and independent environment lifecycle are
required regardless of the robot using the sensor.

Robot policies, audio-guided visual search, navigation and device-specific hardware
acceptance belong to downstream applications. Physical-recording comparisons have
separate evidence and calibration limits. The 08.2 native/RTX checks execute the
simulated sensor; they are not measurements from physical microphones.

NLOS arrival direction may point toward an opening rather than the hidden source.
References must distinguish arrival direction from source bearing.

## Approved operating domain

| Dimension | Mandatory representative coverage | Stress / separate qualification |
| --- | --- | --- |
| Geometry | Rooms with characteristic sizes around 3–10 m; connected rooms/corridors | Arbitrary large/complex spaces |
| Source–array distance | Approximately 0.5–10 m; indirect paths may be longer | Near-contact and longer-range extensions |
| Source speed | Stationary through 1.5 m/s | Faster motion |
| Receiver motion | Fixed, translating through 1 m/s and rotating through 90 degrees/s | Faster motion |
| Doors/obstacles | Ordinary moving obstacles; opening/closing over roughly 0.5–3 s | Extreme asynchronous openings during sound flight |
| Sources | One and two, sustained/intermittent, including distractors | Three sources |
| Reverberation | Target banded decay around 0.2–0.8 s | Around 1.2 s |
| Conditions | Dominant direct, weak direct, reverberation, physical occlusion and changing/sustained NLOS | Never silently omit weak-direct motion |
| Arrays | Maintained four- and five-microphone layouts as initial references | Other layouts need evidence, not API restrictions |

These are approved engineering test bounds, not partner specifications or measured
capabilities. Use a compact matrix with interior/boundary cases and meaningful
interactions, not every Cartesian combination. Before candidate comparisons,
record exact geometry/trajectories, DRR, banded decay, source content/levels, array
spacing, perception bands, scoring, reference validity and
independent trial counts. Routine choices inside this scope need no new approval.
Changing the domain or budget requires the user; never tune them after a failure.

The [[experiments/geometry-acoustics-trial-protocol|simulation fixture record]]
owns prepared scenes, source/array settings, bounded references and preparation
results. The admission record distinguishes measured representative properties
from unavailable full-room references. Use compact representative controls and
reuse unaffected evidence; a prepared recipe or target is not a measured capability.

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
  reset/partial reset and independent environments; coherent simulation timestamps.
- Public PCM, observations, recordings and Lab schemas stay unchanged. Provider
  paths, source IDs, schedules and hidden bearings remain diagnostic/scoring-only.
- Explicit material, coverage and numerical limits; unavailable requested features
  fail visibly. Nominal materials are not measured physical calibration.

Quasi-static geometry, finite reflection order and statistical late reverb are
eligible approximations, not automatic passes. Exact late phase and full moving-
boundary wave physics are unnecessary if the relevant cues/statistics survive.
One-sample exported-route timing and 0.1 controlled isotropic complex-coherence
checks keep their specific meanings. Neither alone certifies full-room fidelity;
arbitrary rooms must not be forced to have isotropic covariance.

## Approved approximation-impact budgets

| Quantity | Allowed change from a valid matched reference |
| --- | --- |
| Mean direction error | Within 5 degrees |
| 95th-percentile direction error | Within 10 degrees |
| Missing and spurious observation rates, separately | Within 5 percentage points |
| Added acoustic/perceptual latency | At most one observation update; about 100 ms at the maintained 10 Hz |

These are approximation effects, not absolute DOA or application reaction-time promises.
Use paired independent trials, 95% confidence intervals and predeclared
latency and missing-observation handling. Negligible-impact intervals must fit the budget; inconclusive
precision is not a pass. Inspect both signs of change: an artifact can make observations
artificially easier. Keep weak-direct/occluded strata, misses, extras and ambiguity
visible. Do not treat adjacent frames as
independent trials or average away a failed mandatory condition.

The Step 3 cube decision below changes the admission role of one recorded
late-response comparison. It preserves these numerical margins and their
application to the remaining representative conditions.

References must be valid for the property: use controlled geometry/native or
analytic references, independent delay/spatial checks and sampling/update
refinement. Neither another provider nor the intermediate implementation is a
universal room oracle. Missing reference validity remains an evidence gap.

Absolute perception accuracy and downstream task benefit require their own
evidence. Passing relative observation budgets or scalar/CUDA parity preserves
only the tested reference behavior, including its limitations.

## Step 3 full-room limitation and admission decision (2026-09-16)

The user declined separate independent room-reference development after the bounded feasibility audit. **Representative full-room moving pressure/observation equivalence is NOT VALIDATED and non-blocking for Step 3.** This includes the missing joint-field reference, dependent conditioning and complete matched full-D routes. Static integration, geometry visibility and controlled planes do not validate that property.

| Requirement | Current admission role |
| --- | --- |
| Causal timing/lifecycle, opaque visibility, shared realization, disjoint energy and native/filter normalization | Binding; structural defects remain blockers |
| Property-valid controlled statistics, band energy/decay, refinement and representative observation impact | Binding within the approved allocation |
| Full-room moving equivalence | Known unvalidated limitation, non-blocking for Step 3 |
| Recorded cube and selected rotating-mirror mismatches | Separate diagnostic limitations; preserve original failures |
| New material representative errors | Binding; no inherited exception |
| Combined producer | Step 4 native and actual RTX Sim/Lab controls pass |
| Physical transfer | Not established by simulated-sensor qualification |

Retain controlled complex error .1, decay tolerance `max(0.03 s, 15% of target)`, omitted energy below .1%, and the independent-episode 95% budgets above. An unconditioned recipe does not establish its nominal target. Diffuse remains opt-in.

The [[experiments/geometry-acoustics-admission#Admission summary|saved-evidence closeout]] found no other binding Step 3 blocker and recorded PASS. No new experiment accompanied that decision. Reopen affected qualification for a demonstrated structural defect or confirmed material representative failure; domain-wide harmlessness is not established.

## Step 3 cube diagnostic decision (2026-09-16)

The user accepted the recorded smooth symmetric 3 m E0/C02, centered-axis, zero-scattering, S0/R05 comparison as a diagnostic limitation. Its late pressure/energy and spurious-update differences remain **FAIL under the original criteria**, but matching that late response is no longer required for Step 3 or PRA retention. The 3 m boundary, smooth surfaces and weak direct remain in the intended domain.

Causal delays, visibility, shared pressure, normalization and energy ownership remain binding even in this cube. Difference from coherent-reference pressure energy is not automatically an accounting defect. No decay/coherence tolerance or observation budget is loosened elsewhere.

The basis is bounded: correcting 1 kHz decay alone did not recover the reference's extra estimates; substituting the complete late response changed several properties together. Less-symmetric speech/head-motion trials preserved bounded AV benefit. Neither invalidates the cube reference nor proves physical transfer or universal harmlessness. Rare false association and raised-only precision limits remain recorded.

Avoid open-ended matching of this diagnostic. New representative failures require predeclared references/scoring and targeted confirmation, not automatic diagnostic status. The later full-room decision above separately governs missing moving-room equivalence.

## Step 3 targeted impact decision (2026-09-15)

A bounded observation comparison was authorized after the rotating-mirror .17045 temporal-coherence failure against .1. The weak-direct selected mixture passed impact budgets, supporting retention of PRA without erasing the physical discrepancy. This was initially a continuation decision, not complete admission. The general producer and its other binding controls were qualified subsequently; results belong to the [[experiments/geometry-acoustics-admission|admission record]].

The later reference-reuse audit stopped before a second room-field formulation. The explicit full-room decision above supersedes its historical blocker status. Detailed decision chronology remains in Git; do not treat old stop instructions as current work orders.

## Provider stop rule and exclusions

Extend Steam/PRA first with the smallest general maintainable changes. If a
material mandatory-domain gap cannot be closed with simpler native/statistical
extensions and requires a repository-owned multibounce engine, stop with working
changes and reproducible failures. Ask whether to evaluate a replacement for the
whole reflection subsystem or revise the domain. Do not automatically add a third
provider or begin replacement evaluation. One failed prototype is not proof of
universal impossibility. [[experiments/geometry-acoustics-admission|Prior failures]]
remain evidence within the declared acoustic domain.

Retain Analytic and the working intermediate. Defer exact asynchronous path-history
search, a general wave solver, exact material twins, new perception/tracking,
semantic target selection, policy training, new physical recordings and Analytic
retirement. Simulation utility is not a physical-transfer claim.

Complete the existing Python/Kit workflow and actionable diagnostics, not an
advanced analysis GUI. Consumer-justified randomization distributions belong to
[[implementation_phases/09-practical-realism-and-randomization|Phase 09]].

During 08.3, measure one/few actual Isaac environments: wall-time mean/p95,
memory, warm-up/reset and simulated/wall ratio. Slower-than-real-time is allowed
with coherent simulated clocks and explicit limits. This does not qualify live
real-time use or mass-parallel learning. Acoustic GPU porting and 32–256 scaling
are deferred; supported Isaac/CUDA perception still uses the actual GPU, native
CPU-only engines remain on CPU. No real-time threshold closes Phase 08.

## Execution

[[implementation_phases/r10-geometry-acoustics-integration|R10]] owns implementation;
[[implementation_phases/08-geometry-acoustics-integration|Phase 08]] owns sequence.
