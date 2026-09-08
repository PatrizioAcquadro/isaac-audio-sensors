# Subphase 04.4 — Multisource Localization Qualification

## Objective and Status

**Bounded direct-path scalar-reference GO for planar and 3D; full indoor qualification remains incomplete. Current priority: continue 04.4 acoustic work before 07.2.** Common perception, recording/dataset and Core/Isaac/Kit consumers are integrated and verified, including actual RTX 4090 Lab projection. The prospective direct-path protocol passes on broader independent content. Subsequent paired development finds room-only false events and weak-source misses; loading, event selection, short/long-context dereverberation, bandwidth conditioning and fixed diffuse-covariance corrections are not admitted. The original combined reverberant-domain qualification remains NO-GO; historical results below remain unchanged. Physical multisource performance, tracking, separation and scalable Lab perception are unqualified or outside this experiment. See [[implementation_phases/04-observed-direction-estimation|Phase 04]].

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


## Original Broad-Domain Closeout — Promotion NO-GO

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

At this broad-domain closeout, scope and acceptance criteria were unchanged. A dedicated event-cardinality approach was proposed as future research, not demonstrated necessary or selected. The subsequent user-directed practical milestone below supersedes that mandatory-next-step interpretation. Further threshold tuning or a longer context is not supported as the next remedy by these measurements. Reuse the existing mixtures as development/regression material and reserve a broader new content partition before evaluating a different approach. Common sequence perception, maintained selection and consumer/Lab GPU qualification remain pending admission; no public runtime, serialized schema or default dependency has changed. Physical multisource performance remains unqualified.


## Practical Scalar Reference — Prospective Integration Milestone

The user requests a useful reference that permits starting 07.2 without open-ended algorithm research. The combined 45-degree separation, 6 dB imbalance, 10 dB SNR and 0.3 s target RT60 condition is plausible; its failures are not dismissed as unrealistic. It remains a measured limitation. What changes is the integration milestone, not those historical results: a bounded opt-in scalar reference may precede qualification over the entire original acoustic domain. No new cardinality algorithm is required by the evidence.

`reference_protocol.json` fixes this prospective milestone before new content evaluation. Retain the weighted covariance-AIC algorithm and every numerical quality, idle and timing threshold. Qualify the existing direct-path nominal, isolated 10 dB imbalance and isolated 5 dB SNR cases on all four geometries. These cases exercise useful direction cues with both spectral overlap and weak/noisy sources; they do not establish a continuous Cartesian operating envelope or arbitrary room performance. Combined room/imbalance, close, reverberant and coherent cases remain mandatory characterization outside this bounded claim. Previous reports keep their original NO-GO; a new result must never overwrite or relabel them.

Use 16 previously unused LibriSpeech speakers, chosen by archive order and minimum duration before running localization, plus independent non-speech realizations, source directions and room/noise seeds. The new reference partition begins at 700000 with eight repetitions per case stratum. Keep prior failures as regression evidence within the newly declared bounded domain and retain the original full-domain decision separately.

07.2 readiness additionally requires the actual common event-sequence implementation, variable cardinality and stereo ambiguity semantics, causal state/reset, recorder/dataset and Core/Isaac/Kit consumer checks, and live GPU Lab projection. Passing an isolated candidate alone is insufficient. Full-domain acoustic and physical multisource qualification remain separate open claims after a bounded reference GO.


## Historical Integration Milestone — Bounded Reference GO

