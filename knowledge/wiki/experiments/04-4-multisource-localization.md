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

## Motion/Indoor Closeout — 2026-09-09

**NO-GO for replacing the maintained localizer. The DOA motion/indoor tradeoff remains open.** The delivered SDK retains the original 750 ms WPE/group-sparse implementation byte-for-byte. The accepted changes concern rotating acoustic geometry and equivalent constant-velocity arrival computation; see [[decisions/continuous-acoustic-clock|Continuous Acoustic Clock]]. No 07.2, physical campaign, demonstration scene, video or ONR material was produced.

### Candidate comparison and rejection

The original four passes and 72 stationary controls reproduce the preceding comparison, including 68 exact baseline cases. Exponentially weighted spatial evidence with a 250 ms time constant keeps 68 exact cases but changes misses/extras from 3/2 to 2/3; 150 ms weighting yields 64 exact cases. A composed candidate preserves the long-window event evidence and accepts 250 ms directions only when counts agree and one-to-one displacement is below 35°. It keeps 68/72 exact cases and reduces the original pass angular p95 to 7.3–14.2°, with apparent age p95 148–296 ms. This is a development benefit, not joint qualification.

A second 144-case, four-geometry screen produces 142 exact cases for both the baseline and this composition; weighted evidence gives 136 and a PyRoom SRP refinement with acoustically inferred count gives 139. The established SRP component is therefore rejected at indoor screening. Historical ODAS SSL/native-lifetime controls already fail nominal count/precision gates; no new native tracking qualification or dependency was claimed or added.

On 864 different stationary cases the equal-count composition and baseline both achieve 820 exact cases, with one square loss and one raised-array gain. Moving tests then reveal that count disagreement prevents many useful updates. Allowing one-to-one updates of individual supported directions improves direct-motion development p95: square broadband/speech 18.4/21.7° → 6.5/9.1°, tetrahedral 17.6/24.6° → 6.2/14.4°. Unmatched directions retain long-window acoustic evidence; directions are never predicted from source trajectories or robot pose.

The independent stationary confirmation of that 35° partial refinement exposes weak-speech regressions: triangle loses three exact cases and raised loses two, concentrated in a few speech episodes. Tightening multiple-direction association to 20° restores the triangle cases and reduces the raised loss to one, but this is now a development control on consumed confirmation inputs. It does not create a new independent GO.

Final conservative control, 216 stationary cases per geometry:

| Geometry | Baseline exact cases | Candidate exact cases | Angular p95: baseline → candidate |
| --- | ---: | ---: | ---: |
| Triangle | 199 | 199 | 5.3° → 8.0° |
| Square | 209 | 209 | 2.5° → 4.2° |
| Raised | 210 | 209 | 6.7° → 7.7° |
| Tetrahedral | 199 | 199 | 5.1° → 6.9° |

A paired bootstrap groups all conditions/counts within each content/episode block (18 blocks per geometry). Exact-case change is zero for triangle/square/tetrahedral; raised is −0.46 percentage points with a 95% bootstrap interval of approximately −1.39 to 0. This stationary preservation is insufficient to close the moving problem. Speech errors already present in the baseline remain visible; these new simulations do not replace the historical 24-group qualification.

### Ordinary moving pairs remain inadequate

The decisive controls use four-second received audio, two distinct speech excerpts, 6 dB emission imbalance, nominal RT60 0.3 s and 20 dB global-mixture SNR in a uniform 6×5×3 m shoebox with image order ten. One source passes at 1 m/s; the other remains spatially separated. The combined case also translates the receiver at 0.25 m/s and rotates it at 0.7 rad/s. The localizer receives only the causal mixture and microphone geometry. Source RMS normalization defines emission levels; received audio is not repaired or renormalized. Room target RT60 is not a measured decay claim.

Each geometry contributes two variants of one episode and 66 scored updates. These are bounded counterexamples, not 66 independent trials or population success rates. Exact success requires the correct count and every one-to-one matched direction within 20°. Angular p95 below includes assigned errors above that gate; misses and extra directions are reported separately in the numerical report.

