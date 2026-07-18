# S3.1 closeout - pose-derived velocity

Status: **passed** (2026-07-18). Entry revisions: frozen specification
`144c83c`; implementation `26218c3`; live gate and gate-found harness fixes
`6a0c729`. Predecessors: the S1.7 compatibility freeze recorded by
`docs/development/closeouts/S1_closeout.md`, and
`docs/development/closeouts/S3/s3_3_channel_response.md` for the shared effects
configuration surface.

## Frozen-tolerance provenance

The complete S3.1 policy order, defaults, analytical fixtures, measurement
methods, and tolerances were committed in
`docs/development/specs/s3_motion_policies.md` at `144c83c`, before
implementation or acceptance evidence. The specification records `839fe90` as
its entry revision. Implementation landed later at `26218c3`, and the live
Isaac gate plus its harness fixes landed at `6a0c729`. No S3.1 tolerance was
selected or adjusted from the measured results.

## Gate results

`outputs/isaac_audio_sensors/S3/S3.1/pose_velocity_gate.json` reports
`status: "passed"`; all 14 criterion rows, including the live Isaac row,
passed. Numerical errors below are maxima, not means or percentiles.

| Criterion | Frozen threshold or exact requirement | Measured result | Status |
| --- | --- | --- | --- |
| Raw constant velocity | Maximum absolute component error `<= 1e-9 m/s` | `7.105427357601002e-14 m/s`; 80 derived samples across 2 entities | passed |
| Smoothing settling | With `alpha=0.5`, component error after exactly 40 derived updates `<= 1e-9 m/s` | `1.816147232602816e-11 m/s`; maximum recurrence error `2.842170943040401e-14 m/s` | passed |
| Policy order and boundaries | Exact reasons, velocities, state preservation, and recovery; exactly `50.0 m/s` derives and greater-than-`50.0 m/s` teleports | 12/12 rows passed: first/duplicate/derived replay, time reset/recovery, exact/over-stale, exact/over-teleport, and recovery | passed |
| Pose-history lifecycle | Reset/removal/rediscovery behavior exact | First after reset and same-id reuse after removal were `first_sample`; structural rediscovery preserved the survivor | passed |
| Snapshot velocity selection | Authored values win; derivation fills only absent fields | Later derived source `(1.0, 0.0, 0.0) m/s` and array `(0.0, 0.5, 0.0) m/s`; exact source map changed from authored to derived | passed |
| Stage-cache continuity | Pose edits and structural rediscovery preserve eligible history | Pose-edit and survivor rediscovery rows both reported source and array `derived`; 1 cached tick and 2 full discoveries | passed |
| Authored precedence | Packed IEEE-754 source and array bytes exact | Source and array bit comparisons both true, including signed-zero fixtures; selected tags both `authored` | passed |
| Teleport no-spike, TDOA | Central and every per-microphone Doppler factor exactly `1.0`; no Doppler waveform render | Central factor `1.0`; front/left/rear/right each `1.0`; waveform-rendered false; source velocity absent and tagged `none:teleport` | passed |
| Teleport no-spike, room | Doppler factor exactly `1.0`; no waveform render or resample call | Factor `1.0`; waveform-rendered false; resample calls `0`; source tagged `none:teleport` | passed |
| Motion off-state | Serialized frame bytes exact; no `motion` or Doppler diagnostic | Frame bytes identical; both frame hashes `f4c35bf436ee2b27c0cab239ada54134aaad7244d1b230b17b73eef90b53c555`; both keys absent | passed |
| Invalid motion configuration | Every matrix row fails closed with the expected typed error | 7/7 rows passed, including unknown key, type/range/non-finite cases, and source/array id collision | passed |
| Invalid pose atomicity | Every invalid pose row fails before history mutation | 6/6 rows passed; history preserved in all 6 | passed |
| Registry twice-run determinism | Exact twice-run registry output | Both hashes `af1e12bb2f14b76ea1883fba9d2ee88e65d52a31d6c34a4a61bb5413d00ec948`; exact comparison true | passed |
| Live Isaac teleport | Required live artifacts present; live summary and row passed | 5 TDOA frames plus 1 room re-render; every scenario assertion passed | passed |

The policy matrix confirms the frozen ordering rather than merely observing a
teleport: duplicates replay the prior tagged result without mutation, strict
time decrease resets before duplicate handling, a gap of exactly `0.5 s`
derives while a larger gap is stale, speed exactly `50.0 m/s` derives, and a
speed above the threshold teleports. Reset, stale, and teleport anchors each
recover on the next valid later sample.

