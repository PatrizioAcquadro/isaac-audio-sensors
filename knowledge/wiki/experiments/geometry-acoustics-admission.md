# Geometry Acoustics Admission Evidence

Decisive results from 2026-09-10–16. [[decisions/robot-audition-fidelity|Robot-Audition Fidelity]] owns acceptance criteria; [[implementation_phases/08-geometry-acoustics-integration|Phase 08]] owns execution order; [[topics/geometry-acoustics|Geometry Acoustics]] owns interfaces and builds.

## Admission summary

**Retain PRA. Step 3 PASS with documented limits**, following the explicit admission revision at `9395b1c`. Representative full-room moving pressure/observation equivalence remains **NOT VALIDATED**, accepted as non-blocking. This decision changes admission, not measurements. Cube and selected-mirror failures remain diagnostic; all other binding controls and budgets remain in force. A newly demonstrated structural defect or material representative error reopens affected qualification.

| Contribution | Established | Boundary |
| --- | --- | --- |
| Steam direct + native PRA specular | Bounded arrival/gain, reflected visibility, continuous PCM and actual Sim/Lab/Kit integration | Receiver-clock quasi-static RIRs; no general dynamic-field claim |
| Steam selected routes | Step 2 transport, ordinary motion/doors, coverage and lifecycle | Probe-sensitive pressure; uncalibrated diffraction; no combined-model admission |
| PRA persistent surface pressure | Step 3 shared-field, energy, visibility, lifecycle and selected motion/observation controls | Full-room moving equivalence unvalidated; cube/mirror limits below |
| Robot consumers | Bounded head/camera diagnostic benefit | Complete AV/mobile usefulness, NLOS+D and physical transfer remain separate |

Steps 4–8 remain open. The next step is the combined producer, not a provider replacement or a repeated qualification campaign.

## Provider corrections and rejected approaches

| Finding | Decisive evidence | Consequence |
| --- | --- | --- |
| Independent Steam reflection IRs lose microphone timing | Plane TDOA errors 6.6754/7.5758 samples at 16 kHz and 20.0262 at 48 kHz; PRA controls ≤.1220 samples | Direct-delay restoration and shared seeds cannot recover information lost by 10 ms energy bins. Reject this mapping; retain Steam direct and PRA specular |
| First hybrid leaked through closed partitions | Peak .0209–.0227 at source offsets 0–100 mm in a 6×6×3 m partition fixture | Native bounded-polygon/visibility corrections pass both orientations, tessellation, closed/open/closed and corridor checks; no fitted attenuation |
| Historical R9.4 NLOS used Euclidean delay | Arrivals 133.11–146.54 samples too early at 48 kHz; moved blocker 327.38–344.86; maximum TDOA errors 13.43/17.48 | Withdraw the stronger timing claim. Export selected weighted polylines before aggregation and render route-specific delay |
| Independent PRA histogram reconstruction lacks a shared field | Co-located PCM relative error 1.380–1.489, correlation -.058–.028 despite identical histograms; shared seeds force coherence 1 | Neither independent nor shared seeds reproduce spatial coherence. Capture native transport before histogram reduction |
| Ray-hit-attached pressure moves with the sampler | 1 cm source shift: temporal errors .117/.227/.687 at 500/1000/4000 Hz; more rays do not fix it | Attach modes to material surfaces. First-scatter anchoring alone still leaves later-scatter persistence errors |
| Banded specular material phase depended on scalar gain | Distance scaling and signed directivity entered minimum-phase conversion | Normalize material bands before phase construction; apply signed level separately; retained native regression covers polarity, gain and distance |

Steam's full-channel reflection experiment also crashed at an unaligned SIMD load; this was separate from the completed W-only timing failure. Its initial 14/16 then 16/16 scalar-count outcomes lacked the PCM needed to resolve the discrepancy. Neither result qualifies physics.

## Operational intermediate

Steam direct/planar transmission plus native PRA specular passed source/channel gain and directivity, physical delay, fragmented reads, stop tails, reset, provider replacement and 0.1 m/s source motion at 60 Hz. Four reflector controls at 16/48 kHz had maximum TDOA error .12191 samples.

The historical RTX 4090 comparison had 1,440 same-PCM updates, 100% count agreement, p95 direction difference .0612° and maximum 2.4187°. Reference agreement preserves reference errors. Historical 16-environment indoor means were 128.52/159.26 ms for four/five microphones; these precede the WPE correction and are **not current throughput promises**. [[experiments/lab-perception-runtime|Lab Perception Runtime]] owns current measured costs.

