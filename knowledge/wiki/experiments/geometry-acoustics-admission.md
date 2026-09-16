# Geometry Acoustics Admission Evidence

Recorded experiments: 2026-09-10/11/15. This page preserves decisive measurements,
reference corrections and replay pointers; it does not repeat the implementation
plan. [[decisions/robot-audition-fidelity|The approved task-domain decision]] governs
which failures block admission. [[implementation_phases/r10-geometry-acoustics-integration|R10]]
owns current implementation work.

## Admission summary

| Contribution | Established | Still unqualified |
| --- | --- | --- |
| Steam direct + native PRA specular intermediate | Bounded arrival/gain, reflected visibility, streaming and actual Sim/Lab/Kit; scalar/CUDA agreement on identical PCM | General motion, diffuse pressure and selected-route production integration |
| Steam selected routes | Step 2 native selected-route transport, producer lifecycle and ordinary-motion controls | Calibrated pressure/diffraction, combined producer and consumer admission |
| PRA persistent surface pressure | Optional D implementation; native visibility, first-scatter quadrature, shared-field and streaming controls | Conditioned smooth-room pressure decay and observation impact fail; full motion/room/task admission remains open |
| Closed-loop tasks | Targeted NLOS benefit and diffuse observation sensitivity | Both approved AV/mobile consumer gates |

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
Probe coverage, duplicate representation weighting, rebake identity and full
production directivity/lifecycle still need qualification.

## Step 2 native preparation — 2026-09-15

The maintained private bridge now uses Steam UniformFloor generation, bounded
probe capacity, native baking and alternate search. All visible source-probe
weights participate in exported routes. LOS is excluded; uncovered endpoints,
missing floor and native preparation failures are explicit errors. Equivalent
geometric/EQ contributions sum interpolation weights; duplicate native records
fail. Native meshes can be retained with immutable instance transforms.

Ten focused native/stream checks pass: automatic probe generation, screen detour
lower bounds and per-route one-sample timing, closure/restoration, LOS exclusion,
coverage/capacity failure and the prior filter/visibility/transport controls.
The SDK baker needs a non-null progress callback; the bridge supplies one.
This is component validation, not ordinary-motion or producer admission.

### Producer integration and surface-endpoint correction

The optional producer path passes static/moving read partitioning, source-stop,
reset and source/array independence tests. Whole-host checks pass 662 unit/contract,
336 integration and 58 release tests. A live RTX 4090 / CUDA Physics run passes
four simulated seconds, 180 native door updates, selected/LOS/selected transitions
and reset; it measured about 228 seconds including application startup/shutdown.
This is bounded integration evidence, not a real-time claim.

Step 1 E4 revealed probes exactly on wall planes: native endpoint exclusion allowed
an impossible 8.23 m path versus a 9.22 m detour bound. E3 also leaked through its
closed planar door on the coarse grid. Native probe clearance and inclusive route
validation remove these shortcuts. ABI 2 preserves interpolation-pair identity
through simplification, fixing false duplicate detection on the denser grid.
Both 1 m and 0.5 m grids now respect E4 bounds across both layouts; E3 closed yields
no selected route on both grids. Screen paths and bounded Office/Hospital coverage
complete on both grids (Hospital 0.5 m: 2399 probes, about 24 seconds preparation).
Initial failures remain in `local/r10/08_step2_nlos/coverage_initial.json`; corrected
coverage and live results are in that directory. Ordinary door/motion refinement
runs are still in progress; no task-utility or diffuse admission follows from these checks.

### Corridor refinement correction

The subsequent refinement control exposed near-total weight loss when an endpoint
aligned with the old lattice: captured weight could fall to 0.00031 instead of 1.
Filtering corner probes alone moved the failure to other grid spacings. The repair
centers the native lattice and uses identical inclusive segment bounds during
native graph baking, alternate validation and route export. It does not renormalize
missing paths. The maintained L-corridor regression passes all nine microphone
positions at 1, 0.5 and 0.25 m spacing: total interpolation weight is 1 within 2e-6,
and every route respects the independent detour bound.

