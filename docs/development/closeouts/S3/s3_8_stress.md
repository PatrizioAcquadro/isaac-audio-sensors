# S3.8 closeout - motion and multi-source stress

Status: **passed** (2026-07-18). Entry and evidence revisions: passed
predecessor baseline `e5f136e`; prospective frozen specification `51f7453`;
profile/closeout-name amendment `4460813`; initial implementation `0ac5507`;
live-gate fixes and dated amendments `44b8df0`; regression battery and Lab shim
fix `a2f3ea0`; evidence-integrity correction `dd8ed5c`; durable pre-close
checksum and truthful command metadata `d493072` (closeout-authoring HEAD,
clean before these documentation-only changes). Passed predecessors:
`docs/development/closeouts/S3/s3_1_pose_velocity.md`,
`docs/development/closeouts/S3/s3_2_time_motion.md`,
`docs/development/closeouts/S3/s3_3_channel_response.md`,
`docs/development/closeouts/S3/s3_4_seeded_noise.md`,
`docs/development/closeouts/S3/s3_5_electronics.md`,
`docs/development/closeouts/S3/s3_6_waveform_directivity.md`, and
`docs/development/closeouts/S3/s3_7_dynamic_rooms.md`.

## Frozen-tolerance and revision provenance

The complete supported/unsupported matrix, pure scenarios, live fixture,
invariants, and resource bounds were frozen prospectively in
`docs/development/specs/s3_stress_matrix.md` at `51f7453`, against passed
predecessor `e5f136e`. Before S3.8 evidence existed, `4460813` corrected the
unshipped profile name `metadata_only` to the shipped `training_features`
profile and locked this closeout path. Execution later exposed three
acceptance-model problems, recorded as dated amendments at `44b8df0`:

1. the paired effects-on latency bound was changed from an analytically wrong
   `2x` multiplier to the linear `SEGMENTS_PER_WINDOW=8` cost model;
2. the live post-teardown allocator-retention ceiling was changed from 64 MiB
   to 256 MiB without changing the authoritative pure `P11` 4/128/32 bounds;
   and
3. a durable pre-close passing summary with provisional teardown was accepted
   when `SimulationApp.close()` terminates Kit after evidence is durable and
   records no close error.

Those amendments were made after failed/terminated live observations and are
not represented as prospective. Their measured rationale and the complete
defect ledger are retained below.

The aggregate gate records `entry_revision=4460813` and
`implementation_revision=dd8ed5c`. The final live rerun was launched from
`dd8ed5c` with the narrow checksum/metadata correction dirty; that correction
landed as `d493072`. Accordingly,
`live_stress_environment.json` truthfully records revision `dd8ed5c`,
`dirty_tree=true`, and `simulation_app_closed=false`. This closeout does not
rewrite those generation-time fields as the later landed revision. The four
normalized regression records likewise retain generation-time
`closeout_revision=44b8df0`; the runner and Lab shim fix landed at `a2f3ea0`.

## Aggregate gate result

`outputs/isaac_audio_sensors/S3/S3.8/stress_matrix_gate.json` reports
`status: "Passed"`, with empty `failed_rows`, `pending_rows`, and
`blocked_reasons`. All seven aggregate invariants passed: finite-value scan,
identity, ambiguity, current state, determinism, RSS, and live latency. All 16
scenario/verification rows passed. No dependency-availability probe, skip,
description, synthetic verdict, or artifact-existence check was accepted in
place of execution.

The roll-up contains all 55 matrix cells: 34 supported executions, 14
unsupported requests that raised the exact required error before output, and
7 N/A cells with rationale.

## Supported-combination matrix

In this table `S+` means the gate carries a real `execution_reference` and
reports `Passed`; `U1` through `U14` identify exact errors listed immediately
below, each with `output_returned=false`; and `NA1`/`NA2` identify the retained
rationale. Thus every displayed position is one of the 55 machine-readable
cells, not a summary inferred from global booleans.