## Step 2 selected-route transport closeout

The native UniformFloor/probe extension excludes LOS, exposes unavailable coverage, preserves interpolation-pair identity and uses immutable geometry snapshots. Fixes retain native geometry ownership:

- Centered probes and inclusive segment bounds eliminate corner shortcuts and closed-door leaks. Nine positions at 1/.5/.25 m spacing retain total weight 1 within 2e-6, without renormalizing missing routes.
- Full native-neighborhood lookup followed by nearest-eight visible selection restores both screen alternatives. Bounding bent-route length by a finite graph path resolves the E4 .883-weight failure; 567 pose/channel/grid checks pass.
- Newly opened paths may recover only previously unassigned emission history. A 1 ms pulse with gate opening at 2 ms matches already-open arrival; opening at 6 ms blocks. Previously assigned/LOS contributions are not duplicated.

Both arrays pass source 1.5 m/s, receiver 1 m/s, yaw 90°/s and doors opening/closing over .5/1.5/3 s with timestamped held geometry. Thirty native/producer regressions cover delay within one sample after separating EQ, alternatives, rebuild, source stop, reset, array isolation and fragmented reads. The RTX Isaac smoke passed four simulated seconds, 180 native updates and reset. Native Steam/Embree executes on CPU.

| Refinement | Result | Interpretation |
| --- | --- | --- |
| Motion 100→200→400 Hz | Relative PCM changes .024%, then .015% | Small selected corridor sensitivity |
| Door selection 100→200→400 Hz, geometry held at 100 Hz | Identical PCM | Faster queries add no unobserved geometry |
| Door probes .5→.25 m, both arrays | Relative PCM 1.283–1.284; envelope difference .347–.349; level .56–.58 dB | Pressure is representation-sensitive |
| Door probes .25→.125 m, square | Relative PCM .618; envelope .213; level .56 dB | Decreasing differences do not establish pressure convergence |

The final native visibility cache preserved dense-door PCM and reduced one run from 178 to 74 s. This is not a general performance claim. The qualified native build identity and commands remain in the technical topic.

### Selected-flight stress limit

A route crossing at 8.416 ms and arriving at 16.713 ms is blocked by closure at 5 ms, preserved by closure at 12 ms and by closure/reopening at 4/6 ms. Endpoint-motion residuals were ≤1.8e-12 samples and partition error ≤1.4e-9.

A two-gate example crosses at 6.958/9.874 ms while every instantaneous scene has one gate closed. A known all-open reference route can propagate, but instantaneous selection exports none. This remains a temporal candidate-discovery stress limit, not an authorization for an IAS space-time solver or an all-open production workaround.

## Step 3 diagnostic limitations

### Rotating mirror

The material-anchored prototype's 5° rotating-mirror control failed temporal coherence at 500 Hz: mean .17045, 95% interval [.16783,.17321], versus the .1 bound at 1,048,576 rays. All twelve fresh realizations failed; reference refinement changed .000406 and native path-length error was ≤4.155e-6 m. More rays do not explain away the bias.

The subsequent 96-episode, 65,536-ray, 2.5 ms selected-mixture comparison passed all observation-impact budgets on both arrays at approximately -15.7 dB DRR. Isolated-family spurious-rate intervals remained inconclusive; weak two-source reference misses were roughly 59.5–69.6%, and selected-mixture extras occurred in roughly 87–89% of updates. Agreement does not establish utility. These are controlled scalar statistical geometries, not furnished-room references.

Earlier moving-ray pressure showed material weak-direct bias: at .5 m/s and 16,384 rays, misses rose 35.71→69.94%, paired change 34.23 points [26.48,42.56]. Strong-direct controls did not show this degradation. This counterexample motivates persistent surfaces; it is not a result for the corrected general producer.

### Conditioned smooth cube

The 3 m, zero-scattering cube used source (2,1.5,1.2), receiver (1,1.5,1.2), both exact arrays and a .5 s decay target. Independent shoebox order 100, conditioned before candidate scoring, produced .4493–.5402 s T20 across 250–4000 Hz; order 100/160 residual energy was ≤5.53e-8. Candidate and reference used identical coefficients.

