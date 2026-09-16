# Geometry Acoustics Trial Protocol

Status: **Step 1 preparation complete within the clarified scope (2026-09-15).**
Saved inputs, bounded Office/Hospital acoustic fixtures, reference ledger, endpoint
scorers and RTX cost pilot are ready for later model-specific work. All cases remain
`score_ready=false`: preparation did not implement Step 2+ or run candidate/task
comparisons. Later results belong to [[experiments/geometry-acoustics-admission|Admission Evidence]].

This page owns exact fixtures, consumers, scoring and the lean sample plan.
[[decisions/robot-audition-fidelity|Robot-Audition Fidelity]] owns the approved domain,
budgets and stop rule, including the
[[decisions/robot-audition-fidelity#Step 3 full-room limitation and admission decision (2026-09-16)|current Step 3 admission revision]]
and earlier C02/R05 diagnostic exception. Step 3 is now PASS under that revision;
full-room moving equivalence remains NOT VALIDATED and explicitly non-blocking.
The saved preparation flags and historical ledger below are not rewritten as passes.
[[implementation_phases/08-geometry-acoustics-integration|Phase 08]] owns sequencing;
[[implementation_phases/r10-geometry-acoustics-integration|R10]] owns implementation.

Scope: simulation on this machine, generic rigs, building-exploration scenes/sounds,
quiet and moderate-noise controls, simple and composed motion, AV acquisition and
mobile proximity. Reuse existing assets; no new recordings, purchases, physical
hardware work or beyond-domain stress campaign. Reference gaps block affected
comparisons, not unrelated preparation.

Reading order:
[[experiments/geometry-acoustics-trial-protocol#Trajectories and trial matrix|trial matrix]] →
[[experiments/geometry-acoustics-trial-protocol#Reference validity and comparisons|references]] /
[[experiments/geometry-acoustics-trial-protocol#Consumers and scoring|scoring]] →
[[experiments/geometry-acoustics-trial-protocol#Trials and cost-first execution|lean execution plan]].
[[experiments/geometry-acoustics-trial-protocol#Prepared inputs and measured boundaries|Saved preparation]]
records completed checks and their limits.

## Relevance and camera decision

Sources checked on 2026-09-15: the
[IHMC SquadBot program](https://www.ihmc.us/ihmc-receives-grant-to-continue-squadbot-research-program/)
and [Luigi Penco page](https://www.ihmc.us/groups/luigi-penco/) identify building
exploration, including entry and obstacles. The rooms, acoustic classes, camera
and acceptance values below are engineering choices, not IHMC specifications.

| Camera example | Published horizontal FOV | Source |
| --- | --- | --- |
| RealSense D435/D435i; D455/D455f | RGB 69°; 90° (depth differs) | [Comparison](https://www.realsenseai.com/compare-depth-cameras/) |
| OAK-D; OAK-D Pro/Pro W | Color 69°; 66°/109° | [OAK-D](https://docs.luxonis.com/hardware/products/OAK-D), [comparison](https://docs.luxonis.com/hardware/platform/comparison/vs-realsense) |
| ZED 2i, 2.1 mm lens | Maximum 110°; effective coverage depends on lens/mode/rectification | [Specification](https://store.stereolabs.com/products/zed-2i) |

Use **90° HFOV**, paired **70°/110° sensitivities**, rectilinear 1280×720 at 30 Hz.
Vertical FOV is `2*atan(tan(HFOV/2)*9/16)`: 43.00°/58.72°/77.55° for 70°/90°/110°.
These generic pinhole choices span conventional/wide-angle examples; they are not
device replicas, calibrated FOVs or a market-weighted estimate. The former 65°
choice represented only the narrow end.

## Common rig, clocks and limits

- World positions below are meters, Z up; XY coordinates omit Z=1.2 for acoustic
  source/array centers unless stated. SDK bearings are clockwise from array forward;
  scene/controller adapters must verify their handedness independently.
- Use exact maintained layouts from `tools/smoke/multisource_reference.py`:
  `square`: (-.033,-.033,0), (-.033,.033,0), (.033,.033,0), (.033,-.033,0);
  `raised`: (-.03,-.03,0), (-.03,.03,0), (.03,.03,0), (.03,-.03,0), (0,0,.04).
  Every main condition runs separately with both. Square reports azimuth only;
  raised-array elevation is diagnostic, never required from the planar layout.
- Camera optical center is the array origin, forward axes aligned, fixed pitch 0.
  Ideal mounts have no acoustic housing. Rendered source markers, axes and rig glyphs
  are excluded explicitly from acoustic geometry. Furniture and walls are included.
- Profile 1 base is fixed. Head yaw limits are [-170,170] degrees, nominal maximum
  speed 60 degrees/s and acceleration 180 degrees/s². Dedicated boundary case uses
  90 degrees/s with the same acceleration. These are generic engineering values.
- Profile 2 uses a 0.25 m radius collision footprint, 0.10 m planned wall clearance,
  nominal translation 0.5 m/s, acceleration 0.5 m/s² and base yaw 45 degrees/s;
  boundary case uses 1 m/s and 90 degrees/s. Head limits remain as above. This tests
  a kinematic audition consumer, not balance, gait, contact-rich locomotion or Alex.
- PCM/perception: 16 kHz, 100 ms observation updates, unchanged maintained
  `MaintainedEventLocalizer`/CUDA counterpart, 750 ms causal context, 300–6000 Hz
  spatial band, activity threshold -60 dBFS; do not import ONR scene-specific gains
  or thresholds. No change to localizer parameters or confidence semantics.
- Sound speed 343 m/s; no wind, Doppler post-effect, AGC, clipping, channel mismatch
  or undeclared air-absorption compensation. Native engine internal rates can differ
  if their resampling/timing controls pass. Supported perception/Isaac use actual
  GPU; native CPU engines keep their supported execution path.
- Common simulated clock: motion/geometry nominal refresh 10 ms; reference checks
  at 5 and 2.5 ms. Integrate continuous kinematics, with no teleport at waypoints.
  Position changes are evaluated at the appropriate emission/reception times.
- Camera frames expose visual observations 100 ms after capture. A candidate must
  remain visible in three consecutive frames to confirm (about 67 ms plus delivery
  delay). Rendering and audio share timestamps. This is an explicitly simulated
  visual reference, not learned recognition or a measured hardware latency.

## Scene reuse and representative environments

Reuse the full NVIDIA Office, then Hospital, from
`/home/pacquadr/Desktop/SquadBot_ONR_Assets/nvidia/Isaac/Environments/`.
`local/onr/office.py` references Office; `local/onr/catalog/scene_build.py` selects
props and disables original colliders. That is visual reuse, not acoustic validity.
Preserve original assets/deliveries; include relevant walls, ceilings and furniture
with justified proxies. Do not inherit ONR robot settings, FOV, thresholds or
acoustic omissions, crop routes, or add hidden closures. Keep E0–E4 for exact controls.

| Representative | Prepared entry point | Required inspection / trials |
| --- | --- | --- |
| Office O01/O02 | Full `Office/office.usd`; initial rig XY (-23.08,13.25) from Video 1; door `/Root/BP_DoorMrSmith_3041` | Static speech, intermittent phone, continuous device; single/two-source mobile search. Corrected generic source poses and bounded continuous approach checks are recorded below; historical robot settings are not inherited |
| Hospital H01/H02 | Full `Hospital/hospital.usd`; inspect doorway `/Root/SM_Door_01b_2`, rig XY (-17.4,10.8) | Connected room and corridor selected with verified initial center rays and bounded approach routes; bounded acoustic boundary representation and its limits are recorded below |

These are bounded representative inputs, not full-room references.
[MolmoSpaces](https://github.com/allenai/molmospaces) and its
[scene dataset](https://huggingface.co/datasets/allenai/molmospaces) were reviewed
on 2026-09-15 for diversity/occupancy metadata. No benefit over local Office/Hospital
was established for this preparation; nothing was imported or downloaded.

## Controlled scenes

Walls are closed polygon shells, nominal thickness 0.15 m, floor Z=0, ceiling Z=3.
The ranges describe inner air volumes; shared walls are represented once. Door
leaves are visual solids with a single declared acoustic partition proxy, avoiding
unsupported doubled transmission through two faces. Construction transmission is
opaque unless the dedicated single-partition test says otherwise. Geometry includes
ceilings, obstacles and all furnished boxes; no invisible acoustic shortcuts.

| ID | Inner air volume / explicit objects | Purpose |
| --- | --- | --- |
| E0 — Small room | [0,3] x [0,3] x [0,3], empty | 3 m boundary; controlled room and short-range reference |
| E1 — Office/workroom | [0,6] x [0,5] x [0,3]; desk box [4.4,5.6] x [4.3,4.9] x [0,.75]; cabinet [.2,1.2] x [4.5,4.9] x [0,2] | Furnished interior, off-camera device/person, crossing and intermittent sound |
| E2 — Large room | [0,10] x [0,6] x [0,3]; cabinet [.2,1.2] x [5.4,5.9] x [0,2] | 10 m scale and source-distance boundary |
| E3 — Two rooms and door | [0,4] x [0,5] and [4.15,8.15] x [0,5], height 3; doorway through shared slab x=[4,4.15], y=[1.9,3.1], z=[0,2.2]; leaf hinge (4.075,1.9), width 1.2, swings from +Y toward +X | Entry, closed/open/closed transmission/visibility, moving person and homing |
| E4 — L corridor | Union of [0,8] x [0,2] and [6,8] x [0,8], height 3; remove interior overlap faces | Sustained NLOS, opening-directed cue and corner navigation |

E1-screen adds box x=[3.4,3.55], y=[1.8,3.2], z=[0,2.5]. For the moving-obstacle
case translate it by (0,1.6,0) and back at 0.5 m/s with 0.5 m/s² acceleration;
include its full swept volume and stop at endpoints. The desk/cabinet never moves.
Visual objects can be simple person/device proxies; photorealistic assets and media
production are not required for these comparisons.

### Acoustic recipes and conditioning

Use octave centers 250, 500, 1000, 2000 and 4000 Hz for reported decay and DRR.
Source-band coefficients remain explicit; endpoint values extend outside these
bands through the maintained mapping. Report actual converted coefficients.

- R02/R05/R08 target banded T20-extrapolated decay 0.2/0.5/0.8 s, respectively.
  Uniform room-shell absorption starts at
  `alpha = 1-exp(-24*ln(10)*V/(343*S*T))`; this inverts the
  [Eyring estimate](https://pyroomacoustics.readthedocs.io/en/stable/pyroomacoustics.acoustics.html#pyroomacoustics.acoustics.rt60_eyring), not a
  measured decay prediction. Empty-room alpha seeds for R02/R05/R08 are
  E0 .33154/.14880/.09579, E1 .43752/.20560/.13398,
  E2 .48896/.23549/.15450 and each E3 room .40202/.18590/.12063.
  E4 uses union volume 84 m³ and boundary area 152 m² in the same formula.
- Main shell scattering is nominal 0.2; furniture/screen absorption 0.2 and
  scattering 0.35 in all bands. These are controlled nominal surfaces, not measured
  wood/concrete twins. Smooth specular controls set scattering to 0; controlled
  diffuse plane uses absorption 0.2/scattering 1 as in the retained reference.
- Before candidate scoring, use reference impulse responses and geometry checks to
  condition each recipe. Accept decay within max(0.03 s, 15% of target), with the
  fitted interval/dynamic range reported. In connected spaces report each room and
  receiver region, including non-exponential or multi-slope decay. Do not force a
  misleading single RT label on a coupled decay.
- DRR means isolated direct-path energy divided by all indirect RIR energy, per
  band and microphone, with the same response horizon. Strong-direct diagnostic
  target: +6 to +15 dB; weak-direct diagnostic target: -12 to -6 dB. NLOS with zero
  direct energy is reported as -infinity, not silently put into a finite DRR bin.
- Use finite-plane strong/weak controls for exact DRR sensitivity. Their explicit
  direct gain 1/0.1 is a diagnostic, never a substitute for physical occlusion.
  Room trials use geometry-derived direct/indirect energy without fitted stem gains.
  E1-screen/R08 and E3/R08 must provide physically weak-direct moving coverage or
  conditioning remains open. Record measured DRR distributions and strata; do not
  discard trajectories because the candidate fails there.
- Only reference-side acoustic conditioning may adjust shell absorption uniformly
  per band by bisection in [0.01,0.95], max 12 iterations per band. Select the first
  recipe meeting the declared tolerance, save its exact coefficients, then use
  unchanged geometry/materials for every candidate. No tuning to DOA/task scores.
  If the fixed geometry cannot realize a required condition, report a preparation
  gap and revise the protocol before new comparisons, retaining the original.
- Response horizon starts at 2 s, checked against 4 s: omitted band energy must be
  <0.1% for a truncation control. Extend if necessary before scoring, without
  suppressing source-stop tails. The bound is numerical, not a physical silence gate.
- Dedicated planar-transmission control: loss 20 dB at every material band, one
  partition, same source and mic coordinates with leaf absent/present. This is an
  authored amplitude-loss control, not calibration of a real door. Other walls
  remain opaque. Thick and sequential transmission remain unsupported.

## Sources, levels and schedules

Sources represent people, entry events and devices; this is an engineering mapping,
not an IHMC requirement or a classifier/identity-tracking claim.

| ID | Content / concrete input | Use |
| --- | --- | --- |
| S1 | Six existing `cmu_arctic_us_{aew,axb}_a000*.wav` files in `evidence/qualification/multisource/assets/`: aew a0001–a0003, axb a0004–a0006 | Speech / two independent talkers; existing development content, not a new speaker-generalization holdout |
| S2 | `local/onr/data/video1/audio/phone_audition.wav`, full 7 s | Intermittent phone/device alert; original provenance in `evidence/onr_video1_final/audio_sources.json` |
| S3 | `local/onr/data/video1/audio/door_audition.wav`, full 2.078 s | Door movement/latch event, attached to leaf center at Z=1.2 |
| S4 | `local/r10/assets/footsteps.wav`, full 3.830 s; adjacent `.license` identifies CC0, Giso Grimm | Moving footsteps at Z=.15; secondary realism/control condition, azimuth scoring only |
| S5 | Procedural stationary device: independent Gaussian input through fixed 4th-order 300–3000 Hz Butterworth bandpass | Sustained broadband device surrogate; explicitly synthetic, not a recording of a specific machine |
| S0 | Exact silence, unit impulse, 2 s log sweep 100–7000 Hz, independent 300–6000 Hz band-limited Gaussian signals | Negative controls and delay/energy/spatial references |

Existing recordings were checked for rate, channels and duration. Preserve originals;
convert copies into ignored preparation storage and retain S1 README attribution
with redistributed clips. No new recording/download is needed.

Mix to mono, resample once to 16 kHz with the existing polyphase resampler and
record its delay handling. Add 10 ms endpoint fades. Speech programs concatenate
one speaker's three files in a seed-selected cyclic order with 0.25 s silent gaps;
loop the program to fill each emission interval, without time stretching. The
second talker uses the other speaker. S2/S4 repeat their full excerpt with 0.25 s
gaps; S3 plays once per prescribed door event, without looping. Synthetic inputs
use fresh independent seeds. Explicit masks retain natural silence in recordings.

Set a single source gain per prepared content so free-field pressure at 1 m has
active-window RMS -35 dBFS using the analytical `1/(4*pi*r)` convention. Active
windows are 20 ms blocks above 1% of that clip's maximum block RMS. Preserve the
resulting envelope; never normalize each received frame, distance or candidate.
This is a digital reference level, not calibrated SPL. Two-source rows have equal
reference levels or the second source at -6 dB, as explicitly listed.

Quiet rows have no extra ambient/electronic noise. Moderate-noise counterparts
add the same realization to all compared producers: 32 isotropically distributed
far-field plane waves of independent 300–6000 Hz noise, with physical spatial and
motion delays, set to -55 dBFS RMS at the initial array center. This is a controlled
background surrogate (20 dB below a source at 1 m), not measured building ambience;
received SNR changes naturally with motion, distance and occlusion. Calibrate the
noise field independently of the candidate diffuse implementation. Noise-only
negative controls use the same level and processing.

AV episodes last 30 s; sustained emission [2,28), intermittent [2,6), [8,14),
[16,28); retain tail through 30 s or the qualified longer horizon. Mobile episodes
allow 60 s from first emission at t=2, then stop sources and retain the qualified
tail. Warm-up is retained in task latency; steady-state cue statistics additionally
report results after one second of received active sound. Controllers do not know
source schedules, seed, identities or scoring onset times.

## Trajectories and trial matrix

`R` is the initial array center, `S` a source position. `P(a,b,v)` holds at a until
t=3, moves along a straight segment with a trapezoidal speed profile (acceleration
1 m/s², cruise v, brake to zero at b), then holds. `P(a,b,c;v)` stops for 0.5 s at
b before continuing to c; no instantaneous velocity reversal. Door angles use
`theta=90*(3*u²-2*u³)` over the listed interval, then hold; closing reverses it.
Positions and maximum speeds, not arbitrary audiovisual keyframes, own motion.
C03/C04 retain the plane x=0, y=[-6,6], z=[-5,7], source initial (2,-1,1.2),
receiver initial (3,.1,1.2), as retained in `local/r10/checks/fixtures.py`. For these
controls only, translation is constant +X over [0,2.1] s at the listed speed and
emission stops at 2.1 s; retain 2 s of tail. Rotation is constant at the listed
rate over the same interval. Each run has either source or receiver motion.

Each listed variant is a separate scored condition, each repeated on both layouts.
Default R05, S1, quiet, one source; explicit entries override these defaults.
Prescribed receiver paths below measure acoustic cues independently of the mobile
controller. Closed-loop runs use the stated initial pose/scene and their own motion;
they are never forced along the prescribed path to create a successful result.

| ID | Scene / positions and changes | Required outcome / reference family |
| --- | --- | --- |
| C01 | Free-field R=(0,0); S=(d,0), d=.5/3/10; S0 | Direct delay, gain, TDOA and no duplicated energy; F1 |
| C02 | Empty E0, R=(1,1.5), S=(2,1.5), R02/R05/R08; smooth walls, S0 | Banded energy/decay, specular delay; F2. Recorded R05 late-response mismatch is diagnostic under the cube decision; structural checks remain binding |
| C03 | Retained finite-plane fixture, source speeds 0/.1/.5/1.5, direct gain 1/.1; S0 | Controlled DRR, source-motion diffuse field; F3 |
| C04 | C03 with source fixed and receiver translation .5/1 m/s or yaw 60/90 degrees/s | Receiver motion/rotation and spatial coherence; F1/F3 |
| C05 | E3 R=(2,2.5), S=(6,2.5); opaque leaf vs 20 dB planar leaf vs absent leaf | Visibility, transmission, non-duplication; F1/F2/F4 |
| A01 | E1 R=(1,2.5), S=(4.5,2.5); R02/R05/R08 | Off-FOV acquisition and reverberation; F2/F5 |
| A02 | E0 R=(1,1.5), S=(1.5,1.5); E2 R=(.5,.5), S=(9.5,4.8588989435) | .5/10 m range; AV acquisition and received level; F1/F2/F5 |
| A03 | E1 R=(1,2.5); S=P((5,1),(5,4),.5/1.5) | Lateral motion and camera reacquisition; F3/F5 |
| A04 | E1-screen R=(1,2.5); S=P((5,.8),(5,4.2),.5/1.5); R08 | Physical shadow, weak-direct motion, visibility transitions; F3/F4/F5 |
| A05 | E1 R=(1,2.5), S=(4.5,2.5); intermittent S1/S2 | Missing estimates, reacquisition after silence; F2/F5 |
| A06 | E3 R=(2,2.5), S=(6,2.5), sustained S1; door opens t=4 over .5/1.5/3 s, closes t=18 over same duration | Hidden vs revealed source and ordinary door timing; F4/F5 |
| A07 | E4 R=(1,1), S=(7,6), sustained S1; R05/R08 | Permanently hidden source: NLOS cue, no false visual confirmation; F4/F5 |
| A08 | E1 R=(3,2.5), S=(3,4), second S=(4.5,2.5); S1+S2 and S1+S1, second 0/-6 dB | Two sources at 90-degree bearing separation, distraction and false association; F2/F5 |
| A09 | E1-screen R=(1,2.5), S=(5,2.5), moving screen; R08 | Moving obstacle, sustained/changed occlusion and reacquisition; F3/F4/F5 |
| A10 | Repeat A01/R05 and A08/S1+S2/-6 dB with 70/110-degree HFOV | Camera sensitivity with identical acoustic inputs/initial poses; F5 |
| A11 | Repeat A03/.5 and A04/.5 with moderate background; repeat A03/1.5 at head limit 90 degrees/s | Noise interaction and head-speed boundary; F3/F5 |
| M01 | E1 R=(1,1), S=(4.5,2.5); prescribed R=P((1,1),(3.5,1),.5/1) with yaw 0→90 degrees at 45/90 degrees/s, plus separate homing | Translation/rotation, single-source proximity and collisions; F1/F3/F5 |
| M02 | E3 R=(1,2.5), S=(6.5,2.5); door open throughout or opens t=4 over 1.5 s and closes t=35 over 1.5 s | Connected-room homing; door-aware waiting/avoidance; F4/F5 |
| M03 | E4 R=(1,1), S=(7,6); R05/R08 | NLOS direction toward opening, corner homing; F4/F5 |
| M04 | E1 R=(1,1); S=P((5,1),(5,4),.5/1.5), intermittent S1 | Both move, cue continuity; source stops so a slower receiver can reach it; F3/F5 |
| M05 | E1 R=(3,2.5), S=(3,4), second S=(4.5,2.5); S1+S2, second 0/-6 dB | Reach either audible source, switching/indecision; F2/F5 |
| M06 | E3 R=(1,2.5); S=P((6.5,4),(6.5,2.5),(2.5,2.5);.5), intermittent S1; door opens t=3 over 1.5 s, stays open; R08, quiet/moderate noise | Composed building-exploration episode: two movers, doorway and weak/changed direct sound; F3/F4/F5 |
| N01 | E1, no emitting sources; exact silence / moderate background; add a silent visible device at (4.5,2.5) | False acoustic events and audio-visual associations; F1/F5 |

S5 continuous-device replay uses A01/R05 with S5 in place of S1; it is a required
content condition. S3 doorway-event replay uses A06/1.5 s with a single S3 source at the moving leaf
center, emitting at t=4 and 18; remove S1 so no row exceeds two event sources.
S4 replay uses A03/.5 at source height .15, recording its reduced visibility and
possible planar bias separately. These are required content checks, not permission
to make footstep recognition claims. Faster-than-domain motion, a third source and
1.2 s room decay are excluded from this campaign.

### Episode variation and independence

Use independent episode seeds for acoustic stochastic realization, synthetic input,
source-program phase and initial head pose. Hold all of them matched across producer
variants/audio controls. Initial AV head yaw differs from first-source bearing by
an independently drawn signed offset uniform in [75,150] degrees, subject to joint
limits; construct the two-source initial pose to exclude both from even the 110-degree
FOV. Record the construction and never supply hidden bearings to the controller.
Mobile initial base yaw is uniform [-180,180); array head yaw starts at zero.

Randomize overall emission/motion/door schedule offset by U[0,.5] s together (extend
episode deadline/tail by that offset). Geometry and speeds stay as declared. Do not
count adjacent frames, repeated reads, layouts, FOVs or producer variants as independent
episodes. Generalization is conditional on this finite scene/content set. Duplicating
a deterministic identical episode under a new seed is a repeatability check, not
an additional statistical sample; use exact enumeration for any such condition.

## Reference validity and comparisons

| Family | Independent property checks / matched comparison | Validity boundary |
| --- | --- | --- |
| F1 — Direct analytical | Euclidean LOS path and retarded equation for moving endpoints, `1/(4*pi*r)`, exact pair distances, authored transmission coefficient; impulse/filter separation | Only visible direct/declared planar transmission; no Euclidean shortcut in NLOS |
| F2 — Specular/decay | Independent image-source calculation for rectangular rooms and a single plane; path-length/visibility controls for selected nonconvex paths; energy partition and 2/4 s tail check | Finite specular order, band/material approximation; analytic decay formula is initialization only, not a universal room oracle |
| F3 — Diffuse | Retained fixed-surface Lambertian plane; co-location, controlled isotropic coherence, directional arrival controls; movement of receiver/source separately; shared-surface and multi-scatter persistence checks | Plane reference is valid for its declared interactions only; passing it or increasing rays does not certify room multibounce motion |
| F4 — NLOS/door | Independent segment/door intersection at interaction time and geometric detour lower bounds; full native selected-route length plus independent impulse timing; closed/open/closed continuity and ordinary moving-screen cases | Selected route checks do not prove route completeness or diffraction amplitude. Missing coverage is unavailable, not physical silence |
| F5 — Task and approximation impact | Same consumer, scene, content and random draws; compare each approximation against a property-valid matched reference; separately compare audio enabled/disabled | Another provider or the working intermediate is not a universal oracle; task benefit cannot validate defective physics |

Producer decomposition: I = working direct+specular intermediate; N = I+NLOS;
D = I+diffuse; C = I+both. Run matched I/N/D/C cue trials after relevant components
are available, without silently enabling unadmitted defaults. Component ablations
explain mechanisms; their differences are not automatically approximation error.
Closed-loop qualification compares C against an admitted matched reference and
C with audio disabled. Source trajectories/noise are matched; receiver trajectories
may diverge legitimately, so each producer evaluates its own causal geometry.

Reference preflight must assign, per row and measured quantity: implementation,
validity domain, independent physical check, numerical convergence evidence and
remaining model uncertainty. Native route export checks receive independent timing
and geometry controls, not self-comparison of one path-length field. Refinement
starts at 10/5/2.5 ms, ray counts 4096/16384/65536 and reflection orders 3/5/7 where
supported; inability to run or convergence failure remains visible. Use the last
converged pair; max-order failure does not authorize truncation or fitted gains.
Convergence alone cannot retire the known structural diffuse-motion error.

**Known reference limitation:** A04/A09/M06 and other diffuse-dominated room strata lack
a validated moving multibounce pressure reference; NLOS amplitude/coverage can
also remain unavailable. The Step 1 ledger records bounded controls and missing
comparisons without implementing later models. Neither this protocol nor numerical
convergence validates those rows or authorizes a new provider/general solver.
The user explicitly made full-room moving pressure/observation equivalence
non-blocking for Step 3. This does not admit complete AV/mobile comparisons or
convert the missing room reference into a PASS.

## Consumers and scoring

### AV reference consumer

Audio-enabled search selects the observed unambiguous direction closest to current
head yaw; ties use increasing clockwise bearing. Hold the chosen observed direction
for at most 0.5 s since its timestamp; update using the nearest current observation
within 30 degrees, then select afresh if unsupported. Never copy source identity.
Absent usable cues, both controllers perform the same deterministic yaw sweep
between -170 and 170 degrees at the configured limit, reversing at the endpoints.
No confidence threshold is introduced for a localizer that does not expose one.

Commands respect the finite joint limits and acceleration; an unreachable yaw
does not authorize base motion in Profile 1. The visual reference returns visible
object bearings with their capture timestamps at delivery time with a
geometric FOV/occlusion mask; no unseen object poses or acoustic-source flags enter
the controller. Associate to an observed audio bearing within 20 degrees; multiple
compatible objects remain ambiguous, not automatically correct. A silent visible
distractor can be incorrectly associated and is scored as such. Audio-disabled
search uses the same visual observations and movement constraints. Truth may score
first acquisition of the emitting object by either search but cannot command it.

Primary AV outcome: true emitting object visually acquired within **10 s of first
emission** (propagation/warm-up/turning/visual latency included). Ten seconds allows
one complete nominal 340-degree sweep, including acceleration, plus time to revisit
sectors, without an indefinite search. Report success difference with/without audio
and its uncertainty. Also
report first-confirmation time, restricted time (failures assigned deadline), false
association, unresolved association, stale cue use and reacquisition within 10 s of
each resumed emission/visibility event. Acquisition and correct audio association
are separate measurements; seeing an object is not proof it emitted the sound.

Physically unrevealable A07 is a mandatory negative visual-confirmation condition,
not a successful-visual-acquisition trial. Report zero possible visibility explicitly
and evaluate false confirmations/NLOS cues. A06 deadlines remain anchored to emission;
report reveal-relative latency secondarily, without hiding the time spent occluded.
The fixed camera cannot infer behind-wall visibility by rotating.

### Mobile reference consumer

Use the same observed-direction selection as above with planar base steering.
The non-audio inputs are odometry and local collision sensing: a 360-degree geometric
range scan, 3 m range, 1-degree bins, 10 Hz; retain an occupancy map of previously
observed space. No complete scene map, source range, source identity or hidden route
is supplied. Both modes use identical collision avoidance and nearest-frontier
exploration when cues are absent (distance ties broken clockwise). Audio guidance
selects a reachable local waypoint up to 1 m along the cue; if blocked, select the
nearest collision-free angular alternative. A wholly blocked cue returns to
exploration. This specifies an untrained reference behavior, not trained navigation.

Primary mobile outcome: reach within **0.75 m horizontally** of a currently emitting
source in an active emission interval, with a collision-free final approach segment,
for **1 continuous second** (natural within-utterance pauses do not reset the dwell),
within **60 s of first emission**, without collision. This avoids credit across a
wall and leaves stand-off clearance; no visual confirmation is required. Position
and emitting identity are evaluator-only. Moving sources eventually stop; this is
not indefinite pursuit of a source faster than the receiver. At .5 m/s the timeout
allows up to 30 m travel before turns/waits, sufficient to probe the declared short
indoor routes while retaining failed exploration as an outcome.

The controller runs to the deadline without oracle arrival feedback; score first
valid dwell offline. With two sources either qualifies. Score target switches
through offline association of selected bearings (retain unresolved intervals),
collisions, timeouts, travel distance, time to first arrival and exploration delay.
Compare time/path ratios for jointly successful pairs, and deadline-restricted time
plus all-pair traveled distance separately; never hide failure differences through
success-only filtering. Collision contact is a failure, not removed data.

### Acoustic observations and acceptance

- Retain raw estimates, ambiguity, activity, missing/extra outputs and available
  timestamps. Never backdate arrival by aligning on the estimated direction.
- For LOS, one-to-one assignment to emission-time source bearing (retarded endpoint
  geometry); azimuth error wraps on the circle. For NLOS, use independently validated
  arrival direction(s), report hidden-source bearing separately. If no unique
  directional target exists, report the reference direction distribution/ambiguity
  and task metrics; do not invent an exact source-bearing target for diffuse sound.
- Match within 20 degrees using minimum-total-error one-to-one assignment; unmatched
  reference events are misses and unmatched observations extras. Multiple valid
  paths from one source are not automatically different emitting sources. Declare
  arrival clusters in reference preflight, retain competing candidates and do not
  choose the easiest target after seeing the candidate output.
- Mean and p95 direction errors use matched frames, accompanied by misses/extras and
  coverage. Missing-observation rate is missed eligible reference events / all
  eligible events. Spurious rate is the fraction of scored updates with at least
  one unmatched observation; additionally report extra events per update. Silence
  and tail intervals have their own false-event rate. Source emission plus validated
  propagation/tails determines evaluator eligibility, never candidate activity.
- Compute per-episode rate/mean summaries; p95 uses an equal-episode-weighted error
  distribution with whole-episode resampling. Report near/far, stationary/moving,
  weak-direct/NLOS, layout and two-source results separately. No passing pooled
  average removes a failed mandatory condition.
- Apply the canonical decision's numerical budgets and admission roles, in both
  signs. Keep the cube's original failed decay/extra-update comparison diagnostic;
  it does not waive representative observation gates. A missing valid reference,
  insufficient usable events or an inconclusive interval leaves its applicable
  gate **open**; a demonstrated budget violation remains **FAIL**. Neither is a pass.
- Utility is a separate test: for each profile, the lower 95% interval for the
  prespecified primary success difference (audio minus disabled) must exceed zero
  on each main task family (AV visible/static, moving/occluded-revealed, two-source;
  mobile room, connected/NLOS, moving, two-source), with equal condition weights.
  Also publish every condition; a clearly harmful or equally failing mandatory
  condition keeps its usefulness gate open. There is no new universal absolute
  success percentage or replacement of the approved approximation margins.

## Lean preparation and execution ownership

The 154-row inventory defines coverage, not every Cartesian combination or 400
repetitions per row. The clarified allocation below retains the approved domain,
numerical margins and cube diagnostic role. Select cases before candidate outcomes.

08.1 already supplies proxies, materials, grouping and transforms. Office/Hospital
preparation uses that API while retaining visual/collision assets; visual-mesh cost
is not an SDK defect. Missing units/up-axis were local generator errors, now fixed.
Automatic room reconstruction and full-robot/gait validation are outside scope.

| Work | Do now in Step 1 | Do once later, at its owning step |
| --- | --- | --- |
| Geometry and fixtures | Author relevant boundaries/openings/large occluders; check scale, initial visibility, declared generic footprint and ordinary door poses | Model-specific path coverage and cost when the final representation/model is available |
| Decay and direct/indirect conditions | Record material recipes and available bounded measurements, identify useful interior/boundary cases, document unavailable DRR/reference quantities | Full emitted microphone-field energy/decay/DRR and normalization in Step 3; combined-stream check in Step 4 only if composition changes it |
| Direct/occlusion controls | Compact static delay/gain diagnostic for both arrays; reuse existing geometric clear/blocked and detour checks | NLOS route timing/coverage/dynamic invariants in Step 2 |
| Diffuse motion/coherence | Save exact controlled inputs and the known reference limitations | Spatial/temporal statistics and 10/5/2.5 ms or ray-count refinement in Step 3, on affected cases only |
| AV/mobile | Inputs, clocks, endpoint scorer and plausible generic routes | Actual closed-loop consumers and benefit/approximation comparisons in Steps 5/6 |
| Runtime | Reuse the completed 24-run RTX pilot | Measure only changed representation/model/consumer costs before extended execution; operating/packaging checks remain Steps 7/8 |

Reuse each invariant unless a relevant geometry, algorithm, material, clock or
interface changes. The generic footprint is sufficient; downstream reuse alone
requires no repeated qualification.

Cover approximately **0.2–0.8 s across selected fixtures**, using simple-room boundary
controls and representative interior conditions. Do not force all three targets
into every furnished/connected/NVIDIA scene. E1_screen's ~0.61 s scalar diagnostic
is useful interior evidence, not accepted 0.8 s conditioning or joint moving PCM.
Preserve failed targets. Exact-target claims still require the declared band tolerance.

Weak-direct motion, occlusion/NLOS, source/receiver motion, two sources and ordinary
doors remain mandatory. Record exact recipes and valid DRR strata before scoring;
choose representative labels before outcomes. Missing references keep affected
comparisons open and never justify dropping a difficult condition.

## Trials and cost-first execution

`local/r10/preparation/proxies/comparison_plan.json` owns the selected cases
and array allocation, replacing blanket 400-pair-per-expanded-row repetition.

| Stage | Allocation and purpose |
| --- | --- |
| Preparation | Reuse the completed 24-run intermediate RTX pilot. Enumerate distinct deterministic geometry; use only realizations/refinement justified by each field metric |
| Diagnostic | 16 independent paired episodes in each of seven families: AV static, AV moving/occluded, AV two-source, mobile room, mobile connected/NLOS, mobile moving, mobile two-source. Balance selected scenes and both arrays with equal analysis weights; arrays share the allocation. This cannot prove ±5-point equivalence |
| Confirmation | Predeclare up to 400 **fresh pairs per family**, not per cell. Draw condition/layout independently and uniformly from the fixed panel, then a fresh episode seed; record realized counts. This estimates the representative family, not every inventory cell |

Use three primary treatments: C, a property-valid matched reference, and C with
audio disabled. Match source/input/initial-condition seeds; reuse each C episode
in both contrasts. I/N/D ablations belong only to mechanism-specific cases.
Publish every condition and difficult stratum: pooled results cannot admit a failed
or inconclusive cell. Any targeted precision follow-up must be prespecified;
no automatic sample extension or selection after favorable outcomes.

Confirmation binary differences use discordant probabilities p+/p−, separate
97.5% two-sided Clopper–Pearson intervals, and `[L+ - U-, U+ - L-]` for the paired
95% difference interval. This applies to independent uniform family draws, not the
balanced diagnostic panel. Continuous/rate summaries bootstrap whole paired episodes
within family, 10,000 samples, seed 8152026. Low-N, broad or degenerate intervals
remain inconclusive; the ceiling does not guarantee precision or relax any gate.

Keep processes warm only after reset independence is established. Reuse identical
acoustic work; FOV replay may reuse PCM only for identical prescribed source/microphone
trajectories, never diverging closed loops. Save all seeds, conditions, metrics and
failure evidence; retain full PCM selectively. No extended comparison ran in Step 1.

### Revised resource envelope

Estimates reserve three full treatments, including audio-off, at measured
simple-fixture intermediate rates. They exclude setup, final-model/reference and
NVIDIA-proxy costs, plus additional physical/ablation work; these are workload
reductions, not measured final-model speedups.

| Panel | Independent episode draws paired across treatments | Executions | Simulated hours | Intermediate-rate wall extrapolation | All FLOAT PCM |
| --- | --- | --- | --- | --- | --- |
| First diagnostic, 16 per family | 112 | 336 | 4.66 | 3.5–8.5 h | 4.50 GiB |
| Confirmation if all seven families use 400 | 2,800 | 8,400 | 116.5 | 86–212 h | 112.49 GiB |

The confirmation ceiling is prospective. Time each changed model/proxy on a small
valid fixture before budgeting execution; unresolved references block only their
affected comparisons. The former 723–1,775 h per-cell estimate is superseded.

## Prepared inputs and measured boundaries

Step 1 completed on 2026-09-15. Ignored `local/r10/preparation/` contains 154 definitions, 116 initial-pose overlays, 18 controlled material layers, 104 episode definitions with 11 shared source programs, and 50 reference-control definitions including exact 2.5 ms motion clocks. `score_ready=false` intentionally distinguishes prepared input from qualified comparison. Its README owns maintenance commands.

| Preparation result | Essential boundary |
| --- | --- |
| Office/Hospital originals compose; actual RTX views and PhysX queries passed | Visual/collision success is not acoustic qualification; Office includes dark views |
| 62 Office / 106 Hospital acoustic proxy surfaces | Preserve openings, whole intersecting structures and original hinges; furniture envelopes/table tops, omitted trim/chairs, nominal .2 absorption/scattering; open outside connections remain |
| 131 case/reference/proxy overlays reopen at 1 meter/unit, Z-up | Earlier local metadata errors were fixed without an SDK change; full meshes still contain unsupported/degenerate cases and exceed path budgets |
| Both arrays and ten FLOAT 16 kHz source files, plus shared background sampler | Source values can exceed 1 under 1/(4*pi*r); no clipping or integer conversion without received-mixture checks |
| Static direct controls .5/3/10 m | Peak timing error <.49 sample; DC discrepancy ≤.145%; only native 40-sample filter latency removed |
| E0 scalar decay .209/.509/.800 s; furnished .8 s recipes .689/.607/.658 | Scalar energy is not joint pressure, DRR or independently conditioned room truth |
| Initial closed-door scattering reference leaked; finite-order ISM accepted no complete banded recipe | Those references were unavailable for the affected claims; subsequent native corrections and current limits are in the admission record |

Office initial rig is (-23.08,13.25,1.2), sources (-20.58,11.5), (-20.05,12.8), (-22.83,11.5) at Z=1.2. Hospital rig is (-17.4,10.8,1.2), corridor source (-13.4,10.8,1.2), connected-room source (-17.9,14.3,1.2). Open-Hospital input rotates two original hinges -90°. Retained routes use continuous .35 m sphere sweeps at Z=.4 with floor/overlap and terminal-ray checks, not full-body qualification or a hidden controller map.

Corrected static order-3 queries took 1.96/14.11 s for Office/Hospital, with 45–46/16–20 visible paths per microphone and explicit candidate limits 3/12 million. These are fixture-consumption costs, not PCM throughput. Later Hospital diffuse integration requires a local 200000-node override; SDK defaults remain unchanged.

The 24-run intermediate RTX pilot completed 1128 simulated seconds: four cases, both arrays, three repeats, 300 Hz physics, 100 Hz geometry/audio and 30 Hz nonempty RGB. Timed loops totaled 26.9 minutes, excluding 5.3–6.2 s startup each; peak RSS 7.67 GiB. Wall/sim ranges were .74–.79 A01, 1.57–1.82 A04, 1.34–1.37 M03, 1.60–1.79 M06. Invalid camera/path attempts were excluded. These prescribed trajectories are not closed-loop success, and timings precede the stable WPE correction.

## Handoff and retention

Retain concrete inputs and reuse unaffected controls; repeat only checks whose geometry, model, clock or consumer changed. Full-field and task qualification belongs to its owning step, not repeated Step 1 preparation. The [[experiments/geometry-acoustics-admission|admission record]] owns Steps 2/3 outcomes and the accepted, NOT VALIDATED full-room limitation. Other binding controls and budgets remain unchanged.

Concluded preparation reports, pilot PCM and obsolete reference executors were removed after consolidating these findings. Retained scenes, source programs, material/proxy mappings, comparison allocation and scoring support Steps 4–8. They do not imply a ready qualified campaign or historical raw-output reproducibility.
