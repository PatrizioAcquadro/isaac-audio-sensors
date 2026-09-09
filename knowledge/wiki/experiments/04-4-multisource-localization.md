# Multisource Localization — Maintained Indoor Reference

## Decision and historical comparison

The SDK maintains one unknown-count multisource method: WPE plus nonnegative group-sparse covariance. It uses only microphone mixtures and geometry, with no tracking, source separation, truth access, known-count input or two-source cap. Stereo and other planar sample rates retain their single-event path.

The completed selection campaign compared PyRoom MUSIC/SRP, ODAS, frequency-local counting, covariance MUSIC, AIC, spectral weighting, DP-RTF, weighted-histogram SRP and several dereverberation/selection corrections. Initial broad-domain gates failed. A bounded direct-path MUSIC reference was integrated temporarily; later indoor confirmation justified its replacement by the current WPE/group-sparse method. Longer history alone and the discarded preprocessing variants did not establish indoor robustness.

Candidate executors, native builds, sweeps and phase-only tests were removed after selection. Their source remains in Git at `1bb4eba`. Historical reports, including failures, are preserved locally in `evidence/qualification/multisource/reports/`; evaluated protocols and asset identities are in the sibling `protocols/` directory. These records do not imply that the retired campaign is a maintained reproduction tool.

The cleanup preserves all selected numerical settings and event semantics. Solver correctness, angular selection, optional dependencies, common consumers and reset behavior remain tested directly against the runtime. Historical measurements below describe the original confirmation, not a newly expanded qualification.

## Confirmed indoor improvement and maintained integration

**GO for the bounded simulated indoor, relatively stable-source capability.** The revision frozen at `40ed585` passes all 24 geometry/condition quality gates on the second independent confirmation. It is integrated through `MaintainedEventLocalizer`. This completes the requested indoor-improvement intervention; it does not complete the original broad 04.4 domain, physical qualification or rapid-response qualification. 07.2 was not started.

### Independent quality and remaining speech errors

`indoor-confirmation-v2-a.json` and `indoor-confirmation-v2-b.json` each use 12 episodes per content/geometry. Together they contain 24 per family/geometry, 5,184 paired cases and 10,368 estimator calls. Counts 0/1/2 and all six acoustic variations of an episode stay in its block; candidates see the identical current mixture and their specified past context. The 16 dev-clean speakers are disjoint from every consumed partition. Across the 24 geometry/condition groups, precision is 98.2–100%, recall 96.8–99.5%, exact count 95.8–99.5%, both-source localization without extras 87.5–98.6%, and angular p95 1.30–5.53°. Each group pools the three equally represented content families; these are empirical results from finite simulations, not population guarantees or per-family passes.

Both sources localized without extras, all three content families:

| Geometry | RT60 .2 / 0 dB | .2 / 3 dB | .2 / 6 dB | .3 / 0 dB | .3 / 3 dB | .3 / 6 dB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Triangle | 93.1% | 97.2% | 95.8% | 91.7% | 93.1% | 93.1% |
| Square | 98.6% | 95.8% | 93.1% | 97.2% | 94.4% | 91.7% |
| Raised | 95.8% | 91.7% | 87.5% | 91.7% | 91.7% | 87.5% |
| Tetrahedral | 95.8% | 97.2% | 95.8% | 93.1% | 95.8% | 94.4% |

At target RT60 0.3 s, 6 dB imbalance, 70° separation, 20 dB SNR and 1.5 m:

| Geometry | MUSIC clean pairs | Maintained clean pairs | Speech clean pairs: before → after | Weak speech recovered: before → after |
| --- | ---: | ---: | ---: | ---: |
| Triangle | 51.4% | 93.1% | 10/24 → 19/24 | 13/24 → 19/24 |
| Square | 58.3% | 91.7% | 14/24 → 18/24 | 19/24 → 18/24 |
| Raised | 33.3% | 87.5% | 2/24 → 16/24 | 6/24 → 17/24 |
| Tetrahedral | 13.9% | 94.4% | 1/24 → 20/24 | 2/24 → 21/24 |

Weak speech remains a material limitation: 3–7 of 24 weak speakers are missed in this condition, and 4–8 pairs have a miss or extra. Square weak-source recall falls by one episode even though its clean-pair reliability improves. The pooled qualification must not be presented as ≥80% clean-pair qualification for weak speech on every geometry. Stationary overlapping and disjoint-band non-speech provide an independently measured part of the improvement; this is not a speech-only method.

Acoustic measurements expose the renderer approximation. Target RT60 0.2 s produces extrapolated Schroeder T20 of 0.121–0.159 s and direct/reflected energy ratios of +2.07 to +6.29 dB. Target 0.3 s produces 0.223–0.279 s and −2.11 to +1.84 dB. These empty uniform shoeboxes are useful controlled indoor simulations, not measured rooms or an assertion that the target equals actual decay.