The corrected native binary rebuilds byte-identically (`b9954dc6…`); seven native
controls, eleven filter/transport controls and fourteen producer regressions pass.
The repeated actual RTX 4090 / CUDA Physics control passes four simulated seconds,
180 geometry updates and reset (about 44 seconds including startup/shutdown).
Final-build evidence is in `local/r10/08_step2_nlos/final/`; earlier failed refinement
evidence remains in `dynamics_before_clearance.json`. Ordinary refinement is still
being assessed; these repairs alone do not close Step 2.

The explicit two-alternative screen test then exposed the native tree's
traversal-order neighborhood cutoff. Querying the full native neighborhood and
retaining the nearest visible eight restores both alternatives while preserving
native interpolation weights. The checked `d8d442dc…` build passes 21 native and
producer tests and repeats the CUDA Physics smoke (about 46 seconds). Evidence
for this subsequent build is in `local/r10/08_step2_nlos/qualified/`; earlier
directories remain historical. New transport regressions cover the declared
1.5/1 m/s endpoint speeds, rebuilt probe identity without duplicate arrivals and
directivity when a moving endpoint meets a route node.

### Accumulated length and ordinary opening controls

The pose sweep exposed a separate preparation error: the scene diagonal had also
limited total baked path length. A bent route can exceed that diagonal; at E4
source (7,6.45), the coarse grid retained only 0.883 of the interpolation weight.
The native bake now admits the finite simple-path bound of the graph, while the
producer enforces its explicit travel-time horizon before history can expire.
The final native artifact is `74f3d78b381afd84ff98e20b000705cf3128a831735c888ca60a13ebf77604ba`.

Across 567 E4 pose/channel/grid checks (both layouts, source motion, receiver motion
and yaw), all selected paths respect the independent corridor detour bound and
native segment visibility; interpolation sums remain 1 within 2e-6. Refining
1 to 0.5 m spacing changes weighted path length by at most 0.6214 m and direction
by 3.53 degrees. Refining 0.5 to 0.25 m reduces these differences to 0.00754 m and
1.45 degrees. These are numerical refinement differences, not calibrated
diffraction-error bounds; the default 1 m grid is deliberately coarse.

An ordinary opening must also reconsider previously emitted, unassigned sound.
Native producer controls emit a 1 ms signal behind a gate and a second, persistent
NLOS screen: opening at 2 ms preserves the same arrival as the already-open
reference; opening at 6 ms blocks it. Geometry is checked at passage time. Only
previously `no_selected_route` intervals are reconsidered; previous LOS and assigned
routes are excluded. Source stop, structural rebaking before arrival, and fixed
geometry epochs under fragmented PCM reads have independent producer regressions.
The asynchronous two-gate stress exclusion below remains unchanged.

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

The minimum anchoring prototype fixes first-scatter positions using surface area
and Lambertian cosines, native ISM incidence and ISM/RT suffixes. Twelve plane
controls pass (max complex error 8.21e-6, relative energy difference <=1e-5), without
fitted gain. But a 1 cm moving mirror shifts second-scatter locations 2 cm on a
stationary floor: errors ~0.151/0.300/1.031 at 500/1000/4000 Hz remain across
4096–65536 rays. Fixed first anchors do not solve general multibounce persistence;
finite specular prefixes also remain incomplete. Under the approved scope these
are diagnostics; task-relevant statistical impact decides further work.

## Step 3 shared statistical extension — not admitted (2026-09-15)

New work under `local/r10/08_2_step3_diffuse/` preserves prior prototypes and the
working producer. The checked native PRA extension captures incident surface and
received band energy before histogramming, including parent interactions and
directions. Disjoint ISM/RT receiver ownership, two-sided closed/open/closed
containment, band branching, reproducibility and independent handles pass five
native checks. Seventeen existing specular/Geometry tests pass against the new
library using the Isaac interpreter. This is CPU-native evidence, not live diffuse
PCM, CUDA perception or overall Phase 08 qualification.