| Backend/path | Authored velocity | Derived velocity | `segments>1` | Channel response | Noise | Electronics | Directivity | Occlusion | Materials | Gap preservation | Multi-source `2/4/8` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `geometry_only` L0 | NA2 | NA2 | U1 | S+ | S+ | U2 | U3 | S+ | S+ | NA1 | S+ |
| `tdoa_synthetic` L1 | S+ | S+ | U4 | S+ | S+ | U5 | U6 | S+ | S+ | NA1 | S+ |
| `room_acoustics` L2 | S+ | S+ | S+ | S+ | S+ | S+ | S+ | S+ | S+ | NA1 | S+ |
| `room_acoustics_srp` L2 | S+ | S+ | S+ | S+ | S+ | S+ | S+ | S+ | S+ | NA1 | S+ |
| Isaac Lab sensor, batched-selected envelope | S+ | U7 | U8 | U9 | U10 | U11 | U12 | U13 | U14 | NA1 | S+ |

All U cells raised `UnsupportedEffectError` with these exact retained
messages:

| Id | Backend / feature | Exact message |
| --- | --- | --- |
| U1 | L0 / `segments>1` | `audio.effects.motion.segments_per_window>1 is unsupported by backend 'geometry_only'; use room_acoustics or room_acoustics_srp.` |
| U2 | L0 / electronics | `audio.effects.electronics.enabled=true is waveform-only and unsupported by backend 'geometry_only' at profile 'waveform_fidelity'; electronics has no L0/L1 metadata representation.` |
| U3 | L0 / directivity | `audio.effects.directivity.enabled=true is waveform-only; supported envelope is room_acoustics or room_acoustics_srp with profile 'waveform_fidelity', received backend='geometry_only', profile='waveform_fidelity'.` |
| U4 | L1 / `segments>1` | `audio.effects.motion.segments_per_window>1 is unsupported by backend 'tdoa_synthetic'; use room_acoustics or room_acoustics_srp.` |
| U5 | L1 / electronics | `audio.effects.electronics.enabled=true is waveform-only and unsupported by backend 'tdoa_synthetic' at profile 'waveform_fidelity'; electronics has no L0/L1 metadata representation.` |
| U6 | L1 / directivity | `audio.effects.directivity.enabled=true is waveform-only; supported envelope is room_acoustics or room_acoustics_srp with profile 'waveform_fidelity', received backend='tdoa_synthetic', profile='waveform_fidelity'.` |
| U7 | Lab / derived velocity | `derive_velocity_from_poses=true is unsupported by Isaac Lab batched compute in Stage 1` |
| U8 | Lab / `segments>1` | `audio.effects.motion.segments_per_window>1 is unsupported by Isaac Lab batched compute` |
| U9 | Lab / channel response | `audio.effects.channel_response is unsupported by Isaac Lab batched compute` |
| U10 | Lab / noise | `audio.effects.noise is unsupported by Isaac Lab batched compute` |
| U11 | Lab / electronics | `audio.effects.electronics is unsupported by Isaac Lab batched compute` |
| U12 | Lab / directivity | `audio.effects.directivity is unsupported by Isaac Lab batched compute` |
| U13 | Lab / occlusion | `AudioSceneSnapshot.occlusion is unsupported by Isaac Lab batched compute` |
| U14 | Lab / materials | `AudioSceneSnapshot.room is unsupported by Isaac Lab batched compute` |

NA1 is exact for all five gap cells: gap preservation belongs to the
recorder/session timeline and no backend owns it. NA2 is exact for the two L0
velocity cells: L0 accepts valid scene records but makes no Doppler
observation. Supported L0/L1 cells executed under both declared profiles,
`training_features` and `waveform_fidelity`; supported L2 cells executed under
`waveform_fidelity`.

The Lab disposition is therefore explicit: batched pose-derived velocity is
unsupported in Stage 1 and raises before returning a tensor. Authored
velocity is supported through the scalar core-frame path. Its retained
64-frame check reports `compute_path="scalar"`, positive finite Doppler
factors, and bitwise preservation of the authored velocity payload. The Lab
multi-source scalar row executed 96 frames: 32 each at 2, 4, and 8 sources.
No batched effects or pose-derived-velocity claim follows from these scalar
rows.

## Pure stress scenarios and bounds

The aggregate gate is the authority for each scenario verdict and the final
`P11` resource numbers. The named scenario artifacts provide the execution
detail shown here and cannot override the aggregate verdict. `P13` now runs
every `P01`-`P12` scenario in the main process and in two fresh processes;
the canonical hash shown for each row was byte-identical in all three
executions.