### Memory, response and computation

The maintained path uses 750 ms of past mixture. A new/reset stream warms up for that duration; after background has filled the buffer, source onset does not wait another fixed 750 ms. Each invocation refits the supplied past window without accumulating overlapping samples or persistent source identities. Stereo and other planar sample rates still request 250 ms and retain their previous temporal semantics.

Two independent diagnostic blocks test 864 transitions at 100 ms updates, using room tails, 6 dB weak sources, speech/non-speech, 0↔1↔2, 0↔2 and same-count direction replacement. A response requires two consecutive correctly localized event sets and includes the current call's compute time. The speech probe repeats an asset-only selected one-second excerpt; it is a controlled transition diagnostic, not natural conversational turn-taking.

| Change | Response p95 across the four geometries | Important observed limit |
| --- | ---: | --- |
| 0 → 1 | 297–464 ms | Maximum 644 ms |
| 1 → 2 | 934–1,322 ms | Maximum 1,490 ms |
| 2 → 1, weak source disappears | 919–982 ms for resolved cases | One tetrahedral speech change lacks a response within 1.5 s; 23/24 resolve |
| 0 → 2 | 506–952 ms | Maximum 1,524 ms |
| 1/2 → 0 | About 400 ms | Includes activity release and the second correct update |
| One-source direction replacement | 921–1,012 ms | Maximum 1,355 ms |

The original response p95 ≤350 ms / maximum ≤500 ms reference is **not passed**. The user-approved tradeoff supports waiting for sustained acoustic cues, with roughly one to one-and-a-half seconds sometimes needed to recognize a weak addition or change. It does not establish rapid robot/source motion or brief-event performance, and the unresolved weak-source removal remains visible.

Separate composed timing after 20 warmups and 200 measured calls, on one CPU thread per numerical library:

| Geometry | MUSIC compute p95 | Maintained compute p95 |
| --- | ---: | ---: |
| Triangle | 3.6 ms | 20.6 ms |
| Square | 3.5 ms | 28.9 ms |
| Raised | 40.8 ms | 67.8 ms |
| Tetrahedral | 33.0 ms | 51.8 ms |

The new path exceeds the 50 ms compute reference in 3D. A 100 ms update period is the measured practical starting point for one array; the consumer still processes the cadence supplied by the application and does not silently throttle. No million-environment or CUDA-native audio throughput claim follows. The GPU Lab smoke measures about 77 ms per warm update for its two scalar square/tetrahedral environments, separately from its empty-entity lifecycle benchmark.

Silence produces zero events. Each geometry also produces zero false-event windows in 200 white and 200 isotropic diffuse-noise windows, at RMS 0.0001, 0.003 and 0.03 across both blocks. These direct-localizer checks do not depend on an activity gate suppressing the noise. The empirical ≤1% reference passes; finite samples do not certify a universal false-alarm probability.

### Regressions and domain boundary

The original direct-path criteria remain unchanged in `indoor-direct-regression.json`. Nominal direct-path quality passes for every geometry. The broader original operational group passes for raised/tetrahedral, but triangle/square now fail its ≥80% exact pair-count criterion when isolated 10 dB imbalance and 5 dB SNR cases are included. This is an explicit regression of the maintained path, not a retained general direct-path GO. The old numerical MUSIC baseline is available in Git history at `1bb4eba`; the SDK has one maintained multisource path and no benchmark-condition selector or ensemble.

The selected threshold's consumed development controls (`indoor-development-limits.json`) retain the requested harder conditions. Clean pairs for triangle/square/raised/tetrahedral are: RT60 0.5 s, 83.3/100/95.8/95.8%; SNR 10 dB with RT60 0.3 s, 87.5/100/87.5/87.5%; 55° separation, 100/100/100/95.8%; 45°, 100/100/95.8/91.7%. The cumulative RT60 0.3 s / 45° / 6 dB / 10 dB condition falls to 70.8/79.2/87.5/87.5%, failing the planar pair criteria. Favorable development controls do not extend independent qualification. Coherent sources, near-coincident bearings, arbitrary microphone layouts, physical recordings and continuously moving geometry remain unqualified.

### Integration and evidence

The maintained computation is implemented directly in the optional SDK, with NumPy/SciPy/PyRoom and NARA-WPE 0.0.11. The existing `room` extra supplies WPE; Kit bundles its used numerical path and Click with their original licenses. NARA's unused CLI/test dependencies are not required by the bundled numerical path. Public imports remain lazy, existing schemas are unchanged, event confidence remains unavailable, and no source count or truth reaches perception.

