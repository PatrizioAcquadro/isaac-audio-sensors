# S3.2 closeout - time gaps and intra-window motion

Status: **passed** (2026-07-18). Entry revisions: frozen specification
`6a77762`; implementation `6de3c7e`; dated live-scenario amendment `9b5bc32`;
live gate and gate-found harness fixes `32f24d9`. Predecessors:
`docs/development/closeouts/S3/s3_1_pose_velocity.md`, and the S2.2 writer
timing contract carried by `docs/development/closeouts/S2_closeout.md`.

## Frozen-tolerance provenance

The complete S3.2 ownership rules, defaults, analytical fixtures, measurement
methods, and tolerances were committed prospectively in
`docs/development/specs/s3_motion_policies.md` at `6a77762`, before S3.2
implementation or acceptance evidence. The specification and roll-up record
`8bc7955` as the S3.2 design revision and pinned pre-implementation golden
baseline. Implementation landed later at `6de3c7e`; the final roll-up records
the post-amendment `9b5bc32` as `implementation_base_revision`. No
pure-fixture tolerance was selected or adjusted from its measured results.

There was one dated, evidence-honest amendment. Code inspection after the pure
evidence had been generated, but before any live evidence existed, exposed an
internal conflict in the original live scenario's `W=H=2400` geometry.
`SessionRecorder` writes the first `H` samples and forms carry only from
`block[:, H:]`, which is structurally empty when `W=H`; the guided controller
also truncates the rendered path to `W`, so samples beyond `W` cannot restore
that carry. The original live scenario therefore could not simultaneously
require a carried decaying RIR tail and use `W=H`. The 2026-07-18 amendment
landed at `9b5bc32` and changed only the then-unexecuted live scenario to
`W=4800`, `H=2400`. The 16,800-sample gap arithmetic remained unchanged. All
pure fixtures, formulas, tolerances, and already-generated pure evidence were
unchanged, and no evidence was invalidated.

Process note: during implementation, the initially bounded write scope did
not include `src/isaac_audio_sensors/isaac/extension_ui/controller.py`, even
though the frozen recorder-owned placement plan required the guided
controller to carry the additive `recording.time_gap` diagnostic into the
unchanged six-field record. The implementation run correctly reported
`BLOCKED`; the orchestrator explicitly expanded the scope to that controller,
after which implementation proceeded. This was a scope/process correction,
not a tolerance change or an acceptance failure.

## Gate results

`outputs/isaac_audio_sensors/S3/S3.2/time_motion_gate.json` reports
`status: "passed"`; all 14 machine-readable rows passed. Numerical errors
below are maxima, not means or percentiles.