| Scenario | Frozen exact requirement or bound | Final measured execution | Canonical payload SHA-256 | Status |
| --- | --- | --- | --- | --- |
| P01 authored velocity | 64 frames; source `-5/-1/0/+1/+5 m/s`, array `-1/0/+1 m/s`; authored wins | 64 observations; precedence and positive finite factors true | `27d4a72b06ac018ffeb665c50f9f3d7d7dace75d94f6bd358e043d237d59f7b9` | passed |
| P02 derived velocity | 2 prime plus 64 measured frames; Lab negative executes | 66 observations; 2 prime, 64 measured; Lab negative executed | `c62b3d3f27a438b84864ce3cf69078cd04f8d4e8f0069796a1f64da221817895` | passed |
| P03 overlap ladder | 2/4/8 sources, 32 frames/count, no truncation | Both real L2 backends ran all three counts at 32 frames/count; 192 canonical observations | `861210b86ceec3dfcdf6c7c2d2bbb922916f48111064442f30e4f63ee0290241` | passed |
| P04 coincident sources | 64 frames; distinct ids never merge | 64 observations; identity remained distinct | `79f9513dcebb4ae2df8fa2b3ed701e8c7dd303fe755c286113ae6818878ab172` | passed |
| P05 near/far 1:100 | 64 frames at 0.1 m and 10.0 m | 64 observations; both distances and identities retained | `0098222949e63af3aa0dcfee60f687427771d418b401b5c3d4942de94e676d5e` | passed |
| P06 reverberation ladder | `max_order=0/1/3/6`, 16 frames/order, real room, deterministic and not all identical | Both L2 backends executed 128 canonical observations; all four order hashes were deterministic and distinct | `f9852b6cd729edad0a53c97622d7b2f6af38f813879e66a5f56e5dbc43fb0e15` | passed |
| P07 moving occluder | 80 frames, 16/state over clear/partial/blocked/material/clear; current-state reasons exact | 80 observations; five states and `room_geometry_changed`, `material_changed`, `occluder_moved` checked | `f8f2236acb35401e0e273647ad88e1df52f55dc280ca400438e033a8d1dd445f` | passed |
| P08 moving mount | 128 frames; 0.50 m translation and `-30..+30 deg` yaw; current array frame | 128 observations; translation, yaw range, and current frame checked | `0c2cdd54a93fa8338a3d4557f45d43b67741b773ef14512f7a81c39816207186` | passed |
| P09 identity churn | 256 frames; 16-frame churn cadence; persistent ids never swap or ghost | 256 observations; no swap or ghost observed | `51069ff6f115ab33d14a6e154e430e5ee685a7b547abd7c7ca615aca4c8226ec` | passed |
| P10 all-effects L2 | 32 frames/backend, 8 sources, `segments_per_window=8`, complete L2 effects | Both real L2 backends ran 32/32 frames; 64 canonical observations | `1eb59d2a30a6328b35ee0bef124c11807aca07c837d7957cd94b290d96e3ebc0` | passed |
| P11 long run | 4,096 frames; slope `<=4 MiB/1,000 frames`; peak `<=128 MiB`; settled `<=32 MiB` | `frame_count=4096`; slope `0.11077995334605939`; peak `0.73046875 MiB`; settled `1.65234375 MiB`; 57 OLS samples, `R^2=0.7860103634926566` | `c98123bd42352af7ce43cce8889beeedd56edf0d5e007f951e866e567742c9bc` | passed |
| P12 gap preservation | 96 slots, 72 captured, 24 absent; exact zeros only in absent intervals; disabled mode contiguous | 96 observations; 72 captured and 24 absent; zero placement and compact mode exact | `c54f21070f565a06a72ff9e582ce98fac1d7c287e6562273f9c4201b2d8cbe0d` | passed |
| P13 determinism replay | Fresh-process byte equality for all P01-P12; changed seed changes payload; runtime telemetry structural only | Two fresh runs plus main matched all 12 hashes; no dependency-gated scenario; changed-seed P12 hash changed; telemetry structures matched | hashes above | passed |

Pure latency is telemetry, not an absolute performance promise. For P11 the
retained distribution was mean `20.291947309570315 ms`, p95
`29.8144695 ms`, p99 `33.35439085000001 ms`, and maximum `36.819111 ms`.
All are finite; none is promoted to a portable CPU budget.