## Live Isaac scenario

The live gate ran headless in an Isaac Sim runtime on one NVIDIA GeForce RTX
4090 with NVIDIA driver `580.159.03`. The environment record identifies Kit
app version `6.0.1`, Kit build
`110.1.2+production.326809.f9bf0dda.gl`, USD `(0, 25, 11)`, and Isaac Sim Kit
Python `3.12.13`; the installed Isaac package version was unavailable, so no
more specific Isaac Sim version is claimed. The live environment pins the
loaded sensor source to implementation revision `26218c3`; `6a0c729` then
records the live runner, evidence ingestion, and gate-found harness fixes.

The running stage contained one continuously active source and one static
four-microphone array. At `1.00 s`, the first pre-teleport frame was tagged
`none:first_sample`; at `1.05 s`, the second pre-teleport frame was `derived`.
The source then moved exactly `3.0 m`, from `(4.0, 0.0, 1.0) m` to
`(7.0, 0.0, 1.0) m`, for the `1.10 s` update. That frame was tagged
`none:teleport`, carried no source snapshot velocity, reported exact central
and per-microphone TDOA Doppler factors of `1.0`, and rendered no Doppler
waveform. Its room-backend re-render likewise reported exact Doppler factor
`1.0` and no Doppler waveform render. The `1.15 s` and `1.20 s` recovery
frames were both `derived`. All six retained frames were finite under the
gate's sentinel-aware scan, and no extreme clamp factor occurred.

## Tests and environment

- Pre-S3.1 `make test` baseline at `839fe90`: 802 passed, 0 failed, 74
  optional-dependency skips.
- Post-S3.1 `make test` at both `26218c3` and `6a0c729`: 871 passed, 0 failed,
  76 optional-dependency skips.
- These totals were measured by the orchestrator with `make test` at the named
  revisions; this documentation-only closeout did not rerun them.

The pure evidence was regenerated under the Isaac Sim Python so the room rows
used installed pyroomacoustics `0.10.1`; consequently
`room_teleport_no_spike.json` records `dependency_available: true` and
`execution_dependency: "installed_pyroomacoustics"`. The base `.venv`
intentionally lacks pyroomacoustics. The room evidence therefore proves the
recorded dependency-capable environment and does not redefine the base
environment.

## Evidence artifacts

All paths below are relative to
`outputs/isaac_audio_sensors/S3/S3.1/`. SHA-256 values are copied from
`pose_velocity_gate.json` and were checked against the files at closeout.

| Artifact | SHA-256 |
| --- | --- |
| `authored_precedence_bits.json` | `c7176cd16312c1d2ab04ec1f3984cb0218cabd1d26bf812a0a591e73812ac8e5` |
| `constant_velocity_results.json` | `e89ff6cb3b6388932f6f4ac78c026ca29e7f638ec85c668cb670e4804ce7166f` |
| `constant_velocity_trace.csv` | `9adbfd8540383258124e42190e6d92028c7d476698740a43d4320a34a5fdfaff` |
| `invalid_motion_config_matrix.json` | `869ea1fe941705ff8289b2b6aa9a89346f0ffcae43992af404a20a7ed8ae2f7d` |
| `invalid_pose_matrix.json` | `c366aeabef7225789e950b3db53f435ebfab3eead72a067b5c423beff198c817` |
| `live_isaac_environment.json` | `7100629823fe5e819371a966dacf61b6b57dcc3fe5e028c883ce290a5cc9afb1` |
| `live_isaac_teleport.log` | `852ffdb6602c53b7d5bc2c2dc72f9735d95f01ee85427ee8192175acb07b5b60` |
| `live_isaac_teleport_frames.jsonl` | `a33c831e950d7b2dc867fee6ec131418f1d41c1d101d61a47dcfb10f9d17f20c` |
| `live_isaac_teleport_stage.usda` | `3d43cf3b3f5a70f970f3ad4016ef751ad9532ed98689d79a36df26ee5884998d` |
| `live_isaac_teleport_summary.json` | `da4ac775c18306925491ecd46396a36112612c0c9b970e882aea46fa7d574637` |
| `motion_off_state_frame.json` | `d0bd81e155de9383732aaba0146f142b7a168ccb521dad828cadb0e201ae5d95` |
| `motion_off_state_golden_sha256.json` | `911ae782ddf194510d4078839a87960475c3ebe569b9f0a71f11981cd821440b` |
| `pose_history_lifecycle.json` | `3a231770935d7bfb165dd4f7f8c28cb8bc03f265c33b30977447c3b5a128c0ce` |
| `pose_policy_matrix.json` | `fdb6c119d570f103504326d137785f0fc58f73f614a848ec59dfe58a0f1a438c` |
| `registry_determinism.json` | `288cb0c5bd204278998ecb3ce30dd0c6dee39c54dc15b93ad1e84add1f8c8c85` |
| `room_teleport_no_spike.json` | `f2d5351c4d7f4fb34bd6260034ba05cbec65223661c27992ed6487f2148f6867` |
| `room_teleport_waveform_sha256.json` | `73d454362070b4d588195f56942b8f43370c81ba3f8b7a9af92d9b0a2a6a599c` |
| `smoothing_settling_results.json` | `d52e9a7d3e02673fb6bf03070c74565dc52e480c1e7e1e1541a9f549829c8007` |
| `smoothing_settling_trace.csv` | `1064b24490559bfd424dc346df6165ce1e3efca2b87eca898d67cfa9d6d654a5` |
| `stage_cache_motion_trace.json` | `b0417aea2bd4c7df6200c682b3ed2ebe2c365324b57dea833e198c51a22cf400` |
| `stage_snapshot_velocity_results.json` | `b7802f39228c814fbd72abc5c49637852704845a5165a3ef4ec62cc226a2b616` |
| `tdoa_teleport_no_spike.json` | `0888db5ca6bb95869c9555c8862dc05bb5d08a199e32874e322b9b8b7087088d` |