| Geometry | Baseline exact updates | Conservative candidate | Angular p95: baseline → candidate |
| --- | ---: | ---: | ---: |
| Triangle | 26/66 | 26/66 | 32.7° → 31.4° |
| Square | 42/66 | 40/66 | 26.4° → 27.8° |
| Raised | 19/66 | 18/66 | 76.1° → 76.1° |
| Tetrahedral | 28/66 | 28/66 | 58.1° → 62.3° |

The long-window count remains correct in only 53.0–89.4% of these updates. Reusing that count cannot resolve its motion errors, and recent directional refinement adds no dependable joint benefit. A supplementary cue audit retains windows where both recent 250 ms speech excerpts have at least 10% of their own nominal RMS; the combined-motion failure remains. Pauses alone do not explain the result. Separate crossing controls include bearings closer than the maintained separation capability and remain limits rather than the reason for rejection.

Post-warm-up transition controls require two consecutive correct event sets and include the final call's complete localizer computation. Across four geometries, 1→2 response p95 is about 748 ms for the baseline and 784 ms for the conservative candidate. Three of four 2→1 changes resolve before the next change, at about 717/757 ms p95; one remains unresolved. Neither resolves the final 1→0 transition before the short remaining 600 ms interval ends. These are localizer-only schedule-relative diagnostics, not activity-detector or physical transport latency measurements. Level-change controls and harder nominal RT60 0.5 s / 10 dB SNR controls also remain numerical limits, not expanded qualification.

### Maintained result and reproducible assessment

The propagation correction passes reception-time rotating microphone offsets, retarded source orientation, shortest-arc interpolation, block partition equivalence, acoustic tails and the near-sonic arrival equation. When future poses are absent, angular extrapolation remains an explicit approximation. Accepted host checks cover the unchanged DOA consumers; supported Isaac Sim/Lab/Kit checks run on RTX 4090. The CPU localizer and empty-entity CUDA lifecycle measurements remain different workloads.

The historical numerical evaluator exercised stationary/moving conditions with paired, read-only mixtures and private scoring truth. Its retired source is recoverable from Git commit `7ff38dc`; 07.3 removes the campaign CLI and candidate loaders. Utterance partitions were disjoint within this comparison, not a new physical or population qualification.

Local closeout: `build/validation/isaac_audio_sensors/motion_closeout.json`. Supporting reports include `motion_final_decision.json`, `motion_stationary_refinement_control.json`, `motion_final_direct_confirmation.json`, `motion_transition_controls.json`, and `motion_stress_controls.json`. Earlier candidate reports retain their at-run column names; their `maintained` column can refer to a rejected candidate temporarily under evaluation, not the delivered SDK. Rejected prototypes were removed in 07.3; the decisive findings remain here.

The next useful investigation must jointly estimate changing event count and direction from temporal acoustic evidence. The present results do not justify choosing a particular tracker or library, predicting missing directions, or advancing 07.2. Signal-level movement corrections are complete within their documented approximations; responsive indoor multisource perception is not complete.

## Joint Count/Direction Investigation — 2026-09-09

**NO-GO for replacing the maintained localizer.** Causal temporal evidence improves selected cases, but none of the evaluated candidates provides dependable joint count/direction estimates during ordinary combined motion. The SDK retains its original WPE/group-sparse algorithm and propagation. The delivered addition is an optional streaming injection boundary and a reusable received-audio evaluator, not a newly qualified perceptual capability. No 07.2, demonstration scene, video or ONR production is included.

### Evaluation boundary and interpretation

The historical joint-motion evaluator fed consecutive 100 ms blocks through the common `AudioPerceptionPipeline`, including Auditok at −60 dBFS, warm-up, silence and tails. Streaming candidates consume each new block once; the maintained method retains its existing causal buffer and activity gate. A separate localizer-only option bypasses Auditok for diagnosis. Full pipeline compute and simulated processing backlog are measured; source rendering time is excluded. These CPU NumPy/SciPy and native-C workloads are separate from GPU consumer validation.

