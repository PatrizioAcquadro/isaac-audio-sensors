# Consumer Audio Dynamic Quality

Measured 2026-10-08 as a focused follow-up to
[[implementation_phases/squadbot-audio-runtime-readiness|readiness 7.1]], before 7.2.
The [[experiments/consumer-audio-operating-envelope|original assessment]], PCM and
reports remain intact. A faster single-voice free-field profile is delivered;
**full dynamic readiness remains open** for room/competition, uniform accuracy,
approximately 100 ms lag and loaded end-to-end performance.

The separate 2026-10-09
[[experiments/consumer-audio-indoor-quality|indoor-quality follow-up]] adds an
opt-in coherence filter and independent single-voice room confirmation. Its
competing/weak-voice failures remain explicit; the historical results below are
preserved as the comparison baseline.

## Correction and causal diagnosis

Matching now maximizes the number of one-to-one pairs within 20 degrees before
minimizing total angular error. Invalid assigned angles remain in angular p95;
misses/extras remain failures. Rescoring saved directions recovers the valid
17.3503-degree pair in historical `distractor_1` at 2.4 s. Competing-voice
precision/recall become 55.12/61.62%, angular p95 39.946 degrees; complete sets
remain 49.3%. This is a scoring correction, not improved perception.

The 750 ms WPE/group-sparse context responds to past receiver-local bearings:
historical rotating single-voice cases fit 360–420 ms of lag. Audio context,
effective directional lag and processing/delivery cost are different quantities.
Every quality score below uses current reception directions and original bin
endpoints. No timestamp is retrospectively shifted.

## Alternatives and SDK change

Selection used the six original episode-zero conditions and identical received
mixtures. Three families were compared: shorter context, recent covariance after
longer WPE, and direct covariance without WPE. No private stem, source pose,
identity, expected count or motion input enters observations.

| Candidate | Static | Rotation | Joint motion | Room joint | Competition |
| --- | ---: | ---: | ---: | ---: | ---: |
| WPE 750 ms, baseline | 96.9% | 44.6% | 75.4% | 43.1% | 55.6% |
| WPE 250 ms | 96.9% | 96.9% | 96.9% | 93.8% | 90.3% |
| WPE 200 ms | 96.9% | 95.4% | 96.9% | 89.2% | 94.4% |
| WPE 150 ms | 87.7% | 87.7% | 90.8% | 73.8% | 90.3% |
| WPE 750 ms, recent 150 ms covariance | 95.4% | 90.8% | 96.9% | 73.8% | 93.1% |
| WPE 250 ms, recent 200 ms covariance | 96.9% | 96.9% | 96.9% | 83.1% | 94.4% |
| Direct covariance 150 ms | 95.4% | 92.3% | 96.9% | 33.8% | 95.8% |
| Direct covariance 200 ms, selected free-field | 96.9% | 96.9% | 96.9% | 43.1% | 95.8% |
| Direct covariance 250 ms | 96.9% | 96.9% | 96.9% | 43.1% | 93.1% |

Rates use fully resolvable active windows after a common 750 ms startup exclusion.
WPE 250 ms is the initial quality compromise, but isolated live updates cost
118 ms p95, exceeding a 100 ms observation period. Direct 150 ms is faster but
loses robustness on independent phrases: historical static success falls to
90.9% overall and 83.0% in its worst episode, while two new motion conditions
fall below 90%. Refining this family on the original selection cases supports
200 ms; 250 ms adds history without improving those free-field results.
The 200 ms choice is frozen before a further 15-episode confirmation.

Relative peak floors of 20%/35% were also diagnosed on episode zero alone to
reject weak reflected peaks. Room complete sets rise to 98.5%, but competition
falls to 84.7/86.1% through loss of weaker real voices. These filters are rejected.
Equivalent CUDA WPE SVD-driver probes did not yield an adopted improvement;
no conditioning shortcut, CPU fallback, tracker or source-count prior is added.

The SDK exposes `MaintainedEventLocalizer(context_duration_s=...,
dereverberation_enabled=...)` and Lab `localization_context_s` plus
`localization_dereverberation` in both reference and entity bindings. Contexts
accept .15–.75 s; defaults remain .75 s with WPE. Stereo/other-rate scalar roles
retain their 250 ms policy and ambiguity. WPE selection affects localization
only, not PCM, propagation or activity detection. Covariance fitting, grids,
precision, peak rules, confidence availability, masks, clocks and capacity remain
unchanged; NARA-WPE is imported only when that preprocessing is enabled.

## Original same-PCM comparison

Corrected matching in every column. Each scenario contains three original
8 s episodes; comparisons use identical active windows after 750 ms.