The order-7/65,536-ray candidate failed the original decay and observation criteria over 96 fresh waveforms:

| Array | Mean-angle change, 95% CI | Spurious-update change, 95% CI | Reference/candidate DRR |
| --- | --- | --- | --- |
| Square | .153° [.144,.161] | -23.08 points [-25.99,-20.18] | -8.48/-6.93 dB |
| Raised | -.131° [-.156,-.106] | -67.43 points [-68.48,-66.28] | -9.21/-7.60 dB |

Candidate 1 kHz T20 was .352–.378 s, outside .425–.575 s; reference .534–.540 s. Energy ratios at 250–2000 Hz were approximately .624/.519/.754/.587. Other observation budgets passed. Fewer extras still failed the original absolute five-point difference budget. This remains a recorded physical/observation mismatch, now diagnostic by explicit user decision.

Absolute extra-update rates were 99.95/76.86% square and 100/32.57% raised, reference/candidate. These are updates with unmatched estimates, not false detections as a fraction of all detections. Long opposite-bearing runs occurred in both models. Correcting only the late 1 kHz decay did not restore the reference's extras; substituting its complete late response largely did. This intervention does not isolate phase, direction or all-band decay and is not a physical repair. Downstream software accepted behind-sector cues, but did not actuate joints; it supplied no closed-loop confirmation evidence.

These rates used the preceding numerical consumer. The later correction below does not retroactively regenerate their confidence intervals.

## Bounded head/camera diagnostics

A less symmetric 6×5×3 m speech scene compared native order-7 plus shared tail, independently conditioned shoebox order 100, and audio-disabled search. Reference T20 across the head ring was .435–.568 s; reference/candidate DRRs approximately -7.61…-6.70/-7.37…-6.51 dB. Camera: 90° HFOV, 30 Hz, 100 ms delivery, three-frame confirmation. Head: ±170°, 60°/s, 180°/s². Audio alone drove cue selection; geometric truth scored outcomes.

The 192 fresh episodes used 65,536 rays, 2.5 ms integration and fixed field seed 17001, with 92 square/100 raised and 100 intermittent programs:

| Measurement | Square reference/candidate | Raised reference/candidate |
| --- | --- | --- |
| First acquisition within 10 s | 92/92 versus 92/92 | 100/100 versus 100/100 |
| Extra-update rate | 53.36/50.44% | 84.23/84.09% |
| Any false association | 0/92 versus 0/92 | 0/100 versus 1/100 |
| Mean wrong-cue dwell | 7.87/6.39 s | 5.32/5.37 s |
| Mean visual resumption | 1.499/1.419 s | 1.339/1.387 s |

Pooled false-association difference was +.52 points [-2.25,3.28]; the raised-only interval [-4.27,6.21] remained inconclusive. Candidate/reference/audio-off mean acquisition was .446/.483/.672 s; resumption 1.402/1.414/3.126 s. The audio-off success ceiling and stationary target prevent a complete profile-usefulness or tracking claim.

Episode 21191 retained three false-association frames (100 ms) and resumption 3.682 s versus 1.048 s reference. Replaying it plus three representatives after the numerical correction preserved outcomes, rates and dwell. Small-batch replay also preserved outcomes. These targeted checks do not renew the complete campaign's intervals.

Auxiliary MeshRIR replay was not a matched physical twin: measured delays implied ~52° versus 36.87° coordinate metadata, and wall/absolute placement data were insufficient. Raised extras were same-sector duplicates, with no >20° estimate in the selected steady-state replay. No channel-wise delay correction was fitted. Neither this nor the 25 ReSpeaker takes adjudicates the cube's fidelity.

## Measurement reliability

At `1565267`, weighted QR/pseudoinverse replaced unstable WPE normal equations; float64 peak sums and stable ties corrected separate plateau discrepancies. Thresholds, context, iterations, acoustic model and public tensors are unchanged.

The exact direct 45° control now returns one event at 45.00° square/45.14° raised. Twelve direct/cube reproductions had scalar/CUDA WPE relative RMS ≤4.13e-7; four full cube streams retained all 128 activity/count updates, maximum angular difference .000366°. Solo/32-environment, reordered, 100x-neighbor and partial-reset checks passed. The maintained 36-recording replay and corrected costs are in [[experiments/lab-perception-runtime|Lab Perception Runtime]].