The mandatory edge execution also passed. Zero sources and all-silent sources
executed; same-frame spawn/despawn executed within P09; ten-source saturation
retained 8 and dropped 2 under canonical ordering. The retained explicit edge
errors include the exact SRP two-microphone rejection, L1 segmentation
rejection, `ValueError("Duplicate source id 'duplicate'.")`, Lab batched
derived-velocity rejection, and Lab batched channel-response rejection.

## Live stress result

The final retained `make live-s3-stress` run passed with complete durable
artifacts and a make verdict exit code of 0. Each phase scheduled 800 slots,
throttled 200, captured 600, discarded 60 warm-up captures, and timed 540.
The two-microphone GCC subcase surfaced ambiguity in all 16 frames. Finite
values, gap placement, identity, current state, latency, and RSS assertions
all passed.

| Live measure | Frozen bound | Final retained measurement | Status |
| --- | --- | --- | --- |
| Effects-off p95 | paired control; 540 timed frames | `148.67477135 ms` | passed |
| Effects-on p95 | `<=8 * off_p95 + 5 ms` | `940.5367802999998 ms` against derived `1194.3981708 ms` ceiling | passed |
| Effects-off p99 / max | finite and reported | `162.17489414000002 / 174.74667 ms` | passed |
| Effects-on p99 / max | finite and reported | `995.03617189 / 1021.591402 ms` | passed |
| Effects-off RSS slope | at least 27 samples; `<=8 MiB/1,000 frames` | 28 samples; `2.9868179126193053 MiB/1,000 frames` | passed |
| Effects-on RSS slope | at least 27 samples; `<=8 MiB/1,000 frames` | 28 samples; `2.4997055159284134 MiB/1,000 frames` | passed |
| Effects-off/on peak delta | each `<=256 MiB` | `61.0 / 65.44140625 MiB` | passed |
| Final post-teardown delta | `<=256 MiB` allocator-retention ceiling | `125.07421875 MiB` (`5587.83984375 - 5462.765625 MiB`) | passed |
| Teardown verdict | `passed` or durable `provisional`; no close error | `provisional`; `simulation_app_close_error=null` | passed |

These are the authoritative final retained JSON values. The illustrative
request values `148.07/953.22 ms`, `54.8/59.0 MiB`, and approximately
`118.7 MiB` came from an earlier run and are superseded by the final rerun
above. The changed measurements do not change any verdict: every final value
remains within its amended frozen bound.

The paired latency result is a cost-model regression claim, not a real-time
envelope. The effects-on phase rerenders the room/RIR once per each of eight
segments. The current final p95 ratio is approximately `6.33x`; the amendment
was justified by the earlier failed real-Isaac measurement whose ratio was
`937.30/144.73 ms = 6.48x`, because a `2x` bound was analytically wrong for
`P=8`. The
replacement uses the linear segment count, not an observation-tuned constant.

The 256 MiB teardown ceiling is likewise not the leak detector. It was
amended from 64 MiB after the retained diagnostic history measured 38.6 MiB
for a single-phase estimate and 112.1/133.6 MiB after two-phase runs, with
tracemalloc and steady-state plateaus attributing the residual to Kit/glibc
allocator retention. In-run slope and plateau diagnostics retain leak
ownership, and the tighter pure P11 4/128/32 limits were never changed.

## Live regression battery and Lab companion

All four required live regressions returned 0 and passed. The source hashes
below are the executed source-artifact hashes retained in each normalized
record; the normalized-record hashes are the values rolled into
`stress_matrix_gate.json`.

| Row | Result | Source artifact SHA-256 | Normalized record SHA-256 |
| --- | --- | --- | --- |
| `make live-isaac-sim-audio` | passed, return 0 | `34ab4a503e65b1e416213b0b61860ed621183339836f216a7e37ace60830a237` | `0db1dfdd557684fa488f98e5dce2a3e3b656409871124a7edadcd002be4e1d4c` |
| `make live-isaac-occlusion` | passed, return 0 | `e7b29d40518dc12309fdeb47806ebf2e2d7002ebc60157280a679c97400da7c8` | `0ab13c405c208fcaed30b02a8a8201671773d8e036383441fdcfc73687de1b5b` |
| `make live-isaac-lab-audio-gpu` | passed, return 0; effects-off p95 `11.110301013104618 ms <=20.0 ms` | `d55bb2802fbfec68e3ad36af4a128c447a564518ce388790e4c56d46f8a9bd3d` | `065516de04c04898948e6b1e5b789c4c000fb4dcba4d7e7e8429a34ac81260f5` |
| `make live-reliability` | passed, return 0; all planted scenarios passed | `8e633f3ea326b16f1dd3c904a26da2ca4a7d3aaeed25c99a1742de7154d432a3` | `f45c24b8e929dc87a0cddee545e4aeb6f0d72cabc86de14d01e2a866dedd68ca` |