| Scenario | Active windows | Baseline 750 ms | Direct 200 ms | WPE 250 ms | Angular p95, baseline / direct |
| --- | ---: | ---: | ---: | ---: | ---: |
| Static | 187 | 97.9% | 97.9% | 98.4% | 1.55 / 2.77 deg |
| Source motion, receiver fixed | 187 | 96.8% | 97.9% | 97.9% | 16.31 / 4.85 deg |
| Receiver rotation | 187 | 49.7% | 97.3% | 96.8% | 41.67 / 12.17 deg |
| Joint motion | 187 | 59.9% | 96.8% | 96.8% | 37.86 / 12.03 deg |
| Geometry room, joint | 187 | 34.2% | 28.9% | 67.9% | 38.42 / 14.77 deg |
| Joint motion, competition | 213 | 49.3% | 92.5% | 89.7% | 39.95 / 11.21 deg |

The direct profile preserves strong static complete sets, with a modest angular
precision tradeoff within 20 degrees. It fails the room, where reflected energy
becomes additional events; a small matched-angle p95 must not hide extra sources.
WPE helps the room but does not qualify it: its worst 3 m episode reaches only
40.6% complete sets. Competition also needs independent confirmation.

## Matched controls and independent episodes

Prepare 39 new eight-second episodes, three at each of 13 conditions. New
utterance pairs include previously unused `S1_axb5`; starts change to 1.1/4.7 s,
competing voice to 2.3 s, noise seeds to 9300–9302, motion phase to
`1.1 + .9*episode`, and wide-arc centers to 55/-95/145 degrees. These inputs are
separate from the original selection episodes. Direct 150 ms results informed
family refinement; the final 200 ms profile therefore receives a further fresh
confirmation below. Speakers/corpus/renderers remain shared; this is bounded
simulation evidence, not population or physical validation.

Square geometry, 16 kHz, 60 Hz acquisition, 100 ms observations, -60 dBFS activity,
-65 dBFS noise, normalization, distances 1.5/2.25/3 m, source speed up to 1 m/s
and receiver yaw up to 90 deg/s remain matched. Narrow free/room controls use
identical 30 +/-10 degree arcs, audio, schedules, phases and noise. Static,
source-only, receiver-only and joint motion isolate the causes. Geometry order
zero separates the direct producer from reflections. Wide free-field motion
covers the original wider envelope. Narrow competition uses a stationary source
at 160 degrees and 2.25 m; all room sources remain inside the fixture.

The room retains the 6 x 5 x 3 m Geometry fixture, specular order 3 and 1 s
horizon. Its decay seed is not measured RT60. Diffuse/NLOS, full-room moving
pressure equivalence and physical transfer remain unqualified. Direct energy
and directions are evaluation references only; unresolved tails remain received
activity and cannot count as resolved directional success.

Complete-set percentages use the same active windows; other metrics below
refer to the direct 200 ms profile. Every scenario is retained, including failures.

| New scenario | Active | Complete sets: baseline / direct / WPE | Worst direct episode | Direct angular p95 | Longest active direct error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Free, static | 122 | 96.7 / 95.9 / 96.7% | 92.9% | 4.88 deg | .1 s |
| Free, source only | 122 | 96.7 / 95.1 / 97.5% | 90.5% | 7.20 deg | .1 s |
| Free, receiver only | 122 | 57.4 / 95.9 / 96.7% | 94.4% | 12.54 deg | .1 s |
| Free, narrow joint | 122 | 55.7 / 95.1 / 96.7% | 94.4% | 12.74 deg | .1 s |
| Free, wide joint | 122 | 63.9 / 95.9 / 95.1% | 92.9% | 11.85 deg | .1 s |
| Geometry direct only, joint | 122 | 55.7 / 95.9 / 96.7% | 94.4% | 12.70 deg | .1 s |
| Room, static receiver/source | 122 | 85.2 / 23.0 / 87.7% | 8.3% | 15.80 deg | 1.9 s |
| Room, source only | 122 | 87.7 / 36.9 / 83.6% | 30.6% | 10.28 deg | .7 s |
| Room, receiver only | 122 | 38.5 / 26.2 / 84.4% | 13.9% | 14.46 deg | 1.5 s |
| Room, joint | 122 | 47.5 / 36.1 / 76.2% | 19.4% | 15.51 deg | 1.6 s |
| Free, narrow competition | 170 | 41.8 / 85.3 / 87.1% | 78.7% | 12.90 deg | .5 s |
| Free, wide competition | 170 | 47.1 / 87.1 / 85.3% | 83.0% | 11.92 deg | .5 s |
| Room, competition | 163 | 41.1 / 24.5 / 71.2% | 12.7% | 23.70 deg | 1.2 s |