The evaluator alone obtains total per-source received power from the same private render used to assemble public PCM. A matching order-zero room render supplies direct-path power; it does not replace or renormalize the mixture. The original numerical evaluator and its default speech construction remain available for historical comparisons. The original four-geometry moving-pair baseline reproduces exactly: triangle/square/raised/tetrahedral have 26/42/19/28 joint successes out of 66 updates each.

The new reference compares each source's 100 ms received energy with the independently generated noise power. Total energy above that floor denotes received contribution; direct energy above it permits a direction target at retarded emission time in current array coordinates. A received tail with insufficient direct energy is explicitly unresolved, not an extra directional source or demonstrated absence. This is an audibility proxy, not a psychophysical threshold or proof of separability under masking. The default 0 dB ratio is accompanied by −3/+3 dB sensitivity. Those changes do not alter the rejection decision. Unresolved windows remain in the report with directions, misses, extras and excess predictions over received contributors; they are excluded only from the fully resolved joint-success denominator. Unavailable/uncertain output cannot earn a zero-source success.

Natural-speech v2 selects distinct utterances without looping short excerpts, normalizes emission RMS once and preserves natural received level changes. Existing development assets and one episode per geometry/content are used; these are paired counterexamples, not independent population qualification. Old alternating utterance partitions are not speaker-disjoint holdouts. Cache names separate protocol, acoustic parameters, partition and asset content to prevent accidental reuse across inputs. Private source arrays, schedules and scoring labels never cross the estimator boundary.

### Candidate evidence

The temporal sparse candidate applies the maintained batch WPE to at most 750 ms, estimates spatial evidence from the latest 250 or 400 ms, and updates a spatial histogram with a 150 ms time constant. Current angular support is required before publishing a direction; previous count is never authoritative. Optional receiver orientation transports stored angular evidence only. Development controls vary time constants, rejection strength and history; lowering rejection recovers weak directions but introduces substantial extras, particularly in 3D.