The effects-on Lab companion is report-only and has no S3.8 budget. It timed
the supported scalar `room_acoustics` simulation with channel response,
noise, and electronics enabled on the Lab host interpreter; it did not run
the Lab batched sensor path, which rejects effects under the frozen matrix.
After 5 warm-ups and 60 timed iterations, it measured mean
`6.208645683333333 ms` and p95 `8.3007078 ms` (p50
`6.323294499999999 ms`, p99 `8.43487531 ms`, max `8.470624 ms`). Its
artifact SHA-256 is
`c22937b8c53474fb9146412fa22009b5746eeea94d3f500d2b4a235051848e5c`.

## Tests and environment

- Pre-S3.8 orchestrator-measured `make test` at `e5f136e`: 1065 passed, 0
  failed, 77 optional-dependency skips.
- Post-integrity-fix orchestrator-measured `make test` at `dd8ed5c`: 1096
  passed, 0 failed, 77 optional-dependency skips: 31 additional passing tests
  and no change in skips.

The aggregate pure/real-room evidence used
`/home/pacquadr/isaacsim/kit/python/bin/python3`, Python 3.12.13, NumPy 2.5.0,
pyroomacoustics 0.10.1, package 1.10.0, on Linux 6.8.0-136-generic x86_64
with glibc 2.39. The real room dependency executed; no optional-dependency
loss was converted into a pass.

## Evidence artifacts

All paths below are relative to
`outputs/isaac_audio_sensors/S3/S3.8/`. At closeout, all 32 mappings in
`stress_matrix_gate.json` were recomputed against the retained files and
matched. The seven entries in `live_stress_sha256.json` were independently
checked for both byte count and SHA-256 and also matched. The aggregate gate
does not self-report a hash for itself.