Core/Isaac, recording/dataset, Kit event history, causal availability, stereo and reset checks pass. The actual RTX 4090 Lab smoke verifies planar/3D events, masks, capacities, scalar parity and partial reset (`build/validation/isaac_audio_sensors/indoor_multisource_lab_smoke_v2.json`). Its initial attempt stopped at missing runtime Auditok; rerunning with isolated locked Kit dependencies passes without modifying NVIDIA's installation. Host `make check` passes 638 unit/contract, 322 integration and 58 release tests; optional audio and source/wheel/Kit artifact audits pass. Source wheels are built from the sdist to exclude stale removed modules. None of these checks starts 07.2 or validates physical sensing.

Preserved ignored reports under `evidence/qualification/multisource/reports/`: `indoor-confirmation-v2-a.json`, `indoor-confirmation-v2-b.json`, `indoor-confirmation-v2-diagnostics-a.json`, `indoor-confirmation-v2-diagnostics-b.json`, `indoor-confirmed-summary.json`, `indoor-runtime-timing.json`, `indoor-direct-regression.json`, and `indoor-development-limits.json`. Earlier failed confirmations, development reports and protected raw material remain preserved.

## Pre-07.2 Motion Comparison — 2026-09-09

This bounded comparison follows the [[decisions/continuous-acoustic-clock|continuous propagation correction]]. It does not replace the historical indoor confirmation above. All candidates receive the same corrected public `AnalyticAcoustics` microphone samples; source count, positions, trajectories, and schedules are used only for scoring.

The four passing-source cases use 16 kHz square/tetrahedral arrays, broadband noise or an existing LibriSpeech excerpt, a four-second straight trajectory from `(6, 3, 0)` at `(-3, 0, 0)` m/s, and a stationary receiver. Captures advance by 100 ms. Evaluation starts after one second. The baseline keeps 750 ms of past audio. The two recent-spatial candidates retain batch WPE on that history but pass only its latest 250 or 400 ms to the existing group-sparse selector. The online candidate uses existing NARA-WPE `OnlineWPE` with six taps, delay two, alpha 0.98, and the same selector over 250 ms. SRP is a declared single-direction control; its fixed capacity is never chosen from the true source count.

The angular reference is the source's retarded emission position at the receiving array center. Apparent estimator age is obtained by inverting the known straight trajectory from the estimated bearing, after accounting for physical travel time. This age includes the observed audio interval and estimator memory; it is not the earlier two-consecutive-event transition response metric, and does not include a full live scheduler/compute delay.

| Candidate | Pass angular p95, range across four cases | Apparent age p95 | Indoor exact cases / 72 | Missed / extra indoor directions |
| --- | ---: | ---: | ---: | ---: |
| Maintained batch WPE + group-sparse | 21.9–23.8° | 448–593 ms | 68 | 3 / 2 |
| Same WPE, latest 250 ms spatial evidence | 7.3–8.5° | 148–181 ms | 46 | 17 / 21 |
| Same WPE, latest 400 ms spatial evidence | 11.5–12.3° | 225–314 ms | 56 | 14 / 9 |
| Online NARA-WPE + existing selector | 8.1–8.6° | 156–204 ms | 25 | 17 / 61 |
| SRP, single-direction control | 7.4–7.6° | 156–178 ms | 40 | 32 / 0 |

All candidates return at least one direction in every evaluated pass window. Extra-direction fractions across the four cases are 0–6.5% for the baseline, 0–3.2% for each recent-spatial candidate, and zero for online WPE/SRP. The apparent age is not evidence that online processing is computationally cheaper; its recorded localizer timing excludes online WPE preprocessing.

The paired stationary set contains square/tetrahedral arrays, nominal RT60 0.2/0.3 s, 0/6 dB source imbalance, 0/1/2 sources, and three content conditions: speech, overlapping broadband signals, and disjoint frequency bands. Non-silent cases have 20 dB SNR; zero-source cases contain noise. The room is a uniform 6×5×3 m shoebox with order ten. Exact success requires the correct count and every matched direction within the existing 20° tolerance; unmatched directions count as misses/extras. These 72 cases probe preservation, not a new independent qualification or every historical gate. Exact silence remains covered by maintained tests.

**Decision: retain the existing localizer.** No tested candidate simultaneously preserves its indoor behavior and meets the nominal moving-source p95 ≤10° goal. The maintained estimator also exceeds 350 ms in apparent age, before a full response test could pass. No sample-rate increase, estimator mode split, oracle source count, or track ID was introduced. Joint fast-motion/multisource qualification remains open, including moving mixtures, difficult reverberant passes, rotation, and physical audio.

The local numerical report is `build/validation/isaac_audio_sensors/continuity_doa_comparison.json`. It contains metrics only; no demonstration media or ONR material was produced. The comparison does not start 07.2.