The fixed-receiver room failures and passing order-zero control separate
reverberation/additional peaks from receiver lag. Faster context is insufficient
for reflections or simultaneous weak speech. WPE's room source-only result also
falls from 87.7 to 83.6%; improvements are not uniform across room conditions.

## Fresh confirmation of the frozen direct profile

A further 15 episodes change utterance pairs, starts (.7/4.1 s), phase
(`.3 + 1.2*episode`), wide angles (65/-125/150 degrees) and noise (10400–10402).
Each of five one-voice free-field conditions again spans 1.5/2.25/3 m.
No configuration is adjusted after these results.

| Confirmation scenario | Active windows | Complete sets | Worst episode | Angular p95 | Longest active error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Static | 160 | 95.0% | 92.6% | 4.72 deg | .1 s |
| Source only | 160 | 93.8% | 91.2% | 7.22 deg | .1 s |
| Receiver only | 161 | 93.8% | 89.7% | 12.29 deg | .1 s |
| Narrow joint | 161 | 95.7% | 94.1% | 13.58 deg | .1 s |
| Wide joint | 161 | 92.5% | 86.8% | 13.03 deg | .2 s |

The proposed 90% target passes **per scenario**, not uniformly per episode.
Two 3 m episodes remain below it (rotation 89.7%, wide joint 86.8%); there is no
claim that every voice/trajectory within 1.5–3 m is reliable. These correlated
windows do not establish population confidence. Complete-set performance is
still useful for bounded trials, while broader dynamic readiness stays open.

## Temporal response and continuity

Context readiness is 200 ms at 10 Hz for direct 200 ms, 300 ms for WPE 250 ms,
and 800 ms for baseline 750 ms. Acquisition is active before new-episode speech.
First source-correct direction after received onset has p95 200 ms in every
confirmation scenario, with zero misses across eight segments per scenario.
Current direct-profile competition/room onset p95 is at most 230 ms, with no
missed segments, despite poor continuous complete sets. Responses have 100 ms
bin resolution and may occur while an extra event is present.

Baseline initial-acquisition onset p95 is 390–400 ms; its already-acquiring
responses and misses are retained separately. The final profiles' original
onsets occur after context is ready. Initial buffer readiness and first CUDA
kernel use are reported independently; no wall-clock onset guarantee is inferred.

Diagnostic directional lag fits past reference directions only in windows with
one estimate/reference and speed >=20 deg/s, on a 10 ms scan. Coverage/residuals
are reported; missing/extra windows remain failures in current-time quality.
This is not multisource or physical latency. Historical direct-profile rotation
fits are 90 ms, joint motion 80–110 ms, versus 310–420 ms with the baseline.
Fresh rotating/joint confirmation fits span 90–130 ms; some source-only cases
reach 140 ms, while slow motion is explicitly unidentifiable. Approximately
100 ms is approached; a universal <=100 ms bound is **not established**.

Historical active error sequences >=.5 s fall from 7/6/10 to zero for receiver,
joint and competition; longest active errors fall from 1.7/.9/1.5 s to .1/.1/.2 s.
The corresponding baseline frequencies are 22.46/19.25/28.17 per active minute;
the direct profile has zero. Every one-voice free control/confirmation also has
zero such runs. Total incorrect sets, including quiet false events, last at most
.2 s in fresh confirmation.

Room direct-profile runs worsen: eleven historical runs, maximum 2.4 s, versus
ten/2.2 s in the baseline. WPE 250 ms reduces those to four/.8 s but does not
qualify room quality. New direct-profile narrow/wide competition each has one
.5 s run (3.53 per active minute); room conditions retain 6–12 long runs per
scenario. Full reports retain every duration/frequency, misses/extras, quiet
false events and unresolved tails. Episodes are never concatenated into runs.

## Recommended profile and limits

For **one audible voice in the bounded free-field trials**, select:

```python
AudioArraySensorCfg(
    prim_path="/World/Audio",
    update_period=0.1,
    doa_enabled=True,
    energy_threshold_dbfs=-60.0,
    localization_context_s=0.2,
    localization_dereverberation=False,
    max_observations=32,
    max_doa_candidates=2,
)
```

Use the tested square array at 16 kHz and acquire poses/PCM at 60 Hz. Core
consumers inject `MaintainedEventLocalizer(context_duration_s=.2,
dereverberation_enabled=False)` into `AudioPerceptionPipeline`. Capacity stays
independent of true source count. No robot/head controller or attention policy
is added. Other geometries/elevation, translating receivers, rooms, competing
voices and physical captures are experimental. The 3 m episodic limits above
remain part of this profile's disposition.

WPE with `localization_context_s=.25` is an **experimental room alternative**,
not a qualified interactive or multisource profile. Default .75 s WPE preserves
the older maintained stable-source behavior. No automatic room/profile selection
is inferred from private scene metadata. Consumer adoption and robot behavior
remain downstream; partner classifiers, policies and physical robots are untested.

