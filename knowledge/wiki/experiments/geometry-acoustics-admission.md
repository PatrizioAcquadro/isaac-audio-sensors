# Geometry Acoustics Admission Evidence

Recorded experiments: 2026-09-10/11. This page preserves decisive measurements,
reference corrections and replay pointers; it does not repeat the implementation
plan. [[decisions/robot-audition-fidelity|The approved task-domain decision]] governs
which failures block admission. [[implementation_phases/r10-geometry-acoustics-integration|R10]]
owns current implementation work. No new experiment was run during consolidation.

## Admission summary

| Contribution | Established | Still unqualified |
| --- | --- | --- |
| Steam direct + native PRA specular intermediate | Bounded arrival/gain, reflected visibility, streaming and actual Sim/Lab/Kit; scalar/CUDA agreement on identical PCM | General motion, diffuse pressure and selected-route production integration |
| Steam selected routes | Per-route timing, LOS exclusion, multiple arrivals; selected-flight interception and endpoint-motion controls | Production lifecycle, identity/rebake/coverage, ordinary dynamic task domain |
| PRA shared-event pressure | Co-location, unchanged refresh, controlled stationary spatial covariance | Persistent moving field, full energy/band/order/radius convergence and room/task admission |
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

## Measured observation impact

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

Production/build interface: [[topics/geometry-acoustics|Geometry Acoustics]].
Provider alternatives: [[experiments/acoustic-provider-evaluation|Provider Evaluation]].
Historical source detail/chronology: R9/R10 paths at `5cfe48d`. This consolidated
record preserves outcomes and limits; it does not retroactively mark failures passed.
