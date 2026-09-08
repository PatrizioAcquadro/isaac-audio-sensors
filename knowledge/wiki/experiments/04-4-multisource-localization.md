# Subphase 04.4 — Multisource Localization Qualification

## Objective and Status

**Partial implementation; NO-GO for production integration.** Candidate comparison and independent simulated evaluation are implemented. Neither the planar nor the rank-3 role passes all fixed gates. Unknown-count zero/one/two-source localization remains the qualification objective. Two sources are a milestone, not an interface capacity. Physical multisource performance, persistent tracking, separated audio, and scalable Lab perception are outside this experiment. See [[implementation_phases/04-observed-direction-estimation|Phase 04]].

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