The statistical candidate uses fixed material surface nodes and shared delay/
directional modes. Mean native path lengths remain unstable under source motion.
A directional source phase gauge repairs the controlled one/two-scatter case:
at 65536 rays, 0.5 m nodes, 4 ms modes and 64 directions, maximum temporal errors
are 0.05586/0.04768, spatial errors 0.00471/0.01088 and energy ratios
0.99693/1.00344. These bounded scalar-plane results do not establish full banded
normalization, radius behavior, high-order ownership or a converged room tail.
Near-surface refinement needs smaller nodes and more samples; increasing to
262144/1048576 rays reduces its two-scatter temporal error to 0.06343/0.05648.

Native interaction derivatives also correct a translating mirror between diffuse
surfaces (bounded maximum error 0.02002 at 65536 rays), but the corresponding
first-order rotation correction retains bias. In the independent two-Lambertian-
surface control, a smooth mirror rotates 5 degrees around a fixed pivot; that
change can occur in 100 ms at 50 degrees/s. This is a controlled transfer-statistics
test, not an asynchronous-flight stress scenario or a furnished-room reference.

| Native rays; 12 sampler realizations each | Mean complex temporal-coherence error at 500 Hz | 95% interval for the mean |
| --- | --- | --- |
| 262144 | 0.16404 | [0.15981, 0.16807] |
| 1048576 | 0.17045 | [0.16783, 0.17321] |

All realizations exceed the controlled 0.1 bound; 1000/4000 Hz controls pass.
Independent exact image-distance quadrature changes only ~0.000406 between
0.25/0.125 m discretizations at 500 Hz. Native selected path lengths agree with
that geometry within 4.155e-6 m. The reference and sample refinements therefore
do not explain away this candidate's bias. Final confirmation uses fresh native
seeds 100–111 after diagnostic seeds 0–11; confidence intervals resample whole
native realizations, not frames or robot episodes. Scripts, inputs, variants,
derivations and commands are in the local README; `summary.json` owns the numbers.

