# Geometry Acoustics Trial Protocol

Status: **Step 1 concretely prepared in part; acoustic conditioning and reference
admission remain incomplete (2026-09-15, after manual reboot).** RTX 4090 CUDA,
Isaac rendering and PhysX scene queries work. Local scenes, episode inputs, bounded
reference diagnostics and technical cost evidence are saved. No candidate comparison,
closed-loop benefit trial or Step 2+ implementation ran. The checklist below owns readiness.

[[decisions/robot-audition-fidelity|Approved domain and budgets]] remain binding.
User choices: generic rigs; building-exploration-relevant indoor scenes and sounds;
representative camera; simple trajectories plus a composed episode; quiet controls
plus moderate background; AV success by deadline; mobile source proximity;
engineering-selected limits; cost estimate first; no beyond-domain stress campaign.

## Relevance and camera decision

Primary sources checked on 2026-09-15:

- [IHMC SquadBot program](https://www.ihmc.us/ihmc-receives-grant-to-continue-squadbot-research-program/)
  describes building exploration, entering structures and moving obstacles.
  [IHMC's Luigi Penco page](https://www.ihmc.us/groups/luigi-penco/) also identifies
  building exploration as a SquadBot objective. Rooms, entrances and corridors
  below are engineering interpretations, not measured IHMC facilities. Neither
  page specifies acoustic classes, camera parameters or audition acceptance values.
- [RealSense camera comparison](https://www.realsenseai.com/compare-depth-cameras/):
  RGB horizontal FOV is 69 degrees for D435/D435i and 90 degrees for D455/D455f;
  their depth FOV is a different specification.
- [Luxonis OAK-D](https://docs.luxonis.com/hardware/products/OAK-D): color HFOV 69
  degrees. [Luxonis model comparison](https://docs.luxonis.com/hardware/platform/comparison/vs-realsense)
  lists color HFOV 66/109 degrees for OAK-D Pro/Pro W.
- [Stereolabs ZED 2i](https://store.stereolabs.com/products/zed-2i): the 2.1 mm lens
  has a maximum 110-degree horizontal FOV. Rectification, lens and image mode can
  change effective coverage; a maximum specification is not a calibrated image FOV.

Select **90 degrees horizontal**, with paired **70/110-degree sensitivity cases**.
This spans conventional and wide-angle examples without claiming a market mode,
market-share-weighted mean, or applicability to most installed cameras. Keeping
only 65 degrees would disproportionately represent the narrow end of this sample.
Use a rectilinear 1280x720 camera at 30 Hz: vertical FOV is
`2*atan(tan(HFOV/2)*9/16)`, respectively 43.00/58.72/77.55 degrees for 70/90/110.
These are generic pinhole parameters, not replicas of the cited devices.

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

**Simulation only, on this machine.** No real measurements, new physical recordings,
purchases or physical hardware work. Use generic camera/microphone supports for both
profiles; the ONR robot, historical camera FOV and tuned audio thresholds are not
inherited. Primary endpoints remain 10 s visual acquisition and collision-free
0.75 m / 1 s arrival within 60 s; either audible source qualifies in two-source homing.

Start with the existing full NVIDIA Office, then evaluate Hospital for connected
rooms and corridors. The local assets under
`/home/pacquadr/Desktop/SquadBot_ONR_Assets/nvidia/Isaac/Environments/` are the same
asset pool used by the ONR evidence. `local/onr/office.py` references the complete
Office; `local/onr/catalog/scene_build.py` selects Office/Hospital props into authored
sets and disables their original colliders. That catalog is visual reuse evidence,
not proof that its geometry or acoustics qualify the new trials. Do not inherit its
acoustic omissions. Include relevant walls, ceilings and furniture, with explicitly
justified polygon proxies where needed. Preserve all original assets and deliveries.

| Representative | Prepared entry point | Required inspection / trials |
| --- | --- | --- |
| Office O01/O02 | Full `Office/office.usd`; initial rig XY (-23.08,13.25) from Video 1; door `/Root/BP_DoorMrSmith_3041` | Static speech, intermittent phone, continuous device; single/two-source mobile search. Corrected generic source poses and bounded continuous approach checks are recorded below; historical robot settings are not inherited |
| Hospital H01/H02 | Full `Hospital/hospital.usd`; inspect doorway `/Root/SM_Door_01b_2`, rig XY (-17.4,10.8) | Connected room and corridor selected with verified initial center rays and bounded approach routes; acoustic boundary representation remains open |

These are required representative preparation entries, currently **unvalidated**;
not qualified substitutes for E0–E4. Keep the simple environments below for exact,
controlled comparisons. Reuse NVIDIA environments for representative building
exploration instead of constructing another furnished building. Do not truncate an
acoustic route or add hidden walls to make an extracted region convenient.

[MolmoSpaces](https://github.com/allenai/molmospaces) and its
[official scene dataset](https://huggingface.co/datasets/allenai/molmospaces) were
reviewed on 2026-09-15. Their scene diversity and occupancy metadata could help a
larger navigation study. No concrete benefit over the already-local Office/Hospital
has been established for this bounded preparation; no MolmoSpaces assets were
imported or downloaded. This is a reuse decision, not an acoustic evaluation.

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

These signals represent people, entry events and devices in building exploration;
this mapping is ours, not an IHMC sound requirement. No classifier, semantic target
selection or identity tracker is introduced.

| ID | Content / concrete input | Use |
| --- | --- | --- |
| S1 | Six existing `cmu_arctic_us_{aew,axb}_a000*.wav` files in `evidence/qualification/multisource/assets/`: aew a0001–a0003, axb a0004–a0006 | Speech / two independent talkers; existing development content, not a new speaker-generalization holdout |
| S2 | `local/onr/data/video1/audio/phone_audition.wav`, full 7 s | Intermittent phone/device alert; original provenance in `evidence/onr_video1_final/audio_sources.json` |
| S3 | `local/onr/data/video1/audio/door_audition.wav`, full 2.078 s | Door movement/latch event, attached to leaf center at Z=1.2 |
| S4 | `local/r10/08_2_complete_coverage/tascar/examples/footsteps.wav`, full 3.830 s; adjacent `.license` identifies CC0, Giso Grimm | Moving footsteps at Z=.15; secondary realism/control condition, azimuth scoring only |
| S5 | Procedural stationary device: independent Gaussian input through fixed 4th-order 300–3000 Hz Butterworth bandpass | Sustained broadband device surrogate; explicitly synthetic, not a recording of a specific machine |
| S0 | Exact silence, unit impulse, 2 s log sweep 100–7000 Hz, independent 300–6000 Hz band-limited Gaussian signals | Negative controls and delay/energy/spatial references |

Recorded inputs already exist and have been inspected for rate/channel count and
length. Copy/convert into a new ignored preparation directory when realizing the
suite; preserve originals and historical evidence. S1 provenance is documented in
its existing README; keep its source attribution with any later redistributed
clips. No new recording/download is required for this protocol.

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
receiver initial (3,.1,1.2), from `local/r10/08_2_usefulness/README.md`. For these
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
| C02 | Empty E0, R=(1,1.5), S=(2,1.5), R02/R05/R08; smooth walls, S0 | Banded energy/decay, specular delay; F2 |
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

**Unresolved reference gate:** the retained plane and route controls do not yet
supply a validated full-room, moving multibounce diffuse reference for A04/A09/M06
and other diffuse-dominated room strata. The same concern can apply to NLOS route
coverage/amplitude. These rows have required checks assigned, but their reference
validity remains pending. Step 1 must expose a property-by-property reference
ledger with bounded valid controls and unavailable comparisons; it must not implement
the whole Step 2/3 models to erase a reference gap. Do not mark an impact budget
passed or the full matrix executable merely because this protocol exists. Preserve the approved stop rule;
no new provider evaluation or repository-owned general solver is authorized here.

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
- Apply all numerical approximation budgets from the canonical decision, in both
  signs. A missing valid reference, insufficient usable events or an interval that
  does not fit wholly inside the budget is **inconclusive/open**, never a pass.
- Utility is a separate test: for each profile, the lower 95% interval for the
  prespecified primary success difference (audio minus disabled) must exceed zero
  on each main task family (AV visible/static, moving/occluded-revealed, two-source;
  mobile room, connected/NLOS, moving, two-source), with equal condition weights.
  Also publish every condition; a clearly harmful or equally failing mandatory
  condition keeps its usefulness gate open. There is no new universal absolute
  success percentage or replacement of the approved approximation margins.

## Trials and cost-first execution

1. **Technical pilot only:** three repetitions of each of four workload representatives
   (A01/R05, A04/.5, M03/R08, M06/quiet), on both layouts: **24 runs**. Initially use
   the working intermediate for setup/cost, explicitly excluding unavailable features;
   repeat affected cost measurements when C/reference exists. Use distinct output
   directories/seeds. Pilot results are not confirmation trials or acoustic admission.
   Measure warm-up, wall/sim ratio, memory and native/perception/camera time separately.
   Do not fit detector/controller parameters or inspect candidate benefit to choose N.
2. Planned confirmation is **400 independent episode pairs per expanded condition
   and layout**, shared across all metrics/configurations for that condition. Pure
   deterministic impulse/geometry controls instead enumerate their exact cases;
   statistical plane controls use 400 independent field/input realizations. Resolve
   the expanded row count and multiply by measured per-mode cost before starting.
   With the conservative binary interval below, 10 wins and 10 losses out of 400
   (5% total discordance) give a difference interval of approximately +/-3.80
   percentage points, inside a 5-point budget when centered at zero. At 20 wins
   and 20 losses it widens to +/-5.16 points and cannot establish equivalence.
   This motivates a bounded near-equivalence trial plan while exposing its limit.
   This fixed N is not a guarantee of an interval narrow enough to
   establish negligible impact or utility. User choice C requests this cost estimate
   before a campaign, not an immediate long execution.
3. For binary paired results use discordant categories p+ and p-. Construct separate
   97.5% two-sided [Clopper–Pearson intervals](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html), then difference interval
   [L+ - U-, U+ - L-], giving at least 95% joint coverage by the union bound. This
   conservative method retains uncertainty at zero discordances (at N=400 each
   zero-count upper bound is about 1.09 percentage points). Do not report a zero-width
   bootstrap interval as proof of binary equivalence. Aggregate family outcomes use
   whole-episode stratified bootstrap and retain per-condition intervals.
4. For continuous/rate summaries and equal-episode p95, use 10,000 whole paired
   episode bootstrap resamples, fixed analysis seed 8152026, percentile 95% intervals.
   Degenerate/too-sparse event distributions remain unresolved or exact conditional
   deterministic comparisons, not population certainty. Adjacent frames are not N.
5. Analyse at the fixed final N; no stop-on-significance, no outcome-selected sample
   extension and no deleting failed seeds. If cost is unacceptable or precision is
   insufficient, report it. Any subsequent campaign has a separately declared
   sample plan before new outcomes; existing evidence is retained and the domain/
   margins are unchanged. Simultaneously passing all mandatory budgets is an
   intersection requirement; isolated positive findings are not global admission.

## Saved preparation and measured limits — 2026-09-15

Local replay instructions and exact outputs: `local/r10/08_step1_preparation/README.md`.
This ignored experimental workspace is intentionally outside the public SDK. No
historical evidence, original NVIDIA asset or `knowledge/raw/` was modified.

| Item | Checked result | Remaining limit |
| --- | --- | --- |
| NVIDIA inventory and runtime | Office: 21,182 prims / 3,785 meshes; Hospital: 13,389 / 2,058, including instance proxies; no USD composition errors. Actual RTX rendering at four head yaws, floor/ceiling rays and local clearance grids saved in `gpu/` | Whole-asset bounds include exterior geometry. Rendering/collision checks do not qualify acoustic geometry; Office has dark viewing directions |
| Controlled geometry | Eight original preparation layers plus 18 E0/E1/E1_screen/E2/E3/E4 target-material layers in `controls/`; inner-shell acoustic proxies, furniture, dynamic screen and an animated single-partition door; both exact arrays and camera convention | Material values are initial recipes, not accepted decay/DRR conditioning. Proxies preserve the declared simple room interiors, not NVIDIA room geometry |
| Concrete cases | `cases.json`: 154 definitions; `case_layers/`: 116 initial-pose overlays with generic source markers and requested FOV; `episodes/8152026/`: 104 source/door/screen clocks and 11 shared source programs | Overlays are initial poses only; mobile receiver remains consumer-driven. All cases retain `score_ready=false`; 50 physical controls additionally have 32 exact motion clocks and 12 smooth-room/door overlays, with six analytical direct cases |
| Stimuli and background | Ten normalized float32 mono 16 kHz source files; matched speech phases, event schedules, device signal and 32-direction independent plane-wave background sampler; source programs are finite and fixed-base ranges remain within 0.5–10 m | Source-file amplitudes can exceed 1 under the 1/(4*pi*r) convention; preserve float32. Background level, co-location and block-independent reads checked; moving-field and angular convergence remain unqualified |
| Scoring preparation | `scoring.py`: evaluator-only AV deadline/three-frame checks and mobile per-source continuous dwell, either-source eligibility, collision and through-wall exclusions; focused synthetic cases pass | Scoring does not implement or qualify the later closed-loop consumers, camera object association or valid acoustic audibility reference |
| Workload enumeration | `workloads.json`: 154 condition/layout entries, 18 deterministic and 136 statistical; both profiles, arrays, S5 and seven NVIDIA variants retained | No statistical/model-comparison campaign is authorized by preparation; every entry remains not ready for campaign |

### Representative scene findings

Office starts at (-23.08,13.25,1.2), with measured floor near Z=0 and ceiling Z=3.
Final generic source centers are speech (-20.58,11.5,1.2), historical phone
(-20.05,12.8,1.2), and device (-22.83,11.5,1.2). All have a clear initial source-center
ray. The first proposed speech approach collided with a chair; the first device
position was hidden behind a cabinet. Those negative checks are preserved in
`route_runtime_checks.json`; final inputs use the corrected coordinates.

`refined_routes.json` computes routes using **continuous 0.35 m sphere sweeps at
Z=0.4**, including overlap checks, floor checks and a clear terminal source ray.
Office routes to eligible approach points are 4.25/8.25/1.25 m for speech/phone/device,
ending 0.707/0.722/0.559 m from their source centers. These are evaluator/preflight
routes, never hidden maps or source targets supplied to an audition controller.
The 0.35 m radius includes the nominal 0.25 m footprint plus 0.10 m planned margin;
the swept sphere at one height is not full-body or moving-obstacle qualification.

Hospital starts at (-17.4,10.8,1.2), with floor near Z=0 and ceiling Z=2.9905.
The corridor source (-13.4,10.8,1.2) has a corrected 3.75 m approach route ending
0.559 m away. Original closed doors block the selected room routes.
`representative/Hospital_open.usda` references the full original scene and rotates
two original door hinges by -90 degrees. The H01 room source (-17.9,14.3,1.2) then
has a corrected 3.0 m approach route ending 0.707 m away. Both initial center rays
are clear. First grid routes that clipped a bed/door frame are retained as failed
preflight results; final routes use the continuous query. Floor and sphere-overlap
positive controls ensure query availability, rather than interpreting absent queries
as empty space. Visual recognition and closed-loop collision avoidance remain later
consumer work; moving-door swept clearance is still unqualified.

Full acoustic import is **not ready**: Office has 5 unsupported deformable meshes;
Hospital has 3 degenerate polygons. Even ignoring these errors, the minimum
order-3 candidate counts are approximately 9.21e17 and 2.68e19 against the existing
1e6 budget. Their visual meshes cannot be passed wholesale to the specular engine.
A declared, verified acoustic representation of the selected rooms, openings,
ceilings and relevant furniture is still needed. Do not discard long paths, crop
openings, add hidden room closures or lower required physics to manufacture a pass.
This is a scene-preparation blocker, not a reason to rebuild the visual assets.

### Measured acoustic conditions and reference ledger

The CPU-native PRA reference diagnostics use the existing engine's supported CPU
path; GPU perception/simulation use the RTX. The original 12 E0 ISM runs (orders
0/3/5/7) took about 1.92 s and order-7 T20 estimates were only 0.057–0.114 s.
Higher orders and bounded bandwise coefficient searches are retained in
`references_refined/` and `conditioning_e0_endpoint/`; none accepted an entire
0.2/0.5/0.8 s banded recipe. Constant endpoint coefficients fix PRA band extrapolation
in the final attempt. No fitted source gain or tolerance change was used.
Finite-order specular decay is not the full room's acoustic truth. Padding a short
RIR with zeros is not tail convergence; PRA's 40-sample filter latency is separate
from physical propagation time.

An independent bounded native **scalar energy** probe (`scalar_energy/`) traces
4096/16384/65536 rays through the prepared polygons. At 65536 rays, E0 scalar T20
is 0.209/0.509/0.800 s for the three target seeds. This supports the plausibility
of the target recipes but supplies neither joint microphone pressure nor calibrated
DRR. It uses scattering 0.2, so it is not C02's smooth-wall pressure reference.
E1 at target 0.8 gives 0.689 s, E1_screen 0.607 s and E4 0.658 s; several difficult
recipes still fail or approach the tolerance boundary without convergence evidence.
E3's closed-door probe yields unexpected reflected energy across the partition;
its nominal 0.930 s decay is **inadmissible for that condition** until the visibility
failure is resolved. No apparent scalar convergence repairs this structural limit.

| Property / rows | Saved reference or check | Admitted boundary / unavailable comparison |
| --- | --- | --- |
| Direct geometry, C01/LOS | `geometry_references.json`: independent exact per-microphone distances, 1/(4*pi*r), delays and TDOAs at 0.5/3/10 m for both arrays | Static analytical expectations prepared; moving retarded timing and new-array impulse/filter checks remain pending |
| Static specular and decay, C02/rooms | E0 finite-order ISM and bandwise search; independent native scalar-energy diagnostic above | Scalar decay only for bounded static geometry; no accepted complete banded pressure/tail recipe, DRR normalization or joint-PCM reference |
| Controlled diffuse motion, C03/C04 | Preserved `local/r10/08_2_usefulness/diffuse.py` plane control and evidence | Single plane only; historical 8 cm square / 20 ms differs from this protocol. Both new arrays and 10/5/2.5 ms still need replay; no room-motion oracle |
| Visibility and NLOS bounds, A04/A06/A07/M02/M03 | Independent triangle-segment intersections: moving-screen source path crosses clear/shadow intervals; E3 closed blocks/open clears. E4 detour via (6,2) is 9.222 m versus 7.810 m straight-line distance, arrival lower bound about 26.9 ms | Geometry and causal lower bounds only; no diffraction amplitude or complete route coverage. Initial M06 intermediate PCM is silent with the closed door and nonzero after opening; this is not NLOS admission |
| Weak-direct moving rooms, A04/A09/M06 and affected NVIDIA strata | Assigned F1/F3/F4 controls, exact inputs and explicit unavailable entries | Full-room moving multibounce pressure reference and valid DRR strata remain unavailable; mandatory rows retained and later comparisons blocked |
| AV/mobile endpoints | Evaluator-only scorer checks and saved inputs | No closed-loop success, perception accuracy, controller usefulness or approximation-budget claim |

Step 1 exposes these limitations. Implementing new NLOS/diffuse synthesis or
qualifying later models to fill them is outside this preparation request. A reference
failure does not authorize deleting a mandatory condition or treating missing sound
as physically correct silence.

### Machine, GPU recovery and cost envelope

After the user's manual reboot, loaded and installed NVIDIA versions both report
**580.178.04**. Actual RTX 4090 CUDA allocation/calculation, Isaac rendering and
PhysX queries pass. Host resources: i9-14900KF (32 logical CPUs), about 62 GiB RAM,
24 GiB-class VRAM, and about 3.2 TiB free disk. A sandbox-only NVML access failure
was bypassed by the authorized host runtime; it was not treated as unavailable GPU.
The first new-driver Office shader warmup exceeded its 120 s preflight cap; the
retry and later rendered checks succeeded. No driver packages, desktop modules or
user applications were changed. The GPU blocker is resolved.

The **24-run technical pilot completed**: 1,128 simulated seconds, all four
representatives on both arrays with three repetitions, actual CUDA perception and
nonempty 1280x720 rendered frames. `pilot_summary.json` records per-stage timing.
These are intermediate-only prescribed cost trajectories, not trained/closed-loop
consumers, calibrated acoustics or success trials. They do not qualify motion-control
limits; later consumer trajectories and producers need affected cost remeasurement.

| Case | Observed wall/sim range | Median native update | Median CUDA observation |
| --- | --- | --- | --- |
| A01 | 0.74–0.79 | 0.67 ms | 23.02 ms |
| A04 | 1.57–1.82 | 9.73 ms | 21.93 ms |
| M03 | 1.34–1.37 | 6.39 ms | 22.95 ms |
| M06 | 1.60–1.79 | 9.85 ms | 22.17 ms |

Total timed episode loops: **26.9 minutes**, excluding isolated-process
startup/warmup (5.3–6.2 s each). Peak process RSS was 7.67 GiB.
End-of-episode device occupancy was 6.15–6.48 GiB, including the desktop;
this is **not peak process VRAM**. No OOM occurred. New-driver shader compilation
and initial NVIDIA scene cooking are additional cold-start costs. Repeated-process
setup is measured; in-process reset independence is not established by this pilot.

The unchanged 400-pair sample plan gives these explicit allocation envelopes:

| Allocation | Streams | Simulated hours | FLOAT PCM GiB | Intermediate-rate extrapolation, wall hours |
| --- | --- | --- | --- | --- |
| One matched comparison per statistical row | 108,800 | 975.8 | 942.2 | 723–1,775 |
| I/N/D/C/reference/audio-off task slots + paired plane controls | 275,200 | 2,869.2 | 2,770.4 | 2,126–5,219 |
| Previous allocation + five-mode prescribed replay for every mobile row | 339,200 | 4,015.8 | 3,877.7 | 2,976–7,304 |

The first row is 54,400 pairs; the later rows reserve the distinct model/control
streams explicitly rather than pricing the entire campaign as one comparison.
Six task slots are a conservative allocation across 104 task condition/layout rows;
32 statistical plane rows reserve candidate/reference pairs. Refinements or different
property references can add more. I/N/D/C differences remain component ablations,
not automatic approximation errors; a shared C stream may support both reference
and audio-off comparisons when inputs/consumer/settings are identical.

**Wall-hour ranges extrapolate only measured simple-fixture intermediate rates.**
They are not predictions for Office/Hospital acoustic proxies, unavailable C/reference
implementations or closed-loop consumers. Isolated setup adds hundreds of hours at
this stream count; deterministic controls, refinements, extra tails and rendered-frame
storage are excluded. Selective PCM retention is necessary before long execution;
retain seeds, conditions, metrics and required failure evidence. The complete final
campaign cost remains provisional until those components can be timed. No broad
campaign was started, and no domain, tolerance or sample-count reduction is implied.

## Precomparison completion checklist

- [x] Preserve approved domain/tolerances, both profiles, scene/content matrix and HFOV variants.
- [x] Save scenes, exact arrays, source programs, motion clocks and initial pose construction.
- [x] Verify RTX CUDA/rendering, original NVIDIA scene queries and generic control imports.
- [x] Prepare evaluator-only primary endpoint checks and explicit trial/mode allocation.
- [x] Complete the 24-run intermediate cost pilot and record measured resource envelopes.
- [x] Record property-specific diagnostics and unavailable references without dropping mandatory conditions.
- [ ] Finish representative acoustic geometry and full required path/visual eligibility checks.
- [ ] Accept per-band scene conditioning and measured strong/weak-direct DRR strata.
- [ ] Complete both-layout physical-reference refinements; retain blocked room-motion comparisons where a valid reference is unavailable.

Step 1 is **not complete**. The GPU blocker is resolved; the remaining gates concern
scene acoustic representation, conditioning and reference validity. The current
reference failures prevent verified difficult-condition labels and valid comparisons.
Keep the saved tests and report unavailable quantities; do not implement Steps 2/3,
start new provider evaluation, or qualify later consumers to force this gate closed.
No acoustic candidate/task comparison was run. No production producer, perception
or SDK implementation was changed. [[experiments/geometry-acoustics-admission|Existing evidence]]
remains unchanged; [[implementation_phases/08-geometry-acoustics-integration|Phase 08]]
owns execution sequence and [[implementation_phases/r10-geometry-acoustics-integration|R10]]
owns implementation and stop rules.
