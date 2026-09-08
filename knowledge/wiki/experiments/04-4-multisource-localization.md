# Subphase 04.4 — Multisource Localization Qualification

## Objective and Status

**Partial implementation; NO-GO for production integration.** Candidate comparison and independent simulated evaluation are implemented. Neither combined role is admitted after checking the latest independent results against known-case regressions. Unknown-count zero/one/two-source localization remains the qualification objective. Two sources are a milestone, not an interface capacity. Physical multisource performance, persistent tracking, separated audio, and scalable Lab perception are outside this experiment. See [[implementation_phases/04-observed-direction-estimation|Phase 04]].

Baseline: `main` at `01eb888`, with no tracked user changes. Historical evidence and `knowledge/raw/` remain untouched. Candidate review below precedes implementation of the comparison.

## Candidate Review

| Candidate | Why evaluate | Count and integration cost |
| --- | --- | --- |
| PyRoom SRP spatial spectrum with calibrated peak rejection | Existing MIT-licensed optional stack; supports planar and spherical grids; low integration cost and a useful conventional baseline. | `num_src` is not an inferred count. Select local maxima from the complete observed spectrum, calibrating rejection and spatial suppression on development cases only. |
| PyRoom MUSIC with MDL model-order estimation | Established subspace alternative in the same maintained implementation, with potentially sharper separation than SRP. | Estimate covariance rank from mixture STFT using minimum description length before passing the inferred count to MUSIC. Requires fewer sources than microphones and enough snapshots; reverberation and colored noise can inflate rank. No earlier MUSIC qualification is claimed. |
| ODAS SSL with calibrated potential-source rejection | Existing native embedded-audition implementation, MIT license, spherical search and iterative correlation suppression. Tests whether an established native algorithm justifies its integration cost. | SSL emits a configured capacity of potential directions, not confirmed events. Evaluate SSL potential powers with mixture-only rejection, without using SST tracks or separation. Native FFTW/libconfig/audio build dependencies stay isolated. |

This is the initial shortlist, not an evaluation order or a prescribed winner. Prefer one implementation for both roles when it meets quality and cost requirements; retain distinct implementations only for demonstrated role-specific benefits.

ISSL was also reviewed: its official instructions require sequential SSNet and ASDNet training and an additional spatial-spectrum dataset, with PyTorch, apkit, and scikit-learn. It is not in the initial shortlist because this adds a training/data/geometry-validation obligation before any demonstrated advantage here. It remains a possible alternative if conventional candidates expose a concrete limitation it addresses. A paper's unknown-count claim alone does not establish suitability for arbitrary arrays or full 3D.

