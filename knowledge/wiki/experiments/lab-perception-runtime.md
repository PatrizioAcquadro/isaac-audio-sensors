# Lab Perception Runtime

Recorded 07.2/07.3 evidence on RTX 4090 (2026-09-09/10), with later numerical
maintenance below. The maintained reference
and CUDA adaptation pass bounded same-PCM agreement; neither general moving-source
perception nor policy learning is qualified. [[implementation_phases/07-isaac-lab-observation-integration|Phase 07]]
owns implementation; [[topics/isaac-lab-integration|Lab Integration]] owns contracts.

## Workload and numerical decision

Free-field microphone mixtures, two explicit independent files, diversified fixed
poses, 16 kHz, 60 Hz acquisition, 10 Hz observations and 750 ms past context.
Practical batches use 30 synchronized uninstrumented updates after warm-up.
Measured work includes PCM/context, activity, WPE, localization and projection;
physics/rendering/learning, initialization and separate scalar checks are excluded.
Indoor validation uses independently supplied recorded PCM, not a GPU room engine.

Float32 WPE reduced a 256-copy update from ~541 to 134 ms but failed raised-array
numerical qualification: count agreement 78.125%, complete sets 79.6875%, versus
95.3125% reference sets. Restoring float64 restored 100% count agreement. It had
passed the smaller indoor subset, which was insufficient evidence. Float64 WPE
is retained for every geometry; spatial fitting keeps reference float32 arithmetic.

Final 36-input/1,440-update indoor comparison: 100% activity/count agreement,
direction-difference p95 <0.00018 degrees across triangle/square/raised/tetrahedral.
Misses/extras remain the scalar reference's errors. Per-environment floors,
convergence and normalized bearing ordering prevent batch/selection artifacts.

## Practical batches

| Copies | Planar mean/p95 ms | Raised mean/p95 ms | Peak Torch GiB planar/raised |
| --- | --- | --- | --- |
| 2 | 40.2 / 41.4 | 42.4 / 44.0 | 0.07 / 0.17 |
| 16 | 62.7 / 63.9 | 90.9 / 99.1 | 0.44 / 0.64 |
| 32 | 86.9 / 87.8 | 142.6 / 144.4 | 0.87 / 1.18 |
| 64 | 140.4 / 142.6 | 252.6 / 253.7 | 1.71 / 2.25 |
| 128 | 250.1 / 253.4 | 471.7 / 475.9 | 3.41 / 4.39 |
| 256 | 462.3 / 481.5 | 935.6 / 965.3 | 3.44 / 4.43 |

All 996 practical same-PCM comparisons preserve counts; maximum direction
difference 0.254 degrees planar/4.143 raised. An extra 1-degree maximum-only
diagnostic failed (3.41 degrees), while the predeclared 97% count/5-degree p95
criterion passed; both results remain visible. Nominal raised complete sets range
92.19–100%; scalar reproduces extra events. Partial reset costs 2.8–4.0 ms plus
subsequent normal warm-up. Memory includes resident fixtures, not total driver VRAM.

16 copies are a measured interactive starting point, with little raised-array
real-time headroom for other work. At 128 copies, aggregate throughput is near
256-copy throughput while each environment advances faster. Ten simulated minutes
per copy extrapolate to ~25/47 wall minutes planar/raised for audio alone, not a
completed training run or an independent-sample/learning-success claim.

## Exploratory large batches and limits

Initial 4096-copy active runs measured ~6.64 s planar/12.98 s raised per 100 ms
update (simulated/wall ratios 0.0151/0.0077). Raised complete sets reached 96.48%,
with 144 extra-event environments; this is not uniform 3D accuracy. WPE and sparse
fitting dominate. Earlier ~0.2 ms empty-entity results do not describe active audio.
The user explicitly removed 4096-copy real-time as a closeout requirement.

Entity propagation is quasi-static between physics poses, unlike Core's retarded
trajectory integration. Gaps >100 ms discard unavailable history and clear context.
Free-field throughput and indoor same-PCM inference are distinct qualifications;
weak speech, extra events and ~1–1.5 s response remain limits. No float32 shortcut,
shortened context, WPE removal, tracking or learner was introduced to improve scores.

## Reproduction

Maintained `tools/smoke/live_isaac_lab_audio_smoke.py` supports `--perf-envs`,
`--perf-layout`, `--perf-steps`, `--perf-substeps` and `--perf-reference-check`.
Use the supported Isaac launcher, actual GPU and isolated optional dependencies;
[[topics/validation-and-release|Validation and Release]] owns runtime setup.

Reports: `build/validation/phase07_2/practical/`, `indoor-parity-final.json`,
`double-{256,1024,4096}.json`, `double-raised-4096.json` under `phase07_2/`;
07.3 preservation at `build/validation/isaac_audio_sensors/lab_received_parity.json`.
Local source/recordings and rejected reports remain protected. Historical detailed
commands/table derivation are recoverable from Phase 07 at `5cfe48d`.

## Measurement reliability correction (2026-09-16)

R10 same-PCM diagnostics isolated unstable WPE normal equations in nearly duplicate
channels, including exact 45-degree free-field input. Scalar and CUDA could both
return finite but erroneous events. Weighted QR/pseudoinverse solves the same WPE
objective without squaring conditioning; float64 peak sums and stable ties address
a separate equal-neighborhood count discrepancy. No perception threshold, context,
iteration count or acoustic model was retuned. The
[[topics/isaac-lab-integration|Lab contract]] owns the implementation details.

The 27 affected tests pass on the actual RTX 4090, including eight symmetric direct
cases, two equal-score plateau regressions and existing batching/reset/capacity
controls. The 15 affected scalar localization/event tests also pass. Historical
tables above describe the preceding solver and are not current throughput promises.
Fresh same-PCM evidence is stored separately under
`local/r10/08_2_step3_measurements/`; numerical agreement does not qualify acoustic
fidelity or general moving-source perception.
