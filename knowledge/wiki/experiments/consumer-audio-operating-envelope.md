# Consumer Audio Operating Envelope

Measured 2026-10-08 for [[implementation_phases/squadbot-audio-runtime-readiness|SDK readiness 7.1]].
This is a bounded simulated quality screen. It preserves the separation between
runtime compatibility, scalar/CUDA agreement and perceptual usefulness.

## Runtime and inputs

SDK `3.0.0` remains unreleased. Baseline `e7c3b48`; the reusable evaluation
extension starts at `97d92a7`. Executable perception/propagation and public schemas
are unchanged. The local runtime is Isaac Sim
`6.0.1-rc.7+release.42383.32955d8d.gl`, Isaac Lab `3.0.0` at `2e44ddb2e1`,
RTX 4090, driver `580.178.04`, and Torch `2.10.0+cu128`. Sim's native NumPy,
Torch, PRA `0.10.1`, SciPy and SoundFile remain authoritative. Auditok `0.5.2`
and NARA-WPE `0.0.11` use isolated existing module paths; the host virtualenv is
not inserted wholesale into Isaac's path. The first Isaac attempt omitted
Auditok, failing 22 cases; the corrected complete lane passes 251 cases.

Each of six conditions has three eight-second episodes, using 1.5, 2.25 and 3 m
array-center distances and different natural utterances/trajectory phases.
The four omni microphones are ordered
`(-.033,-.033,0), (-.033,.033,0), (.033,.033,0), (.033,-.033,0)` meters.
Acquisition uses 480 sample-aligned intervals at 60 Hz; perception consumes
80 non-overlapping 100 ms windows at 16 kHz. Auditok threshold is -60 dBFS,
localization context 750 ms, CUDA observation capacity 32 and candidate
capacity two.
The scalar reference remains uncapped; no case reaches the CUDA capacity.
No source count or private source information enters perception.

Retained CMU Arctic clips are `S1_aew1/aew3`, `S1_axb4/axb6` and `S1_aew2/aew3`
from `local/r10/preparation/audio/`. Utterances begin at .3 and 4.4 s, preserving
their natural pauses. Existing source normalization is -35 dBFS active received
level at 1 m in free field; this is a simulation amplitude, not calibrated SPL.
Independent microphone noise is -65 dBFS RMS, with seeds 7100–7102. The competing
voice starts at 2 s and remains stationary, 90 degrees from the target
trajectory center; instantaneous separation ranges from 55 to 125 degrees.
Mixture peaks are below full scale; PCM and references are finite and aligned.
Original inputs remain unchanged.

Source motion is a smooth constant-radius arc with maximum speed 1 m/s.
Receiver yaw is `-60 + 90*sin(t + phase)` degrees, reaching 90 degrees/s.
Initial free-field source angles are 70, 110 and -110 degrees. The room uses a
narrower 30 +/-10 degree arc to keep every source inside the existing
6 x 5 x 3 m `E1_R05.usda` fixture. Thus room/free-field differences do not isolate
reverberation alone. Receiver position remains fixed; this screen does not cover
translating receivers, elevation, different array geometries or robot dynamics.

Free-field signals use Analytic's maintained continuous motion/arrival path.
The room uses base Geometry direct/specular order 3, a 1 s response horizon,
60 Hz pose updates, and no diffuse/NLOS options. Its material recipe is an
unconditioned nominal .5 s decay seed, not a measured RT60. A separately owned
order-zero Geometry stream supplies the direct-energy scoring reference.
This measures the current renderer's received observations; it does not qualify
full-room moving pressure, faster-update fidelity or physical acoustics.

## Scoring and preservation

Received total/direct powers are compared with measured noise power per 100 ms
window; +/-3 dB sensitivity is retained. Total received presence includes tails.
Only directly resolvable contributors enter directional matching; received tails
remain unresolved activity. One-to-one matching uses current receiver-local
directions and a 20 degree tolerance. References use the current reception pose
and bounded retarded source position, never a best retrospective time shift.

The table pools fully resolvable active windows after the common first seven
updates; silence cannot increase its complete-set rate. Precision/recall also
retain false events during resolvable quiet windows. Angular p95 covers assigned
directions, including incorrect assignments; extra and missing events are
reported separately. Longest errors are calculated within episodes.
Full warm-up-inclusive rows and summaries remain in the report.

Dynamic same-PCM preservation passes on all 1440 updates: activity 100%, counts
1439/1440 (99.93%), retained-direction difference p95 .0000178 degrees.
The existing gates remain 100%, >=97% and <=5 degrees respectively. The sole
count difference is room episode zero at 6.4 s: scalar reports a weak second
event while CUDA reports one. Scalar sparse fitting reaches its 100-iteration
limit without convergence. A separate single-episode replay reproduces the same
CUDA counts on every window, including that discrepancy; the 18-case batch
introduces no count difference relative to the solo run. This remains a bounded
numerical discrepancy, not erased by claiming perfect preservation.

The default 36-input/1440-update stationary comparison still passes all four
layouts with 100% activity/count agreement and worst direction-difference p95
.0001742 degrees. Existing batch isolation, clocks, reset and tensor contracts
pass the complete Isaac lane. Live Sim with native Geometry and two-environment
Lab square-array acquisition at 60 Hz/10 Hz pass; the latter preserves scalar
counts and directions. Those runtime controls do not validate head control or
the new moving-source acoustic field end to end through a robot.

## Quality results

CUDA outcomes; scalar quality is essentially the same under the paired gate.
Each row contains three episodes. These correlated windows and reused utterances
are descriptive results, not population estimates or independent confirmation.