| Criterion | Frozen threshold or exact requirement | Measured result | Status |
| --- | --- | --- | --- |
| Pause/throttle accounting | Pure pause: exactly 16,800 inserted samples, 24,000 total samples, and zero-tail gap `[4,800, 21,600)`; throttle starts `0.00, 0.05, 0.10 s` with 7,200 samples and no gap | Pause starts `0.00, 0.05, 0.45 s`, placements `0, 2,400, 21,600`, exactly 16,800 inserted samples, 24,000 total samples, and exact-zero gap span `[4,800, 21,600)`; 11 throttle ticks retained exactly the three frozen starts | passed |
| Tolerance and round-half-even | Inclusive `Q=240`: `+/-240` absorbed, `+241` inserts 241, `-241` rejects; `2.5 -> 2`, `3.5 -> 4` | All eight matrix rows matched exactly; `+1` was absorbed with zero insertion and the two tie cases inserted 2 and 4 | passed |
| Carry and bounded streaming | Carry advances sample-for-sample; remainder exact zero; blocks `<=1 MiB` and `<=65,536` samples; no gap-sized allocation | Carry and zero remainder comparisons true; maximum block 1,048,576 bytes / 65,536 samples; allocation proportional to gap false | passed |
| Additive schema and validator | Six exact record fields; time-gap diagnostic reconciles; three planted codes exact | Six fields retained; diagnostic at `frame.diagnostics.recording.time_gap`; clean fixture passed; planted `time_gap_metadata_mismatch`, `unexpected_audio_gap`, and `non_monotonic_window_placement` found exactly | passed |
| Shard, cancellation, and resume | Single/sharded and uninterrupted/resumed output exact; cancellation never commits a partial gap | Single vs sharded and uninterrupted vs resumed were exact; shard-boundary carry and mid-gap resume passed; first, middle, final, and before-frame-append cancellation rows passed | passed |
| Segment partition and endpoints | Eight exact segments cover `W=2400`; endpoint and pose sourcing exact | Boundaries `0, 300, 600, 900, 1200, 1500, 1800, 2100, 2400`; eight lengths of 300; sum 2,400; endpoint/pose row passed | passed |
| Analytical motion bounds | Linear `<=0.062500001 m`; acceleration interpolation `<=0.002500001 m` and total `<=0.0412890635 m`; circular total `<=0.0751953135 m` | Linear `0.062291666666666856 m`; acceleration interpolation `0.0025000000000000022 m` and total `0.040497916666666633 m`; circular interpolation `0.012497396050338179 m` and total `0.06350751277362332 m` | passed |
| Doppler/RIR assembly | `P=8`, exact `W=2400`, one full-window estimator pass, and cross-segment RIR tail | All exact; waveform sample count 2,400 and SHA-256 `7bd31a50de89a54ac4616fbb5b8a3c5bfc82f5ee18e57c4b30a85869a11447c4` | passed |
| Boundary continuity | Maximum normalized residual `<=2e-6` full scale | `0.0` across one source, four microphones, and seven boundaries per signal; output finite | passed |
| Unsupported L0/L1 | `segments_per_window=2` raises `UnsupportedEffectError` before output | `geometry_only` and `tdoa_synthetic` rejection rows both passed | passed |
| Gap off-state and `P=1` identity | Absent gap setting and one-segment field preserve pinned `8bc7955` goldens exactly | Off-state full-session hash `77aa7521801985c7346e5ec707535c3be43579ef97c3b3ef662f1b08e3f6de52`; public-append hash `6cb66c3487ab471d8abf5a515c09cf6b9a32ad9a4c7a389cad473b91f3188442`; absent and explicit-`P=1` hashes both `de3dc9ca59fb51e6bf1497864bdd642ebb881d59c211317ea644bf4918d90e6a` | passed |
| Registry twice-run determinism | Enabled `P=8` fixture byte-identical twice | Both hashes `7bd31a50de89a54ac4616fbb5b8a3c5bfc82f5ee18e57c4b30a85869a11447c4`; exact comparison true | passed |
| Live throttled capture | Amended headless Kit scenario, exact gap/ranges/carry, `P=8` finite motion, continuity `<=2e-6`, and zero validator errors | All 17 live assertions true; details below | passed |
| S2 reliability regression | Complete `make live-reliability` rerun after recorder changes | 5/5 scenarios passed | passed |

The pure pause frame ranges are `[0, 2,400)`, `[2,400, 4,800)`, and
`[21,600, 24,000)`. The recorder counters reconciled exactly to one gap event,
16,800 inserted samples, zero absorbed-drift events, and zero signed absorbed
drift. The off-state hashes cover session configuration, frame records, WAV,
shard marker, and manifest rather than only one selected payload.

## Live Kit scenario

The amended scenario ran headless in Kit with one continuously active source,
one static four-microphone array, the `room_acoustics` backend, 48 kHz, a
0.05 s capture period, `W=4800`, `H=2400`, and
`preserve_time_gaps=true`. The environment record identifies Kit app version
`6.0.1`, Kit build `110.1.2+production.326809.f9bf0dda.gl`, USD
`(0, 25, 11)`, Isaac Sim Kit Python `3.12.13`, pyroomacoustics `0.10.1`, one
NVIDIA GeForce RTX 4090, and NVIDIA driver `580.159.03`. The installed Isaac
package version was unavailable, so no more specific Isaac Sim package
version is claimed. The environment pins the loaded extension and source to
repository revision `9b5bc32`; `32f24d9` records the live runner, final
evidence ingestion, and gate-found harness fixes.

Capture was driven on Kit's reported 60 fps update lattice. The capture
subscription retained lattice times `0.00`, `0.05`, and `0.45 s` at ticks 0,
3, and 27. After the second capture it was paused over `[0.05, 0.45] s` while
simulation time continued; `simulation_time_paused` is false. Kit reported
the final requested `0.45 s` crossing as `0.44999999999999996 s`, within the
frozen 5 ms lattice-drift tolerance. Placement still rounded exactly to
21,600 samples, producing `D=16,800`, a gap over `[4,800, 21,600)`, record
ranges `[0, 4,800)`, `[2,400, 7,200)`, and `[21,600, 26,400)`, and an exact
26,400-sample final stream. Every recorder input block was float32 with shape
`(4, 4800)` and there were zero duplicate frames.

The carried tail had support length 2,399 samples. Its first sample vector was
`(-0.03326280415058136, -0.02592821978032589,
-0.00778611097484827, -0.02592821978032589)`; early-quarter RMS
`0.04163500819872801` exceeded late-quarter RMS `0.009554100301646778`.
The decoded gap head equaled the float32 carry bit-for-bit, and the remainder
after the tail was exact zero.

The separate `P=8` moving-source phase primed at `1.0 s` without emitting a
backend frame, then retained the fully bracketed `[1.0, 1.1) s` window. Its
eight segment lengths were exactly 600 samples; all segment poses and Doppler
factors were finite. The live maximum boundary-jump residual was
`6.834050669812797e-8` full scale against `2e-6`, across one source and four
microphones with seven boundaries per signal.