## Validation and preliminary 10 Hz cost

Host gates pass 682 unit/contract, 357 integration and 56 release tests. The
supported Sim/Lab runtime passes 261 Isaac tests, including optional WPE,
scalar/CUDA order/capacity/reset and retained ambiguity controls. Activity agrees
on every update. Direct 200 ms counts agree on 1439/1440 original and 3119/3120
control updates; both discrepancies are room windows. Confirmation agrees on
1200/1200. Direction-difference p95 is .0000194/.0000202/.0000169 degrees.
The existing >=97% count gate passes; finite discrepancies are not called identity.
WPE 250 ms agrees on 1439/1440 original and 3120/3120 control updates.

Single-array isolated received-PCM replay measures about 20.45 ms active p95
for direct 200 ms after the first active call, versus 88.97 ms for WPE 250 ms
and 91.49 ms for the baseline. Direct's first active CUDA call takes 128.45 ms;
serial completion recovers to at most 45.01 ms thereafter and does not accumulate.
The baseline's first active CUDA call takes 246.20 ms; its subsequent 250 ms
run reuses CUDA initialization, so those startup values are not a fair profile
comparison. No startup deadline is inferred from them.

Isolated live Lab at 60 Hz acquisition/10 Hz observations measures direct
200 ms at 31.16 ms mean / 31.75 ms p95 over ten timed updates, versus WPE 250 ms
at 116.19 / 117.71 ms over five. Both preserve scalar events and partial reset.
The small direct-profile check shows useful headroom against a 100 ms period;
WPE does not. Live checks exercise sensor lifecycle/acquisition/perception, not
representative loaded rendering, robot control or complete end-to-end latency.
Replay batch timing and tests run concurrently are not the single-array cost gate.
**No real-time claim follows from these measurements.**

7.2 must measure producer/acquisition, buffering, device/consumer delivery,
wall-clock onset/direction age, rendering/simulation load, scheduling/queue growth
and multi-environment throughput. Investigate WPE cost without losing its
conditioning/quality properties. Room/competition accuracy needs separate work;
a latency pass cannot close those failures.

The subsequent [[experiments/consumer-audio-runtime-performance|7.2 performance
assessment]] now measures those costs and qualifies the initial free-field
profile under its declared 30 Hz camera load. Its 60 Hz rendering and native
indoor-stage limits remain explicit; the future indoor selection still needs
its own loaded measurement after integration.

## Artifacts and reproduction

Preserved originals: `local/sdk-runtime-readiness/` and
`build/validation/sdk-readiness-7.1/`. New ignored preparation/selection scripts:
`local/sdk-dynamic-quality/`; fresh confirmation PCM:
`local/sdk-dynamic-confirmation/`. Separate corrected historical metrics,
candidate runs, all per-window paired results, quality summaries, runtime logs
and timing probes: `build/validation/sdk-dynamic-quality/`.
`knowledge/raw/` and original clips remain unchanged.

```bash
IAS_DYNAMIC_PATH="$PWD/src:$PWD/build/validation/phase06_1/runtime_deps:$PWD/build/validation/continuity_runtime_deps"
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH="$IAS_DYNAMIC_PATH" \
  "$ISAAC_LAB_ROOT/isaaclab.sh" -p local/sdk-dynamic-quality/prepare.py \
  --out local/sdk-dynamic-quality \
  --geometry-library build/qualification/r9/steam-audio/core/build/r9-release/src/core/libphonon.so \
  --specular-library build/native/libias_specular.so
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH="$IAS_DYNAMIC_PATH" \
  "$ISAAC_LAB_ROOT/isaaclab.sh" -p tools/validation/lab_perception.py \
  --inputs-dir local/sdk-dynamic-quality/received --layouts square \
  --input-glob '*_{layout}_*.npz' --include-rows --localization-context-s .2 \
  --no-localization-wpe --out build/validation/sdk-dynamic-quality/holdout-direct200.json
```

Run `confirm.py` with `--out local/sdk-dynamic-confirmation` and the same native
arguments for the fresh confirmation; replay that received directory with the
same frozen flags. Use the original received directory for historical replay.
WPE 250 ms omits `--no-localization-wpe` and sets context `.25`; defaults reproduce
750 ms. `--rescore-report` recomputes saved directions without inference and
preserves context metadata. Summaries distinguish configured/common warm-up,
+/-3 dB received-reference sensitivity, startup/onsets, diagnostic lag and serial
replay completion. Propagation stays CPU-side for its non-CUDA producers; mixture
inference uses the actual RTX 4090 without CPU fallback.

[[topics/isaac-lab-integration|SDK configuration and contracts]] · [[index|Wiki index]]
