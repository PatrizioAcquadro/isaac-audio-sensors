# Geometry Acoustics Admission Evidence

Experiments: 2026-09-10/11/15/16. This page owns decisive results, reference
corrections and replay pointers. [[decisions/robot-audition-fidelity|Robot-Audition Fidelity]]
owns admission criteria; [[implementation_phases/r10-geometry-acoustics-integration|R10]]
owns current work; [[topics/geometry-acoustics|Geometry Acoustics]] owns implementation
contracts/builds. Historical milestones below retain their original scope and verdicts.

## Admission summary

| Contribution | Established | Still unqualified |
| --- | --- | --- |
| Steam direct + native PRA specular intermediate | Bounded arrival/gain, reflected visibility, streaming and actual Sim/Lab/Kit; scalar/CUDA agreement on identical PCM | General retarded motion and the full diffuse/combined field; selected-route integration is qualified separately below |
| Steam selected routes | Step 2 native selected-route transport, producer lifecycle and ordinary-motion controls | Calibrated pressure/diffraction, combined producer and consumer admission |
| PRA persistent surface pressure | Step 3 PASS under the revised admission criteria; shared-field, energy, visibility, lifecycle and controlled motion/observation evidence | Full-room moving equivalence NOT VALIDATED; accepted cube/mirror diagnostic limits; combined producer and AV/mobile remain separate |
| Closed-loop tasks | Targeted NLOS benefit and diffuse observation sensitivity | Both approved AV/mobile consumer gates |