| Condition | Active windows | Complete sets | Exact count | Precision / recall | Angular p95 | Longest incorrect set |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Static source/receiver | 187 | 97.9% | 97.9% | 95.3 / 97.9% | 1.55 deg | .2 s |
| Moving source, fixed receiver | 187 | 96.8% | 97.9% | 94.3 / 96.8% | 16.31 deg | .2 s |
| Rotating receiver | 187 | 49.7% | 85.6% | 52.8 / 61.0% | 41.67 deg | 1.7 s |
| Joint motion | 187 | 59.9% | 92.0% | 59.3 / 64.7% | 37.86 deg | .9 s |
| Joint motion, Geometry room | 187 | 34.2% | 49.2% | 40.1 / 66.8% | 38.42 deg | 2.2 s |
| Joint motion, competing voice | 213 | 49.3% | 81.7% | 54.8 / 61.3% | 41.01 deg | 1.5 s |

Room tails contribute three post-warm-up unresolved received windows, excluded
from resolved directional success without being relabeled silent. No ambiguity
observations or capacity truncation occur in these four-microphone cases; incorrect
bearings can still be emitted. Existing stereo ambiguity tests preserve the
separate unresolved/candidate contract.

There are nine directional received-onset segments per condition, twelve with
the competing voice. Every segment obtains at least one matching direction;
onset-response p95 is 400 ms (360 ms in the room). Mixture-activity onset p95 is
200 ms, with no missed segments. These responses measure onset-bin start to
observation-bin end at 100 ms resolution, include initial warm-up and can occur
while extra/wrong events are present. They do not establish continuous tracking,
persistent identity, wall-clock response or a closed-loop reaction guarantee.

## Disposition and reproduction

### Subsequent scoring correction (2026-10-08)

The original 7.1 report remains unchanged. The follow-up evaluator maximizes
the number of one-to-one pairs inside 20 degrees before minimizing total angular
error, retaining invalid assigned angles in p95. At `distractor_1`, 2.4 s, the
old minimum-angle assignment counted zero matches; the corrected assignment
retains the valid 17.3503-degree pair (one miss and one extra remain).
Rescoring saved directions, without new inference, changes competing-voice
precision/recall from 54.8/61.3% to 55.12/61.62% and angular p95 from 41.01 to
39.946 degrees. Complete-set rates and the other scenario metrics above are
unchanged. These are corrected historical metrics, not improved perception.
The separate report is `build/validation/sdk-dynamic-quality/historical-rescored.json`.
The evaluator's `--rescore-report` option reproduces it from the original report
and received inputs; targeted tests include the failure and exhaustive small
rectangular assignments.

The provisional listening profile is 16 kHz square-array, free-field Analytic,
fixed receiver, explicit -60 dBFS threshold, `doa_enabled=True`, current
750 ms localizer and 100 ms
observations. It supports bounded follow-up trials for one audible voice moving
up to 1 m/s in the tested trajectories. Rapid receiver yaw, moving-room listening
and competing voices remain unsuitable for a reliability claim. A robot may need
to acquire a cue while stationary, but choosing that behavior and verifying it
belongs downstream. No production localizer correction or selectable research
candidate was introduced.

7.1 closes as an assessment with these limits. 7.2 must measure acquisition,
perception, buffering and delivery costs under its own representative load;
overlapping validation/replay timings here are not a latency or throughput gate.
The full dynamic domain remains unqualified even though the integration gate
passes. No physical capture or partner/policy validation was performed.

Run from the repository root with the configured Isaac Lab launcher and the
isolated Auditok/NARA paths. The local preparation script accepts explicit
output and native-library paths:

```bash
IAS_READINESS_PATH="$PWD/src:$PWD/build/validation/phase06_1/runtime_deps:$PWD/build/validation/continuity_runtime_deps"
PYTHONPATH="$IAS_READINESS_PATH" "$ISAAC_LAB_ROOT/isaaclab.sh" -p \
  local/sdk-runtime-readiness/prepare.py --out local/sdk-runtime-readiness \
  --geometry-library build/qualification/r9/steam-audio/core/build/r9-release/src/core/libphonon.so \
  --specular-library build/native/libias_specular.so
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH="$IAS_READINESS_PATH" \
  "$ISAAC_LAB_ROOT/isaaclab.sh" -p tools/validation/lab_perception.py \
  --inputs-dir local/sdk-runtime-readiness/received --layouts square \
  --input-glob '*_{layout}_*.npz' --include-rows \
  --out build/validation/sdk-readiness-7.1/operating-envelope.json
```

Omit layout/glob options and use `local/lab/received_stationary/` for the unchanged
stationary default. The tool also accepts an explicit `--threshold-dbfs`;
this screen did not retune it. Core/Geometry propagation remains CPU-side because
those maintained producers do not support CUDA; received-mixture inference uses
the actual GPU. There is no implicit CPU fallback.

Ignored `local/sdk-runtime-readiness/` retains preparation, assets and 18 PCM
archives. `build/validation/sdk-readiness-7.1/` contains full dynamic/stationary
reports, pooled summaries, host/Isaac logs, live Sim/Lab reports and diagnostic
attempts. `make check` and the complete Isaac lane cover the implementation.
The live Lab command uses `--perf-envs 2 --perf-steps 5 --perf-sources 1
--perf-layout square --perf-substeps 6 --perf-reference-check
--perf-reference-steps 2`; live Sim receives the same native-library arguments.

[[topics/isaac-lab-integration|Lab contracts]] ·
[[decisions/product-boundary-and-compatibility|Consumer migration]] ·
[[index|Wiki index]]