All four geometries pass `reference_protocol.json` on the 1,728-case `reference-evaluation.json`, plus `reference-diagnostics.json` and the applicable known-case regression. `reference-regression.json` explicitly re-scores prior raw cases only for the prospective bounded domain; it is not fresh evaluation and does not replace `promotion-decision.json`. `reference-admission.json` is the bounded candidate GO. No algorithm or numerical gate changed. The new content comes from 16 unused speakers in the [LibriSpeech corpus](https://www.openslr.org/12) (Panayotov et al., CC BY 4.0), with source members recorded in `reference_assets.json`.

| Geometry | Direct-path precision | Recall | Exact pair count | Matched angle p95 | Warm compute p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Triangle | 99.53% | 98.15% | 93.06% | 3.03° | 2.97 ms |
| Square | 99.52% | 96.76% | 91.67% | 3.24° | 3.54 ms |
| Raised-center | 100% | 98.15% | 94.44% | 3.16° | 30.50 ms |
| Tetrahedron | 100% | 98.15% | 94.44% | 3.40° | 31.02 ms |

The qualified case family is the tested 16 kHz direct-path nominal condition (70-degree separation, equal received levels, 20 dB SNR), isolated 10 dB imbalance, and isolated 5 dB SNR. Sources are in the array plane for planar scoring; rank-3 sources vary azimuth and elevation. Speech, overlapping non-speech and disjoint spectra are represented. These are discrete conditions, not proof of every intermediate combination. The same new evaluation reports combined room-condition precision of 79.2–90.6% and recall of 79.2–84.7% across geometries. Room robustness remains a real limitation. Merely lowering the old 80% pair threshold was not the remedy.

All four independent nominal 0→1→2→1→0 probes respond correctly, with maximum observed delay 338.8 ms, including composed compute. The fixed 250 ms context and 20 Hz update remain. White/diffuse-noise and silence gates pass. Known failure cases remain available for later targeted work; the reference partition is now consumed evidence and cannot qualify an evaluation-informed correction again.

The maintained algorithm is shared with the experiment through `_multisource_music.py`, avoiding a copied implementation. No native ODAS dependency is promoted. The new common `EventLocalizer` receives only mixture, ordered valid geometry and sample rate. Tests exercise variable cardinality beyond two, deterministic order/IDs, candidate ambiguity, missing dependencies, malformed outputs, truth isolation, causal context and all reset boundaries. Real analytic direct-path mixtures with two independent WAV sources pass through Core and Isaac, frame serialization, session recording, learning datasets and Kit history on all four layouts. Stereo and other planar sample rates retain their previous single-event behavior; 16 kHz is the explicit multisource reference rate.

`build/validation/isaac_audio_sensors/phase04_4_lab_live_smoke.json` records a PASS on the actual RTX 4090: planar/spherical two-source scalar/reference parity, masks, finite padding, zero/one-slot capacity loss and independent environment reset. Two-environment warm updates measured 41.2–42.9 ms; the first full localization update took 148.5 ms, measured separately from the 250 ms audio warm-up. These short measurements are smoke evidence, not a throughput qualification. The existing 4,096-empty-environment lifecycle check averages 0.208 ms/step; it does not represent multisource computation at scale. MUSIC executes on CPU because this implementation is CPU-only; tensor projection executes on CUDA.

At this integration milestone, the bounded 04.4 implementation became available as a reference for 07.2. The later project-level decision below prioritizes further acoustic work before starting that phase. Full original-domain simulated acoustic qualification and physical multisource validation remain open. Further cardinality research is driven by measured consumer needs; it is not a prerequisite for starting 07.2 with this bounded reference.


## Progressive Indoor-Utility Diagnosis

The user requests a room-only test followed by gradual added difficulty before deciding whether the current method is practically sufficient. `progressive_protocol.json` fixes paired development comparisons: direct control; 0.2/0.3/0.5 s target RT60 alone; 3/6 dB imbalance, 10 dB SNR and 55/45-degree separation separately at 0.3 s; then cumulative level/noise/separation combinations. All four geometries and zero/one/two-source controls are included. The current algorithm is unchanged initially.

Hold episode content, noise realization, dimensions and off-center array position fixed across conditions. Use the same image-source direct-path renderer even for the reflection-free control, avoiding a comparison confounded by switching plane-wave and spherical propagation. Measure decay and direct/reflected RIR energy; a target RT60 is not a measured room or complete description of reverberation. Existing consumed speech is development material. Room-only failures warrant a targeted algorithm/model diagnosis before claiming general indoor utility; new independent content is required to confirm a retained correction. The previously integrated direct-path reference remains available, but does not settle this new practical-utility question.

### Paired Results and Practical Interpretation

`progressive-baseline.json` contains 3,168 development cases: 24 paired episodes per geometry (eight speech, eight overlapping bandlimited-noise, eight disjoint-band realizations), each with 11 conditions and zero/one/two-source controls. Counts and conditions share an episode; these are not 3,168 independent acoustic/content samples. No source count, room, stems or truth reaches localization. The scored context remains 250 ms at 16 kHz. These static probes do not requalify onset response, motion or physical sensing.

The following percentage requires **both true sources matched one-to-one and no extra event**, using the existing 30-degree matching gate. It is stricter than getting the count right, but does not imply every direction is within 15 degrees; angular p95 remains a separate metric. Each cell has 24 pair episodes, so one outcome changes it by 4.17 percentage points. This small development sample supports diagnosis, not a precise real-world success probability.

| Condition | Triangle | Square | Raised-center | Tetrahedron |
| --- | ---: | ---: | ---: | ---: |
| Direct control | 100.0% | 100.0% | 100.0% | 100.0% |
| Room only, target 0.2 s | 91.7% | 83.3% | 79.2% | 87.5% |
| Room only, target 0.3 s | 83.3% | 79.2% | 70.8% | 70.8% |
| Room only, target 0.5 s | 58.3% | 70.8% | 8.3% | 12.5% |
| 0.3 s + 3 dB imbalance | 66.7% | 79.2% | 54.2% | 41.7% |
| 0.3 s + 6 dB imbalance | 62.5% | 54.2% | 33.3% | 12.5% |
| 0.3 s + 10 dB SNR | 70.8% | 79.2% | 83.3% | 83.3% |
| 0.3 s + 55-degree separation | 79.2% | 70.8% | 91.7% | 75.0% |
| 0.3 s + 45-degree separation | 70.8% | 79.2% | 70.8% | 79.2% |
| 0.3 s + 6 dB + 10 dB SNR | 58.3% | 45.8% | 37.5% | 37.5% |
| 0.3 s + 6 dB + 10 dB SNR + 45 degrees | 37.5% | 45.8% | 41.7% | 33.3% |

At the 0.3 s target room-only condition, precision / recall are 90.9 / 97.2%, 85.5 / 98.6%, 90.3 / 90.3%, and 90.3 / 90.3%, respectively. Matched angular p95 is 8.9 / 7.1 / 9.9 / 13.1 degrees. Exact pair counts are 87.5 / 83.3 / 75.0 / 79.2%; their difference from the table shows why counting alone is insufficient. Single-source controls already produce 3 / 7 / 3 / 4 false events across 24 windows. All 1,056 zero-source controls produce zero events. The failure therefore concerns observed mixtures and event selection, not fabricated detections from the quiet control.

Speech is materially harder than the aggregate: room-only at target 0.3 s gives both speech sources without extras in 5/8 triangle, 6/8 square, 2/8 raised-center and 2/8 tetrahedral episodes. The paired 6 dB imbalance further reduces pair recovery; adding noise or reducing separation does not degrade every cell monotonically. Acoustic realization, content and finite-window covariance matter. The overall recall must not conceal the weaker simultaneous-speech result.

For target decays 0.2 / 0.3 / 0.5 s, median Schroeder T20 extrapolations are 0.139 / 0.251 / 0.475 s; median direct-to-reflected RIR energy ratios are +4.58 / +0.33 / -3.37 dB. Thus the middle case has comparable total direct and reflected energy at 1.5 m. The renderer is an empty approximately 6 × 5 × 4 m shoebox with uniform absorption and off-center array placement. These are plausible acoustic challenges, not a measured furnished-room specification, and T20/energy ratios do not capture every early-reflection feature. A general claim about all ordinary rooms would exceed this evidence.

`progressive-distance.json` keeps the same episodes, room and target 0.3 s, with separate matched reflection-free controls at 0.5 and 1 m. At 0.5 m the median direct/reflected ratio rises to +9.95 dB; at 1 m it is +3.96 dB. At 0.5 m both-source/no-extra recovery is 91.7 / 83.3 / 87.5 / 79.2%, with precision 97.3 / 95.9 / 94.7 / 94.7% and recall 98.6% on every geometry. The corresponding direct controls recover 100 / 91.7 / 100 / 95.8% of pairs. At 1 m, both-source/no-extra recovery is 83.3 / 83.3 / 95.8 / 87.5%, precision is 92.3 / 86.7 / 91.0 / 95.8%, and recall is 100 / 100 / 98.6 / 95.8%. These outcomes are not monotonic for every geometry; 24 pair episodes per cell do not establish a universal distance boundary. This indicates a promising close-range use, not a qualified distance envelope; spherical propagation also exposes occasional direct-path false peaks. Moving closer changes geometry and relative reflection strength, while received levels and SNR remain normalized.

### Bounded Corrective Probes — None Promoted

All probes use consumed development content and the paired direct, room-only target 0.3 s, and combined cases. They are not independent confirmation. The maintained SDK algorithm, context, acceptance criteria and optional dependency contract are unchanged.

- `progressive-loading.json` compares the existing relative eigenvalue loading 0.0001 with 0.001 / 0.003 / 0.01. No setting consistently removes the room-only precision failures; some worsen direct-path counting. More loading is not an admitted remedy.
- `progressive-selection.json` post-filters stored candidates with absolute floors 0.015–0.04 and relative floors 4–20% of the largest score. At absolute 0.02, square room-only precision / recall improves to 98.6 / 95.8%, but raised-center and tetrahedral recall falls to 63.9 / 51.4%, and both-source/no-extra recovery to 8.3 / 4.2%. A stronger rejection threshold trades false events for lost real sources.
- `progressive-power.json` tests the existing weighted covariance powers without multiplying by spatial contrast; the same selection report evaluates floors 0.03–0.20. No common floor preserves the direct controls and reaches all four room-only quality references. Dropping spatial contrast also produces false events in quiet controls at low floors. This is not a justified simplification.
- `progressive-wpe.json` evaluates established [NARA-WPE](https://github.com/fgnt/nara_wpe) 0.0.11 dereverberation before unchanged MUSIC: NumPy `wpe_v7`, FFT 512 / hop 128, three iterations, delay three frames and three or five taps, using only the available 250 ms mixture. The STFT/inverse-STFT control reconstructs every input within 1e-12 and reproduces baseline matching. Three taps raises room-only pair recovery to 87.5% raised-center and 83.3% tetrahedral, but leaves square precision at 85.5%, reduces direct triangle pair recovery to 87.5%, and does not resolve combined cases. Five taps reduces raised-center room-only pair recovery to 50%. Composed compute p95 spans approximately 7–45 ms with three taps; raised-center exceeds 50 ms with five taps. This narrow short-context probe rejects promotion of these settings; it does not establish that WPE with longer causal history cannot help.

The WPE package and its probe remain only in the ignored evidence directory, with no public dependency or plugin added. The probe deliberately exercises the package's NumPy implementation on CPU; the separate historical TensorFlow implementation was not evaluated. Existing MUSIC and room rendering are also CPU implementations. No new GPU integration claim is made because no correction was promoted. `selection_probe.py` and `wpe_probe.py` beside the reports preserve these small rejected experiments without adding unused maintained SDK surfaces.

**Decision after the initial progressive probes (followed by the comparisons below):** the shared multisource capability is functional, and the prior direct-path reference remains qualified. General indoor usefulness is not established: room-only failures and weak-source misses are sufficiently concrete to warrant work on robustness, not a relaxed gate or nominal relabeling. Close-range results are promising development evidence, not a replacement qualification. A custom cardinality algorithm is not yet demonstrated necessary; the next bounded intervention should compare a conventional room-robust approach, including whether longer causal dereverberation buys enough quality to justify its context/compute, against this unchanged reference. Any selected correction needs new independent speakers/episodes and response/consumer validation before promotion. 07.2 has not started; its technically available bounded reference does not resolve the user's requested indoor-utility review.

### Project-Level Priority and Causal-History Comparison

The user clarifies that the decision concerns the utility of the whole robot-audition project, not merely the technical dependencies of 07.2. Indoor simultaneous sensing is a central capability. Therefore, continue bounded acoustic-robustness work before scaling the current reference in 07.2; technical readiness alone is not the requested product-level decision.

The subsequent development comparison supplied NARA-WPE with 500 or 750 ms of past mixture, five or ten taps, delay three STFT frames and three iterations. MUSIC still sees only the most recent 250 ms. Use the same paired direct, target-0.3-s room-only and combined episodes, with unchanged count/quality references. The extended renderer preserves the original scored mixture exactly, including received levels and noise, and nested history windows share identical overlapping samples. No future samples, room parameters, stems or truth enter preprocessing or localization. Each call refits WPE from the supplied past buffer; no tracking is added. Longer history affects warm-up and adaptation, not automatically the timestamp of every emitted event; response tests are required if quality supports retaining a setting. The dedicated `dereverberation.py` runner loads the existing ignored NumPy dependency and reports composed compute, with no public runtime change.

### Longer-History and Acoustic-Model Results — No Correction Admitted

`progressive-wpe-history.json` compares five settings on the same 864 development cases (4,320 estimator calls, not independent cases). All 864 unprocessed controls reproduce the earlier baseline matching exactly. Five-tap WPE with 750 ms history illustrates both the benefit and remaining cost:

| Geometry | Room-only both sources, no extras: baseline → WPE | WPE room precision / recall | Room composed compute p95: baseline → WPE |
| --- | ---: | ---: | ---: |
| Triangle | 83.3 → 91.7% | 93.5 / 100% | 3.5 → 14.1 ms |
| Square | 79.2 → 83.3% | 89.7 / 97.2% | 4.3 → 19.6 ms |
| Raised-center | 70.8 → 83.3% | 88.7 / 98.6% | 39.3 → 60.6 ms |
| Tetrahedron | 70.8 → 91.7% | 93.4 / 98.6% | 32.7 → 47.5 ms |

The room condition is still only target 0.3 s decay, 70-degree separation, equal received levels, 20 dB SNR and 1.5 m range. The extra recovered sources come with remaining false events; square/raised-center direct controls also lose perfect pair recovery, reaching 91.7%. Combined-case pair recovery is 58.3 / 54.2 / 70.8 / 45.8%. Ten taps costs more and does not solve precision; raised-center room compute reaches 98.2 ms at 750 ms history. Five taps at 500 ms still leaves room precision below 93% on every layout and raised-center compute above 50 ms. These NumPy measurements include STFT, WPE, inverse STFT and MUSIC in a single CPU process with one BLAS thread; they are not a GPU or large-scale throughput result. Development post-filtering at 0.012 / 0.015 / 0.020 again trades false events for lost sources without a common all-geometry remedy. No setting merits independent confirmation or response qualification yet.

Two inexpensive acoustic alternatives were then evaluated on the same cases, with their raw reports and exact prototype code retained under the ignored evidence root:

- `progressive-band.json` / `band_probe.py`: causal sixth-order Butterworth conditioning at 300–2500, 300–3500, 1000–6000 and 1500–6000 Hz before unchanged MUSIC, using the extended past mixture and scoring the same trailing window. Lower cutoffs lose useful directional evidence; removing low frequencies can improve 3D precision but loses true sources. At 1500–6000 Hz, raised-center/tetrahedron room precision reaches 100%, but both-source recovery falls to 45.8 / 41.7%; square precision falls to 75.3%. None is promoted.
- `progressive-whitening.json` / `whitening_probe.py` / `whitened_music.py`: an isolated adaptation of the MUSIC engine uses a fixed geometry-only isotropic diffuse covariance, `sinc(2 f d / c)`, mixed with independent noise at diffuse fractions 0.5 / 0.9. Apply the same inverse-square-root transform to covariance samples and steering vectors, normalize transformed steering energy, and bound small eigenvalues at 5% of the largest. Retain the original unwhitened covariance event-power fit. No room parameters or measured true noise covariance are supplied. This is an experimental approximation, not an exact model of the simulated early reflections. At fraction 0.5, room precision is 93.2 / 86.6 / 90.4 / 91.5%; fraction 0.9 does not improve that tradeoff. No setting solves the observed problem. The production MUSIC module remains unchanged.

Each alternative's 864 unmodified controls reproduces baseline matching; all zero-source controls remain event-free. The band comparison has 4,320 calls and the whitening comparison 2,592 calls, sharing the same consumed episodes. These repeated comparisons are development diagnosis, not accumulating independent evidence of qualification. The extended renderer and inverse-STFT boundary are covered by 21 passing qualification integration tests.

**Project-level decision:** continue acoustic work before 07.2. Improving parallel execution now would not improve simultaneous indoor sensing, which the user identifies as the product priority. The longer-history hypothesis has now been tested and is insufficient; increasing context again is not the selected next action. The next substantive comparison must address direct-source versus reflected-arrival selection, rather than repeat the rejected loading/bandwidth/fixed-diffuse-model adjustments. Prefer an established approach with explicit source-event selection; any custom adaptation must earn its maintenance cost through measured gains. The whole original 04.4 acoustic objective remains incomplete. No correction, expanded operating domain, physical validation or new GPU qualification is claimed.


### Evidence Coverage and Handoff

The current experiment page preserves the initial candidate review, successive corrections and independent evaluations, the bounded reference integration and actual consumer/GPU outcome, and every subsequent progressive comparison. Full numerical outputs below are local ignored evidence under `build/qualification/doa/04_4/`; the wiki's findings are versioned, but those JSON files and prototype scripts are not included in Git. Preserve or transfer that evidence directory when a future worker needs the complete numerical records on another machine.

| Report | Coverage |
| --- | --- |
| `progressive-baseline.json` | All 11 paired acoustic stages, four geometries, zero/one/two-source controls; 3,168 calls. |
| `progressive-distance.json` | Matched direct and room controls at 0.5 and 1 m; 1,152 calls. |
| `progressive-loading.json` | Four model-order loading settings on three stages; 3,456 calls. |
| `progressive-power.json` | Covariance powers without spatial contrast on three stages; 864 calls. |
| `progressive-selection.json` | Seventeen post-filter comparisons using stored baseline/power predictions. |
| `progressive-wpe.json` | No-processing control and two short-context WPE settings; 2,592 calls. |
| `progressive-wpe-history.json` | Control and four longer-history WPE settings; 4,320 calls. |
| `progressive-band.json` | Control and four causal frequency-band choices; 4,320 calls. |
| `progressive-whitening.json` | Control and two fixed diffuse-covariance choices; 2,592 calls. |

These call counts must not be summed as independent evidence: candidates, source counts and acoustic stages reuse paired development episodes. Full row reports retain predictions, truth/matching, false events, misses, counts, angular errors, abstentions and timing; the post-filter report points to its source reports and stores comparison summaries. No later correction was retained, so no new independent qualification or physical-validation claim follows from these studies.

The controlled room-only comparison demonstrates that adding reflections changes observed performance. It does not establish that every false event is a particular physical echo, that source counting is the only failure mechanism, or that a custom algorithm is necessary. Direct-source versus reflected-arrival selection is a motivated research direction, not a proven unique remedy. The handoff objective is to find a suitable existing approach and implement a practically useful planar/3D improvement with unknown source count. Merely proposing another method, repeating rejected parameter adjustments, or treating the bounded reference GO as full indoor qualification does not complete that objective.

## Indoor candidate implementation and comparison

The implementation restarts from clean `main` at `8bc9c9f`, with 07.2 excluded. `indoor_protocol.json` crosses target RT60 0.2/0.3 s with 0/3/6 dB imbalance at 70°, 20 dB SNR and 1.5 m, and retains direct-path and harder controls. It is a development protocol using consumed assets, not the independent confirmation partition. The new runner reuses the progressive renderer, acoustic measurements, assignment and summaries. Admission now explicitly checks both correctly localized sources without extras and total count accuracy; exact cardinality alone cannot pass a wrong-direction pair. Reports also retain the matched truth indices so second-source recovery is measurable without passing truth into an estimator.

### Published alternatives and implemented adaptations

- [Li et al., DP-RTF sparse localization](https://team.inria.fr/perception/files/2018/03/dprtf_multispeaker-final.pdf) and [online RLS/EG localization](https://arxiv.org/abs/1809.10936) motivate direct-path CTF cross-relations, two-reference consistency checks and a sparse complex-Gaussian mixture over directions. The [authors' MATLAB reference](https://github.com/Audio-WestlakeU/OnlineSSL_DPRTF_EG) is not imported or copied into the SDK. The independent NumPy trial uses geometry-derived omnidirectional templates, a circular or uniform spherical grid, window-local RLS and batch exponentiated-gradient likelihood/entropy optimization. It omits tracking and the speech-specific noise-minimum gate because continuous non-speech is required. An explicitly separate adaptation adds a uniform background component; it is not an unchanged reproduction of the published complete system.
- The [SRP review, section 5.4](https://arxiv.org/html/2405.02991v2) motivates weighted histograms of time-frequency directions. The implemented trial weights narrowband votes by spatial agreement, with a development confidence exponent. It uses the same angular-neighborhood event extraction in planar and 3D geometry. This is an implementation of the reviewed approach family, not a claim to reproduce Hadad and Gannot's exact confidence statistic.
- [X-SRP's multisource class](https://raw.githubusercontent.com/egrinstein/xsrp/main/xsrp/multi_source_srp.py) is incomplete. The [LOCATA DPD pipeline](https://arxiv.org/pdf/1812.04942) uses a supplied cluster count in its final stage. Neither provides the required ready-to-use unknown-count replacement.

All trials receive only mixture samples, microphone positions and sample rate. Direction grids, neighborhoods and suppression use angular distance, including poles and the azimuth seam. Neither two-source capacity nor persistent identities are imposed. These NumPy/SciPy/PyRoom implementations run on CPU; no GPU-capable workload is being silently redirected to CPU.

### Initial paired screening

`build/qualification/doa/04_4/indoor-candidate-comparison.json` contains 108 paired cases and 432 estimator calls: one episode per content/geometry, three stages, counts 0/1/2, and four candidates. This small screening is sufficient to expose failures of these settings; it cannot establish that an entire published family is unsuitable. On joint RT60 0.3 s / 6 dB imbalance, both-source recovery without extras is:

| Candidate | Triangle | Square | Raised | Tetrahedral |
| --- | ---: | ---: | ---: | ---: |
| Unchanged MUSIC, 250 ms | 66.7% | 33.3% | 33.3% | 0% |
| Weighted SRP histogram, 250 ms | 33.3% | 33.3% | 0% | 0% |
| DP-RTF sparse mixture, 250 ms | 33.3% | 33.3% | 0% | 0% |
| DP-RTF with background component, 750 ms | 33.3% | 33.3% | 0% | 0% |

The plain DP-RTF mixture produces false events in 6–9 of nine noise-only controls per geometry. The background component removes these control events but leaves weak-source misses and does not repair triangle precision. No candidate in this screening is admitted. Parameters, raw predictions and acoustic measurements are in the report; different settings and intermediate prototypes remain ignored development evidence, not maintained runtime paths.

### Dereverberation follow-up in progress

The targeted NARA-WPE follow-up tests an earlier prediction delay (8 ms rather than the previous 24 ms), FFT 256 / hop 64, ten taps and three iterations, on 750 ms of supplied past audio. Extending MUSIC's own covariance context to 750 ms and FFT to 1024 gives a measurable development improvement. `indoor-wpe-development.json` contains eight episodes per content/geometry, 864 paired cases and 4,320 calls. At rejection threshold 0.010, joint RT60 0.3 s / 6 dB both-source recovery changes from 62.5/54.2/33.3/12.5% for unchanged MUSIC to 83.3/95.8/83.3/70.8% for triangle/square/raised/tetrahedral respectively. These are consumed development episodes; threshold comparisons are development calibration, not independent confirmation.

This setting is not promoted: tetrahedral pair recovery is below target, 3D compute exceeds the reference budget, and the development transition probe measures 650–750 ms for a two-to-one change. Exponential temporal weighting reduces that delay but worsens some static results. Twenty-one uncorrelated and 21 diffuse-noise windows per geometry produce no events with the tested WPE/coarse-grid trial, but this is not the required final background qualification. WPE settings, localization grids and temporal weighting differ between these probes and must not be combined into a fictitious single passing candidate. The next selection still requires one fixed implementation passing the complete quality/response comparison and fresh confirmation before common-consumer integration.

### Group-sparse covariance selection and confirmation freeze

The next established alternative is nonnegative group-sparse covariance fitting: [Pejoski and Kafedziski, 2014, equation (9)](https://journal.telfor.rs/Published/Vol6No2/Vol6No2_A6.pdf). Each direction has independent nonnegative power at each frequency, with a shared group penalty across frequencies. Unlike a common-power spectral model, this accommodates different source spectra. The isolated NumPy implementation uses standard ADMM, checked against a nonnegative orthogonal closed-form solution. Geometry-derived steering atoms work in planar and 3D arrays. Explicit adaptations are frequency normalization and thinning, unpenalized white/diffuse noise atoms, finite iterations, angular peak rejection, and preprocessing with the existing [NARA-WPE implementation](https://github.com/fgnt/nara_wpe). This is a published optimization approach with documented adaptations, not a new custom source-counting algorithm.

`indoor-group-joint-development.json` contains eight consumed episodes per content/geometry, 3,456 paired cases and 6,912 estimator calls across twelve conditions. The chosen setting uses 750 ms supplied past audio, WPE FFT 256 / hop 64 / delay 2 / six taps / three iterations, and spatial FFT 1024 / hop 128. Up to 48 active frequency bins between 300 and 6,000 Hz use a relative energy floor of 0.0001. The spatial dictionary has 72 circular or 642 uniform spherical directions. ADMM uses rho 1, at most 100 iterations and float32 algebra; the penalty is 0.03 times the square root of the frequency-bin count. Ten-degree angular smoothing/refinement and final 30-degree angular suppression have no source-count cap.

Development selection of rejection threshold 0.015 passes all 24 joint geometry/condition quality gates. `indoor-group-selected-development.json` derives this threshold comparison from the recorded predictions; it is calibration, not another independent experiment. At RT60 0.3 s / 6 dB, both-source recovery without extras is 87.5/95.8/87.5/95.8% for triangle/square/raised/tetrahedral, with precision 100/100/98.6/100%. The same threshold produces zero events in 100 uncorrelated and 100 diffuse-noise development windows plus silence per geometry (`indoor-group-idle-scores.json`). Weak-speech misses remain visible; development aggregates do not establish general speech robustness.

`indoor_confirmation_protocol.json` fixes this implementation before evaluating two fresh blocks: 12 episodes per content/geometry in each block, 16 previously unused speakers split eight/eight, and new room/orientation/noise seeds. All acoustic variations of an episode remain in its block. Neither block has been scored at this freeze. The candidate is still isolated and is not yet selected for public runtime use.

The user explicitly accepts investigating a slower mode for relatively stable sources when reliability improves substantially. The 50 ms compute and 350/500 ms response references remain comparison points, not silently revised requirements. The earlier group-covariance development transition probe distinguishes 750 ms memory from measured response: some source removals approach 0.9 s, while many onsets take a few hundred milliseconds. Final timing must use the frozen threshold and include room tails, weak-source removal, 0↔2 and direction replacement. Stable-source usefulness would be a bounded 04.4 result, not a change to the whole project's objective or physical/general-indoor validation.

### First independent outcome and revised freeze

The first two blocks (`indoor-confirmation-a.json`, `indoor-confirmation-b.json`) contain 24 episodes per content/geometry, 5,184 paired cases and 10,368 calls. Twenty-three of 24 geometry/condition quality gates pass. Tetrahedral RT60 0.3 s / 6 dB fails precision at 94.7%, although recall is 99.5% and both-source recovery without extras is 84.7%. On simultaneous speech, exact clean pairs in that condition are 22/24, 20/24, 23/24 and 15/24 respectively. Extra directions, rather than widespread loss of the weak source, dominate the tetrahedral failure. This is a failed admission, not a rounded-up pass.

Both first blocks are now consumed evidence. Raising the single, geometry-independent rejection threshold to 0.025 preserves all original joint development gates and removes most extras in the consumed first confirmation. It does not change WPE, the optimizer, grid, source-count policy or any acoustic-condition selector. `indoor_confirmation_v2_protocol.json` fixes that revision before a new pair of blocks: 16 entirely new dev-clean speakers, 48 utterances and new seeds. The first protocol and reports remain intact. Shared computation has been relocated behind the isolated comparison; 36 paired development inputs reproduce the first frozen numerical outputs within 1e-12 at its explicit threshold. The public maintained localizer still uses its existing reference pending fresh confirmation.

The first-block response diagnostic at threshold 0.015 has zero background events in 100 white and 100 diffuse windows per geometry, but shows the real reactivity limitation: finite response p95 is about 0.92–0.97 s, maximum 1.35 s, and two of 432 transitions lack two consecutive correct sets within their 1.5 s phase. These results cannot qualify the revised threshold; its response is measured separately. They support a stable-source use case only, not the original rapid-update reference or general weak-speech robustness.