**Current decision (2026-09-16): retain PRA; Step 3 PASS with documented limits.**
The user explicitly made representative full-room moving pressure/observation
equivalence non-blocking; that property remains **NOT VALIDATED**, not PASS.
The cube and selected rotating-mirror failures retain their separately accepted
diagnostic roles. The
[[decisions/robot-audition-fidelity#Step 3 full-room limitation and admission decision (2026-09-16)|governing decision]]
keeps other binding controls, numerical budgets and material representative errors
binding. The review below finds no additional unresolved Step 3 blocker in the
saved evidence. Historical OPEN/FAIL artifacts are preserved unchanged.

Key results:
[[experiments/geometry-acoustics-admission#Step 2 selected-route transport closeout|NLOS closeout]] ·
[[experiments/geometry-acoustics-admission#General D implementation and conditioned-room admission (2026-09-15)|general D / cube]] ·
[[experiments/geometry-acoustics-admission#Practical significance follow-up (2026-09-16)|cube impact]] ·
[[experiments/geometry-acoustics-admission#Bounded head/camera diagnostics (2026-09-16)|AV evidence]] ·
[[experiments/geometry-acoustics-admission#Measurement reliability (2026-09-16)|corrected measurements]] ·
[[experiments/geometry-acoustics-admission#Step 3 formal admission (2026-09-16)|Step 3 closeout]] ·
[[experiments/geometry-acoustics-admission#Evidence and reproduction|reproduction]].

## Steam reflection reconstruction — rejected mapping

Native independent-receiver reflection IRs lost physical microphone timing.
The single-plane control at 16 kHz returned zero pair lags where the image-source
reference required up to 6.6754 samples. Restoring each direct-path delay, W-only
Ambisonics order 3, rotated/mirrored geometry and 48 kHz did not fix it:

| Control | Maximum native TDOA error | PRA specular control |
| --- | ---: | ---: |
| Original, 16 kHz | 6.6754 samples | 0.1203 |
| Rotated array, 16 kHz | 7.5758 | 0.1220 |
| Mirrored source, 16 kHz | 6.6754 | 0.1203 |
| Original, 48 kHz | 20.0262 | 0.0389 |

Native Steam subtracts direct travel time, bins energy at 10 ms, then reconstructs
noise-weighted pressure. A global/per-mic direct delay cannot recover missing
reflection differences. Full-channel convolution also crashed at an unaligned
SIMD load; this is separate from the completed W-only failure. PRA removed only
its documented 40-sample filter latency; maximum peak-arrival error was 0.463
samples. This admitted a specular candidate, not a complete replacement engine.

Initial actual-RTX candidate measurements included a 14/16 scalar-count failure
and a later 16/16 pass; the first run has no saved PCM, so that discrepancy was
not resolved. Neither that timing nor tensor parity established acoustic validity.
Failed candidate code was removed; the original operational baseline was restored.

## PRA specular visibility — corrected for the intermediate

The first hybrid leaked specular pressure through a fully closed partition at
all five source offsets (0, 0.1, 1, 10, 100 mm); peak ~0.0209–0.0227 persisted even
when direct transmission was effectively opaque. Fixture: 6×6×3 m room, x=3
partition, 1 m doorway, source (2,3+offset,1.2), array centered (4,3,1.2), 80 mm arms.
Avoiding symmetric poses or inventing wall thickness was not an acceptable repair.

The optional native PRA bridge corrected bounded polygon/visibility issues while
preserving native ISM ownership. Final production controls pass original face
orientations, tessellation, five offsets, closed/open/closed/opaque states and
reflected corridor NLOS. No fitted gain or second attenuation stage was added.
Installed PRA and historical Steam builds remain unchanged.

## Operational intermediate — admitted within bounds

Production Steam direct/planar transmission + native PRA specular PCM passes
source/channel gain and directivity, physical delay, continuous/fragmented reads,
source-stop tails, resets, provider replacement and 0.1 m/s source motion at 60 Hz.
The receiver-clock RIR updates are quasi-static, not full retarded dynamic transport.

Actual RTX 4090 Sim/Lab/Kit and 1,440 same-PCM comparisons pass: 100% count agreement,
no scalar-relative missing/extra events, worst case direction-difference p95
0.0612 degrees and global maximum 2.4187 degrees. Four reflector controls at 16/48
kHz have maximum TDOA error 0.12191 samples. Reference agreement preserves reference
errors; it does not establish accurate event counting in arbitrary rooms.

Audio-only timing on i9-14900KF/RTX 4090: two sources, 16 kHz, 60 Hz acquisition,
10 Hz observations, 750 ms context, 40 updates after one-second warm-up. Indoor
case: six planes, absorption 0.4, zero scattering, specular order 3. Native scene
state is independent per environment; physics/rendering/learning are excluded.

| Environments / mics | Free-field mean/p95 ms | Indoor mean/p95 ms |
| --- | --- | --- |
| 2 / 4 | 41.11 / 42.72 | 42.25 / 43.53 |
| 2 / 5 | 43.40 / 44.31 | 43.88 / 44.87 |
| 16 / 4 | 120.87 / 123.68 | 128.52 / 131.16 |
| 16 / 5 | 148.57 / 151.55 | 159.26 / 164.79 |

Two environments exceeded real time in this audio-only fixture; 16 did not.
Process RSS 4.22–4.41 GiB includes resident Isaac fixtures; reset cost 0.49–0.85 ms.
A native flat-gain one-tap optimization reduced 16-copy free-field means from
141.12/173.33 to 120.87/148.57 ms without changing physical/parity results.
Equivalent Analytic means at 16 copies were 62.15/86.71 ms. Native PCM, WPE and
localization dominate different parts; nested profiler times must not be summed.
Retain both producers. These are intermediate results, not extended-field cost.

## Archived Steam NLOS timing — stronger claim withdrawn

The old R9.4 bridge scheduled aggregated path PCM with straight-line distance;
its arrival and NLOS TDOA references also used that distance. Rechecking the
corridor against an independent geometric detour lower bound gives arrivals
133.11–146.54 samples too early at 48 kHz; moving the blocker gives 327.38–344.86
samples too early. Maximum pair TDOA errors are 13.43 and 17.48 samples.
The bound detects impossible shortcuts, not exact physical diffraction paths.

Native open/LOS path output is nonzero and cannot be added blindly to direct.
Validation-only retained output after complete closure in the archived harness;
validation plus alternate routing yielded silence. Public path effects aggregate
SH/EQ/weights before rendering; visualizer segments include rejected candidates
and cannot supply selected weighted temporal contributions.

The private pre-aggregation route extension validates endpoints/internal segments,
excludes LOS, removes redundant visible probe segments and preserves per-route
EQ/weight/delay. The screen fixture has two routes per microphone. All 44 native
arrival cases pass (max error 0.6252 samples against route delay plus native filter
peak); geometric lower bounds also pass. Later filter controls at 5.706/9.494 m
pass one-sample timing, <0.1% gain error and independent filter state.
At that milestone, probe coverage, duplicate weighting, rebake identity and
production directivity/lifecycle were unqualified; Step 2 below records their closeout.

## Step 2 native preparation — 2026-09-15

Steam UniformFloor generation, bounded probes, native baking/alternate search and
pre-aggregation route export were integrated through checked private ABIs. LOS is
excluded; missing floor, uncovered endpoints, capacity/preparation errors and duplicate
native records fail explicitly. Equivalent geometric/EQ representations sum weights.
Immutable instance transforms preserve meshes; the baker receives its required callback.

### Corrected failures and retained evidence

| Failure | Correction | Decisive check |
| --- | --- | --- |
| Surface/corner probes let E4 take 8.23 m versus a 9.22 m detour bound; coarse E3 leaked through a closed door | Native probe clearance and inclusive endpoint bounds; ABI 2 retains interpolation-pair identity through simplification | Both layouts respect E4 bounds and E3 closure at 1/.5 m spacing; screen and Office/Hospital bounded endpoint coverage pass (Hospital .5 m: 2399 probes, ~24 s preparation) |
| Lattice alignment reduced captured interpolation weight to .00031 instead of 1; corner filtering alone shifted the failure | Center the grid; use identical inclusive segment bounds in baking, validation and export, without renormalizing missing paths | Nine microphone positions at 1/.5/.25 m spacing: weight 1 within 2e-6, independent detour bounds pass |
| Native tree traversal cutoff omitted one side of a symmetric screen | Query the full neighborhood, select nearest eight visible probes, retain native weights | Both alternatives restored; producer regressions cover 1.5/1 m/s endpoints, rebake identity and directivity at route nodes |
| Scene diagonal incorrectly bounded total bent-route length; E4 source (7,6.45) retained weight .883 | Bound total baking by a finite simple path through the graph; keep producer travel-time horizon explicit | 567 E4 pose/channel/grid checks pass visibility/detour bounds and weight 1 within 2e-6 |
| Ordinary opening must reconsider emitted sound with no assigned route | Recover only `no_selected_route` history; test segments at passage time, exclude prior LOS/assigned intervals | 1 ms emission behind gate plus NLOS screen: opening at 2 ms matches already-open arrival; opening at 6 ms blocks. Stop/rebake/fragmented-epoch regressions pass |

E4 source/receiver/yaw refinement changes weighted length/direction by at most
.6214 m/3.53° for 1→.5 m grids and .00754 m/1.45° for .5→.25 m. These are numerical
sensitivities, not diffraction error bounds; default 1 m spacing is coarse.

`local/r10/08_step2_nlos/` retains `coverage_initial.json`,
`dynamics_before_clearance.json`, intermediate `final/` and `qualified/` builds,
and final `closeout/`/`validation/` evidence. Earlier test/smoke results are
superseded by the closeout below, not additional admission claims. The final native
artifact is `74f3d78b381afd84ff98e20b000705cf3128a831735c888ca60a13ebf77604ba`;
repeat-build identity was checked during correction.

### Step 2 selected-route transport closeout

Both maintained layouts pass the bounded source 1.5 m/s, receiver 1 m/s and
90 degree/s yaw trials. Ordinary doors open/close over 0.5, 1.5 and 3 seconds with
held, explicitly timestamped geometry. The 30 native/producer regressions pass,
including delay within one sample after separating native EQ, route alternatives,
LOS exclusion, rebuild, source stop, reset, array isolation and fragmented reads.
The actual RTX 4090 Isaac run passes four simulation seconds with CUDA physics,
180 native scene updates and reset; Steam/Embree remains CPU native.
The final host check passes 668 unit/contract, 336 integration and 58 release
tests. The wheel built through the sdist matches all 183 source Python modules
and imports NLOS in isolation without experimental script dependencies.

| Refinement | Measured difference | Interpretation |
| --- | --- | --- |
| Motion refresh 100 → 200 → 400 Hz | Maximum relative PCM difference 0.024%, then 0.015% | Small update sensitivity in the measured corridor motions |
| Door refresh 100 → 200 → 400 Hz | Identical PCM with geometry held at 100 Hz | Faster selection does not add unobserved geometry |
| Door probe spacing 0.5 → 0.25 m, both arrays | Relative PCM 1.283–1.284; 10 ms RMS-envelope difference 0.347–0.349; integrated level difference 0.56–0.58 dB | Pressure remains sensitive to probe representation |
| Door probe spacing 0.25 → 0.125 m, square array | Relative PCM 0.618; RMS-envelope difference 0.213; integrated level difference 0.56 dB | Differences decrease, but pressure convergence is not established |

These controls close selected-route transport with measured approximation limits;
they do not admit calibrated diffraction pressure, unavailable full-room references,
the diffuse branch, combined-model energy partition or consumer impact budgets.
No fitted gains, temporal fades or new multibounce solver were introduced.
The final native visibility cache gives identical dense-door PCM and reduces that
run from 178 to 74 seconds; this is one measurement, not a general runtime claim.

Final ignored evidence is in `local/r10/08_step2_nlos/closeout/`: `summary.json`,
`dynamics.json`, `refinement.json`, `native_cache.json`, `live.json`, logs and PCM.
Independent geometry/weight refinement is in `validation/path_refinement.json`;
`validation/coverage.json` includes both layouts, the corridor, connected rooms,
screen and bounded Office/Hospital endpoint coverage. The latter is not full-field
qualification. Earlier reports remain historical and are not overwritten.

## Selected-flight dynamics — bounded correction, stress limit

`retarded_pathing.py` retains emission history and tests only the traveled segment
in each immutable native scene epoch. Source is evaluated at emission and mic at
reception; native EQ tails survive fragmented reads. Corridor crossing is at
8.416 ms, arrival at 16.713 ms: closure at 5 ms blocks, closure at 12 ms preserves,
closure/opening at 4/6 ms preserves the arrival. Four endpoint-motion cases have
retarded-equation residual <=1.8e-12 samples; partition error <=1.4e-9.

A two-gate route crosses at 6.958/9.874 ms; first closure 7.459 ms, second opening
9.374 ms. Every snapshot has one gate closed and exports no route, although a
reference all-open route is valid during flight. Diagnostic history rendering
has peak 0.001626; selected-only output is zero. An all-open scene is not a
production workaround. This exposes missing temporal candidate discovery, now a
stress limit rather than a mandatory general space-time solver. Ordinary-domain
impact remains to be measured. Geometry is held between epochs; exact moving bends
and continuous boundary physics are not established.

## PRA diffuse reconstruction and shared-field prototypes

Five native RT runs (8192 rays, 150 ms horizon, 4 ms bins, absorption 0.2,
scattering 0.3) give identical co-located histograms but PCM relative error
1.380–1.489 and correlation -0.058–0.028. Reconstructing again changes pressure.
Independent seeds decorrelate receivers; shared seeds force coherence 1 at every
spacing. Neither recovers the isotropic reference `sinc(2*f*d/c)` (0.6786 at
80 mm/1 kHz, -0.1361 at 200 mm). Directional arrivals separated by 3.7318 samples
can occupy the same histogram bin; seed changes cannot restore that information.
The isotropic reference applies only to controlled homogeneous input, not rooms.
[Diffuse-field derivation](https://pub.dega-akustik.de/DAGA_1999-2008/data/articles/000952.pdf).

Pre-histogram shared-event prototypes corrected co-location/refresh. Later native
iterations separated pure specular ownership, used probabilistic specular/diffuse
branches and native ISM suffixes, per-ray RNG and the correct two-sided hemisphere.
Twenty-realization controlled isotropic/directional errors were 0.04332/0.00146
(below 0.1); bounded room/door visibility passed. Scalar-band, finite-order success
did not establish full energy convergence or dynamic field validity.

A 1 cm source displacement moves random scatter locations on a stationary plane.
Against a fixed-surface Lambertian reference, coherence errors are ~0.117/0.227/
0.687 at 500/1000/4000 Hz; 4 kHz error persists at 4096–65536 rays. More rays and
stable seeds do not fix phase attachment to moving ray hits.

First-scatter anchoring using surface area/Lambertian cosines and native ISM/RT
prefixes/suffixes passes twelve plane controls (complex error ≤8.21e-6, relative
energy difference ≤1e-5, no fitted gain). A 1 cm mirror translation still moves
second-scatter hits 2 cm on a stationary floor: errors ~.151/.300/1.031 at
500/1000/4000 Hz persist at 4096–65536 rays. First anchors and finite specular
prefixes do not solve multibounce persistence; these diagnostic discrepancies
require task-relevant statistical-impact evidence.

## Step 3 shared statistical extension — not admitted (2026-09-15)

The preserved experimental extension captures pre-histogram incident/received
band energy, parent interactions and directions. Five native checks pass disjoint
ISM/RT ownership, two-sided containment, branching, reproducibility and handle
isolation; seventeen existing specular/Geometry tests pass with the Isaac interpreter.
This is CPU-native component evidence, not live diffuse/CUDA admission.

| Statistical control | Result | Limit |
| --- | --- | --- |
| Fixed material nodes with directional source phase gauge; 65536 rays, .5 m nodes, 4 ms modes, 64 directions | One/two-scatter temporal errors .05586/.04768; spatial .00471/.01088; energy ratios .99693/1.00344 | Scalar planes only; full bands/radius/high-order/room-tail qualification absent |
| Near-surface two-scatter refinement | Temporal error .06343/.05648 at 262144/1048576 rays | Requires finer nodes/more samples |
| Translating mirror between diffuse surfaces, native interaction derivatives | Maximum error .02002 at 65536 rays | First-order rotation still biased |

Independent two-Lambertian-surface rotation control: mirror turns 5° about a fixed
pivot (100 ms at 50°/s). This tests ordinary transfer statistics, not asynchronous
flight or a furnished room.

| Native rays; 12 sampler realizations each | Mean complex temporal-coherence error at 500 Hz | 95% interval for the mean |
| --- | --- | --- |
| 262144 | 0.16404 | [0.15981, 0.16807] |
| 1048576 | 0.17045 | [0.16783, 0.17321] |

All realizations exceed the controlled .1 bound; 1000/4000 Hz pass. Independent
image-distance quadrature changes ~.000406 at 500 Hz for .25→.125 m discretization;
native path-length error is ≤4.155e-6 m. Reference/sampler refinement does not
explain the bias. Fresh seeds 100–111 follow diagnostic seeds 0–11; intervals
resample native realizations, not frames/robot episodes.

**Historical stop:** Step 3 was unqualified before a larger pressure redesign.
The subsequent [[decisions/robot-audition-fidelity#Step 3 targeted impact decision (2026-09-15)|targeted-impact decision]]
authorized the observation comparison below, retaining the failed .1 statistic.
No public diffuse option was enabled at this milestone. Full energy/decay/radius,
causal, room-reference and weak-direct qualification remained open; this candidate
failure did not establish PRA impossibility or authorize replacement evaluation.
Reproduction/variants: `local/r10/08_2_step3_diffuse/README.md`; values: `summary.json`.

## Earlier candidate: targeted observation impact (2026-09-15)

The unchanged `surface_field.project` candidate was compared against fixed-surface
Lambertian quadrature and exact mirror-image geometry after the physical stop.
The .17045 temporal-coherence failure remains; its observation impact is measured.

**Result:** rotating-mirror selected-mixture budgets pass on both arrays, including
weak direct; other cases retain inconclusive intervals. No fresh interval establishes
an over-budget impact. This supports retaining PRA, not full Step 3 admission.
Reproduction: `local/r10/08_2_step3_impact/README.md`, `summary.json`, `impact.png`.

### Method and essential controls

- Exact square/raised arrays, 16 kHz, 3.2 s with interruption/final stop. Pilot:
  four independent signal/field-phase episodes per static, moving-source/receiver,
  yaw, one/two-source and rotating case. Direct gains 1/.1 are sensitivity axes,
  not physical-door attenuation; no fitted field gain.
- Selected refinement: 4096/16384/65536 rays, 10/5/2.5 ms. Fresh confirmation:
  24 moving-source/two-source episodes at 65536 rays/10 ms; 96 isolated/mixed,
  rotating/held-mirror episodes at 65536/2.5 ms. Keep layouts/hard conditions separate.
- Analytic energy/kernel controls: expected plane-energy error ≤.313%; fractional
  passband power .99528–1.000002, phase-delay error <.000352 samples. Whole-Nyquist
  kernel energy enters the random-RIR expectation. Colocation/order/grouping,
  refresh/source-coordinate equivalence, partition/tails/reset/state isolation pass.
- Reference quadrature .25→.0625 m changes source/receiver/yaw temporal coherence
  <.000097; mirror energy/coherence changes <.137%/<.00425. Importance sampling
  8192→65536 at .25 m changes joint temporal/cross-mic covariance ≤.01740.
- Unchanged RTX 4090 `TorchPerception`, observed PCM/positions only: eight-stream
  scalar count/activity parity passes, max angle difference 1.246°. CUDA solo,
  reordered, loud-neighbor and partial-reset controls retain counts/activity,
  max angle difference <.000016°.

Use 10,000 paired whole-episode bootstrap samples. Mean/pooled-p95 angles use emitted
estimates with separate misses; spurious rate counts updates with an unmatched
estimate. Raw results retain extras/update and penalized assignment error.
First/reacquisition keep timeout deadlines. All-zero paired differences additionally
use unseen-discordance bound `1 - 0.025**(1/n)` times metric range: 24 identical
observed episodes cannot prove a five-point bound. Numerical refinement does not
itself provide independent reference validity or full convergence.

### Fresh weak-direct effects

Values below are candidate minus reference; rate intervals are percentage points.
Each interval is 95%. All source/mirror mean-angle intervals are inside +/-5 degrees.

| Case / array | Mean angle change (degrees) | Miss-rate interval | Spurious-rate interval | Remaining budget result |
| --- | ---: | ---: | ---: | --- |
| Moving source / square | -0.905 [-2.882, 0.920] | [-17.763, 2.851] | [-13.596, 6.579] | Rates inconclusive; p95 and both latency budgets pass |
| Moving source / raised | -0.805 [-2.603, 0.931] | [-10.088, 4.825] | [-1.316, 0.000] | Misses inconclusive; other budgets pass |
| Two sources / square | -0.660 [-2.608, 1.395] | [-8.553, 2.632] | [-4.386, 1.316] | Misses and p95 inconclusive; both latency budgets pass |
| Two sources / raised | -0.315 [-2.111, 1.589] | [-4.167, 5.702] | [-2.632, 0.000] | Misses inconclusive; other budgets pass |
| Rotating family isolated / square | 0.057 [0.020, 0.095] | [-3.770, 3.770] | [1.645, 10.855] | Spurious updates increase; exceeding five points is inconclusive |
| Rotating family isolated / raised | -0.021 [-0.052, 0.010] | [-3.770, 3.770] | [-1.316, 6.360] | Spurious budget inconclusive; other budgets pass |
| Rotating selected mixture / square | 0.142 [-0.482, 0.769] | [-1.206, -0.055] | [-0.932, 3.565] | All observation-impact budgets pass |
| Rotating selected mixture / raised | -0.027 [-0.447, 0.402] | [-0.987, 0.164] | [-1.754, 0.384] | All observation-impact budgets pass |

Measured reference DRR is about -8.23 dB for moving source, -8.45 dB for two
sources, -2.97 dB for the isolated rotating family, and -15.68 dB for the selected
mixture. The latter adds the two first-scatter families to the tested
diffuse/specular/diffuse family. At the initial position the rotating family is
5.36% of these diffuse components' expected energy, or 1.45% with unit-gain direct.
These fractions exclude other reflections and are not full-room budgets.

The isolated square case already has a spurious-rate difference with the mirror
held: +4.276 points [1.590, 7.018]. The added dynamic-minus-static difference is
+1.864 points [-2.467, 6.195]. This ablation does not isolate a confirmed
over-budget effect attributable specifically to rotation. Held-mirror rate bounds
also remain inconclusive for the isolated square and mixed raised cases.

### Interpretation and limits

The passing selected mixture shows that this failed .1 statistic alone does not
establish an observation-budget violation. Isolated-family spurious differences
and inconclusive intervals remain. Absolute behavior is poor in some controls:
weak two-source reference misses ~59.5–69.6%; selected-mixture extras occur in
~87–89% of updates in both variants. Approximation agreement is not robot utility.

References are controlled scalar statistical geometry, not measured/moving-boundary
rooms. The mixed case omits other paths, including direct mirror reflection;
geometry is held per emission update and emitted tails drain. Full D, band/decay/
radius/order/horizon, arbitrary-surface persistence, general causal motion,
C03/C04/room and AV/mobile/learning qualification remained open at this milestone.
No public option or perception/controller change came from this follow-up.

Retained: 2304 multichannel streams, not independent episodes per condition.
Offline generation/inference-plus-analysis: 345/41 s for motion, 643/143 s for
mirror; CUDA batch 32 inference mean/p95 88/124 ms per update. Shared RIR work
precludes live-throughput claims. Local synthesis/scoring/Ruff checks passed.

## General D implementation and conditioned-room admission (2026-09-15)

**Original result: implemented, not admitted.** The general candidate failed
conditioned smooth-room decay and observation criteria after refinement, causing
the then-required stop. The later cube decision makes this comparison diagnostic;
it neither erases the failure nor admits the remaining field/motion gates.

### Implemented and verified boundary

`GeometryAcousticsConfig.diffuse=PRADiffuseConfig()` is experimental opt-in;
default `None` is unchanged. Native PRA owns geometric transport; object-local
pressure elements preserve disjoint first/later-scattering and higher-specular
ownership. [[topics/geometry-acoustics|The technical contract]] owns synthesis details.

Thirty-six native/field/producer/convolution controls pass: two-sided containment,
corrected partition-crossing surface-projection leak, analytic Lambertian energy/
covariance, colocation/reordering/regrouping, refresh/source-identity invariance,
object motion/return, late arrays, filter power/delay, stop tails and reset.
Banded specular minimum-phase conversion was corrected to exclude geometric
level and signed directivity from material phase construction.

| Bounded control | Result |
| --- | --- |
| 6×6×3 m banded energy envelope, targets .2/.2/.35/.5/.65/.8/.8 s | T20 .226/.226/.374/.522/.671/.821/.821 s, within tolerance |
| Native horizon, 2/4 s | Captures agree at 1e-7 ray cutoff |
| Fully diffuse late field, .05 m source shift vs reciprocal receiver motion | Covariance differences .0781/.0698/.0164 at 500/1000/4000 Hz |

These controls do not qualify the complete moving-room field.

### Reference conditioning and validity

The full-D diagnostic uses prescribed smooth E0/C02 geometry: a 3 m cube, source
(2,1.5,1.2), array center (1,1.5,1.2), both exact maintained layouts, zero scattering
and a .5 s decay target. Higher pure-specular orders belong to the chosen
statistical tail, so zero scattering still exercises that approximation.

An independent native PRA shoebox image model provides reflected pressure through
order 100. Reference-only absorption conditioning yields .4493–.5402 s across
250–4000 Hz and all microphones, inside .5 +/- .075 s. Both models use identical
band coefficients. Orders 100/160 differ by at most 5.53e-8 relative RIR energy;
native polygon and shoebox early responses agree within 2.6e-9 at orders 3/5/7.
No gain, consumer parameter or acceptance budget was fitted to the candidate.

Earlier local pilots used an unconditioned recipe, insufficient reference order
or the subsequently corrected banded filter. They remain diagnostic evidence,
excluded from the final admission comparison. Ray/order refinement is numerical
sensitivity evidence, not an independent physical model reference.

### Maintained RTX 4090 observation impact

Use unchanged `TorchPerception`, -60 dBFS activity threshold, 750 ms context,
100 ms updates and the maintained candidate limit. Each array receives 96 fresh
independent S0 source waveforms, with interruption/reacquisition and final stop.
The scene and field realization are frozen; intervals are conditional on this
one scene/realization, not across-material or across-room claims. The 65536-ray
refinement reuses the same defined 96 episodes as the 16384-ray order-7 comparison.
Whole-episode paired bootstrap and zero-discordance bounds are unchanged.
PCM uses the production specular/surface-pressure components and an analytically
checked direct path. Native USD producer lifecycle is tested separately; this is
not a moving Isaac consumer run.

Final order-7 / 65536-ray results, candidate minus reference:

| Array | Mean-angle change, 95% CI (degrees) | Spurious-update change, 95% CI (percentage points) | Other impact budgets |
| --- | ---: | ---: | --- |
| Square | .153 [.144, .161] | **-23.08 [-25.99, -20.18] — FAIL** | p95 angle, misses, first/reacquisition latency pass |
| Raised | -.131 [-.156, -.106] | **-67.43 [-68.48, -66.28] — FAIL** | p95 angle, misses, first/reacquisition latency pass |

Reference/candidate DRR is -8.48/-6.93 dB square and -9.21/-7.60 dB raised.
The candidate suppresses additional direction estimates relative to the reference;
this observation comparison does not measure robot-task success. Absolute changes,
including improvements, were scored against the original five-point bound.
At 4096 rays/order 3, corresponding changes were
-99.78 and -78.45 points; at 16384/order 7, -15.73 and -67.93. Increasing rays
does not resolve this selected failure.

The final candidate's 1 kHz pressure T20 is .352–.378 s across microphones,
outside the .425–.575 s target interval; the conditioned reference is .534–.540 s
in that band. The 250–2000 Hz RIR-energy ratios are approximately .624/.519/.754/.587
relative to the coherent reference. These are measured pressure differences,
not a failure of the independently checked scalar-energy bookkeeping.

### Consumer limits and stop boundary

CUDA solo/batch/reorder/loud-neighbor/reset controls pass for candidates and square
reference. One raised reference changes count at one of 19 updates across batch
sizes (binary spurious outcome unchanged); final selected raised scalar/CUDA count
agreement is only 50%. These are separate consumer limits. The stable square
comparison establishes the original observation FAIL; no localizer tuning was used.

At this milestone, C03/C04, two-source/general rooms, full isotropic/later-scatter
mirror controls, moving-geometry causality and room references were open. The static
failure stopped the wider matrix under the then-binding criteria; Steps 4–6 had
not begun. The older rotating-mirror diagnostic was not the sole blocker.

CPU-only synthesis of one held nine-channel RIR costs ~77/210/493 s for
4096 rays/order 3, 16384/order 7 and 65536/order 7, retaining 7.45–32.44 million
modes. RTX batch-32 inference mean/p95: 88/114 ms per update. These are offline costs.
Reproduction, coefficients, PCM, intervals and plot:
`local/r10/08_2_step3_general/README.md`, `summary.json`, `summary.png`.
Working code/failures were retained; no replacement, domain/budget change or
larger repository-owned solver was introduced.

### Practical significance follow-up (2026-09-16)

This follow-up retained the renderer/invariants/budgets to investigate practical
impact before considering replacements. The symmetric 3 m cube, centered axis,
smooth identical walls and S0 Gaussian input are a controlled case, not an office/
speech task; neither an SDK-unsuitability nor a harmlessness claim follows.

**Absolute rates and persistence.** Reanalysis of the same 96 source episodes,
order 7/65536 rays, frozen scene/field:

| Measurement (% of scored updates) | Square reference | Square candidate | Raised reference | Raised candidate |
| --- | ---: | ---: | ---: | ---: |
| Any unmatched estimate | 99.95 | 76.86 | 100.00 | 32.57 |
| Any bearing >20 degrees from the source | 99.95 | 76.86 | 94.41 | 32.13 |
| Any bearing >90 degrees from the source | 99.95 | 76.86 | 89.86 | 29.82 |
| Multiple estimates within 20 degrees of the source | 0.00 | 0.00 | 79.66 | 1.86 |

Rows overlap. The metric is the fraction of updates with extras, not false detections
among all detections. Mean extras/update: square reference/candidate 1.00/.77,
raised 3.25/.58. Nearby duplicates explain some raised multiplicity, but large
angular errors remain; square extras are approximately opposite the source.

In windows at ticks 7–14 and 18–28, median longest opposite-bearing runs are
1.1/.8 s square and .8/.6 s raised. Every reference episode and 95/96 square,
85/96 raised candidate episodes have ≥.5 s runs. These censored 100 ms update-bin
spans are not tracks; 750 ms reused context makes adjacent updates dependent.
First-bearing timing likewise does not establish moving camera/track reacquisition.

**Causal late-response diagnostics.** Four artificial interventions reuse 16 of
those episodes (2200–2215), both arrays and unchanged actual RTX 4090 perception.
They preserve direct pressure and the entire candidate response before 80 ms;
the intervention blends in between 80 and 100 ms. No perception output is used to
fit a filter, decay or energy weight. This is paired exploratory reuse, not fresh
confirmation or a physical fix.

| Response | Square extra-update rate | Raised extra-update rate |
| --- | ---: | ---: |
| Original candidate, these 16 episodes | 78.62% | 32.24% |
| Correct 1 kHz decay to mean .5 s | 81.58% | 32.24% |
| Same decay target, hold projected late-band energy constant | 79.93% | 32.24% |
| Match projected 1 kHz late-band energy to reference | 84.54% | 33.22% |
| Substitute coherent reference response after 80–100 ms | 98.03% | 100.00% |
| Reference, these 16 episodes | 100.00% | 100.00% |

Decay interventions reach 1 kHz T20 .474–.529 s and .464–.534 s, inside the original
tolerance. A common delay-compensated FIR/envelope spans all nine microphones.
The energy-controlled variant preserves projected-component energy exactly while
full 1 kHz response energy changes ~−.12%; interference prevents equating these
or claiming exact broadband DRR control.

**Inference:** correcting this one decay descriptor is insufficient. Substituting
the reference tail recovers most extras, implicating late response jointly; it
changes multiband energy and inter-mic pressure together and isolates neither
phase, direction, coherence nor every band's decay. It does not establish a need
to replace PRA. Preparation ~14 s; 320 RTX replays ~37 s, no new native ray generation.

**Downstream replay:** unchanged SquadBot `audio_sensor_frame_to_auditory_cues` and
`run_all_new_audio_cued_searches` produce `orient_to_sector` for every bearing.
Behind-sector updates: square reference/candidate 99.95/76.86%, raised 88.32/29.00%.
Thus cues are not discarded, but the controller records decisions without commanding
joints. Fresh graphs, `Unknown` classes and no visual objects make zero confirmation
structural, not AV rejection evidence. Tracks and physical/mobile actions were unmeasured.

**Reference boundary:** independent shoebox paths share PRA/geometrical-acoustics
and material assumptions; convergence validates numerics, not physical fidelity.
[[experiments/physical-signal-comparison|The 25 ReSpeaker takes]] lack matched
weak-direct room RIR/decay calibration.
[ACE](https://www.imperial.ac.uk/speech-audio-processing/projects/ace-challenge/) and
[BUT ReverbDB](https://speech.fit.vut.cz/software/but-speech-fit-reverb-database)
were inspected, not downloaded/validated. Independent RIR evidence must match
array/room/source geometry, decay, DRR and transducer limits; an unrelated room
cannot adjudicate this cube.

The recommended moving-head/camera, less-symmetric speech comparison was subsequently
executed below. A fixed-head RIR replay cannot qualify diverging head trajectories.
Full summaries, ablated RIRs/PCM and scripts:
`local/r10/08_2_step3_relevance/README.md`.

## Measured observation impact — earlier evidence

Actual RTX 4090 `TorchPerception`, observed PCM only; truth used after inference.
Twelve paired corridor realizations give arrival-direction mean error 0.03685
degrees with corrected route delay versus 57.99938 degrees with Euclidean-delay
ablation (same EQ/gain/weight). Hidden-source bearing is separate. The moved-blocker
signal is -61.85 dBFS, below unchanged -60 dBFS activity threshold: no observation.

Diffuse sensitivity: 8 cm square array, finite plane, 24 paired phase/signal trials
per condition, source speeds 0/0.1/0.5 m/s. Direct gain 1 or 0.1 is a sensitivity
axis, not physical door occlusion. Reference uses fixed surface positions and
updated cosine/distance illumination/delay; not a general room solver. All 72
stationary PCM pairs are identical. Score 0.8–2.1 s after 750 ms warm-up, retain
2.4 s streams/source-stop tails. A miss includes no direction within 20 degrees,
not merely absent output. Confidence intervals bootstrap paired trial means.

| Condition | Reference / candidate misses | Excess percentage points, 95% CI |
| --- | --- | --- |
| Strong direct, 0.5 m/s, 4096 rays | 0 / 0% | 0 |
| Weak direct, 0.1 m/s, 16384 rays | 13.39 / 13.10% | -0.30 [-12.80, 11.01] |
| Weak direct, 0.5 m/s, 4096 rays | 33.93 / 77.08% | 43.15 [31.85, 54.47] |
| Weak direct, 0.5 m/s, 16384 rays | 35.71 / 69.94% | 34.23 [26.48, 42.56] |
| Weak direct, 0.5 m/s, 5 ms refresh | 34.23 / 74.11% | 39.88 [27.38, 52.38] |

Strong-direct DRR ~+10 to +12 dB, angular difference <0.14 degrees. Weak-direct
DRR ~-8.5 to -10.4 dB; at 0.5 m/s/16384 rays, assignment error rises 8.97 degrees
[5.06,13.39], with 3/24 never recovered versus 0/24 reference. Competing-source
results are mixed: the defective model can improve scores or both variants miss
50%. No universal degradation or latency benefit follows. This is material bias
in a controlled condition, not general-room or closed-loop admission.

888 streams used actual CUDA; 960 selected frames had 100% scalar count/activity
agreement and max direction difference 3.798 degrees. CPU native engines and the
existing actual-Isaac intermediate smoke passed. Neither validates a live USD
experimental branch. No new physical recordings, policy training or replacement
engine were introduced.

## Bounded head/camera diagnostics (2026-09-16)

This bounded Profile 1 diagnostic uses a physically moving microphone layout and
geometric camera observations, with unchanged SDK/localizer/budgets. It does not
qualify SquadBot hardware, learned vision or tracking. Prospective design and
corrections: `local/r10/08_2_step3_av/PLAN.md`.

**Matched scene and pressure:** 6×5×3 m room, source (2.983,2.817,1.213), array
center (1.2,1.7,1.2) m. Reference-only conditioning precedes scoring. Across the
receiver ring, reference 250–4000 Hz T20 is .435–.568 s (within .5±.075 s);
reference/candidate DRR is −7.61…−6.70 / −7.37…−6.51 dB. Native polygon order 7
plus shared tail is compared to independent shoebox order 100 and audio-off search.
Order-80/100 residual energy is <1e-9 at the checked point; one-point candidate
2/4 s checks retain identical events and <1.1e-14 relative band-energy difference.

Both exact layouts rotate through the field using a periodic angular cache with
fractional delays; divergent trajectories never reuse fixed-head PCM. Controls
cover causal prefixes, partition/query order, off-diagonal handedness, finite
head limits, visual delivery, post-onset three-frame confirmation, stale/ambiguous/
invisible cues. Camera: 90° HFOV, 30 Hz, 100 ms delivery. Head: ±170°, 60°/s,
180°/s². Observed bearings alone drive selection/association; truth scores outcomes.
Thirty-second sustained/intermittent S1 programs retain natural pauses/tails.

**Coarse diagnostic:** 16 independent source/pose programs, both layouts/schedules,
four fixed 4096-ray field seeds. Candidate/reference/audio-off all acquire within
10 s and at every scored resumption. The audio-off sweep creates a first-success
ceiling. Mean acquisition times are .813/.597/.478 s; resumption 1.498/1.352/3.188 s.
Resumption concerns a stationary target, not moving-target identity tracking.

| Diagnostic measurement | Square reference | Square candidate | Raised reference | Raised candidate |
| --- | ---: | ---: | ---: | ---: |
| Extra-update rate | 53.89% | 59.81% | 84.34% | 84.66% |
| Episode with any false visual association | 0/8 | 0/8 | 0/8 | 1/8 |
| Mean selected wrong-cue dwell | 7.76 s | 7.51 s | 6.38 s | 6.95 s |

Extra updates include near-source duplicates. Wrong-cue dwell is time with selected
bearing >20° from truth during scheduled emission, not an identified false track.
Whole-episode rates retain natural pauses across treatments.

**Numerical limits:** the single candidate false association disappears on the same
four initial episodes at 5/2.5 ms integration or 48 instead of 24 angular samples;
first-acquisition success stays unchanged, while ray refinement affects other outcomes.
Native polygon/ideal-shoebox early paths differ at a few positions (worst residual
energy .1235%, dominant arrival unchanged). Held-out candidate cache RMS error:
3.21% at 24 samples, 2.23% at 48; reference <.07%. These failed isolation controls
prevent attributing every consumer change to the tail or claiming full numerical
admission. They add no physical budget and do not establish replacement necessity.
Fresh 65536-ray/2.5 ms confirmation was separately predeclared.

**Consumer and physical-reference controls.** Exact free-field direct propagation
at a local bearing of 45 degrees triggers large erroneous CUDA estimates on both
layouts; three off-diagonal controls remain within .59 degrees. A direct-only
closed-loop ablation on the sixteen episode programs has no false visual
association and still has about 21.7% extra updates and 5.97 s selected wrong-cue
dwell. These expose an unchanged consumer limitation independently of the late
field; replacing a reflection engine cannot correct that direct-only behavior.

Selected [MeshRIR S1-M3969 measured responses](https://zenodo.org/records/10852693)
provide an auxiliary independent check at exact recorded positions (a different
four/five-element layout). The [primary dataset description](https://www.sh01.org/MeshRIR/)
describes sequential robot-positioned microphone measurements, a 7 x 6.4 x 2.7 m
room and mean .38 s decay. The six selected responses measure .333–.438 s mean
band T20 at 250–4000 Hz. Unchanged RTX replay of eight speech programs per layout
shows 0% extra updates for the planar layout and 85.42% for the raised layout at
one common approximate digital calibration; +/-6 dB sensitivity is retained.
However, early measured delays imply about 52 degrees versus 36.87 degrees from
source-coordinate metadata; absolute grid placement/wall materials are also
unavailable in the inspected primary metadata. No channel-wise delay correction
or source-coordinate rewrite is applied. This is neither a matched physical twin
nor evidence that one simulated room response is closer to reality.

### Refined conditional confirmation and recommendation

The predeclared **192 fresh episodes (21000–21191)** completed on RTX 4090 at
65536 rays, 2.5 ms integration and fixed field seed 17001. Independent uniform
layout/schedule draws gave 92 square, 100 raised, 100 intermittent episodes.
Inference concerns this fixed room/field/task recipe, not room/field populations;
the four-field coarse diagnostic and failed controls remain retained.

| Confirmed measurement | Square reference | Square candidate | Raised reference | Raised candidate |
| --- | ---: | ---: | ---: | ---: |
| First visual acquisition within 10 s | 92/92 | 92/92 | 100/100 | 100/100 |
| Extra-update rate | 53.36% | 50.44% | 84.23% | 84.09% |
| Episode with any false visual association | 0/92 | 0/92 | 0/100 | 1/100 |
| Mean selected wrong-cue dwell | 7.87 s | 6.39 s | 5.32 s | 5.37 s |
| Mean visual resumption time | 1.499 s | 1.419 s | 1.339 s | 1.387 s |

Pooled candidate-minus-reference acquisition success is 0 points, conservative
95% interval [-2.26,+2.26]. The false-association difference is +.52 points,
interval [-2.25,+3.28]. Using the same five-point rate margin as a conservative
AV diagnostic, this pooled interval fits; it does not redefine the existing
observation-rate gate. The **raised-only false-association interval remains
inconclusive**, [-4.27,+6.21] points. Pooling does not admit that individual stratum.
The square interval is [-4.65,+4.65]. All 100 intermittent episodes acquire the
object after both resumptions; treating the whole episode as the independent
binary unit gives a pooled difference interval [-4.29,+4.29] points.

The extra-update difference is -2.92 points on square, interval [-4.35,-1.51], and
-.14 on raised, interval [-.71,+.44]. Thus the original large cube discrepancy
is **not reproduced in this different, less symmetric speech/head-motion case**.
That does not erase the valid original counterexample or admit missing scenarios.
The measured MeshRIR raised extras are also all duplicates within the same source
azimuth sector: no >20-degree or opposite-sector estimate occurs in the selected
steady-state replay. High multiplicity alone cannot establish wrong robot turns.

There is a bounded timing benefit. Mean first acquisition is .446/.483/.672 s for
candidate/reference/audio-off. Candidate minus audio-off is -.226 s, interval
[-.329,-.134]. Mean resumption times are 1.402/1.414/3.126 s; candidate retains a
1.724 s advantage over audio-off, interval [1.522,1.917] s. Candidate minus reference
resumption time is -.012 s, interval [-.139,+.114]. These are head/camera reaction
times, not the 100 ms added acoustic/perceptual-latency gate. First-acquisition
success itself has an audio-off ceiling, so this does not close the complete
profile's primary usefulness gate or prove moving-target tracking.

The lone false association is retained: raised intermittent episode 21191 has
three consecutive 30 Hz false-association frames (100 ms), with first resumption
acquisition 3.682 s versus 1.048 s for the reference. A short false-association
span therefore does not imply negligible episode cost. The association does not
command the head; both effects occur in the divergent audio-guided trajectory.
Replaying this episode plus three other condition representatives in a much
smaller GPU batch preserves all task outcomes, rates and dwell; only tiny angle
summaries change. This focused check does not remove the broader existing
raised-array scalar/CUDA qualification limit.

**Interpretation: retain PRA.** The less-symmetric speech/head-motion case preserves
bounded AV benefit without reproducing the cube discrepancy. It neither erases the
cube counterexample nor proves universal harmlessness, physical transfer or full
profile usefulness. This experiment changed no threshold/domain/budget; the later
user-approved cube decision changed that comparison's admission role.

At that stage Step 3 remained unadmitted for binding field controls, numerical/
cache/consumer limits and missing C03/C04/general-motion/two-source room evidence.
Combined producer and full AV/mobile utility remain Steps 4–6. Address measured representation/consumer
issues; these results do not establish a need for a new transport engine.

The refined bank takes about 724 s including reference preparation with eight CPU
workers; the 192-episode, three-treatment GPU loop takes about 480 s. These are
observed offline evaluation costs, not live producer capacity. Exact endpoints,
whole-episode intervals, source/pose programs, full traces and the inspected compact
plot are in `local/r10/08_2_step3_av/confirmation192/summary_final.json`,
`confirmation192/episodes.json`, `confirmation_batch_control/result.json`,
`task_impact.png` and `README.md`. No new physical capture, provider installation,
proprietary multibounce solver or push was performed.

## Measurement reliability (2026-09-16)

**The reproduced numerical perception defects are corrected.** Baseline
`2f9b27b` could return finite but unstable WPE solutions for nearly duplicate
channels. Both scalar and CUDA now solve weighted least squares with reduced QR
and a rank-aware pseudoinverse; float64 peak sums and stable ties correct a
separate equal-neighborhood count discrepancy. Thresholds, context, solver
iterations, acoustic model and public tensors are unchanged. This changes
numerical observations, not the cube's physical response or diagnostic role.
[[experiments/lab-perception-runtime#Measurement reliability correction (2026-09-16)|Lab replay and runtime evidence]]
owns the maintained-consumer checks and cost.

The same direct 45-degree input now yields one event: square 45.00 degrees,
raised 45.14 degrees, agreeing with the scalar solution. Across the twelve direct
and cube-window reproductions, WPE scalar/CUDA relative RMS difference is at most
4.13e-7. Four complete saved cube streams (128 updates) have 100% activity/count
agreement, with maximum matched direction difference .000366 degrees. Solo versus
32-environment checks also pass, including reversed IDs, a 100x louder neighbor
and selective neighbor reset; maximum difference is .000009 degrees. This resolves
the reproduced raised-reference numerical limit, not general perception accuracy.

### Sampling and early-response attribution

The existing angular bank's full-response interpolation error is dominated by
native early specular paths. Three order-6/7 image paths are absent at each of two
ring positions near corner intersections; there are no duplicate paths. Narrow
visibility discrepancies spread around the ring through periodic interpolation.
Native opaque-door tolerances were not relaxed. Using the existing held-out points,
300–6000 Hz RMS normalized to the total indirect response gives:

| Existing bank | Full indirect error, maximum | Late-component error, maximum |
| --- | ---: | ---: |
| 4096 rays, 24 angles | 3.214% | .0801% |
| 4096 rays, 48 angles | 2.234% | .00671% |
| 65536 rays, 24 angles | 3.211% | .0784% |

A targeted 36-case observation control uses both layouts, three saved speech
clips and six head poses, including either side of the affected early-path
transition. Cached full D versus exact native early/direct plus the same cached
late field produces no count disagreement; maximum matched angular difference is
.305 degrees. Replacing only native early response with the independent shoebox
early response changes one count (square, -30-degree yaw, clip 2: two events versus
one); maximum matched angular difference is .497 degrees. This intervention
identifies a separate early-model contribution to observations. It does not
establish a population rate bound or prove that all consumer differences are due
to the late tail. The saved PCM permits reuse without another ray campaign.

The full-cache 1% pressure-isolation control remains failed. Small late-component
error does not establish full-response interpolation accuracy. General-motion
admission must evaluate the actual D producer at the microphone positions, or
qualify the evaluator's sampling on the affected trajectories. Tail-only causal
claims require matched early components or an explicit early-response intervention;
do not replace production native paths with ideal-shoebox paths to force agreement.

### Focused AV preservation

Four previously selected episode programs (21000, 21002, 21004, 21191), covering
both layouts and emission schedules, were replayed with the same saved field and
candidate/reference/audio-off treatments. All acquisition/resumption outcomes,
miss/extra rates, wrong-cue dwell and false-association metrics are unchanged.
Only angular summaries change, by at most .00153 degrees. Episode 21191 retains
its 100 ms false association and delayed resumption; correcting WPE does not erase
that consumer counterexample. This is targeted numerical preservation on the
existing angular bank, not renewed confidence intervals or general-motion admission.

Earlier cube/AV/direct-only/measured-replay rate tables and confidence intervals
retain the preceding numerical runtime. They are historical evidence, not fresh
qualification of the corrected consumer. No acoustic matrix or 192-episode campaign
was repeated for this numerical maintenance. Step 3 then remained `not_admitted`
pending its binding field and representative motion/room/observation gates. These
findings do not establish a need to replace PRA.

## Joint motion and observations (2026-09-16)

The new panel starts from `main@e3fee8f` and uses the actual optional D producer
at microphone positions, followed by the corrected maintained RTX 4090 consumer.
It does not use the earlier angular cache. Parameters and the compact allocation
were recorded before scoring in `local/r10/08_2_step3_motion/README.md`.

### Controlled-plane evidence

C03 covers source speeds 0/.1/.5/1.5 m/s; C04 covers receiver translation
.5/1 m/s and yaw 60/90 degrees/s. Both exact arrays use the protocol plane,
2.1-second emission/motion and two seconds of retained tail. The gain-.1 direct
condition is the declared sensitivity ablation, not physical occlusion. Each of
32 layout/motion/gain cells has four paired independent S0 waveforms. Inference
is conditional on the prescribed geometry and one persistent field realization;
it does not establish a random-room or field-seed ensemble result.

The transport reference derives Lambertian weights and retarded source-to-plane-
to-receiver lengths analytically. It shares the declared persistent quadrature,
band synthesis and convolution primitives, whose normalization has separate
controls; this is independent transport validation, not independent software
validation of the shared synthesis. An independent .05 m surface quadrature
checks the actual plane at twelve trajectory states. Maximum relative energy
error is .00169%; spatial/temporal complex-coherence errors are .0000189/.0000151,
below .1. Initial analytical/native pressure agreement is within .000287% RMS.

Actual-producer replay from the exact-pose responses differs by less than
2.7e-7 relative RMS, including the checked reuse of the held tail. Dynamic array
reordering/regrouping, equivalent source IDs, reset and independently owned
environments preserve the signal exactly. Different PCM partitions differ by
less than 1e-7 in the dynamic structural control. Plane responses are unchanged
for 4096/16384/65536 rays and orders 3/5/7: this scene has only explicit first
scattering. The 2/4-second omitted-energy fraction is below 5e-16. These controls
do not establish room late-tail, horizon or higher-interaction convergence.

At 10 ms, diagnostic mean/p95 angular intervals fit their budgets in all cells;
maximum point changes are .613/.950 degrees. Miss/extra point differences reach
7.14 percentage points for the fastest source, but their four-episode intervals
are inconclusive. Zero differences also remain inconclusive under the unseen-
discordance guard. This is not a blanket C03/C04 PASS.

The same four programs refine C03 at 1.5 m/s and C04 yaw at 90 degrees/s to
5/2.5 ms. From 10 to 5 ms, a conditional angular p95 changes by 7.81 degrees
and a miss rate by 5.36 points. From 5 to 2.5 ms, maximum point changes across
the two models are .224 degrees on mean, .515 on p95, 1.79 points on rates and
25 ms on acquisition. Few-episode rate convergence remains open; neither this
refinement nor a favorable model comparison admits unrestricted 10 ms updates.

### Fresh fastest-source confirmation

**All five approximation-impact budgets pass** for C03 at 1.5 m/s, both arrays
and gains, using 96 fresh paired waveforms per cell and 2.5 ms responses. The
95% intervals use whole-episode resampling; the gain-.1 extra-rate zero-discordance
bound is +/-3.77 points. Absolute rates and paired changes are:

| Array / direct gain | Misses: reference → candidate | Extras: reference → candidate | Miss change, pp [95% CI] | Extra change, pp [95% CI] |
| --- | --- | --- | --- | --- |
| Square / 1 | 35.27% → 33.48% | 35.27% → 33.48% | -1.79 [-3.20, -.44] | -1.79 [-3.20, -.44] |
| Raised / 1 | 36.38% → 34.97% | 45.24% → 44.12% | -1.41 [-2.98, .15] | -1.12 [-2.53, .22] |
| Square / .1 | 88.84% → 85.79% | 100% → 100% | -3.05 [-4.84, -1.26] | 0 [-3.77, 3.77] |
| Raised / .1 | 53.42% → 51.34% | 100% → 100% | -2.08 [-3.27, -.89] | 0 [-3.77, 3.77] |

Maximum mean/p95 point changes are .445/.384 degrees; every angular interval
fits the 5/10-degree budgets. The largest upper endpoint for added acquisition
latency is 19.8 ms, below 100 ms. The weak-direct PCM ratio is about -8.5 dB.
Directional occupancy in the retained tail averages .2 seconds in both treatments;
these are update events, not false tracks or robot actions.

Angular quality is conditional on matched observations, with coverage retained.
In square/gain-.1, reference and candidate match 150/191 of 1344 eligible events,
from 82/92 of 96 episodes. Empty episodes contribute full misses and no angular
error mass; they are not zero-angle successes. The final `qualification.json`
corrects the first summarizer's unnecessary rule that any empty episode makes
the entire angular estimate undefined. Whole-episode bootstrap samples with no
usable angular observations remain undefined. Raw PCM, observations, eligibility,
thresholds and budgets are unchanged; diagnostic summaries are preserved to
numerical precision. `RESULTS.md` provides all absolute values, intervals and coverage.

This is a **relative-fidelity PASS**, conditional on one persistent field, not a
claim of good absolute tracking at this speed. Both treatments have substantial
misses/extras. A fixed, unfitted context-midpoint diagnostic on the four earlier
gain-1 programs reduces nearest-direction error from 18.9–20.4 degrees against
instantaneous truth to 4.3–6.6 degrees against the 375 ms midpoint of the 750 ms
consumer window. This suggests a shared temporal-averaging contribution. No
timestamp is backdated and admission scoring is unchanged. The other C03/C04
rate confirmations, field-seed generalization and unrestricted update-rate
qualification remain open; this result does not admit the full movement domain.

### Representative-room boundary

The cost preflight measures about .12 seconds per plane pose, 83 seconds in E1
R05 and 109 seconds in E1 screen R08 at 4096 rays, before parallel-job contention.
The furnished/screened fields contain 8.67/12.93 million pressure modes. These
native CPU costs are separate from simulated perceptual latency. The allocation
therefore includes bounded two-source/receiver-motion and screen-edge/source-
motion probes, with exact 10 ms poses over a declared 200 ms movement segment.
They do not replace full A04/A08/M01 routes or their source/material conditions.
Two sequential furnished/two-source producer poses, including an interrupted
emission prefix, reproduce the saved responses and PCM exactly.

Both bounded probes complete 21 exact motion poses and a 4.1-second PCM program
per layout. E1 two-source/receiver motion has no missed/extra events in twelve
eligible LOS updates on either array; mean/p95 errors are 4.24/12.72 degrees on
square and 4.70/13.55 on raised. Tail directional occupancy is .4 seconds.
The screen-edge probe has 17/12 directional updates on square/raised out of 41,
with .5 seconds of tail occupancy. Its arrivals remain directionally unresolved
for qualification. These are one-program absolute results without rate intervals.

The room probes do not cover the prescribed physical weak-direct range: E1
two-source layout DRR spans about -5.93 to -3.92 dB; the screen probe begins at
-20.84 dB on square with only one directly illuminated microphone, then has no
direct energy. Raised is fully occluded throughout. Band/source/microphone/pose
energies are retained in `rooms/observations.json`; zero direct energy is explicit,
not a finite logarithmic-floor measurement. Full weak-direct moving routes,
ordinary moving geometry, room conditioning and matched references remain open.

Full moving multibounce room references and material conditioning remain open.
NLOS observations must not be scored against hidden-source bearing as though it
were a validated arrival direction. The room probes can establish integration
and absolute observations; they cannot by themselves establish approximation
budgets. At this stage the cube's diagnostic exception and Step 3's
`not_admitted` status were unchanged. The 96-program confirmation takes about
20.5 minutes including PCM replay and both consumers, excluding native bank preparation; this is an offline
campaign time, not an isolated throughput benchmark. No provider replacement or
new multibounce solver is implied by these results.

## Targeted closeout and projection correction (2026-09-16)

A fresh E3 closed/open/closed probe exposed a small opaque-door leak in the
persistent projection: summed closed-door reflected RIR energy was 1.2041e-8,
about 5.94e-7 of the open response. The native flight left the door and reached
its jamb only 4.8 micrometers away in the door-normal direction. Segment endpoint
tolerance then allowed interpolation onto a surface element behind that door.
This was a structural defect, independent of the diagnostic cube mismatch.

The corrected native connection check preserves the previous reflector's exit
side using its recorded surface and outgoing flight direction. Transport remains
native; no received gain or energy threshold masks the residual. Actual D now
has exactly zero direct and reflected pressure energy on all nine microphones
at both closed poses, nonzero open pressure, and an exactly identical returned
response. Open reflected energy is .0202555 summed over the nine microphones.
Fifteen native/field regressions and nine actual-producer tests pass. The added
private projection capability requires rebuilding the bridge; specular-only
compatibility and installed PRA remain unchanged.

Fresh evidence and predeclared C04/seed/room allocation are in
`local/r10/08_2_step3_closeout/README.md`. Original room responses and the prior
native library are retained there. Room projection checks are repeated only
where the correction can affect them. Single-scatter C03/C04 response banks
never enter later-surface projection and remain applicable. This correction
does not admit Step 3 or change any physical/observation budget.

### Fresh C04 confirmations

**All forty metric decisions pass** on the selected maximum receiver translation
(1 m/s) and yaw (90 degrees/s): each trajectory has 96 fresh paired source
programs, both exact arrays and direct gains 1/.1, at 2.5 ms. Field seed 31001
and unchanged RTX 4090 perception are used throughout. The reference independently
evaluates retarded Lambertian transport with the checked shared surface synthesis;
it is valid for this single-scatter plane, not arbitrary room pressure.

Every per-program miss/extra rate and acquisition latency is identical between
candidate and reference. The retained unseen-discordance guard gives 95% rate
intervals of +/-3.77 points and latency intervals of +/-79.2 ms. Mean/p95 angular
differences are numerical-scale; the largest p95 point change is .000733 degrees.
No source programs from the diagnostic pilot enter either confirmation. Lower
speeds retain their compact diagnostic coverage; these selected confirmations
do not establish unrestricted 10 ms updates or all-field population equivalence.

Absolute difficulty remains visible. For yaw with gain .1, square reference and
candidate both have 10.64% misses and 96.95% spurious updates; raised has 6.92%
misses and 99.93% spurious updates. Translation/gain 1 has zero misses/extras in
both treatments on both arrays. Relative agreement does not certify useful
tracking. The local `RESULTS.md` contains every cell's absolute values and
intervals; update extras are not false tracks or robot actions.

### Independent field seeds and both signed follow-ups

Three fresh native/pressure seeds (31002–31004) exercise C03 at 1.5 m/s and C04
yaw at 90 degrees/s, with four new source programs per case/seed and both
arrays/gains. C04 rate/latency differences are zero throughout. C03 maximum
absolute mean/p95 point changes are 2.00/3.35 degrees, while miss/extra changes
reach +/-12.5 points. Two low-N empirical intervals are FAIL: increased misses
on field 31004/square/gain .1 and reduced extras on field 31002/raised/gain 1.
Both signs matter; fewer extras cannot inherit the cube diagnostic exception.

Each signal receives a separate, fixed **96-fresh-program confirmation**,
declared before its new outcomes. Programs 49000–49095 and 50000–50095 do not
overlap either pilot. **Both confirmations pass all five budgets.** No sample
is automatically extended and no other completed cell is repeated.

| Field / array / gain | Misses reference → candidate | Miss delta, pp [95% CI] | Extras reference → candidate | Extra delta, pp [95% CI] |
| --- | --- | --- | --- | --- |
| 31004 / square / .1 | 73.66% → 72.47% | -1.19 [-3.13, .67] | 100% → 100% | 0 [-3.77, 3.77] |
| 31002 / raised / 1 | 35.04% → 33.26% | -1.79 [-3.35, -.22] | 43.90% → 42.63% | -1.26 [-2.68, .07] |

For the first row, mean/p95 changes are -.533/.422 degrees; the added-latency
interval is [-175.0, -7.3] ms. For the second, mean/p95 changes are .042/-.058
degrees and the latency interval is [-31.3, 13.6] ms. Directional tail occupancy
remains .2 seconds in both treatments. The two original four-program FAIL
outputs are preserved; their out-of-budget effects are not reproduced in the
fresh confirmations. Remaining low-N rate intervals are inconclusive, not
population evidence. This completes the requested finite-seed diagnostic and
targeted follow-ups, not a 95% equivalence claim over all possible field seeds.

### Representative properties and room integration

The minimum panel adds thirteen exact corrected D poses across E0_R02, E2_R08,
four E1 field seeds, a physical weak-direct position and E3 door/E1 screen
return poses. Nine non-door poses are bitwise identical before and after the
departure-side correction. Ordinary geometry visibility is tested separately:
301 door poses and 841 screen poses give **10278 microphone connections with
zero disagreements** against independent finite-door-plane/box intersection.
This validates geometry updates and visibility; full diffuse PCM/history over
those ordinary trajectories remains open.

The initial E1 receiver measured about -14 dB DRR, outside the prescribed -12 to
-6 dB stratum. That result is retained. A physically repositioned receiver gives
**-11.64/-11.59 dB** on square/raised without fitted gains. Four independent
source programs through unchanged RTX perception have zero misses in eligible
updates, but 21.43%/42.86% spurious updates; conditional mean/p95 errors are
.92/1.55 and 1.20/2.68 degrees. Directional tail occupancy is .4 seconds. Across
the four farther E1 fields, misses remain zero while spurious rates vary widely,
including 5.36–100% on square. These are static absolute diagnostics without a
matched room-pressure reference or population confidence claim. The 4.1-second
PCM replay agrees with production convolution below 3.4e-7 relative RMS.

Actual band/microphone pressure T20 ranges are .169–.222 s in E0_R02,
.486–.619 in E1's in-range weak-direct position, .601–.713 in the original
screen pose, .807–.916 in E2_R08 and .509–.565 with E3's door open. Some do not
meet their nominal recipe target tolerance. Those recipes were not independently
conditioned: these results establish neither matching target decay nor a
renderer/reference failure. They are pressure measurements, separate from the
older scalar-energy envelope controls. The unchanged E2 response at 2/4 s has
maximum omitted band energy fraction **1.02e-14**, below .001, conditional on the
same declared native energy cutoff.

Controlled isotropic synthesis now passes both arrays, including displacement
and yaw: maximum spatial complex-coherence error .01181 and cross-pose error
.02907, below .1. This is an exact independent-mode ensemble using the actual
fractional-delay/filter synthesis; it does not assert arbitrary-room isotropy.
Production incident surface capture is exactly invariant for receiver radii
.05/.1/.2/.4 m with zero native microphone receivers. Finite-radius histogram
convergence remains a separate reference limitation.

The original bounded Office/Hospital acoustic proxies each complete a static D
integration pilot with nonempty actual PCM. Hospital initially hits the existing
100000-node resource guard. An exact count gives 173848 nodes; one explicit local
`max_nodes=200000` follow-up passes without changing geometry, spacing, rays,
order, horizon, SDK defaults or accuracy budgets. The original capacity failure
is retained. Office/Hospital DRRs are -10.21/-10.33 and -8.09/-8.04 dB. These
approved early-acoustic proxies retain their outside connections and material
limits; they are not whole-building late-field references or full moving routes.

### Cost and remaining admission boundary

This subsection records the targeted campaign's verdict before the later
full-room admission revision. The formal closeout below owns current status.

Fresh C04 translation/yaw confirmations take 33.6/29.7 minutes including PCM
replay, RTX perception and bootstrap. They ran concurrently; these are not
isolated throughput measurements or additive elapsed times. Corrected native
room response preparation takes 24.2–157.3 seconds per exact pose in this panel;
Office/Hospital successful pilots take 27.4/24.5 seconds. Native PRA work is
CPU-only by implementation. Offline computation is separate from the unchanged
100 ms simulated added-latency budget. The two targeted field confirmations take
6.4/8.5 minutes including replay, perception and resampling.

| Property | Result at campaign closeout | Boundary |
| --- | --- | --- |
| Shared representation, normalization and causal lifecycle | PASS in retained native/analytic/producer controls | No arbitrary moving-room conclusion from a plane |
| Controlled isotropic synthesis and Lambertian field | PASS | Property-specific independent moment/transport references |
| Selected C03/C04 maxima, field 31001 | PASS | 96 paired programs per trajectory, both arrays/gains, 2.5 ms |
| Three independent field seeds | Diagnostic complete; both adverse-stratum fresh confirmations PASS | Intervals conditional on the selected fields; no population-wide equivalence claim |
| Closed/open/closed D and ordinary geometry visibility | PASS after the jamb correction | Ordinary-motion full diffuse pressure/history remains OPEN |
| Production radius invariance and E2 2/4 s horizon | PASS | Declared native capture/cutoff; finite-radius references remain limited |
| Physical weak direct | Measured in representative static rooms | Complete moving weak-direct reference/observations remain OPEN |
| E0/E1/E2/E3 and Office/Hospital | Bounded property/integration evidence complete | Not complete conditioned full-room pressure qualification |
| Representative moving-room approximation impact | OPEN | Property-valid multibounce reference, conditioned input strata and complete full-D routes are missing |
| Cube late response and earlier selected-mirror mismatch | Diagnostic limitations retained | Original failed evidence remains; no automatic provider replacement |
| NLOS+D, AV and mobile | Later Steps 4–6 | No new combined-model or complete consumer claim |

**The targeted campaign did not close global Step 3 under the decision then in force.**
At that time the remaining room gate required applicable evidence or an explicit
change to its admission role. Missing references cannot be relabeled PASS, and the cube
exception does not extend to other properties. The results do not establish a
need to replace PRA. Preserve the implemented renderer and the completed controls;
do not repeat the full matrix to address an absent reference.

## Bounded full-room reference feasibility (2026-09-16)

Historical outcome before the subsequent explicit admission revision:
**STOP within the authorized reference-reuse scope; representative full-room
pressure/observation equivalence remains OPEN.** The user retained the current
gate and requested a bounded feasibility audit before complete room trajectories.
No acoustic rendering, GPU perception campaign, qualified-control rerun, provider
evaluation or production change was performed. Evidence is in
`local/r10/08_2_step3_room_reference/{README.md,audit.py,audit.json,RESULTS.md}`.

The missing capability is an independently justified **joint spatial/temporal
pressure field** for the existing furnished, scattering rooms. Exact late phase
throughout the room is not required. A statistical reference remains eligible,
but it must preserve the geometry-dependent correlations that affect multichannel
observations and must not reuse the candidate's late projection as its own oracle.

| Reusable component | Valid contribution | Remaining boundary |
| --- | --- | --- |
| Saved coherent shoebox ISM/order bases | Specular pressure, independent reference conditioning and retained order convergence | Empty rectangular specular rooms; omitting E1 furniture/scattering changes the prescribed case |
| Retarded Lambertian plane and selected two-scatter/mirror integrals | Qualified transport/covariance for their declared interaction families | No complete furnished-room sum of mixed/later interactions |
| Installed PRA 0.10.1 hybrid RIR | Static per-receiver band/directional energy and RIR synthesis | `Room.compute_rir` calls `compute_rt_rir` separately per microphone/source; each generates a Poisson/directional sign sequence without joint microphone coordinates or persistent world-field state |
| Checked native pre-histogram capture | Reusable surface/local coordinates, directions, lengths, energy and interaction history | Energy samples and capture-local ray IDs do not define a persistent material pressure realization; an independent joint-field mapping remains missing |
| Candidate with finer sampling, or early-only replacement | Numerical refinement or causal ablation | Does not independently validate the candidate's full-room late-field formulation |
| Existing measured MeshRIR subset and NVIDIA/D artifacts | Auxiliary physical replay or bounded integration | No matched moving E1/E1-screen room reference |

These implementation findings are grounded in the installed source and recorded
native interface. The [PRA room documentation](https://pyroomacoustics.readthedocs.io/en/latest/pyroomacoustics.room.html)
describes specular ISM and hybrid scattering; it does not establish the missing
shared moving-room reference. A single small algebraic diagnostic using saved E1
1 kHz energies constructs distinct positive-semidefinite cross-channel matrices
with the same marginal energy to below 1.6e-16 relative error. It demonstrates why
energy/decay alone cannot identify joint pressure; it is not a new renderer FAIL,
a pair of matched physical rooms or an application of the isotropic 0.1 budget.
Native directions/history contain more information than this marginal example;
the missing work is their independently justified pressure mapping.

### Minimum conditional path allocation

Keep three existing motion trajectories and one existing static companion, with
both exact arrays, original source content, materials, emissions and full episode
durations. Nothing was scheduled or removed from the wider approved domain.

| Existing cases | Scope of the missing reference |
| --- | --- |
| A04_1, E1-screen/R08, 30 s | Full 3.4 m source path at 1.5 m/s through shadow/visibility transitions; receiver fixed |
| M01_1, E1/R05, 64 s | Full 2.5 m receiver path at 1 m/s, .5 m/s² acceleration and prescribed 0→90-degree yaw; source fixed |
| A09_0, E1-screen/R08, 30 s | Screen +1.6 m and back at .5 m/s with .5 s endpoint dwell; source/receiver fixed |
| A08_1, E1/R05, 30 s | Existing static S1/S2 two-source mixture, second source -6 dB; no extra trajectory |

Saved source programs and source/screen clocks exist. The prepared episode pack
does not bake M01's receiver path: its existing motion declaration and trapezoidal
helper can supply that small adapter. This is separate from reference-model
validity. No AV/head policy or homing test is introduced. Nominal R05/R08 recipes
still need reference-side decay/DRR conditioning; the existing NLOS scoring rule
must not substitute hidden-source bearing for a validated arrival direction.

### Why execution stopped

The smallest missing reference would need an independent statistical coupling of
late/mixed native transport, persistent multichannel responses through endpoint
and geometry motion, and evidence validating that formulation before conditioning
or confidence repetitions. This is a second full-room **pressure-field model and
its qualification**, beyond a thin adapter to existing validated references.
PRA's native geometric traversal could still be reused. The audit does not prove
that another complete ray engine is necessary or that no smaller future approach
exists; it found no valid bounded reuse path available in this checkout.

Saved per-pose timings also discourage launching brute-force trajectories before
resolving that validity gap. At 10 ms, a naive serial extrapolation for only the
moving segment is 11.9–14.0 hours for A04, 11.5–13.9 for M01 and 26.5–31.2 for A09,
one source/field with nine combined microphones. At 2.5 ms the corresponding
ranges are 47.5–56.0, 45.9–55.3 and 105.9–124.7 hours. These are not measured route
costs or lower bounds: receiver-only reuse, caching and parallelism could reduce
them. They exclude reference development/rendering, conditioning, full-episode
replay and confirmation. No cadence or budget was changed to fit a cost estimate.

**Retain PRA and stop this reference-construction work.** At this point a separate
user decision was needed before reference-model development beyond the audit or
revision of the full-room requirement. The user subsequently declined reference
development and explicitly accepted that unvalidated property as a non-blocking
limitation. The audit's capability findings and cost limits remain unchanged.

## Step 3 formal admission (2026-09-16)

**PASS under the explicitly revised criteria. Retain PRA.** This is an admission
review of saved evidence at `ad4a6e2`, not a new experiment or a renderer repair.
The full-room property is **NOT VALIDATED — accepted known limitation**. No other
binding Step 3 requirement or confirmed material representative failure remains
open within the approved representative allocation. No tests, reference runs or
provider evaluations were started for this closeout.

### Retained binding evidence

| Requirement | Admission result and existing evidence |
| --- | --- |
| Shared realization and causal lifecycle | PASS in the retained native/field/producer controls: co-location, microphone reorder/regrouping, equivalent sources, unchanged refresh, reset/environment isolation, fractional delays, partitioned PCM and emission-stop tails; general D and joint-motion records above |
| Energy accounting and synthesis | PASS for disjoint ISM/scattering/tail ownership, native/filter normalization and bounded band-energy/decay controls; production capture is invariant at receiver radii .05/.1/.2/.4 m; E2 2/4 s omitted pressure-energy fraction is 1.02e-14 with the same native cutoff |
| Qualifiable field statistics | PASS for the retained Lambertian and controlled isotropic references; maximum isotropic spatial/cross-pose complex errors .01181/.02907 are below .1; selected-mirror discrepancy remains separately diagnostic |
| Opaque visibility and ordinary geometry updates | PASS after the native departure-side correction: actual closed/open/closed D is exactly zero/nonzero/zero; 10278 ordinary door/screen connections agree with independent geometry; this is not a claim about full moving diffuse pressure/history |
| Joint C03/C04 observation impact | PASS for 96 fresh paired programs per selected maximum source/receiver/yaw trajectory at 2.5 ms, both arrays and direct gains, with the unchanged RTX consumer and 95% budgets; C03's corrected `qualification.json` is authoritative |
| Independent-field follow-up | Approved finite-seed check complete: three fresh fields; both signed low-N adverse strata have separate 96-program confirmations, all five metrics PASS in each; no population-wide field-equivalence claim |
| Representative room integration and material-error review | Bounded E0/E1/E2/E3, two-source room probe and Office/Hospital integration evidence retained; static physical weak direct measures -11.64/-11.59 dB; the demonstrated jamb defect is fixed and both adverse seed pilots are resolved by their planned confirmations |

Sources: `local/r10/08_2_step3_general/` for original structural/energy controls;
`local/r10/08_2_step3_motion/{RESULTS.md,qualification.json}` for joint motion and
corrected C03 inference; `local/r10/08_2_step3_closeout/{RESULTS.md,summary.json}`
for final C04, both seed confirmations and representative controls. The latter
directory's `summary_initial.json` predates the second seed confirmation and is
not the final verdict. Original artifact-level OPEN labels describe the criteria
at execution time; this section changes admission, not measurements.

### Accepted limitations and outstanding-scope reconciliation

| Item | Current role; no implicit PASS |
| --- | --- |
| Representative full-room moving pressure/observation equivalence | **NOT VALIDATED, non-blocking known limitation** by explicit user decision. The missing independent joint-field reference, dependent room conditioning and complete matched full-D routes are one unresolved property, not new completed controls |
| Ordinary-motion full diffuse PCM/history and moving physical weak-direct room equivalence | Unvalidated parts of the full-room limitation. Geometry-only visibility and static weak-direct evidence do not establish these properties |
| Cube late response | Original pressure-decay/spurious-update FAIL remains diagnostic under the earlier cube decision; no physics repair or rewritten interval |
| Selected rotating-mirror covariance | Original approximately .17045 error above .1 remains diagnostic with bounded weak-direct impact evidence; controlled-statistics tolerances elsewhere are unchanged |
| Numerical cadence and finite sampling | Maximum-motion observation admission uses 2.5 ms; unrestricted 10 ms is not qualified. Lower-speed and low-N seed cells retain diagnostic scope; no indiscriminate matrix repetition or population-wide confidence claim |
| Nominal room decay recipes | Actual pressure decay is reported; some recipes miss nominal targets and lack independent conditioning. No target-match PASS is claimed. Analytical normalization and property-valid band-decay requirements remain binding |
| Resources and runtime | Offline native preparation measured 24.2–157.3 s per room pose; Hospital requires the existing 200000-node local capacity override. No real-time or whole-building fidelity claim |
| Full-pressure angular cache | Failed evaluator isolation remains excluded from unrestricted motion claims; C03/C04 closeout uses actual microphone-position producer responses |
| NLOS+D, complete AV/mobile usefulness and physical transfer | Combined producer and consumer gates remain Steps 4–6; physical transfer is separate. Step 3 does not establish robot task success |

Full-room equivalence remains unknown, so this review does not assert that no
material room error could exist. Any subsequently demonstrated structural defect
or confirmed material representative error reopens affected qualification under
the unchanged budgets. The already passed controls remain reusable; no new
independent room reference or alternative provider is planned by this decision.
The next implementation step is **Step 4: qualify the combined producer**.

## Evidence and reproduction

All locations are local ignored evidence, not package dependencies. Keep original
reports/builds unchanged; use new output directories for reruns.

| Directory under `local/r10/` | Contents |
| --- | --- |
| `08_2_gate/` | Initial failed candidate patch, native probes, PCM/logs; isolated replay at `5d96078` |
| `08_2_timing_recheck/` | Corrected time-origin controls, PRA reference, full-channel crash backtrace and runner |
| `08_2_architecture/` | Initial hybrid/PRA visibility and co-location audit; native component controls |
| `08_2_intermediate/` | README recipes, final physical/stream/Isaac/parity reports, PCM and profiles |
| `08_2_complete_coverage/` | README, diffuse/pathing/visibility gates, archived R9 replays and TASCAR component |
| `08_2_extensions/` | README, native route/shared-event prototypes and Python/Isaac result equivalence |
| `08_2_usefulness/` | README, paired observations, sensitivity figure, configurations and replay |
| `08_2_dynamics/` | README, selected-flight history and anchored/later-scatter native controls |
| `08_2_step3_diffuse/` | Checked native transport, persistent statistical candidates, independent rotating-mirror reference/refinement, fresh sampler confirmation and the Step 3 stop result |
| `08_2_step3_impact/` | Earlier selected-mixture observation impact, retained physical discrepancy and bounded continuation evidence |
| `08_step2_nlos/` | Native preparation, corrected coverage, refinement and final selected-route closeout |
| `08_2_step3_relevance/` | Cube absolute-rate/persistence, late-response ablations and downstream decision replay |
| `08_2_step3_av/` | Historical moving-head/camera diagnostics, 192-episode confirmation, batch control and measured-reference audit |
| `08_2_step3_measurements/` | README, numerical failure/fix reproduction, same-PCM scalar/CUDA/batch checks, early/cache isolation, targeted AV replay and corrected runtime cost |
| `08_2_step3_motion/` | Predeclared joint panel, actual-producer exact-pose PCM, analytic/dense-plane references, dynamic lifecycle controls, update refinements, RTX observations and bounded room probes |
| `08_2_step3_closeout/` | Fresh C04/field-seed confirmations, isotropic and radius controls, E3 correction, representative room pressure/observations, ordinary visibility, horizon and NVIDIA integration/cost pilots; per-property summary and remaining admission gaps |
| `08_2_step3_room_reference/` | Bounded reuse/capability audit, unchanged three-path/static-companion selection, energy-information diagnostic, saved-cost extrapolation and precise reference-construction stop result |
| `08_2_step3_general/` | General optional D implementation, physical/reference corrections, conditioned-room decay and RTX observation-impact failure after refinement |

Production/build interface: [[topics/geometry-acoustics|Geometry Acoustics]].
Provider alternatives: [[experiments/acoustic-provider-evaluation|Provider Evaluation]].
Historical source detail/chronology: R9/R10 paths at `5cfe48d`. This consolidated
record preserves outcomes and limits; it does not retroactively mark failures passed.