The historical full-pressure angular cache still failed its 1% isolation control: maximum indirect RMS error 3.214% at 24 angles, 2.234% at 48; late-only errors .0801%/.00671%. Missing native order-6/7 corner paths dominate. A 36-case early-response intervention changed one count; cache-versus-exact-native sampling changed none, with maximum .305° direction change. Future motion checks must use actual microphone-position responses or separately qualify their sampling. Do not substitute ideal early paths to force agreement.

## Joint motion and observations

The corrected consumer and actual D producer evaluated C03 source speeds 0/.1/.5/1.5 m/s and C04 receiver .5/1 m/s, yaw 60/90°/s on the protocol plane. Both arrays and direct gains 1/.1 used 2.1 s motion/emission plus 2 s tail. Gain .1 is an ablation, not physical occlusion.

Independent retarded Lambertian transport with separately checked shared synthesis agreed with dense .05 m quadrature: energy error ≤.00169%, spatial/temporal coherence errors .0000189/.0000151. Exact-pose producer/replay RMS difference was <2.7e-7; dynamic partitions differed <1e-7. Reordering/regrouping, equivalent source IDs, reset and independent environments preserved PCM. Ray/order invariance here exercises first scattering only, not room-tail convergence.

Four-program diagnostics at 10 ms had inconclusive rate intervals. Refining 10→5 ms changed angular p95 by up to 7.81° and misses by 5.36 points; 5→2.5 ms reduced point differences. **Unrestricted 10 ms remains unqualified.**

### Fresh maximum-motion confirmations

Each selected trajectory used 96 fresh paired programs at 2.5 ms, field 31001, both arrays/gains. All five C03 budgets and all forty C04 translation/yaw metric decisions passed.

| C03 at 1.5 m/s | Misses reference→candidate | Extras reference→candidate | Miss delta, points [95% CI] |
| --- | --- | --- | --- |
| Square / gain 1 | 35.27→33.48% | 35.27→33.48% | -1.79 [-3.20,-.44] |
| Raised / gain 1 | 36.38→34.97% | 45.24→44.12% | -1.41 [-2.98,.15] |
| Square / gain .1 | 88.84→85.79% | 100→100% | -3.05 [-4.84,-1.26] |
| Raised / gain .1 | 53.42→51.34% | 100→100% | -2.08 [-3.27,-.89] |

C03 maximum mean/p95 point differences were .445/.384°; largest added-acquisition upper endpoint 19.8 ms. Angular metrics are conditional on matched observations: square/gain-.1 matched 150/191 of 1,344 eligible events in reference/candidate, across 82/92 of 96 episodes. Empty episodes count as misses, not zero-angle successes. Resamples without angular observations remain undefined.

C04 per-program rates/latency were identical. Zero-discordance uncertainty remains ±3.77 points and ±79.2 ms; maximum angular p95 difference .000733°. Yaw/gain-.1 still had square 10.64% misses/96.95% extras and raised 6.92%/99.93%; translation/gain-1 had none. This is relative fidelity, not useful tracking. Lower-speed cells retain diagnostic coverage.

### Independent field seeds

Three fresh fields (31002–31004), four programs per trajectory/field and both arrays/gains exposed two low-N signed failures: increased square/gain-.1 misses at 31004 and reduced raised/gain-1 extras at 31002. Both received separate predeclared 96-fresh-program confirmations; **all five budgets passed in each**.

| Field / array / gain | Misses reference→candidate | Miss delta [95% CI], points | Extras reference→candidate | Extra delta [95% CI], points |
| --- | --- | --- | --- | --- |
| 31004 / square / .1 | 73.66→72.47% | -1.19 [-3.13,.67] | 100→100% | 0 [-3.77,3.77] |
| 31002 / raised / 1 | 35.04→33.26% | -1.79 [-3.35,-.22] | 43.90→42.63% | -1.26 [-2.68,.07] |

Original pilot failures remain part of the interpretation; their over-budget effects did not reproduce. This is a finite-field follow-up, not population-wide equivalence.

## Representative properties and room integration

The E3 jamb defect allowed projection behind the previous reflector at a 4.8 μm departure. Native departure-side checks (`6644e95`) fix it without an energy threshold: actual closed/open/closed D has exact zero/nonzero/zero pressure and identical returned response. Open reflected energy summed over nine microphones is .0202555. Fifteen native/field and nine producer checks passed; the bridge requires its projection capability.