**Step 3 is not qualified.** The initial stop preceded a larger pressure-transport
redesign. The user subsequently authorized a targeted PCM/observation comparison
of this candidate before deciding on the provider; see
[[decisions/robot-audition-fidelity#Step 3 targeted impact decision (2026-09-15)|the revised diagnostic role]].
The failed 0.1 control remains unchanged. No diffuse configuration is enabled; complete
energy/decay/radius qualification, causal integration, full-room reference validity
and weak-direct observation comparisons remain open. No new CUDA/consumer result
is inferred from these controls. The failed candidate does not prove all PRA or
statistical extensions impossible; replacement evaluation has not started.

## Earlier candidate: targeted observation impact (2026-09-15)

The user authorized this follow-up after the physical stop. The preserved native
transport and `surface_field.project` candidate were not changed. A separate
experimental PCM harness compares them with fixed-surface Lambertian quadrature
and exact mirror-image reference geometry. The 0.17045 temporal-coherence failure
remains recorded; its relevance to observations is measured rather than assumed.
Evidence and reproduction: `local/r10/08_2_step3_impact/README.md`; compact values
in `summary.json`, confidence-interval plot in `impact.png`.

**Result: the rotating-mirror selected-mixture observation comparison passes on
both arrays, including weak direct. Overall Step 3 remains open.** Other cases
retain inconclusive rate/p95 intervals. No fresh confirmation interval establishes
an impact outside its budget; this does not turn inconclusive intervals into passes.
The results support retaining PRA and pursuing the missing qualification, rather
than inferring provider inadequacy from the failed field statistic alone.

### Method and essential controls

- Exact maintained square/raised arrays; 16 kHz, 3.2 s episodes with an interruption
  and final source stop. Pilot: four independent signal/field-phase episodes per
  case; static, source/receiver translation, receiver rotation, one/two sources,
  and the rotating family. Both direct gains 1 and 0.1 are sensitivity axes;
  attenuation does not represent a physical door. No gain is fitted to the field.
- Refine 4096/16384/65536 native rays and 10/5/2.5 ms updates on selected source/
  mirror episodes. Fresh confirmation: 24 episodes for moving source/two sources
  at 65536 rays/10 ms, and 96 for isolated/mixed, rotating/held mirror controls at
  65536 rays/2.5 ms. Arrays and hard conditions remain separate. These refinements
  do not provide an independent model reference or prove full numerical convergence.
- Native scalar energy and the synthesis kernel are checked analytically. Plane
  expected energy differs from reference by at most 0.313%; the fractional kernel's
  passband power is 0.99528–1.000002 and its phase-delay error is <0.000352 samples.
  Whole-Nyquist kernel energy is included explicitly in the random-RIR expectation.
  Co-located/reordered/split microphone, refresh, equivalent source-coordinate,
  partition, stop-tail, reset and independent-state checks pass in this harness.
- Source/receiver/yaw reference quadrature .25→.0625 m changes temporal coherence
  by <0.000097 over the actual episode lags. Mirror energy/coherence refinement
  changes are <0.137%/<0.00425 in the center-microphone control. Refining actual
  reference importance sampling 8192→65536 at .25 m changes joint temporal/
  cross-microphone covariance by at most 0.01740. These are independent analytic
  statistical controls with quantified approximation limits.
- Actual RTX 4090 `TorchPerception`, unchanged thresholds/parameters, observed PCM
  and microphone positions only. Scalar parity on eight selected streams preserves
  every count/activity decision; maximum angular difference is 1.246 degrees.
  Solo/reordered/loud-neighbor/partial-reset CUDA controls also preserve counts
  and activity, with maximum angle difference <0.000016 degrees.

Bootstrap 10000 paired whole episodes, never frames. Mean and pooled p95 angular
errors use emitted estimates, with misses reported separately. A spurious rate
is the fraction of scored updates containing an unmatched estimate; extras/update
and penalized assignment error remain in raw results. Score first acquisition and
reacquisition separately, retaining timeout deadlines. When every paired episode
difference is zero, supplement the degenerate bootstrap with the exact upper
probability of unseen discordance: `1 - 0.025**(1/n)`, scaled by the metric range.
At 24 episodes, identical observed rates therefore do not prove a five-point bound.

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

Preserving this candidate's field statistic exactly to 0.1 is not established as
necessary for the measured observation budgets. A relevant weak-direct mixture
passes despite that statistic's failure. The isolated-family spurious discrepancy
and remaining interval widths still warrant attention; neither is waived.

Passing approximation-impact budgets is not useful robot behavior by itself.
The weak two-source reference already misses about 59.5–69.6% of targets in these
noise-signal controls. Selected-mixture spurious-update rates are about 87–89% in
both variants. These limitations cannot be assigned to the PRA approximation
alone, and no perception parameters or controller were changed to improve scores.

The renderer holds geometry per emission update and drains emitted responses;
general interaction-time visibility/retarded motion is not solved here. References
are controlled scalar statistical geometric acoustics, not measured rooms or
moving-boundary wave solutions. The mixed case omits other paths, including the
mirror's direct specular reflection. It does not implement the complete D branch.
Full band/decay/radius/order/horizon qualification, arbitrary-surface persistence,
C03/C04 room representatives, general causal integration and AV/mobile/learning
utility remained open at that milestone. No public diffuse configuration was
enabled by that earlier follow-up.

There are 2304 retained multichannel streams, not 2304 independent episodes per
condition. Fresh motion generation/inference-plus-analysis took 345/41 s; mirror
confirmation took 643/143 s. CUDA batches of 32 have about 88 ms mean and 124 ms
p95 inference per observation update. Generation shares geometry/RIR work across
episodes; these are offline experiment costs, not live producer or real-time
qualification. Local synthesis/scoring checks and Ruff pass; the maintained SDK
implementation and historical evidence remain unchanged.

## General D implementation and conditioned-room admission (2026-09-15)

**Result: implemented, not admitted. The general Step 3 qualification stops with
a material smooth-room decay and observation-impact failure after refinement.**
This is a new bounded result, separate from the retained rotating-mirror statistic
and its passing selected-mixture follow-up. It does not establish that PRA is
universally unsuitable, or invalidate the working intermediate.

### Implemented and verified boundary

`GeometryAcousticsConfig.diffuse=PRADiffuseConfig()` enables an experimental D
producer; `None` remains the default. Native PRA owns flights, multibounce band
energy, surface quadrature and visibility. Persistent object-local elements own
pressure realization, independent of ray/microphone/source identifiers. First
scattering is explicit; subsequent scattering and higher/mixed specular energy
enter the statistical representation with disjoint ownership. The interface and
normalization are documented in [[topics/geometry-acoustics|Geometry Acoustics]].

Thirty-six native, field, producer and convolution controls pass. They cover
two-sided closed/open/closed visibility, an initially discovered and corrected
surface-projection leak across a partition, analytic Lambertian energy/covariance,
colocation/reordering/regrouping, unchanged refresh, equivalent source identity,
object motion/return, late-joining arrays, filter power, delay, source-stop tails
and reset. A separate banded specular defect was corrected: minimum-phase material
conversion no longer absorbs geometric level or signed directivity.

The banded 6x6x3 m energy-envelope control has targets .2/.2/.35/.5/.65/.8/.8 s
and candidate T20 values .226/.226/.374/.522/.671/.821/.821 s, within the approved
tolerance. Native 2/4 s captures agree at the stated 1e-7 ray cutoff. A fully diffuse
late-field .05 m source-shift control gives complex covariance differences
.0781/.0698/.0164 at 500/1000/4000 Hz against reciprocal receiver motion. These
bounded controls do not establish full moving-room pressure qualification.

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
The candidate suppresses reflected false detections and makes this task
artificially easier. Absolute changes, including improvements, remain subject to
the approved five-point bound. At 4096 rays/order 3, corresponding changes were
-99.78 and -78.45 points; at 16384/order 7, -15.73 and -67.93. Increasing rays
does not resolve this selected failure.

The final candidate's 1 kHz pressure T20 is .352–.378 s across microphones,
outside the .425–.575 s target interval; the conditioned reference is .534–.540 s
in that band. The 250–2000 Hz RIR-energy ratios are approximately .624/.519/.754/.587
relative to the coherent reference. These are measured pressure differences,
not a failure of the independently checked scalar-energy bookkeeping.

### Consumer limits and stop boundary

CUDA solo/batch/reorder/loud-neighbor/reset checks pass for both candidate streams
and the square reference. One raised reference changes its count at one of 19
scored updates across batch sizes; the binary spurious-update outcome remains
unchanged. Scalar/CUDA count/direction parity also fails on the raised reference
(50% count agreement on the final selected stream). These are separate consumer
qualification limits; no localizer parameters were changed. The stable square
comparison already establishes an observation-impact failure.

Full C03/C04 motion, two-source/general-room confirmation, complete isotropic and
later-scatter moving-mirror controls, ordinary moving-geometry causal admission
and missing room references remain open. The current run stops before repeating
that wider matrix because the required static room already fails. Steps 4–6 are
not started by this result. The original rotating-mirror .17045 diagnostic has
not been reclassified as the sole blocker.

Native synthesis is CPU-only: one held nine-channel RIR takes about 77 s at
4096 rays/order 3, 210 s at 16384/order 7 and 493 s at 65536/order 7, with 7.45–32.44
million retained modes. RTX inference at batch 32 averages 88 ms, p95 114 ms per
observation update. These are offline costs, not live or real-time qualification.

Working changes and failed evidence are retained. The approved stop rule requires
a decision on the reflection-model/provider boundary before a larger proprietary
multibounce solver or replacement evaluation. No replacement provider, threshold
change, implicit domain reduction or push was performed. Reproduction, exact
coefficients, PCM, intervals and the compact plot are in
`local/r10/08_2_step3_general/README.md`, `summary.json` and `summary.png`.

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
| `08_2_step3_general/` | General optional D implementation, physical/reference corrections, conditioned-room decay and RTX observation-impact failure after refinement |

Production/build interface: [[topics/geometry-acoustics|Geometry Acoustics]].
Provider alternatives: [[experiments/acoustic-provider-evaluation|Provider Evaluation]].
Historical source detail/chronology: R9/R10 paths at `5cfe48d`. This consolidated
record preserves outcomes and limits; it does not retroactively mark failures passed.