Primary references: [PyRoom DOA](https://pyroomacoustics.readthedocs.io/en/stable/pyroomacoustics.doa.doa.html), [PyRoom MUSIC source](https://github.com/LCAV/pyroomacoustics/blob/master/pyroomacoustics/doa/music.py), [ODAS paper](https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2022.854444/full), [ODAS SSL source](https://github.com/introlab/odas/blob/bcb845434495e293df3d48f1203b7a86e1852449/src/module/mod_ssl.c), [ISSL implementation](https://github.com/FYJNEVERFOLLOWS/ISSL). Current local PyRoom is 0.10.1; ODAS evaluation revision is `bcb845434495e293df3d48f1203b7a86e1852449`.

## Evaluation Design

The evaluator alone owns source signals, positions, schedules and received-level normalization. Each candidate receives only the final mixture, ordered valid-channel XYZ positions and sample rate. A fixed candidate capacity may bound compute but must not encode the case's true count; observations remain variable-length. The existing single-source perceiver is a regression reference, not a multisource candidate.

Start at 16 kHz with trailing 250 ms context and 50 ms updates. Include planar triangle/square and nonplanar layouts including the existing square-plus-raised-center test geometry. Evaluate independent speech and non-speech content, spectral overlap, silence, single controls, simultaneous pairs, onset/offset, near-coincident sources, unequal received levels, noise, reverberation and more-than-two-source diagnostics.

Separate development and final partitions by complete input asset and simulated episode/room/noise realization. No overlapping windows cross partitions. Report within-speaker scope when speech speakers are shared; do not claim speaker-independent generalization. Development diagnoses feasibility and fixes thresholds; final cases must remain unused until the operating criteria and selected settings are recorded.

Metrics use gated one-to-one matching: circular angular distance for planar azimuth, great-circle distance for 3D. Report count accuracy, false events, missed sources, precision/recall, matched error, and abstention separately, per geometry and acoustic condition. Empty predictions on active cases count as misses. Separately measure update cadence, audio context, compute and buffering, and response delay after event changes. Native startup cost must not be mislabeled as steady-state latency or omitted from end-to-end startup.

The nominal domain is only an initial feasibility milestone. Robust selection requires the difficult-condition results and a justified quality/latency/maintenance comparison. Numeric final gates were recorded after development and before opening the final partition; the earlier proposed thresholds are not treated as accepted requirements.

## Failure and Integration Policy

Integrate only qualified roles. A planar GO does not complete 04.4 or cancel 3D work. Diagnose failed roles and evaluate corrective changes or alternative candidates; after evaluation-informed changes, use fresh independent final cases. Distinguish measured NO-GO from missing data, runtime dependencies or untested conditions. Do not lower gates or narrow the objective after observing final results.

The minimal sequence-returning common boundary is designed after candidate evaluation. Reuse observation/frame schemas where sufficient; preserve per-event ambiguity, optional scores, causal context, deterministic ordering and stream resets. Keep global activity distinct from event scores and avoid persistent identities.

## Artifacts

Isolated working directory: `build/qualification/doa/04_4/`. Downloaded native code, dependencies, audio and generated outputs are local evaluation material, not package contents. These CPU algorithms do not support GPU execution; GPU-capable supported-runtime checks use the verified RTX 4090.

## Development Diagnostics and Corrective Trials

The first development pass exposed SRP sidelobe over-counting, MUSIC MDL under-counting at low SNR and inflated order in reverberation, and ODAS weak-source misses. The initial wall times included repeated grid-neighborhood construction and ODAS process startup, so they were not accepted as steady-state performance. A grid-coordinate ordering error in the first six-case sanity probe was corrected before the full comparison.

The next development pass caches spatial neighborhoods, compares frequency-normalized MUSIC, lowers trial rejection floors to permit threshold calibration, and normalizes received levels/SNR over the actual scored window. Earlier development reports are exploratory and superseded: their received-level normalization used a longer interval and did not establish the advertised instantaneous imbalance for speech.

An additional corrective candidate is admitted for development: broadband covariance pursuit with per-frequency nonnegative least-squares refitting using SciPy. Its specific purpose is to remove already-explained source contributions before selecting another direction, addressing SRP sidelobes without assuming a common source spectrum or MDL rank in reverberation. This is a custom experimental adapter around established numerical operations, not an existing qualified localizer or an exact implementation of CLEAN-SC. It must demonstrate a material benefit to justify maintenance. No production dependency is added. Relevant methodological context: [broadband deconvolution](https://arxiv.org/abs/2307.06181), [SciPy NNLS](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.nnls.html).

## Final Evaluation Protocol — Fixed Before Evaluation

Development covered 432 cases, with complete speech assets held apart from final evaluation. The corrective covariance adapter now jointly refits source powers and locally refines directions to reduce the first-peak bias measured in 3D. Its custom code is justified only provisionally by development improvements; final evidence still decides admission. ODAS now uses an isolated in-memory STFT+SSL binding, recreating STFT history for each causal window and caching only geometry-dependent SSL state. Planar projection takes the maximum potential power per hop to avoid counting mirror directions as separate events. No tracking/separation modules run.

`tools/qualification/doa_04_4/final_protocol.json` fixes settings and gates before generating or opening the `evaluation` partition. Final evaluation uses four independent repetitions of each count/content/condition/geometry combination (864 cases), plus explicit idle, capacity and transition diagnostics. Geometries include the triangle, square, raised-center and tetrahedron. Rank-3 pair separation is measured on the sphere, with both azimuth-tangent and elevation-tangent orientations in every acoustic condition; source directions themselves are randomized. This removes the orientation/condition coupling present in earlier exploratory cases.

- Nominal control: 70-degree separation, equal received levels, 20 dB mixture SNR, free field. Require precision at least 95%, recall and exact count accuracy at least 90%, and matched angular p95 at most 15 degrees for each geometry. Additionally require at least 90% exact count accuracy on two-source cases. Silence does not contribute true positives; zero/one/two count strata are also reported independently.
- Intended initial operational domain: nominal plus the combined 45-degree/6 dB imbalance/10 dB SNR/0.3 s target RT60 condition, 10 dB imbalance alone, and 5 dB SNR alone. Require precision at least 95%, recall and count accuracy at least 85%, angular p95 at most 15 degrees, and no constituent condition below 75% recall, separately per geometry. Two-source cases must independently reach at least 80% exact count accuracy in this domain. These are useful reliability targets for coarse robot direction cues, not estimates of the best attainable algorithm score. The stronger precision target limits invented targets; the per-condition floor prevents averaging away weak-source failures.
- Stress conditions: 25-degree separation and 0.5 s target RT60, reported independently with all misses/false events. They are required comparison evidence, not qualified operating claims. Additional coherent/near-coincident inputs expose observability limits. The operational domain and stress distinction are fixed now, not retrospectively narrowed after evaluation.
- A 30-degree matching gate separates gross wrong directions from the 15-degree p95 requirement, so angular acceptance is not guaranteed by matching. Fifteen degrees is three 5-degree grid steps and below half the minimum operational separation; it supports coarse direction cues without claiming high physical accuracy. Pair resolution remains constrained by the 6–10 cm apertures and signal bandwidth. Single-source errors cannot establish two-source observability.
- Every no-source control must return no events for exact silence; at most 1% of independent diffuse-noise windows may create any event. Check multiple absolute noise levels so an amplitude-only gate cannot manufacture a pass.
- The warmed composed localizer must have compute p95 below 50 ms and maximum below 250 ms (20 warmups and 200 measurements), separately from its 250 ms observation context. Measure startup independently. Changed-source response targets are p95 at most 350 ms and maximum at most 500 ms: 250 ms context plus one 50 ms update and up to 50 ms normal compute explains the p95 budget. Failure to reach a correct response is a failure, not an omitted latency sample.

Thresholds are selected on development only: SRP planar/3D 0.25/0.45; MUSIC 0.10/0.30; normalized MUSIC 0.55/0.60; ODAS 0.05/0.05; refined covariance pursuit 0.125/0.125. The first three families were calibrated by detection F1; covariance uses a common threshold attaining at least 95% development precision after its measured refinement gain. These are estimator-specific thresholds, not comparable probabilities. Cases are rerun with actual stopping thresholds, rather than assuming post-filtered development proposals have identical execution.

Passing only nominal is intermediate evidence. Standard integration additionally requires operational, idle-noise and latency gates. Report each role separately and continue diagnosis/alternatives after failure. The held-out confirmation assets remain reserved for a correction informed by final evaluation. All acoustic claims here are simulated; small shared-speaker speech assets and one image-source room model do not establish broad real-world generalization.

## Independent Evaluation and Corrective Confirmation

The first 864-case evaluation at commit `5cfd90d` produced no operational GO. The covariance candidate passed nominal quality on square and tetrahedral arrays but not the entire declared domain. Frequency-normalized MUSIC remained precise when answering but missed sources; its one global MDL order cannot represent two broadband events when each frequency contains only one of them. This was particularly visible in the disjoint-band controls. ODAS and covariance showed a different false-event/missed-source tradeoff. No candidate was integrated into common perception.

The resulting corrective trial replaces the global order with independently observed per-frequency MDL orders, groups compatible bins for PyRoom MUSIC, and fuses the complete normalized spatial spectra without a global event-count cap. Subtracting each group's median spectrum removes the broad response floor before peak selection. This remains a mixture-only, stateless, CPU algorithm; neither truth nor tracks supply its count. Development-only calibration selects the same contrast threshold `0.11` for both roles (432 cases); development F1 is 0.939 planar and 0.916 3D. These are development figures, not qualification.

`tools/qualification/doa_04_4/confirmation_protocol.json` retains every original acceptance criterion and geometry. It fixes the new threshold before opening the reserved confirmation assets and cases, and compares the correction against unchanged normalized-MUSIC and covariance settings on those same fresh cases. Separate idle/background, onset/offset, three-source capacity and composed-compute diagnostics accompany the quality reports. The evaluator's transition timing includes two consecutive correct emitted sets and compute time; no persistent identities are introduced into localization.


## Confirmation Outcome — NO-GO for Both Roles

The reserved confirmation evaluates 864 new cases per candidate, with unchanged acceptance criteria. Normalized MUSIC and covariance pursuit fail static operational qualification on every geometry. Frequency-local order improves detection, but its static passes on square and raised-center arrays do not pass the independent transition gate. No candidate wins full qualification, and no experimental adapter is exposed as a public plugin.

| Frequency-local order geometry | Operational precision | Recall | Exact count | Matched angular p95 | Static failures | Unresolved transitions |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Triangle, planar | 97.12% | 93.75% | 90.97% | 4.32° | Two-source count accuracy | 0→1, 2→1 |
| Square, planar | 95.10% | 94.44% | 90.97% | 3.06° | None | 1→2 |
| Raised-center, rank 3 | 99.27% | 94.44% | 93.75% | 4.18° | None | 0→1, 2→1 |
| Tetrahedron, rank 3 | 96.95% | 88.19% | 85.42% | 3.46° | Two-source count accuracy; moderate-condition recall | 2→1 |

A transition is unresolved when no two consecutive correct event sets occur before the next change (800 ms). Missing responses are failures, not excluded latency samples. All four frequency-local geometries return no false events in exact silence, 100 uncorrelated-noise windows and 100 diffuse-noise windows. Their warmed composed compute p95 values are 1.64, 1.92, 36.56 and 30.94 ms respectively; maximum is below 39 ms. These CPU measurements satisfy the compute gate at 250 ms context / 50 ms updates, but do not repair quality or response failures. They are isolated Auditok-plus-localizer measurements, not production consumer throughput or a live GPU smoke.

The steady single-source portions of the transition probe expose model-order inflation at very high SNR: per-frequency MDL can assign the maximum subspace order when finite-window/narrowband model residuals exceed the near-zero estimated noise eigenvalues. This is the leading algorithm/model-mismatch diagnosis, not a proven complete explanation of every missed transition. The probe uses interpolated propagation, so propagation approximation should also be isolated in the next development diagnosis. Angular accuracy conditional on a matched event cannot hide these cardinality errors.

The three-source diagnostic returns three correctly matched events for frequency-local order on all four geometries, including the three-microphone triangle. This demonstrates no artificial two-event output cap; it does not qualify arbitrary three-source mixtures. Separate 5-degree controls produce one detection and one missed source for every confirmation candidate and geometry. Coherent 70-degree inputs expose additional misses and spurious directions; covariance resolves this one coherent case on triangle/square/raised-center but produces an extra event on tetrahedron. These controls describe limitations, not qualified coherent-source performance.

### Native ODAS Repair and Re-evaluation

The first native diagnostics crashed during teardown. GDB located the failure in `fftwf_destroy_plan` through ODAS `fft_destroy`: per-instance `fftwf_cleanup()` invalidated FFT plans still owned by other live SSL modules. The isolated bootstrap removes that global cleanup call while retaining individual plan destruction. Repeated multigeometry windows and repeated close now pass in a subprocess. This local patch adds native maintenance cost; it is not a change to the installed/public package.

Earlier ODAS numerical reports are superseded by post-repair confirmation using the unchanged 0.05 threshold. All four geometries still fail static qualification and at least one transition. Planar triangle and square each generate false events in 100/100 diffuse-noise windows; raised-center generates one, tetrahedron zero. All return zero false events on uncorrelated noise and exact silence. Native composed compute p95 is 1.56–2.72 ms, so compute is not the observed blocker. Cheap potential directions still require a substantially better event-selection rule.

### Evidence and Remaining Work

The maintained experimental source is `tools/qualification/doa_04_4/`; it remains useful because qualification is unfinished. Generated inputs, native dependencies and reports remain ignored under `build/qualification/doa/04_4/`:

- `final-evaluation.json`: initial fixed evaluation, 864 cases × five candidates. Its pre-repair ODAS results are superseded.
- `confirmation-evaluation.json` and `confirmation-diagnostics.json`: fresh confirmation, 864 cases × three candidates, plus independent idle/transition/capacity/compute diagnostics.
- `odas-repair-evaluation.json` and `odas-repair-diagnostics.json`: post-repair ODAS confirmation and lifecycle-safe diagnostics.
- `observability-controls.json`: coherent and near-coincident controls, kept separate from operational acceptance.
- `final-diagnostics.json`: incomplete historical run ending at the native crash; never a complete qualification report.

The next intervention is development-only model-order regularization against finite-window/model residuals, coupled with diagnosis of weak-source counting on triangle and tetrahedral arrays. Compare that cost with improving ODAS potential rejection before choosing a maintained implementation. Both evaluation and confirmation speech assets have now been consumed: any evaluation-informed correction requires new independent assets, rooms, noise and transition episodes. Keep the original operating criteria unless a separately justified future protocol explicitly changes them; do not reuse these reports as uncontaminated proof.

Sequence-based common perception, multi-event temporal semantics, recording/dataset/consumer verification and the new live Lab GPU smoke remain unimplemented because no role passed admission. Existing stereo ambiguity, opt-in behavior, serialized contracts and consumers are unchanged. Startup and complete consumer latency are not qualified. Simulated 04.4 is incomplete; physical multisource localization remains unqualified.


## Continued Development — Regularized Covariance MUSIC

Work continues at `main` / `85fcb23` without a scope or acceptance change. Development separates two observed failures: near-zero-noise eigenvalues inflate MDL order; broad spatial sidelobes become extra events. Relative diagonal loading of `0.0001` times the largest observed eigenvalue stabilizes order. The next candidate proposes MUSIC peaks at contrast `0.03`, then fits their full cross-spectral covariance with nonnegative source powers plus white and isotropic diffuse noise components. Only mixture, geometry and sample rate enter this calculation. Mean fitted power is an internal rejection statistic, not a calibrated event probability.

Development compared narrow/wide per-frequency peak votes, covariance refits without diagonal terms, full-covariance refits, local angular refinement, excluding frequencies below 1 kHz, and an additional spectral-support gate. Narrow votes missed weak sources; wider votes increased 3D compute beyond the 50 ms reference. Angular refinement added substantial cost without a consistent counting gain. Frequency exclusion and support rejection did not improve the overall result. The retained correction uses the full covariance and the original 300–6000 Hz band; these failed variants remain only in ignored development evidence, not the maintained tool implementation.

The 432-case development comparison supports testing rejection thresholds `0.12` planar and `0.11` rank 3. At these thresholds, rank-3 geometries meet the static development gates, while both planar geometries still miss the two-source count target. This is a candidate for independent confirmation, not a declared winner. Directed noiseless single/pair controls and independent white/diffuse-noise development controls now pass on all four geometries. Every original final acceptance gate remains unchanged.

`tools/qualification/doa_04_4/verification_protocol.json` fixes this candidate and settings before opening the new `verification` partition: 864 cases with new room/noise/source-direction seeds beginning at 300000. The two previously unused utterances and speakers are from [LibriSpeech / OpenSLR 12](https://www.openslr.org/12), CC BY 4.0, prepared by Vassil Panayotov and colleagues from LibriVox audiobooks. `verification_assets.json` records their official archive members and content hashes. Bootstrap retrieves only those members and verifies their identity. Downloading the files did not use them for calibration. Two utterances still provide limited content coverage and cannot establish broad speech generalization.

New transition diagnostics randomize direction relative to the grid, with 70-degree spherical separation for rank-3 arrays. Earlier on-grid probes remain regression evidence, not sufficient qualification. The new partition remains independent of every earlier evaluated window and episode. No production role or consumer changes before its results are known.


### Verification Failure and Second Correction

The 864-case `verification-evaluation.json` passes every static gate except operational two-source count accuracy on every geometry. Pair count accuracy is 66.7% triangle, 70.8% square, 68.8% raised-center and 77.1% tetrahedron; the fixed minimum remains 80%. Nominal and 5 dB SNR pairs all pass. Failures concentrate in the combined reverberation/imbalance condition and 10 dB imbalance alone. Power-only rejection at 0.11–0.12 is an unsuitable general event criterion: a fully overlapping source 10 dB below another contributes only about 0.09 of total signal power. Lowering that floor alone admits sidelobes, so it does not solve qualification.

`verification-diagnostics.json` passes idle controls and warmed compute on all geometries. Transitions pass on triangle, square and tetrahedron; raised-center fails single-source phases. A controlled comparison identifies an evaluator defect in that probe: linear interpolation creates channel-dependent magnitude/phase responses rather than ideal delays. On the failed raised-center direction, channel RMS ratios span 1.133 under linear interpolation versus 1.00013 under bandlimited delay, and only the former creates a second event. Earlier linear-transition failures remain evidence of response-mismatch sensitivity; they cannot establish failure under an ideal-channel nominal model. The new nominal transition generator uses bandlimited delays, with a regression test for channel-response preservation and fresh episode seeds.

A second development correction combines spatial contrast with fitted covariance power instead of rejecting by power alone. Local weighted peak centroids within 8 degrees reduce grid-error leakage into false components before refitting. The rejected support-fraction alternative did not improve precision. Expanded development (864 cases) passes every fixed static gate on every geometry for a common rejection threshold from 0.012 through 0.016. The next fixed setting is the middle value, 0.014, for both roles; proposal contrast remains 0.03 and MDL loading remains 0.0001. This is development evidence only.

`tools/qualification/doa_04_4/validation_protocol.json` fixes the unchanged quality/latency criteria, selected correction and bandlimited nominal transitions before opening the `validation` partition. Seeds start at 400000 and the two LibriSpeech assets use new speakers 5639 and 260, separate from all earlier partitions. Asset members/hashes are appended to `verification_assets.json`. The prior verification inputs are consumed diagnostic material and will not be relabeled as independent proof of this correction.


### Bandlimited Validation and AIC Comparison

The independent `validation-evaluation.json` passes static quality on square and raised-center arrays. Triangle has 38/48 correct operational pair counts (79.2%), tetrahedron 37/48 (77.1%), below the unchanged 80% gate. All other static gates pass. In contrast to power-only rejection, 10 dB imbalance pairs now achieve exact count in 12/12 triangle, square and tetrahedral cases and 11/12 raised-center cases. Remaining misses concentrate in combined room/imbalance and noisy speech. `validation-diagnostics.json` passes every bandlimited transition, idle-noise and compute gate on every geometry; it also correctly detects three events in each capacity diagnostic. Thus square/raised-center have complete per-geometry passes, but the combined planar and 3D roles remain unqualified.

The final targeted model-order comparison retains the same covariance/contrast correction and tests AIC against MDL. These are established source-count criteria from [Wax and Kailath (1985)](https://doi.org/10.1109/TASSP.1985.1164557). AIC uses a smaller finite-sample complexity penalty here; its known overestimation risk makes the separate event-rejection and idle tests essential. Expanded development improves weak-source recall, and every geometry passes all static gates at AIC thresholds 0.010–0.012. The fixed common setting is 0.011. No audio context, operating condition or acceptance gate changes.

`qualification_protocol.json` compares AIC at 0.011 against unchanged MDL at 0.014 on the same new 864 cases, beginning at seed 500000, with new LibriSpeech speakers 7729 and 2094. Bandlimited transitions use fresh noise/directions. The new assets remain excluded from development; all earlier partitions retain their original failures and limits. The method comparison and acceptance remain separate decisions: no role is admitted by a development pass or by a partial geometry pass.


### Spectral Normalization Diagnosis

The fresh `qualification-evaluation.json` does not admit either MDL or AIC: every geometry fails operational pair counting, and AIC tetrahedron also fails aggregate count accuracy. AIC pair count accuracy is 72.9% on triangle, square and raised-center, and 60.4% on tetrahedron. Idle and transition checks pass; warmed AIC compute remains below the 50 ms gate. Increasing context to 400/500 ms on these consumed failure cases does not repair counting (`context-failure-diagnosis.json`); this is post-hoc diagnosis, not independent qualification or a reason to change latency criteria.

The noisy-speech misses reveal a spectral normalization problem: averaging fitted powers uniformly across frequency penalizes signals concentrated in a few bands, while bins classified as noise dilute the spatial contrast. The correction weights fitted covariance powers by observed spectral energy and normalizes the spatial sum by bins with positive inferred order. Explicit white/diffuse covariance terms still perform noise rejection. A controlled two-band-plus-noise regression returns two events with the correction where the unweighted variant abstains. Post-hoc checks recover the missed noisy-speech sources, but are not reused as final evidence.

Expanded development passes every static gate on every geometry at thresholds 0.009–0.011; the fixed common value is 0.010. `assessment_protocol.json` compares it with unchanged AIC on 864 new cases starting at 600000 and new LibriSpeech speakers 3575 and 7127. Every acceptance criterion and the 250 ms / 20 Hz reference remain unchanged. This additional confirmation is necessary because failure analysis informed the normalization change.


## Current Closeout — Improved Candidate, Promotion Still NO-GO

The final `assessment-evaluation.json` / `assessment-diagnostics.json` passes every fixed gate on all four geometries for the weighted covariance-AIC candidate, using unseen speakers, cases and bandlimited transitions. Warmed compute p95 is 3.03 ms triangle, 3.51 ms square, 30.34 ms raised-center and 25.02 ms tetrahedron; all changes receive correct responses within 336 ms. Exact silence and uncorrelated noise produce no false events; diffuse noise produces one event window in 100 on triangle (the permitted 1%) and none on the other layouts. The same-run unweighted AIC baseline also passes, illustrating why a favorable final content sample alone does not determine the winner.

Before promotion, the fixed weighted candidate was rerun on all 2,592 previously consumed LibriSpeech cases (`verification`, `validation`, `qualification`). This is regression evidence, not another independent evaluation and not data used to choose a new threshold. It exposes remaining dependence on content and acoustic realization:

| Geometry | Known-case operational precision | Recall | Exact pair count | Pair minimum | Remaining gate failures |
| --- | ---: | ---: | ---: | ---: | --- |
| Triangle | 94.63% | 93.75% | 74.31% | 80% | Precision and pair count |
| Square | 95.34% | 94.68% | 78.47% | 80% | Pair count |
| Raised-center | 95.13% | 94.91% | 82.64% | 80% | None |
| Tetrahedron | 96.12% | 91.67% | 73.61% | 80% | Pair count |

The latest three-source diagnostic returns three correct events on square, raised-center and tetrahedron; triangle returns five (three matches plus two false events). This confirms variable capacity without qualifying three-source reliability.

These failures remain within the originally declared operating domain. Pooling favorable new samples with older failures or relabeling supported roles would not resolve them. The raised-center layout has useful positive evidence, but it does not establish the full rank-3 role; planar qualification also remains incomplete. The broader check prevents premature integration based only on the latest PASS. The unweighted AIC alternative has its own measured failures in the preceding independent qualification.

`tools/qualification/doa_04_4/admission.py` combines static, idle and response gates and optionally known-case regression. Missing responses never disappear from latency statistics. `assessment-admission.json` is a single-run PASS; `promotion-decision.json`, with the source-linked `promotion-regression.json`, is the current combined NO-GO decision. `assessment-promotion.json` was an intermediate decision with only the weighted regression input; use `promotion-decision.json` for both candidates.

Scope and acceptance criteria remain unchanged. The next step is a dedicated event-cardinality approach that models spectral occupancy and reverberant/coherent contributions explicitly, compared against this retained baseline. Further threshold tuning or a longer context is not supported as the next remedy by these measurements. Reuse the existing mixtures as development/regression material and reserve a broader new content partition before evaluating a different approach. Common sequence perception, maintained selection and consumer/Lab GPU qualification remain pending admission; no public runtime, serialized schema or default dependency has changed. Physical multisource performance remains unqualified.


## Practical Scalar Reference — Prospective Integration Milestone

The user requests a useful reference that permits starting 07.2 without open-ended algorithm research. The combined 45-degree separation, 6 dB imbalance, 10 dB SNR and 0.3 s target RT60 condition is plausible; its failures are not dismissed as unrealistic. It remains a measured limitation. What changes is the integration milestone, not those historical results: a bounded opt-in scalar reference may precede qualification over the entire original acoustic domain. No new cardinality algorithm is required by the evidence.

`reference_protocol.json` fixes this prospective milestone before new content evaluation. Retain the weighted covariance-AIC algorithm and every numerical quality, idle and timing threshold. Qualify the existing direct-path nominal, isolated 10 dB imbalance and isolated 5 dB SNR cases on all four geometries. These cases exercise useful direction cues with both spectral overlap and weak/noisy sources; they do not establish a continuous Cartesian operating envelope or arbitrary room performance. Combined room/imbalance, close, reverberant and coherent cases remain mandatory characterization outside this bounded claim. Previous reports keep their original NO-GO; a new result must never overwrite or relabel them.

Use 16 previously unused LibriSpeech speakers, chosen by archive order and minimum duration before running localization, plus independent non-speech realizations, source directions and room/noise seeds. The new reference partition begins at 700000 with eight repetitions per case stratum. Keep prior failures as regression evidence within the newly declared bounded domain and retain the original full-domain decision separately.

07.2 readiness additionally requires the actual common event-sequence implementation, variable cardinality and stereo ambiguity semantics, causal state/reset, recorder/dataset and Core/Isaac/Kit consumer checks, and live GPU Lab projection. Passing an isolated candidate alone is insufficient. Full-domain acoustic and physical multisource qualification remain separate open claims after a bounded reference GO.