| Property | Measured result | Limit |
| --- | --- | --- |
| Ordinary door/screen visibility | 301 door + 841 screen poses; 10,278 connections, zero independent-geometry disagreements | Geometry, not full moving diffuse PCM/history |
| Controlled isotropic synthesis | Maximum spatial/cross-pose complex errors .01181/.02907 <.1, both arrays | Controlled input, not arbitrary-room isotropy |
| Radius and horizon | Surface capture invariant at .05/.1/.2/.4 m receiver radius; E2 2/4 s omitted energy 1.02e-14 | Zero native receivers and declared native cutoff; no finite-radius-reference convergence claim |
| Static physical weak direct | DRR -11.64/-11.59 dB; four programs, zero misses, 21.43/42.86% extras | No matched room-pressure reference or population inference |
| Two-source bounded room probe | No misses/extras in twelve eligible updates; mean/p95 4.24/12.72° square, 4.70/13.55° raised | One program and 200 ms motion segment, not full routes |
| Screen-edge probe | 17/12 directional updates out of 41; arrivals unresolved | Does not establish arrival-bearing accuracy or moving weak-direct equivalence |
| Office/Hospital static D | Nonempty PCM; DRRs -10.21/-10.33 and -8.09/-8.04 dB | Original early-acoustic proxies, not whole-building field references |

Hospital exceeded the default 100,000-node guard; 173,848 nodes required explicit local `max_nodes=200000`. Defaults, geometry and accuracy budgets were unchanged. Initial E1 weak-direct placement measured ~-14 dB and was outside the -12…-6 dB stratum; physical repositioning supplied the in-range case above, without fitted gain.

Pressure T20 ranges: E0_R02 .169–.222 s; weak-direct E1 .486–.619; original screen .601–.713; E2_R08 .807–.916; open E3 .509–.565. Some miss nominal recipe targets; independent conditioning was not established. These are not target-match passes or demonstrated reference-relative renderer failures. Across four farther E1 fields, square extras varied 5.36–100% despite zero misses.

The earlier banded 6×6×3 m envelope control measured .226/.226/.374/.522/.671/.821/.821 s for .2/.2/.35/.5/.65/.8/.8 targets within its declared tolerance. That bounded scalar/energy result is distinct from the room-pressure measurements above.

Native corrected room preparation cost 24.2–157.3 s per pose; Office/Hospital pilots 27.4/24.5 s. Native PRA is CPU-only. CUDA inference remains on the GPU; offline wall time is separate from simulated perceptual latency.

## Full-room reference boundary

The bounded audit at `ad4a6e2` found no independently justified joint spatial/temporal pressure reference for the furnished scattering rooms. Plane/shoebox references cover narrower geometries; energy/history lacks the pressure correlation law; reusing the candidate's synthesis is not independent validation. PRA traversal remains reusable, and no new geometry engine is proved necessary.

Conditional routes were A04_1 source motion, M01_1 receiver translation/yaw, A09_0 moving screen, plus static two-source A08_1. Neither their complete matched D routes nor dependent input conditioning were executed. Serial 10 ms moving-segment cost extrapolations were roughly 12–14, 11–14 and 27–31 hours respectively; 2.5 ms about four times those values. These exclude reference development and are not measured route costs or lower bounds.

The user declined separate reference-model development and explicitly accepted this full-room property as non-blocking. **It remains NOT VALIDATED**, including ordinary moving-room diffuse history and moving physical weak-direct equivalence. The audit did not show that PRA needs replacement. Cube/mirror exceptions do not waive other structural or representative failures.

## Evidence retention and future work

Historical trial executors, reports, PCM banks and obsolete provider copies were removed during the user-authorized cleanup after consolidating results here. They are no longer promised as replayable archives. Earlier tracked narrative and implementation are recoverable at `9395b1c`; ignored raw outputs are not in Git.

Ignored `local/r10/` retains only preparation inputs/generators, licensed assets, reusable producer controls and head/scoring helpers for Steps 4–8. Its README owns commands. Current runtime regression tests remain under `tests/`; native builds remain under `tools/native/`. Existing ONR production and the 36 Lab parity inputs are retained separately.

Future work must preserve the admission boundaries above, reuse unaffected controls, and measure actual combined-producer/consumer behavior. No new reference campaign, acoustic solver, physical capture or provider evaluation is implied by cleanup.