The DP-RTF trial independently implements persistent cross-relation estimation, spectral smoothing and exponentiated-gradient directional mixture weights from [Li et al., JSTSP 2019](https://arxiv.org/abs/1809.10936), checked against the [authors' MATLAB reference](https://github.com/Audio-WestlakeU/OnlineSSL_DPRTF_EG). Loaded normal equations replace numerically unstable inverse-form RLS; array-derived templates and spherical smoothing are adaptations. Unlike the previous batch trial, history and directional weights persist across blocks. Minimum-statistics speech selection loses stationary non-speech; disabling it restores features but does not recover adequate joint reliability. No complete VEM tracker reproduction is claimed, and the MATLAB reference has no explicit redistribution license in the checked tree. Its code is not distributed in the SDK.

[ODAS](https://github.com/introlab/odas) is built in isolation and tested with continuous STFT, SSL and dynamic Kalman SST, rather than the previous SSL-only binding. Its standard four-track capacity is never set from truth. Published tracks require native activity plus current spatial support; predictions alone are not emitted. A mobility/no-source-lifetime control increases Kalman process noise and shortens inactive lifetime. Both configurations miss too many received sources. The MIT dependency is not added to the product; the isolated build preserves per-plan FFT destruction while avoiding the previously identified global FFTW cleanup lifetime defect.

The nominal moving comparison uses distinct speech, 6 dB emission imbalance, 20 dB global-mixture SNR, nominal RT60 0.3 s, a source moving at 1 m/s, receiver translation at 0.25 m/s and rotation at 0.7 rad/s. Other sources remain separated. The following results exclude the common first 750 ms so faster startup cannot account for the comparison. Joint success requires the correct directional count and every one-to-one direction within 20°.

| Geometry | Maintained joint success | Temporal 250 ms | Temporal 400 ms | Online DP-RTF | ODAS SSL + SST |
| --- | ---: | ---: | ---: | ---: | ---: |
| Triangle | 23.1% | 26.9% | 42.3% | 19.2% | 7.7% |
| Square | 33.3% | 70.0% | 76.7% | 10.0% | 0.0% |
| Raised | 13.8% | 13.8% | 17.2% | 0.0% | 3.4% |
| Tetrahedral | 37.9% | 41.4% | 41.4% | 10.3% | 0.0% |

Each row is one episode, with 26–30 fully resolvable post-warm-up updates; percentages are not independent-trial rates. The 400 ms candidate improves square performance substantially, but count accuracy remains 37.9–76.7% across geometries and angular p95 ranges from 14.0° to 116.0°. It cannot be promoted on the strength of the square result. Exact, missing, noisy (5° standard deviation), 100 ms delayed, and interrupted/reacquired receiver orientation do not remove the failure.

Thirty-six natural-speech/non-speech stationary controls cover all four geometries and 0/1/2 sources at the same nominal room/SNR/imbalance. The 250 ms temporal candidate loses approximately nine percentage points of post-warm-up square speech joint success and some triangle/tetrahedral broadband updates. The 400 ms variant preserves or improves these particular joint-success controls, but that does not establish the requested three-point non-inferiority margin for precision, recall and count. Sparse development blocks cannot support that statistical claim. Both temporal variants fail nominal movement before independent confirmation; DP-RTF and ODAS also fail stationary multisource controls. No two fresh confirmation blocks were consumed.

The received-reference transition probe retains two consecutive correct updates and unresolved responses. For square speech, the 400 ms candidate changes onset/addition/removal/final-zero response from approximately 631/527/330/826 ms to 212/315/316/515 ms. Tetrahedral responses remain mixed. These are two controlled episodes using the earlier speech construction, not natural-speech p95 qualification. The 350–500 ms references are not used as a rigid veto: the rejection is driven by incorrect or missing joint sets during normal motion, not an isolated latency exceedance or an extreme condition. No broad three-source/coincident-source qualification was attempted after this failure.

### Bounded real-data comparison

The authors' reference includes `LOCATA-dev-task6-rec3.wav`, four published robot-array channels, microphone coordinates and 120 Hz azimuth/VAD annotations. The probe processes the complete 65.6 s covered by full 100 ms blocks at native 16 kHz, with no gain correction or receiver-motion input. The documented reference coordinate conversion is applied only for scoring. Official Zenodo access timed out; this author-supplied subset enables the bounded check. [LOCATA task 6](https://www.locata.lms.tf.fau.de/tasks/) contains moving talkers and a moving array.

Joint azimuth/count success is 11.4% for the maintained algorithm, 12.7% for temporal 250 ms, 15.1% for temporal 400 ms, 15.1% for DP-RTF and 8.7% for ODAS. ODAS precision is 98.6% but recall only 34.7%; the temporal variants retain approximately 51% precision with many extra directions. These results use supplied VAD, not the synthetic received-energy reference, and provide no elevation truth. This single nearly planar robot-array excerpt is not physical qualification of the SDK's simulated layouts or a robot deployment.

### Delivered result and next step

The maintained selection was unchanged. Subphase 07.3 removes the unshipped streaming interface, explicit receiver-orientation injection, candidate loaders and campaign executables. Their source remains in Git commit `7ff38dc`; no calibrated confidence estimator or reliable moving-source count was delivered.

Numerical reports remain under `evidence/qualification/multisource/reports/joint-motion-*.json`. The 36 stationary received-PCM controls used by the maintained scalar/CUDA comparison now live in `local/lab/received_stationary/`. Development prototypes, isolated research dependencies and superseded caches were removed. This retains the active regression role without maintaining the abandoned research harness.

Historical validation passed 641 unit/contract, 335 integration and 58 release tests, including received-reference/transition checks and streaming reset/inactive/recording tests. The optional-audio smoke and all three supported Isaac Sim/Lab/Kit smokes pass on RTX 4090. Forty-eight focused propagation/rotation/consumer regressions pass; propagation, motion and maintained localization source files have no diff from `0d44f0c`. GPU lifecycle/projection checks do not establish perceptual accuracy or CPU localizer throughput.

The next experiment should target the acoustic front end on these exact weak-speech/combined-motion counterexamples: test whether causal multichannel dereverberation or time-frequency source discrimination improves current directional evidence and weak-source recall without increasing extras. Compare the resulting event sets before adding further track persistence. The present evidence does not justify another direction smoother or a library selection based only on responsiveness.

### Historical project disposition — paused, not solved

On 2026-09-09 the user chose to close this iteration for now and retain the current capability. Joint moving-source count/direction reliability remains an open limitation, including ordinary motion and source transitions; it is not confined to weak speech with simultaneous robot/source motion. The next acoustic-front-end experiment above is deferred.

At that point, the pause lifted the earlier project-priority hold on 07.2 while preserving its bounded reference and validation requirements. It did not qualify Video 03: the separate production subsequently documented in [[topics/onr-video-production|ONR Video Production]] owns its scene-specific feasibility and media outcome. No 07.2 implementation, media, scene or ONR production was part of this investigation closeout.

### Project disposition at reopening — before 07.2

Later on 2026-09-09, following the occlusion/GUI audit, the user requested that joint count and direction over time be addressed before 07.2 for the SDK's long-term practical usefulness. This supersedes the pause as a sequencing decision; candidate failures and the bounded reference results remain unchanged. [[implementation_phases/04-observed-direction-estimation#Pre-07.2 Follow-up — Joint Count and Direction over Time|Phase 04]] owns the renewed outcome, without prescribing a library or treating display smoothing as perception. [[status|Current Status]] also records the separate confidence and live occlusion corrections. No further acoustic experiment or new qualification has been executed by this documentation update.

## Pre-07.2 Acoustic Front-End Evaluation

**Experimental outcome on 2026-09-09: NO-GO for replacing the maintained localizer; the temporal objective remains open.** The initial 07.2 sequencing block is superseded by the final user disposition below. This follow-up executes the previously proposed acoustic-front-end comparison. It delivers confidence/occlusion corrections separately, but finds no frontend that supports ordinary indoor joint count/direction reliably across the maintained layouts. This rejects the tested implementations, not the feasibility of robot audition or OnlineWPE in general. The tested domain and failures are unchanged; there is no automatic narrowing to whichever array or signal happened to improve.

### Domain and method

The requested domain remains triangle, square, raised and tetrahedral arrays at 16 kHz, 0–2 separable speech/non-speech events, nominal RT60 0.2–0.3 s, 20 dB global-mixture SNR, up to 6 dB emission imbalance and at least 70° separation. Motion references remain 1 m/s source speed, 0.25 m/s receiver translation and 0.7 rad/s rotation. Two events are a qualification domain, not an estimator count cap. Initial admission references are 90% complete sets within 20°, 95% precision/recall, at most 1% noise false events, approximately 500 ms p95 reaction including computation/backlog, and a three-point static non-inferiority margin. None alone is a sufficient certificate.

Development reuses the consumed natural-speech combined-motion inputs above and 36 stationary controls. Twenty-four direct broadband controls add three single-source directions, all-channel occlusion, partial-channel occlusion and occlusion of only one source in a pair, with obstacle removal. The production renderer generates clear/blocked PCM with identical noise; the evaluator selects receive windows at 1–3 s with 20 dB path loss. Direct scoring now uses attenuated received paths, including when private `direct_premix` precedes attenuation. Clear/recovered PCM equality, unchanged noise and received-power scaling are regression-tested. These controls isolate the existing window-local direct-loss model; they do not model continuously moving edges or diffraction.

Candidates consume received PCM through the existing streaming interface. Source count, positions, identities and separate contributions remain evaluator-only. Persistent [NARA OnlineWPE](https://github.com/fgnt/nara_wpe/blob/master/nara_wpe/wpe.py) uses six taps, delay two, forgetting factor 0.98, a 256-sample STFT and 64-sample hop, causal overlap-add and initially 400 ms spatial context. It advances through inactivity. A chunking check produces identical history for 50 and 100 ms ingestion: 16,000 input samples yield 15,808 processed samples, with 192 samples buffered (12 ms). Reset/new-stream parity passes. This is sample-handling evidence, not physical dereverberation qualification.

The separate spatial candidate normalizes cross-channel covariance by measured channel powers and weights frequency bins by observed coherence, retaining observed-energy admission. A local time-frequency ablation uses three-frame coherence/energy support. Both use the existing group-sparse fit; coefficients remain diagnostic strengths, confidence remains unavailable. OnlineWPE and normalization are combined only after separate trials show complementary isolated gains. Shorter/longer spatial histories, a lower rejection threshold, and normalization after the maintained batch WPE isolate history and dereverberation confounding. No angular smoothing, rejected DP-RTF/ODAS rerun, learned model, source-truth input, scene-selected mode or new product dependency is introduced.

### Joint moving-speech results

All rows below use identical received episodes and exclude the common first 750 ms. Each geometry has only one consumed episode, with 26–30 fully resolvable updates; these correlated updates do not estimate population reliability. A correct set has the exact count and every one-to-one direction within 20°.

| Geometry | Maintained | OnlineWPE, 400 ms | Normalized, 400 ms | Combined |
| --- | ---: | ---: | ---: | ---: |
| Triangle | 23.1% | 19.2% | 34.6% | 42.3% |
| Square | 33.3% | 60.0% | 6.7% | 6.7% |
| Raised | 13.8% | 17.2% | 6.9% | 10.3% |
| Tetrahedral | 37.9% | 10.3% | 20.7% | 31.0% |

The square OnlineWPE improvement still has only 63.3% exact count, 87.9% precision and 89.5% recall. Normalization raises square precision to 90.5% but recall falls to 33.3%: cleaner individual bearings conceal missing events. In the raised case the combined candidate has 81.5% precision, 45.8% recall, 83.6° angular p95 and a continuous 1.5 s incorrect-set sequence. No post-warm-up localization abstention in these four representative methods excuses those errors: output is available but often wrong or incomplete. Per-update reports retain unresolved received activity separately from resolved directional targets.

Matched-history OnlineWPE at 750 ms reaches only 10.3–26.9% across geometries. Normalization after maintained batch WPE reaches 0–24.1% at 750 ms and 6.7–30.8% at 400 ms. Local time-frequency weighting also fails. Lower rejection can recover square recall but produces many extras elsewhere; the sensitive normalized triangle trial has 48 extras and 0% complete sets. Even selecting the best development variant separately for each geometry would reach no more than 63.3%, and such scene/geometry-specific promotion is not adopted. Changing the received-energy audibility reference by ±3 dB leaves rejection unchanged.

### Preservation and occlusion counterexamples

The representative methods are compared on the same 36 consumed stationary episodes. Natural-speech pair success for maintained/online/normalized/combined is 6.9/6.9/13.8/17.2% for triangle, 81.2/78.1/15.6/31.2% for square, 20.0/6.7/3.3/10.0% for raised and 70.0/16.7/46.7/43.3% for tetrahedral. These streamwise controls are not the historical stable-source confirmation protocol and do not retroactively relabel its 24 qualified groups.

The disjoint-band stationary pair is an especially clear preservation failure:

| Geometry | Maintained | OnlineWPE | Normalized | Combined |
| --- | ---: | ---: | ---: | ---: |
| Triangle | 100% | 0% | 9.1% | 0% |
| Square | 100% | 0% | 100% | 0% |
| Raised | 100% | 9.1% | 6.1% | 21.2% |
| Tetrahedral | 100% | 63.6% | 75.8% | 93.9% |

Across the three stationary noise controls per geometry, the maintained, normalized and combined methods produce no extras; OnlineWPE produces 12 triangle and four tetrahedral extras. These finite controls do not establish a population false-event rate or a statistical non-inferiority bound.

Conversely, normalized evidence directly helps unequal-channel controls. With two attenuated microphones, maintained versus normalized complete-set success is 42.4% versus 100% for square, 30.3% versus 97.0% for raised, and 27.3% versus 97.0% for tetrahedral; triangle is 100% for both. The clear frontal tetrahedral control changes from 0% to 100%. This supports the channel-amplitude hypothesis in these direct cases, but cannot justify integrating a method that loses ordinary indoor pairs. The band-limited control also differs from the earlier live white-noise frontal audit; success on one signal is not a contradiction or a general single-source qualification.

All-channel attenuation and removal remain perceptually imperfect despite correct received levels: representative complete-set results range from 42.4% to 78.8% across those episodes. Blocking only source zero in a pair preserves the other source's rendered contribution, but joint success remains 72.7–90.9%. Correct physics and level recovery therefore do not imply correct event recovery.

### Timing, unexecuted qualification and disposition

Reports retain exact count, matched precision/recall, complete sets, angular errors, unavailability, incorrect-set durations, localization interruptions, received transitions, missed responses, computation and accumulated backlog. In the moving screen, OnlineWPE computation p95 is approximately 14–64 ms per 100 ms update; this excludes rendering and is not reaction time. Natural speech produces missed received transitions, and no independent end-to-end p95 reaction qualification is claimed. Stationary and control timing runs overlapped, so their measurements do not establish realtime throughput. Rejection rests on joint quality and preservation failures, not the 500 ms reference alone.

The historical protocol separated development from two conditional fresh confirmation blocks with independent speakers, utterances, signal seeds and trajectories, 12 episodes per content/layout/block and paired episode uncertainty analysis. No confirmation assets were selected or consumed after the nominal screen failed. Intermediate/harder conditions, three sources, brief impulses, higher reverberation, full acoustic shadow and a new physical-data comparison were not expanded in this iteration. Sparse development episodes cannot establish confidence intervals for the requested domain. No independently qualified temporal operating domain is delivered.

Subphase 07.3 retains `local/pre72/summary.json` and the live occlusion evidence directories; it removes the frontend prototypes, screening scripts, redundant per-update reports and generated control caches. The summary and findings above preserve the tested methods, decisive regressions and reasons for rejection. `knowledge/raw/` and protected qualification evidence remain unchanged.

The maintained localizer and propagation source remain unchanged from `ba65cf3`. The separately completed confidence and native occlusion changes are owned by [[topics/public-contracts-and-recording|the observed contract]] and [[implementation_phases/r8-analytic-acoustics-backend|R8]]. Their host/runtime/package checks do not close this perceptual gate. The failed candidates do not authorize perceptual claims; the later user decision below separately governs 07.2 admission. Full GUI consolidation remains 07.3, advanced geometry remains 08 and realism distributions remain 09.

### Final User Disposition — Bounded 07.2 Admission

After reviewing these results, the user explicitly suspends this research iteration and authorizes: **07.2 is admitted on the current reference and within its verified domain; general temporal reliability remains unqualified.** The maintained localizer, numerical outcomes, counterexamples, unexecuted confirmation and limits are preserved. The candidates remain rejected; neither this decision nor subsequent scaling is evidence of perceptual improvement.

The unresolved temporal problem no longer generally blocks repository progression. [[implementation_phases/07-isaac-lab-observation-integration|07.2]] must preserve available perception, including delays, uncertainty and missing/extra events, without source truth or artificially perfect observations. Keep optimization proportional and allow a later localizer improvement. Follow with 07.3 and its planned GUI, then 08–09 geometry/realism; these do not automatically repair perceptual failures. Qualification remains required for declared capabilities and [[implementation_phases/10-end-to-end-validation-and-product-closeout|Phase 10]]. Reconsider temporal research against concrete robot behaviors requiring reliable dynamic multisource listening. This was a documentation-only admission; the subsequent 07.2 implementation and 07.3 cleanup are recorded in Phase 07.

## Subphase 07.3 — Maintained Regression Boundary

The retained comparison is `tools/validation/lab_perception.py`, consuming the same 36 stationary archives from `local/lab/received_stationary/`. It runs the unchanged scalar pipeline and CUDA path on identical PCM, preserving one-to-one direction matching, observed activity, missing/extra events and unavailable/diffuse-tail distinctions. Truth is used only by scoring. Count agreement remains at least 97%, activity agreement 100%, and direction-difference p95 at most 5 degrees; these are integration-preservation gates, not new acoustic qualification.

Rejected float32 WPE, short/online contexts, normalization, DP-RTF and ODAS remain documented failures, not selectable runtime modes. Existing propagation, rotating-arrival, occlusion and batch-independence regressions remain maintained because they protect delivered behavior. Future temporal research should begin with the counterexamples and measured limitations above rather than revive every previous executable.
