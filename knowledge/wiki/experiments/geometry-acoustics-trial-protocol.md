# Geometry Acoustics Simulation Fixtures

Status: **Step 1 preparation is complete; 08.2 qualification is recorded in
[[experiments/geometry-acoustics-admission|Admission Evidence]].** This page owns
prepared inputs, bounded references and measured preparation results. It does
not establish full-room equivalence or application performance.

[[decisions/robot-audition-fidelity|Robot-Audition Fidelity]] owns acoustic/interface
criteria and limits. [[implementation_phases/08-geometry-acoustics-integration|Phase 08]]
owns sequencing; [[implementation_phases/r10-geometry-acoustics-integration|R10]]
owns implementation. These fixtures use simulation and existing source recordings;
no physical microphone measurement is part of the 08.2 checks.

## Common rig, clocks and signals

- Positions are meters, Z up; acoustic source/array centers are at Z=1.2 unless
  stated. SDK bearings are clockwise from array forward.
- Maintained layouts in `tools/smoke/multisource_reference.py` are `square`:
  (-.033,-.033,0), (-.033,.033,0), (.033,.033,0), (.033,-.033,0); and `raised`:
  (-.03,-.03,0), (-.03,.03,0), (.03,.03,0), (.03,-.03,0), (0,0,.04).
  Square reports azimuth; raised supports 3D projection. Mounts have no acoustic
  housing; markers and rig glyphs are excluded from acoustic geometry.
- Prepared PCM is FLOAT 16 kHz. Perception uses 100 ms updates, a 750 ms causal
  context, 300–6000 Hz spatial band and -60 dBFS activity threshold. The maintained
  scalar/CUDA localizer and its confidence semantics are unchanged.
- Sound speed is 343 m/s. Prepared geometry/audio refresh uses 10 ms with 5/2.5 ms
  refinement. C03/C04 maximum-motion confirmations use 2.5 ms; this does not
  qualify unrestricted 10 ms motion.
- Isaac simulation and CUDA perception use the GPU; native CPU-only acoustics
  retains its supported execution path. Offline wall time is distinct from
  simulated latency.

## Prepared geometry and material recipes

Existing NVIDIA Office/Hospital assets under
`/home/pacquadr/Desktop/SquadBot_ONR_Assets/nvidia/Isaac/Environments/` supply
representative composed scenes. Their bounded proxies preserve relevant openings,
large structures and door hinges; visual reuse is separate from acoustic validity.
The measured preparation section below records proxy omissions and costs.

Controlled shells have floor Z=0, ceiling Z=3 and nominal wall thickness .15 m.
Shared walls are represented once. Doors use a single acoustic partition;
construction transmission is opaque except in the declared planar control.

| ID | Inner air volume / objects | Acoustic use |
| --- | --- | --- |
| E0 | [0,3] x [0,3] x [0,3], empty | Small-room/specular and recorded cube diagnostic |
| E1 | [0,6] x [0,5] x [0,3]; desk [4.4,5.6] x [4.3,4.9] x [0,.75]; cabinet [.2,1.2] x [4.5,4.9] x [0,2] | Furnished-room pressure and weak-direct probes |
| E2 | [0,10] x [0,6] x [0,3]; cabinet [.2,1.2] x [5.4,5.9] x [0,2] | Distance/room-size boundary and response horizon |
| E3 | [0,4] x [0,5] and [4.15,8.15] x [0,5], height 3; doorway x=[4,4.15], y=[1.9,3.1], z=[0,2.2]; hinge (4.075,1.9), leaf width 1.2 | Door visibility, planar transmission and selected-route transport |
| E4 | Union of [0,8] x [0,2] and [6,8] x [0,8], height 3, without interior overlap faces | Corridor/NLOS preparation |

E1-screen adds x=[3.4,3.55], y=[1.8,3.2], z=[0,2.5]. Its prepared motion translates
by (0,1.6,0) and back at .5 m/s with .5 m/s² acceleration.

R02/R05/R08 label nominal .2/.5/.8 s decay recipes, reported at octave centers
250/500/1000/2000/4000 Hz. Initial shell absorption uses
`alpha = 1-exp(-24*ln(10)*V/(343*S*T))`; these are estimates, not measured decay.
Main shell scattering is .2; furniture/screen absorption is .2 and scattering .35.
Smooth controls use zero scattering; the diffuse plane uses absorption .2 and
scattering 1. Materials are nominal, not calibrated physical twins.

DRR is direct-path energy divided by all indirect RIR energy, per band/microphone
with the same horizon. Diagnostic strong/weak ranges are +6…+15 / -12…-6 dB;
zero-direct NLOS is -infinity. The plane's direct gains 1/.1 are controlled
ablations, not physical occlusion. The admission record owns actual room DRR/decay
measurements and failures to meet nominal targets. A recipe label alone is not
conditioning evidence.

## Source inputs

Prepared programs reuse speech from
`evidence/qualification/multisource/assets/`, phone/door audio from
`local/onr/data/video1/audio/`, CC0 footsteps in `local/r10/assets/footsteps.wav`,
and synthetic band-limited noise, impulses, sweeps and silence. Provenance remains
with the retained inputs; no new capture is required.

