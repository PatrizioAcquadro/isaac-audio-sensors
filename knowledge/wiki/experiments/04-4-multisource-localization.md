# Subphase 04.4 — Multisource Localization Qualification

## Objective and Status

In progress. Qualify unknown-count zero/one/two-source localization in simulation for planar and rank-3 arrays. Two sources are a milestone, not an interface capacity. Physical multisource performance, persistent tracking, separated audio, and scalable Lab perception are outside this experiment. See [[implementation_phases/04-observed-direction-estimation|Phase 04]].

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

The nominal domain is only an initial feasibility milestone. Robust selection requires the difficult-condition results and a justified quality/latency/maintenance comparison. Numeric final gates will be recorded after development and before opening the final partition; the earlier proposed thresholds are not treated as accepted requirements.

## Failure and Integration Policy

Integrate only qualified roles. A planar GO does not complete 04.4 or cancel 3D work. Diagnose failed roles and evaluate corrective changes or alternative candidates; after evaluation-informed changes, use fresh independent final cases. Distinguish measured NO-GO from missing data, runtime dependencies or untested conditions. Do not lower gates or narrow the objective after observing final results.

The minimal sequence-returning common boundary is designed after candidate evaluation. Reuse observation/frame schemas where sufficient; preserve per-event ambiguity, optional scores, causal context, deterministic ordering and stream resets. Keep global activity distinct from event scores and avoid persistent identities.

## Artifacts

Isolated working directory: `build/qualification/doa/04_4/`. Downloaded native code, dependencies, audio and generated outputs are local evaluation material, not package contents. These CPU algorithms do not support GPU execution; GPU-capable supported-runtime checks use the verified RTX 4090.