`pose_velocity_gate.json` is the machine-readable roll-up and does not
self-report a SHA-256 for itself.

## Reproduction commands

The gate records these commands:

```bash
.venv/bin/python -m pytest -q tests/test_pose_history.py tests/test_motion_stage_snapshot.py tests/test_motion_doppler_integration.py
make test
make lint
make check-version
make live-s3-1-pose-velocity
.venv/bin/python scripts/s3_1_evidence.py
```

Reproducing the committed `dependency_available: true` room row requires the
recorded dependency-capable Python environment with pyroomacoustics `0.10.1`;
the base `.venv` intentionally exercises the dependency-absent capability
state.

## Defects found and fixed during the gate

The live gate found three evidence-harness/script defects, all fixed in
`6a0c729` before the passing rerun:

1. The live script initially used an invalid frame provenance for the room
   re-render; the retained room frame now uses the allowed `room_acoustics`
   provenance.
2. The summary and environment were initially written after
   `SimulationApp.close()`, allowing Kit teardown to destroy otherwise valid
   evidence; final artifacts are now written before closing the app.
3. The blanket finite-value scan treated the USD
   `Usd.TimeCode.Default()` NaN sentinel in frozen stage-snapshot diagnostic
   `time_code` fields as a sensor non-finite value; the scan now excludes
   `time_code` keys while continuing to reject non-finite sensor values.

These were harness/script defects, not sensor defects. Sensor behavior itself
passed unchanged on the rerun: teleport classification, absent snapshot
velocity, exact unity Doppler, no waveform render, and next-frame recovery all
met the frozen contract.

## Limitations carried forward

- Isaac Lab batched pose-derived velocity remains explicitly unsupported
  until S3.8 either adds a per-environment batched derivation contract or
  declares the combination unsupported.
- Angular velocity and angular-velocity Doppler are out of scope; S3.1 derives
  world-frame linear velocity only.
- Intra-window interpolation, piecewise Doppler, and session-gap rendering are
  not implemented or accepted here. S3.2 tolerances remain deferred and must
  be frozen prospectively before S3.2 evidence is generated or viewed.
- This gate validates the specified simulation behavior. It makes no
  calibrated real-world motion or sim-to-real fidelity claim.

## Input contract for S3.2

S3.2 time gaps and intra-window motion consumes the S3.1 `PoseHistory` motion
contract and the S2.2 writer timing contract in
`docs/development/specs/s2_atomic_writers.md`. Pose history continues to own
tagged snapshot-to-snapshot velocity derivation; the dataset/session writer
owns absolute placement, gap accounting, atomicity, bounded memory, and final
gap metadata. S3.2 must freeze its deferred gap, interpolation,
segment-boundary, and non-monotonic-time tolerances before acceptance evidence.