The published shard validator did **not** report literal status `passed`.
It reported `passed_with_warnings`: 33 `portability_warning` findings for
absolute-path-like diagnostic strings, all severity `warning`, with zero
`ERROR` findings. This passes under the frozen S2.9 warning-only precedent;
it is validator-clean in the contract sense of zero errors, not warning-free.

## Tests and reliability regression

- Pre-S3.2 `make test` baseline at `8bc7955`: 871 passed, 0 failed, 76
  optional-dependency skips.
- Post-S3.2 `make test` across `6de3c7e..32f24d9`: 913 passed, 0 failed, 76
  optional-dependency skips.
- These totals were measured by the orchestrator at the named revisions; this
  documentation-only closeout did not rerun them.
- The recorder reliability target was rerun after the S3.2 recorder changes.
  `live_reliability_rerun_summary.json` reports `status: "passed"`: all five
  scenarios passed (`cancellation_restart`, `simulator_replacement`,
  `dependency_removal`, `disk_failure`, and `resume`).

## Evidence artifacts

All paths below are relative to
`outputs/isaac_audio_sensors/S3/S3.2/`. SHA-256 values are copied from
`time_motion_gate.json` and were checked against the files at closeout.

| Artifact | SHA-256 |
| --- | --- |
| `gap_cancellation_matrix.json` | `02358d52f5acb986b557dd2b7f917ad35082e8bd7ace9996cc84191d6ac53db3` |
| `gap_carry_results.json` | `cc94db7eaba390d70af831b2e7243681c1415b7bd767394888d99ab26d5ef0e1` |
| `gap_carry_trace.csv` | `28d8fa1c8031969a39a9fab8b91228854477ff8626148abca2cc4198d07933a2` |
| `gap_cursor_trace.csv` | `cb2dd346c7fe9ae23c158d630ed3c019fd820f8f8a0588a0e0141c2f5f3a9f49` |
| `gap_memory_telemetry.json` | `802da20305aef02e469c86f6a3fe1b98ee167be3fb545f9c1b305b9e66f8d341` |
| `gap_metadata_results.json` | `3a92008e029d314619f479e044551b4fe9f6a397b5665d3e7d97b3146729cba8` |
| `gap_rounding_matrix.json` | `9616011ceb174a5ff376fcbda066c6b7164cdd4502caaafdaf41e3401a4dbb51` |
| `gap_shard_hashes.txt` | `3efdabf03f2d41a0be8bfc3ba7c9531264900a5047acbfbb90111db9146924d9` |
| `gap_shard_resume_results.json` | `ffc6670690665312e89c0f53285e4480b815efb9bd081b3518a05eb627ee76f4` |
| `gap_validator_findings.json` | `b11c4c977b581c225c7bc64809e83cddfa3f5be9e45b339a5648be4374e80e9c` |
| `interpolation_error_results.json` | `d2c575c7ceed3364775e6a16b274db5e743e844041b2b3796a01777048b14f7e` |
| `interpolation_error_trace.csv` | `d418be0b21b9df5c5ba469505033c9554e703eb9ffe93414e86da166d709e4dd` |
| `live_reliability_rerun.log` | `9c5fb3ef856c10bd7fade4a5a4eeeaacce2409172cd6ca5c253feaa3ea207dc1` |
| `live_reliability_rerun_summary.json` | `8e633f3ea326b16f1dd3c904a26da2ca4a7d3aaeed25c99a1742de7154d432a3` |
| `live_throttled_capture.log` | `41ab78588b1eac21a6e1bf25c7e773685f0de2fda1ef39e732c6d671297f2792` |
| `live_throttled_capture_audio.wav` | `60fbe42540fee864ea42b1caea7aa914eea3709c7ed32d083050d01da95b08cb` |
| `live_throttled_capture_frames.jsonl` | `c5e89b8b3d9e9330b7cb341bba9e003ee2947e2416f0d315250a105bbc0dfa55` |
| `live_throttled_capture_stage.usda` | `2e81d69c68e020e481668f7f71253e9a9577d38d2f44754279218c42efd19d1d` |
| `live_throttled_capture_summary.json` | `3ba3053e6597a4ff2f6f15de33893dcd46609a8ec7ca1033aa4e0109128f6ca4` |
| `live_time_motion_environment.json` | `807052c4024b558cff480f630178d2baa8fcf9f74b10bed0f3d0d38bb820a336` |
| `pause_audio.wav` | `ac7e4c26657d617dde45e15401ba1043be042bd64f73b551e3cb13adb627fd62` |
| `pause_frames.jsonl` | `8e319e8b609e63adf78249c0a247e6288c0aadf717705997aee99ca62b246971` |
| `pause_sample_accounting.json` | `62ee9bf5e79eb3cb936c3d1447fd704e1e12a7c28f93d86bb22af061e0f5e310` |
| `piecewise_doppler_trace.csv` | `f4141a154b1775f96f1c10250ec1b2b7f5151294bf51f7478c51eccea24438b4` |
| `piecewise_room_results.json` | `b9b4198904ca251bee10cfc29efce14a7f81f9245b8974bac3b34fa46c56d226` |
| `piecewise_waveform_sha256.json` | `b6762baae8a30d03e0171b8b582b96d8344f29f2b60299f1009544be8d38f7fd` |
| `registry_self_test.json` | `d01213fcc53acf8bb5366e611395b9c27180fe95a0fcbbc6928c65926299ed20` |
| `segment_continuity_results.json` | `5b11f72ec27485590f31904acc989240e67a68149c703a7f2cf2f51af2b79f98` |
| `segment_continuity_trace.csv` | `e6fd5a766bb6fd6325c90b776804e39583e6cdd4fa60941babd76ea26605ab9c` |
| `segment_partition_results.json` | `70a48a69a189a2c2df1f4c75fb7f08fdb36e8abea25de150828b5a50a658fb96` |
| `segment_pose_trace.csv` | `d418be0b21b9df5c5ba469505033c9554e703eb9ffe93414e86da166d709e4dd` |
| `segments_one_golden_sha256.json` | `3e5e2c1d717b5826b9829c48364ad8df0f0aeae482499698b6c4350627bc31b1` |
| `throttle_trace.jsonl` | `6fc81aa978ebe5e1407106a57a090ec625eb8674632657883aad58441535b8e9` |
| `time_gap_off_state_sha256.json` | `af08d06c81af0e44fb8c66f6a9f773a2eeb592bce145d3d49983b8b9a92c83c5` |
| `unsupported_segment_backend_matrix.json` | `8a88bba891e1f55b8af8fb40c6d801971fd8821b0bc54d6754c3c929803cb9ab` |