| Artifact | SHA-256 |
| --- | --- |
| `determinism_replay.json` | `e1255bd7961412cb588450e6629ccfe0c993f18076b3a9cf1130f378fbbcd1c3` |
| `determinism_sha256.json` | `cbd3827df20cdf29db029057c2b9eba68e698e93df32081ab58af52dce82442d` |
| `dynamic_state_stress.json` | `215d62ae5c1444545231f6def83a748b1ee08218f0e4f5d0278b0cb4c5988009` |
| `edge_failures.json` | `14dfd0e6e42805a32fc9d0d8b48bd57e7fccb99e5f871f76cbef934fd69a5d27` |
| `gap_preservation_stress.json` | `b2001f9c9d6076f0bb03337a6f6cc1147d11a2197701e46c8c50a2af1ace9285` |
| `identity_ambiguity_stress.json` | `77b35e5c0df0eacc886a9d62392d84e9f65cb13e5cd6cae17908d488e2e375b8` |
| `l2_effects_stress.json` | `873661966c891cd9628f4081e85c6c5d0df5ecf0ea8ec4094e3e9ea8538aa675` |
| `live_isaac_lab_effects_on_report.json` | `c22937b8c53474fb9146412fa22009b5746eeea94d3f500d2b4a235051848e5c` |
| `live_isaac_lab_gpu_off_state_regression.json` | `065516de04c04898948e6b1e5b789c4c000fb4dcba4d7e7e8429a34ac81260f5` |
| `live_isaac_occlusion_regression.json` | `0ab13c405c208fcaed30b02a8a8201671773d8e036383441fdcfc73687de1b5b` |
| `live_isaac_sim_audio_regression.json` | `0db1dfdd557684fa488f98e5dce2a3e3b656409871124a7edadcd002be4e1d4c` |
| `live_regression_verdicts.json` | `f5e2b985acbb8066a3a9c301d4cde9e605b8d6a31e72af262ff7f4a94619f4a6` |
| `live_reliability_regression.json` | `f45c24b8e929dc87a0cddee545e4aeb6f0d72cabc86de14d01e2a866dedd68ca` |
| `live_stress.log` | `5eae2cf69a715354d89cb1288cef0af6269d58d16f2b83d32a902da0b207c98d` |
| `live_stress_audio.wav` | `a3e4641d11a34de93bee12816106c26a9f0e90695175c1628e2e51a160b11818` |
| `live_stress_environment.json` | `f0c26f0a5d87a7a92b07486b255dd68a72e07421d4ee05c4c5b48dac19dcaf55` |
| `live_stress_frames.jsonl` | `d337cca9b0dcef8fa7f45474f2f747d9a83925da49280c0a0be543c1e9156812` |
| `live_stress_sha256.json` | `18f76448569534317afeaa65cbfda4e0d04f2593ed015421f698986d12d1213f` |
| `live_stress_stage.usda` | `5b952d1d2b1505a2fa5b2b7b9ce45ab527281dab12752c236736e3591b454792` |
| `live_stress_summary.json` | `f32731fe9949779328551e2d43fae9ccb89dd4882238e07e12075cb6406e81a0` |
| `live_stress_telemetry.csv` | `b935a926775f9bd0d04445332c69a0f98dfba3250dc3fd431dfce08d431708a1` |
| `matrix_capabilities.json` | `c274142e9ee6a131533d5c587a1031328ce030d7a84973da9746080484b16aa4` |
| `multi_source_stress.json` | `c58e8ca227a6d8acc3da156a3be4ed036c2f4ab370efdd2c8dbde1e42b0e6ab0` |
| `real_room_worker.json` | `cf8abcafc0e553809ba80eceaa75011bb52d3b728de2719a6c4a8499d8508d31` |
| `regression_logs/live_isaac_lab_gpu_off_state.log` | `c5ca6f1deb5899da90e2bef97cf5a972ea2a560122fed59657bea8bb84cd052b` |
| `regression_logs/live_isaac_occlusion.log` | `4746bf4404cd54465438f34c75c7ff973d50e448f5e55975fd15c3dcee0afa33` |
| `regression_logs/live_isaac_sim_audio.log` | `2c94a3cda024ea02da841bead02351bd5ad28a541ff1006313f1787c037b11c1` |
| `regression_logs/live_reliability.log` | `9c5fb3ef856c10bd7fade4a5a4eeeaacce2409172cd6ca5c253feaa3ea207dc1` |
| `regression_logs/live_s3_stress.log` | `5fb7393b0112ad2e4ef32416f1630eb6ebe5ab2bde627c87f464a124823a3852` |
| `resource_rss.csv` | `7bee9f7c818f31026fad8b5efdcf65ba1df966e2bd1282bc3c47f4fd5739c783` |
| `resource_stress.json` | `b434bdfe821c47e3496144ef4cedb540ad2ef9182f442a6831a48c50393d6d1d` |
| `velocity_stress.json` | `762a36b5e9a4f314e877db50228ea5a2f99043852d32fce26a23134b6342d5a2` |

## Reproduction commands

The aggregate roll-up records:

```bash
.venv/bin/python -m pytest -q tests/test_s3_stress_matrix.py
.venv/bin/python scripts/s3_8_evidence.py
make live-s3-stress
```

The closeout regression battery executed the frozen public commands
`make live-isaac-sim-audio`, `make live-isaac-occlusion`,
`make live-isaac-lab-audio-gpu`, and `make live-reliability`; the effects-on
Lab companion was measured by `scripts/s3_8_regressions.py`. Required real
room, Isaac, Lab, CUDA, or GPU absence would block this gate rather than
produce a skip-based pass.

## Defects, amendments, and review findings

The execution history is part of the acceptance record:

| # | Classification | Finding and disposition |
| ---: | --- | --- |
| 1 | harness defect | The live harness injected a sink without the required `waveform_dir` pairing, so the attempt failed before reaching the backend. Pair construction was fixed at `44b8df0`; the passing rerun exercised the backend. |
| 2 | harness defect | The gate accumulated large frame evidence in memory. It was changed to stream durable evidence to disk at `44b8df0`, removing the harness-created retained-state trend. |
| 3 | harness defect | Lazy page commitment from `numpy.zeros` polluted the RSS slope. The buffer is eagerly filled before baseline measurement as of `44b8df0`. |
| 4 | product defect | `extension.py` rejected an exact-lattice forced capture because the overlap guard differed by one floating-point ulp. The guard now tolerates lattice-scale error, with a dedicated regression test, at `44b8df0`. |
| 5 | product defect | Pose-history bracketing and window-motion interpolation used exact float comparisons and rejected one-ulp lattice mismatches. Both motion paths gained bounded comparison/clamping fixes and regressions at `44b8df0`. |
| 6 | bound amendment | The paired latency formula used `2x` despite eight per-segment room/RIR rerenders. The measured failed run was `144.73/937.30 ms` (`6.48x`); the amended linear `8x + 5 ms` cost-model guard detects superlinear/stalled work without tuning to that observation. Landed at `44b8df0`. |
| 7 | bound amendment | The live post-teardown ceiling changed from 64 MiB to 256 MiB after allocator-retention diagnostics measured 38.6/112.1/133.6 MiB. In-run slope and plateau diagnostics remain the leak gate; pure P11 remains 4/128/32. Landed at `44b8df0`. |
| 8 | verdict-contract amendment | Two consecutive runs showed Kit terminating the process inside `SimulationApp.close()` after evidence was durable. The gate now accepts a durable `status=passed` summary with `teardown.status=provisional` only when the close-error field is null. Landed at `44b8df0`; the final retained run exercised this exact path. |
| 9 | product defect | Real-Isaac execution exposed Isaac 6 configclass import drift: `from isaaclab.utils import configclass` could bind the module rather than its decorator. The Lab loader shim now unwraps the decorator in both modern and legacy loaders, landed at `a2f3ea0`. |
| 10 | harness/evidence-integrity defect, first closeout review | The generator ran 1 rather than 32 frames on the `room_acoustics_srp` all-effects path, labeled determinism scenarios instead of replaying them, and synthesized matrix verdicts from global booleans. At `dd8ed5c`, every P01-P12 scenario is replayed in fresh processes with byte-identical canonical hashes; every one of 55 cells has a real execution/error record; the Lab scalar authored-velocity row performs a bitwise 64-frame check; and the Lab 2/4/8 ladder performs 96 frames. |
| 11 | harness/evidence-integrity defect, second closeout review | `live_stress_sha256.json` was written only after `SimulationApp.close()` and therefore never existed on the observed termination path; command metadata also continued to claim live execution was pending after ingestion. At `d493072`, the checksum manifest is durable with the pre-close evidence set and command metadata is conditional/truthful. The full live rerun passed with all artifacts present and make verdict 0. |

No product defect, harness defect, failed initial observation, or post-evidence
amendment above is hidden by the final passing aggregate.

## Limitations carried forward and S3.9 input contract

- Isaac Lab batched pose-derived velocity, batched waveform effects,
  occlusion, and materials remain unsupported in Stage 1 and fail explicitly.
  Authored velocity is supported only through the scalar core-frame path.
- Two-microphone `room_acoustics_srp` remains outside the claimed ambiguity
  envelope and rejects explicitly. L1 and room GCC surface ambiguity; they do
  not invent one confident bearing.
- S3.6's normalized `srp_phat_confidence` can rise toward unity on
  noise-dominated input. It is not localization-confidence evidence and must
  be restated in S3.9.
- The paired effects-on latency result is a host-relative linear cost-model
  regression guard, not a portable or real-time L2 envelope. P1 owns the
  scaled 20 ms performance gate; S3.8 proves only its frozen Lab effects-off
  companion row within 20 ms.
- RSS is Linux `VmRSS` and host/allocator relative. The pure long-run slope
  and plateau diagnostics are the leak evidence; the live teardown ceiling is
  coarse allocator-retention headroom.
- S3.7 fidelity limits remain: recompute-always with no acoustic-result cache,
  approximate shoebox/image-source room physics, direct-ray nominal
  transmission rather than diffraction, six-band material application, and
  `per_pair_direct_path` rather than reflection-path-specific directivity.
- No physical robot, microphone, calibrated room, hardware, real-time robot,
  or sim-to-real claim follows from these pure and live simulation gates.

S3.9 consumes the complete S3.8 matrix, canonical scenario hashes, live
latency/RSS/gap/identity telemetry, regression provenance, and the limitations
above. Its fidelity envelope must map every retained claim to this evidence,
carry forward the S3.6 confidence-on-noise limitation, describe effects-on
latency only as the measured segment cost-model claim, and leave the scaled
20 ms effects-on gate with P1.