Preparation mixes to mono, resamples once to 16 kHz, applies 10 ms endpoint fades
and preserves natural silence. Source gains target active-window free-field RMS
-35 dBFS at 1 m under `1/(4*pi*r)`. This is a digital reference, not calibrated SPL;
received frames are not independently normalized. Quiet inputs and a shared
32-plane-wave background sampler are available; prepared noise is a controlled
surrogate, not measured building ambience.

## Controlled references and evidence identifiers

| Control | Input / reference | Limit |
| --- | --- | --- |
| C01 | Free field, array (0,0), source distances .5/3/10 m; analytical direct gain, delay and pair distances | Direct LOS/declared planar transmission only |
| C02 | E0, array (1,1.5), source (2,1.5), smooth R02/R05/R08 | Recorded R05 late-response mismatch is diagnostic; structural invariants remain binding |
| C03 | Plane x=0, y=[-6,6], z=[-5,7]; source (2,-1,1.2), receiver (3,.1,1.2); source +X speed 0/.1/.5/1.5 m/s, direct gain 1/.1 | Controlled first-scattering motion, not room-tail equivalence |
| C04 | C03 with fixed source; receiver +X .5/1 m/s or yaw 60/90 degrees/s | Controlled receiver motion/coherence; same room limitation |
| C05 | E3, array (2,2.5), source (6,2.5); opaque, 20 dB planar or absent leaf | Authored visibility/transmission, not calibrated door amplitude |

C03/C04 use one moving entity per run, constant motion/emission over [0,2.1] s
and 2 s of tail. `local/r10/checks/fixtures.py` retains the exact plane inputs.
Independent dense quadrature, retarded timing, geometry intersection, normalization
and refinement checks have property-specific validity. Another provider, higher
ray count or convergence alone is not a universal room reference.

The admission evidence also uses these prepared scene identifiers:

| Identifier | Geometry / prescribed input |
| --- | --- |
| A01 | E1, array (1,2.5), source (4.5,2.5) |
| A04 | E1-screen, array (1,2.5), source from (5,.8) to (5,4.2), .5/1.5 m/s, R08 |
| A08 | E1, array (3,2.5), sources (3,4) and (4.5,2.5), second source 0/-6 dB |
| A09 | E1-screen, array (1,2.5), source (5,2.5), moving screen, R08 |
| M01 | E1, source (4.5,2.5), array from (1,1) to (3.5,1), .5/1 m/s with yaw |
| M03 | E4, array initially (1,1), source (7,6) |
| M06 | E3, array initially (1,2.5), source through (6.5,4), (6.5,2.5), (2.5,2.5) at .5 m/s; door opens at t=3 over 1.5 s |

These identifiers locate prepared inputs and bounded measurements. Their presence
does not mean every route or complete matched moving-room comparison was executed.
Full-room moving pressure/observation equivalence remains **NOT VALIDATED**.

Producer variants I/N/D/C denote direct+specular, I+NLOS, I+diffuse and I+both.
Combined composition/lifecycle checks live in `tests/isaac/test_geometry_combined.py`;
actual Sim/Lab validation uses `tools/smoke/live_nlos.py --combined` and
`tools/smoke/live_isaac_lab_audio_smoke.py --geometry-combined`. Their measured
results belong to the admission record.

## Prepared inputs and measured boundaries

Step 1 preparation completed on 2026-09-15. Ignored `local/r10/preparation/` contains 154 definitions, 116 initial-pose overlays, 18 controlled material layers, 104 episode definitions with 11 shared source programs, and 50 reference-control definitions including exact 2.5 ms motion clocks. `score_ready=false` intentionally distinguishes prepared input from qualified comparison. Its README owns maintenance commands.

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

Corrected static order-3 queries took 1.96/14.11 s for Office/Hospital, with 45–46/16–20 visible paths per microphone and explicit candidate limits 3/12 million. These are fixture-consumption costs, not PCM throughput. Hospital diffuse integration required a local 200000-node override; SDK defaults remain unchanged.

The 24-run intermediate RTX pilot completed 1128 simulated seconds: four cases, both arrays, three repeats, 300 Hz physics, 100 Hz geometry/audio and 30 Hz nonempty RGB. Timed loops totaled 26.9 minutes, excluding 5.3–6.2 s startup each; peak RSS 7.67 GiB. Wall/sim ranges were .74–.79 A01, 1.57–1.82 A04, 1.34–1.37 M03, 1.60–1.79 M06. Invalid camera/path attempts were excluded. These prescribed trajectories are not closed-loop success, and timings precede the stable WPE correction.

## Retention and reuse

Retain concrete inputs and reuse unaffected controls; repeat only checks whose
geometry, model, clock or interface changed. Preparation assets and bounded
head/scoring diagnostics live in ignored `local/r10/`; its README owns commands.
Runtime regression tests live under `tests/` and native build recipes under
`tools/native/`.

Concluded preparation reports, pilot PCM and obsolete reference executors are not
retained. The evidence summaries do not promise historical raw-output replay.
08.3 owns operating workflow, diagnostics and bounded runtime/distribution checks.