`time_motion_gate.json` is the machine-readable roll-up and does not
self-report a SHA-256 for itself.

## Reproduction commands

The gate records these commands:

```bash
.venv/bin/python -m pytest -q tests/test_dataset_time_gaps.py tests/test_intra_window_motion.py
make test
make lint
make check-version
make dataset-validate-fixture
make live-reliability
.venv/bin/python scripts/s3_2_evidence.py
```

The live scenario is exposed through the `live-s3-2-time-gaps` Make target
added at `32f24d9`; reproducing the committed live evidence requires the
recorded Isaac/Kit, GPU, and pyroomacoustics-capable environment.

## Defects found and fixed during the live gate

The live gate found two harness assertions that were stricter than the frozen
contracts. Both were fixed at `32f24d9` before the passing rerun; neither was a
sensor defect.

1. The harness initially asserted that setting a Kit timeline time would be
   reported back as the identical binary float. Kit quantized updates to its
   reported 60 fps tick lattice (`0.45` requested,
   `0.44999999999999996` reported). Capture was changed to use the reported
   lattice crossing while retaining the frozen 5 ms drift and exact sample
   placement checks.
2. The harness initially required validator status exactly `passed`. The
   frozen validator contract, already exercised by S2.9, permits
   `passed_with_warnings` when there are zero error findings. The gate now
   checks that exact contract; the retained live result has 33 warning-only
   portability findings and zero errors.

The sensor and recorder behavior passed unchanged on the final run: exact gap
placement and ranges, bit-exact advancing carry, exact post-tail zeros,
finite bracketed `P=8` motion, and continuity below the frozen bound.

## Limitations carried forward

- `geometry_only` and `tdoa_synthetic` reject
  `segments_per_window>1`; their metadata cannot represent piecewise waveform
  motion honestly. Their `P=1` behavior remains supported and unchanged.
- Gap preservation remains opt-in and defaults off. With
  `preserve_time_gaps` absent, the pinned pre-S3.2 append path is selected.
- The 30-minute live endurance run was not repeated for this subphase. The
  S2.9 endurance result remains the standing long-duration evidence; S3.2
  reran the complete five-scenario reliability target, and S3.8 will stress
  motion behavior at scale.
- This gate validates the specified simulation and recording behavior. It
  makes no calibrated real-world motion or sim-to-real fidelity claim.

## Input contract for S3.4

S3.4 seeded noise consumes the established channel-effects order and stable
configuration/diagnostic surfaces in
`docs/development/specs/s3_channel_effects_chain.md`. Before S3.4
implementation or acceptance evidence, that specification's §7 deferred PSD,
RMS, delay-statistic, drift, replay, and cross-correlation tolerances must be
frozen prospectively in a dated revision.
