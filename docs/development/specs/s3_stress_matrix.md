# S3.8 motion and multi-source stress matrix

## Status and scope

| Field | Frozen value |
| --- | --- |
| State | Frozen prospective `S3.8` design, protocols, fixtures, and tolerances |
| Design date | 2026-07-18 |
| Entry revision | `e5f136e0d0d3fcc4c9c73756617c0c6f1561e283` (`e5f136e`) |
| Governing gate | `S3.8` motion and multi-source stress |
| Governing acceptance | `docs/development/specs/s0_squadbot_readiness_acceptance.md` §S3 |
| Passed predecessors | `S3.1` through `S3.7` |
| Evidence root | `outputs/isaac_audio_sensors/S3/S3.8/` |
| Required closeout | `docs/development/closeouts/S3/s3_8_motion_multi_source.md` |

This specification freezes the complete `S3.8` supported-combination matrix,
pure and live stress scenarios, invariants, resource bounds, and evidence
contract prospectively. It is documentation only and makes no implementation
or passing claim.

The governing acceptance is exact: no NaN, identity corruption, hidden
ambiguity, stale state, or unbounded resource growth; unsupported
combinations fail explicitly. Unsupported cases are recorded and excluded
from claims, never silently downgraded.

## 1. Responsibility boundary and entry-revision reality

`S3.8` integrates and stresses behavior already introduced by `S3.1` through
`S3.7`. It does not widen acoustic fidelity merely to make every matrix cell
green. Each backend is accepted only inside the envelope in §2.

At the entry revision:

1. `geometry_only` is L0 known-source geometry. It has no Doppler claim.
2. `tdoa_synthetic` is L1 synthetic time-difference geometry. Authored or
   pose-derived velocity affects Doppler diagnostics, not a rendered
   waveform.
3. `room_acoustics` and `room_acoustics_srp` are L2 waveform backends and are
   the only backends that support intra-window `segments_per_window > 1`,
   frequency-response FIRs, waveform noise, electronics, and the `S3.6`
   directivity stage.
4. The Isaac live adapter has pose history and implements authored-velocity
   precedence plus pose-derived velocity. Its complete effects configuration
   must be forwarded to the selected backend for the all-effects live case;
   forwarding only the motion subconfiguration is not compliant.
5. The Isaac Lab batched tensor kernel stores positions and orientations but
   no previous pose, velocity tensor, or velocity-source diagnostic. It cannot
   derive velocity and does not implement the waveform effects chain,
   occlusion, or materials. The Lab sensor's scalar core-frame path can carry
   an authored `AudioSceneSnapshot.velocity_world_mps` and remains the
   supported Lab authored-velocity path.
6. Gap preservation belongs to the recorder/session timeline, not a
   propagation backend. It is therefore not applicable in backend cells and
   is tested once at the session boundary.
7. There is no acoustic-result cache. Room/RIR state is recomputed for each
   segment, and live occlusion is resolved for each capture. `S3.8` tests this
   recompute-always baseline using the `S3.7` mutation reasons.

The `S3.1` deferred disposition is now closed: **Isaac Lab batched
pose-derived velocity is unsupported in Stage 1.** Enabling it on an
explicit batched compute path must raise `UnsupportedEffectError` before any
output tensor is returned. Authored velocity remains supported through the
Lab scalar core-frame path. An `auto` compute path may select scalar before
execution only if its diagnostics record `compute_path="scalar"` and the
capability reason; it must not run the batched kernel and silently discard
velocity.

## 2. Frozen supported-combination matrix

### 2.1 Cell vocabulary

Every cell has exactly one of these meanings:

- **S — supported:** the combination is claimed and must execute in `S3.8`.
- **U — unsupported, explicit error:** configuration must fail before a frame,
  waveform, or tensor is returned. The failure is evidence, not a skip.
- **N/A — not applicable:** the feature has no semantics at that layer. It is
  not counted as a passing supported combination.

“Channel response,” “noise,” “directivity,” and “materials” mean the
level-specific envelopes in §2.3, not an assertion that L0/L1 reproduce L2
waveform physics.

### 2.2 Matrix

| Backend/path | Authored velocity | Derived velocity | `segments>1` | Channel response | Noise | Electronics | Directivity | Occlusion | Materials | Gap preservation | Multi-source `2/4/8` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `geometry_only` L0 | N/A | N/A | U | S | S | U | U | S | S | N/A | S |
| `tdoa_synthetic` L1 | S | S | U | S | S | U | U | S | S | N/A | S |
| `room_acoustics` L2 | S | S | S | S | S | S | S | S | S | N/A | S |
| `room_acoustics_srp` L2 | S | S | S | S | S | S | S | S | S | N/A | S |
| Isaac Lab sensor, batched-selected envelope | S [1] | U | U | U | U | U | U | U | U | N/A | S |

[1] `S` preserves the Lab sensor's authored-velocity capability through its
scalar core-frame execution path. The batched tensor kernel itself is
velocity-invariant and makes no Doppler claim. With `compute_path="batched"`,
requesting authored-velocity Doppler semantics must fail explicitly rather
than ignore the authored value. The gate records the actual compute path for
every Lab row.

### 2.3 Exact cell envelopes

The matrix is interpreted as follows.

- **Velocity.** L1 reports a deterministic Doppler factor derived from
  source/receiver radial velocity. L2 resamples the waveform and reports the
  factor. L0 accepts valid scene records but makes no Doppler observation, so
  velocity is N/A rather than supported. Authored velocity always wins over a
  derived value. Derived velocity requires a primed, monotonic pose history.
- **Profiles.** Every L0/L1 S cell executes under both declared profiles,
  `metadata_only` and `waveform_fidelity`, while retaining its level-specific
  semantics. Every L2 S cell executes only under its declared
  `waveform_fidelity` profile. An undeclared profile is an explicit registry
  resolution failure, not a downgraded run.
- **Segments.** `segments_per_window=8` is the claimed stress setting. Only
  L2, profile `waveform_fidelity`, with derived poses supports it. L0, L1, and
  Lab reject it. The inherited maximum remains 64 and never exceeds the
  window sample count.
- **Channel response.** L0/L1 support metadata gain, delay, and polarity only;
  a frequency-response curve raises `UnsupportedEffectError`. L2 supports
  gain, delay, polarity, and magnitude-response FIR. Nonzero `phase_deg`
  remains unsupported everywhere.
- **Noise.** L0/L1 support clock jitter/drift metadata only; self-noise,
  ambient noise, or a noise spectrum raises `UnsupportedEffectError`. L2
  applies seeded self and ambient noise once to the mixture.
- **Electronics.** L2-only, applied once after mixture formation. L0/L1/Lab
  reject enabled electronics.
- **Directivity.** The matrix column means the `S3.6` waveform directivity
  effect. It is L2-only and remains `per_pair_direct_path`: the entire
  convolved source/microphone stem receives a weight computed from the direct
  path. It is not reflection-path-specific. The legacy intrinsic source
  `omni`/`cardioid` approximation on L0/L1 does not turn their U cell into S.
- **Occlusion.** L0/L1 consume per-pair broadband attenuation and surface
  occlusion metadata. L2 consumes per-pair band loss before source summation.
  Live raycasts remain an Isaac-layer responsibility.
- **Materials.** L0/L1 consume already-resolved nominal transmission loss via
  occlusion records. L2 additionally resolves measured room absorption.
  Transmission remains nominal-only and direct-ray; diffraction is not
  claimed.
- **Gap preservation.** The dataset/session writer preserves an opt-in gap in
  the audio timeline. No backend owns this behavior, hence all N/A cells.
- **Multi-source.** Counts 2, 4, and 8 must run without truncation with
  `max_events=8`. The saturation edge is specified separately in §5.

`room_acoustics_srp` with two microphones is outside the supported ambiguity
envelope at entry. It must raise `UnsupportedEffectError` rather than return
one confident SRP bearing. Two-microphone ambiguity coverage uses
`tdoa_synthetic` and the room GCC estimator. Lab TDOA requires at least three
microphones.

### 2.4 Frozen explicit failures

Existing validation messages for predecessor effects remain authoritative.
New `S3.8` checks freeze these exception classes and message fragments:

Every U cell in §2.2 raises `UnsupportedEffectError` unless this section
explicitly names another type. Registry/profile declaration failures remain
`ConfigValidationError`. Catching a generic `ValueError`, returning a frame
with an error diagnostic, warning and continuing, or selecting another path
does not satisfy a U cell.

| Unsupported request | Required exception | Required message fragment |
| --- | --- | --- |
| Lab batched pose derivation | `UnsupportedEffectError` | `derive_velocity_from_poses=true is unsupported by Isaac Lab batched compute in Stage 1` |
| Lab batched authored Doppler semantics | `UnsupportedEffectError` | `authored velocity Doppler semantics require the Lab scalar frame path` |
| Lab batched channel/noise/electronics/directivity | `UnsupportedEffectError` | exact configured `audio.effects.<stage>` path and `unsupported by Isaac Lab batched compute` |
| Lab batched occlusion or materials | `UnsupportedEffectError` | exact configured feature and `unsupported by Isaac Lab batched compute` |
| `room_acoustics_srp` with two microphones | `UnsupportedEffectError` | `room_acoustics_srp requires at least three microphones for an unambiguous S3.8 claim` |
| L0/L1 `segments_per_window>1` | `UnsupportedEffectError` | inherited `segments_per_window>1 is unsupported by backend` |
| Duplicate source id | `ValueError` | inherited `Duplicate source id '<id>'.` |
| Motion segments greater than sample count | `UnsupportedEffectError` | inherited `must be no greater than window_sample_count` |

Dependency absence is not an unsupported-combination pass. Direct backend
construction/simulation raises `OptionalDependencyUnavailable`; registry
resolution raises its existing `ConfigValidationError`. A required real-room,
Isaac, Lab, CUDA, or GPU row that cannot execute makes the applicable gate
`Blocked` and the aggregate verdict non-passing.

## 3. Canonical pure fixtures

### 3.1 Shared lattice, geometry, and signals

Unless a scenario overrides a value, use:

```text
sample_rate_hz = 48_000
window_duration_s = 0.050
window_sample_count = 2_400
segments_per_window = 8 where supported, otherwise 1
max_events = 8
room_dimensions_m = (12.5, 4.0, 3.0)
room_material_id = "pra.rough_concrete"
array_position_world_m = (1.0, 2.0, 1.5)
array_orientation_xyzw = (0.0, 0.0, 0.0, 1.0)
microphone_layout_m = cross4 at (+/-0.04, 0, 0), (0, +/-0.04, 0)
speed_of_sound_mps = 343.0
signal_seed = 20260718
noise_seed = 38017
```

Source ids are `source-00` through `source-09`, prim paths are
`/World/Audio/Source00` through `/World/Audio/Source09`, and creation order is
deliberately permuted. Expected ordering is canonical
`(start_time_s, source_id, prim_path)`, never discovery order. Signals are
different deterministic, band-limited seeded signals with nonzero energy
from 300 Hz through 6 kHz. Same-position sources retain different ids and
different signals.

The near/far fixture places one source at `(1.1, 2.0, 1.5)` and one at
`(11.0, 2.0, 1.5)`, exactly `0.1 m` and `10.0 m` from the array: a `1:100`
distance imbalance. The fixture controls source gains rather than normalizing
received stems, so it genuinely stresses dynamic range.

The two-microphone fixture uses the first opposing pair of the cross. It is
run only for producers with an explicit ambiguity policy. The three- and
four-microphone fixtures are non-collinear.

### 3.2 Canonical all-effects L2 configuration

The all-effects case enables every implemented L2 stage at once:

- motion derivation, authored-precedence check, and
  `segments_per_window=8`;
- per-microphone gain `(-1.5, 0.0, +1.0, -0.5) dB`, delay
  `(0, 1, 2, 3)/48_000 s`, alternating polarity, and deterministic
  three-point magnitude responses at 500, 2,000, and 6,000 Hz;
- finite microphone self-noise plus seeded diffuse and directional ambient
  noise;
- enabled AGC, clipping, 16-bit quantization, and deterministic dither;
- non-omnidirectional source and microphone patterns with valid
  orientations, retaining `per_pair_direct_path` semantics;
- per-source/per-microphone band occlusion, including nominal material
  transmission, before summation; and
- measured room absorption with `max_order=3`.

The gate serializes the fully resolved effects configuration and all seeds.
No test may replace a stage with a mock, zero-strength value, or metadata-only
stand-in while calling this “all effects.”

## 4. Frozen pure stress scenarios

Each applicable backend/path from §2 runs every scenario marked for its
supported envelope. Expected U cells are executed as negative tests.

| Id | Frames | Definition and required observations |
| --- | ---: | --- |
| `P01_velocity_authored` | 64 | Source radial velocities `(-5, -1, 0, +1, +5) m/s` and array radial velocities `(-1, 0, +1) m/s`; authored values win over deliberately conflicting derived candidates. L1 factors and L2 factors/waveforms agree with the signed radial convention and stay positive and finite. Lab runs through scalar; L0 records N/A. |
| `P02_velocity_derived` | 66 | Two prime frames followed by 64 measured frames on an exactly linear source and array trajectory using the same velocity ladder. Derived values match finite differences and the authored reference after priming. Lab batched executes the frozen error. |
| `P03_overlap_ladder` | 3 x 32 | Simultaneous 2-, 4-, and 8-source cases at distinct bearings; `max_events=8`; every active id persists, per-source diagnostics remain attributable, and no source is silently dropped. |
| `P04_coincident_sources` | 64 | Sources `source-00` and `source-01` occupy the exact same pose with distinct signals and ids. Geometry may coincide, identity may not. Ambiguity or coincident-geometry metadata is surfaced; ids never merge or swap. |
| `P05_near_far_1_100` | 64 | Exact `0.1 m` and `10.0 m` source distances plus two crossing frames; the far source remains attributable when observable, and absence due to an explicit estimator threshold is recorded rather than reassigned to the near id. |
| `P06_reverberation_ladder` | 4 x 16 | Real `pyroomacoustics`, L2 only, `max_order=(0, 1, 3, 6)` with identical inputs. Every row is finite and deterministic; diagnostics report the selected order; outputs are not byte-identical across all four orders. |
| `P07_moving_occluder` | 80 | Reuse the five-state `S3.7` clear/partial/blocked/material/clear sequence, one state per 16 frames, while one source and the array move. Current rays, attenuation, material evidence, waveform, RMS, and diagnostics agree. The final clear state cannot replay the blocked state. |
| `P08_moving_mount` | 128 | The array translates `0.50 m`, yaws from `-30` to `+30` degrees, and returns while four persistent sources remain fixed. Bearings follow the current array frame; derived receiver velocity is current; no prior-frame transform is reused. Angular velocity itself has no Doppler claim. |
| `P09_identity_churn` | 256 | `source-00` and `source-01` persist throughout. Other ids are added and removed on a frozen 16-frame cadence, including one remove/add in the same frame. Persistent ids never swap; removed ids disappear on that frame and never ghost. |
| `P10_all_effects_l2` | 32 | Eight sources, canonical all-effects configuration, `max_order=3`, `segments_per_window=8`, moving source, moving mount, and changing occlusion/material state. Effects ordering and once-per-mixture stages match predecessor contracts. |
| `P11_long_run` | 4,096 | L2 `room_acoustics`, exactly two active source slots, `max_order=1`, `segments_per_window=1`, all remaining L2 effects enabled, fixed allocation shapes, and deterministic id replacement without cardinality change every 256 frames. Apply §6 memory bounds after warm-up. |
| `P12_gap_preservation` | 96 slots | Backend-independent recorder case with 72 captured frames and every fourth 50 ms slot absent. With preservation enabled, markers and waveform placement retain all 96 slots and put exact zeros only in the 24 absent intervals; with preservation disabled, the captured blocks are contiguous. |
| `P13_determinism_replay` | replay | Rerun `P01` through `P12` in a fresh process with identical seeds and canonical inputs. Canonical frames, diagnostics, markers, and waveform bytes are byte-identical. Runtime telemetry is compared structurally but excluded from byte equality. |

The 2/4/8 ladder is tested on every S multi-source row. L2 rows use both room
estimators where valid. Real optional implementations are required; a fake
room is allowed only in focused unit tests and cannot satisfy a matrix row.

## 5. Mandatory edges and failure cases

1. **Zero sources.** L0/L1/L2 return a structurally valid, finite frame with
   zero detections and zero source stems; waveform backends return the defined
   silence/noise floor for their enabled configuration. Lab's fixed batched
   source shape cannot represent this case and raises `ConfigValidationError`
   containing `Isaac Lab batched compute requires at least one source`; it is
   not silently padded and claimed as tested.
2. **`max_events` saturation.** Ten simultaneously active, permuted sources
   with `max_events=8` retain exactly the first eight under canonical source
   ordering. Diagnostics record `active=10`, `retained=8`, `dropped=2`, and
   the exact dropped ids. No downstream component may choose a different
   eight.
3. **All sources silent.** Acoustic samples and RMS contain no unexplained
   nonzero energy except explicitly seeded noise. Analytic known-source
   detections, where a backend intentionally emits them, are labeled as such;
   a waveform estimator emits no confident false bearing from silence.
4. **Spawn/despawn in the same frame.** The removed id is absent in that
   frame, the new id is present if active, and neither inherits the other's
   identity, pose history, diagnostic record, or waveform attribution.
5. **Identical source ids.** Scene/config construction raises the exact
   inherited `ValueError("Duplicate source id '<id>'.")` before simulation.
6. **Sub-sample motion window.** A window of `0.25 / sample_rate_hz` rounds to
   zero motion samples. Requesting `segments_per_window=2` raises
   `UnsupportedEffectError` containing `must be no greater than
   window_sample_count=0`; it must not divide by zero, fabricate segment
   poses, or return a frame. A non-piecewise backend may retain its inherited
   one-sample clamp but makes no intra-window-motion claim for that window.
7. **Two-microphone ambiguity.** L1 and room GCC emit the existing ambiguity
   metadata and multiple candidate bearings or an explicit unresolved result.
   They never emit one high-confidence false bearing. SRP rejects the case as
   frozen in §2.4.
8. **Pose-history faults.** First observation, non-monotonic time, stale time,
   missing prim, and teleport threshold use the inherited `S3.1` policy. No
   stale derived velocity is reused.
9. **Optional dependency loss.** The row is `Blocked`, not passed, skipped,
   or replaced with another backend.

## 6. Frozen invariants and resource bounds

### 6.1 Finite-value scan

Every scenario recursively scans every numeric scalar and array in frames,
detections, diagnostics, effect descriptors, motion plans, telemetry fields,
and waveforms, plus decoded artifact WAV samples. NaN and positive or negative
infinity fail immediately.

The sole inherited exclusion is an actual USD default-time sentinel stored
under the exact dictionary key `time_code`. The scanner may exclude that
sentinel value only. It may not exclude the whole containing record, any
other key, string values that happen to contain “time,” or Lab padding.
JSON is serialized with `allow_nan=False`.

For Lab ladder rows, source count equals `max_events`, so the full returned
tensors are scanned without padding. Masked NaN padding in other Lab API
uses is not evidence for `S3.8` and is not exempted by this gate.

### 6.2 Identity, ambiguity, and current-state invariants

- Identity is keyed by stable `source_id`, never the frame-local
  `detection_id`, bearing rank, tensor row coincidence, or discovery order.
- A persistent source's id never changes or trades observations with another
  source. A removed source disappears in the first post-mutation frame and
  never ghosts. A newly added source starts a new history.
- Same-position sources remain distinct records even when their geometric
  observables coincide.
- The existing ambiguity policy is mandatory. Two-microphone cases surface
  ambiguity metadata or an unresolved result; no single confident false
  bearing is accepted. Normalized SRP confidence alone is not localization
  evidence.
- Every mutation is observed in the same frame after synchronization.
  Evidence includes the inherited `S3.7` reasons `room_geometry_changed`,
  `material_changed`, and `occluder_moved`, plus current source and array
  endpoints. No prior RIR, occlusion record, pose, effect state, waveform,
  RMS, or diagnostic may be replayed.
- Authored velocity precedence and every derivation reset reason remain
  visible in velocity-source diagnostics.

### 6.3 Determinism

Two fresh-process runs with the same canonical configuration, dependency
versions, seeds, and inputs must produce byte-identical canonical JSON and
little-endian float waveform bytes. Canonical JSON uses sorted keys, compact
separators, UTF-8, and `allow_nan=False`. Runtime timestamps, RSS samples,
latency samples, process ids, absolute output paths, and environment strings
are stored in telemetry but excluded from the deterministic payload hash.

A different signal or noise seed must change the corresponding payload hash;
this guards against a seed that is recorded but ignored.

### 6.4 RSS method and bounds

The RSS method is the established S2.9 endurance convention, not a new
portable-memory estimator:

1. on Linux read `VmRSS` in KiB from `/proc/self/status` in the same process
   as the gate;
2. after scene/backend construction and before frame 0, collect three samples
   and use their arithmetic mean as `baseline_rss_mib`;
3. collect at least every 5 seconds of wall time and force a sample every 64
   frames, after every source-churn mutation, after frame 4,095, and after
   teardown;
4. record raw frame index, monotonic timestamp, and RSS without smoothing;
5. fit ordinary least squares to `(frame_index, rss_mib)` for forced and
   periodic samples from frames 512 through 4,095 inclusive; report sample
   count, slope, intercept, and `R^2`; and
6. report peak RSS delta from the baseline separately from the slope.

`P11_long_run` passes memory only if all of the following hold:

```text
frame_count == 4_096
post_warmup_ols_slope_mib_per_1_000_frames <= 4.0
peak_rss_mib - baseline_rss_mib <= 128.0
final_post_teardown_rss_mib - baseline_rss_mib <= 32.0
```

The 128 MiB peak and 32 MiB settled bounds inherit the S2.9/S2 endurance
conventions. The 4 MiB/1,000-frame slope is an intentionally host-relative
linear-growth guard: it allows allocator warm-up and approximately 14 MiB of
post-warm-up drift over this run while rejecting one-frame-at-a-time retained
state. The prior S2.9 30,000-frame evidence peaked near 14.9 MiB over baseline,
so these bounds add stress headroom without permitting unbounded growth.

The script named `live_reliability_gate.py` is still rerun for failure and
teardown behavior, but it does not itself sample RSS at the entry revision.
`S3.8` therefore uses its teardown-safe verdict pattern and the S2.9
`VmRSS` measurement method. The evidence must say this explicitly.

### 6.5 Latency bounds

Pure stress records latency but has no absolute CPU budget. The new live gate
uses a paired same-process, same-stage effects-off control. It times the whole
capture/update path with `time.perf_counter_ns()`, including current pose
resolution, raycasts, backend simulation, effects, and in-memory invariant
checks, but excluding artifact serialization. It discards 60 warm-up frames
and retains 540 timed frames for each on/off phase.

The live stress latency regression passes when:

```text
effects_on_p95_ms <= (2.0 * effects_off_p95_ms) + 5.0
effects_on_p99_ms and maximum_ms are finite and reported
timed_frame_count == 540 for each phase
```

This is a relative regression guard, not a real-time envelope for L2 room
physics. It is robust to host speed while still detecting an accidental
superlinear or stalled all-effects path.

The separate Lab effects-off regression retains the S0/P1 fixture exactly:
4,096 environments, four microphones, two sources, `tdoa_synthetic`, CUDA,
`dt=0.02`, 10 warm-ups, 50 synchronized timed updates. Its effects-off p95
must be at most **20.0 ms**. The gate must compute and enforce p95 even if an
older helper only enforced the mean. Effects-on Lab performance is measured
with the same timing protocol and reported with its selected scalar/batched
path, but has no pass/fail budget in `S3.8`; its envelope is deferred to P1.

## 7. Live stress gate

### 7.1 New command and scene

Implementation adds `scripts/live_s3_stress_gate.py` and Make target:

```text
make live-s3-stress
```

The target launches headless Kit and executes the real stage, PhysX raycasts,
real room backend, effects chain, and artifact writers. It must not pass using
only import probes, mocks, a fake room, or artifact existence.

The live scene uses a 12.5 x 4.0 x 3.0 m room, a moving cross4 array mounted
under `/World/Robot/AudioMount`, two continuously sounding sources, and one
moving occluder with an authored nominal transmission material. Each on/off
phase schedules exactly 800 audio slots and deliberately throttles every
fourth slot, leaving exactly 600 captured frames. Captured frames 0 through
59 (the first 80 scheduled slots) are warm-up; captured frames 60 through 599
are the 540 measured frames. During each phase:

- source A traverses from `0.25 m` to `10.0 m` array range and back while
  crossing the array's forward axis;
- source B follows a lateral path at 3 to 5 m range so both sources overlap
  throughout;
- the mounted array translates 0.50 m and yaws from -30 to +30 degrees and
  back;
- the occluder cycles clear, partial, blocked/material-A,
  blocked/material-B, clear, with a physics synchronization before capture;
- velocities are pose-derived with `segments_per_window=8` and the all-effects
  L2 configuration from §3.2 is enabled; and
- the deterministic throttle skips slots whose zero-based scheduled index is
  congruent to 3 modulo 4. Audio windows retain scheduled timestamps, and the
  session writer has gap preservation enabled. The gate records scheduled,
  requested, throttled, and captured indices, writes exact silence for each
  absent interval, and never fills it with stale state.

The gate runs an effects-off paired phase as required by §6.5 and asserts all
applicable finite-value, identity, ambiguity, current-state, determinism,
RSS, and latency invariants live. Since the main live array has four
microphones, ambiguity is additionally checked in a short 16-frame
two-microphone GCC subcase; it is not inferred from the four-microphone run.

Live RSS uses the same `VmRSS`, baseline, and raw OLS conventions as §6.4,
with a forced sample every 20 captured frames. Over measured frames 60
through 599, each phase must have at least 27 samples, slope at most 8
MiB/1,000 frames, and peak delta at most 256 MiB. The single final
post-teardown delta must be at most 64 MiB. These looser Kit bounds admit lazy
simulator allocation while still rejecting a per-frame retained-state trend;
`P11` remains the authoritative long-run memory gate with the tighter
4/128/32 bounds.

### 7.2 Teardown and artifacts

All artifacts live under
`outputs/isaac_audio_sensors/S3/S3.8/`. The script creates parent directories,
writes temporary files in that directory, flushes and `fsync`s them, and
atomically promotes complete artifacts. A summary with a provisional
failure/verdict is durable before `SimulationApp.close()`. Teardown exceptions
are captured and the summary is atomically rewritten afterward. A missing or
malformed required artifact is failure, but existence alone is never pass.

The live gate writes:

| Artifact | Required content |
| --- | --- |
| `live_stress_summary.json` | scenario/config hashes, invariant verdicts, counts, dependency versions, teardown verdict, aggregate verdict |
| `live_stress_frames.jsonl` | canonical per-frame ids, poses, velocity sources, detections, ambiguity, mutation reasons, effect diagnostics |
| `live_stress_audio.wav` | interleaved finite four-channel measured waveform with exact sample metadata |
| `live_stress_telemetry.csv` | frame index, monotonic time, capture latency, RSS, phase, requested/captured/throttled state |
| `live_stress_stage.usda` | resolved test stage sufficient to audit paths and authored material state |
| `live_stress_environment.json` | command, revision, Python/Kit/CUDA/dependency versions and non-secret environment |
| `live_stress.log` | complete command stdout/stderr and exception traceback if any |
| `live_stress_sha256.json` | byte count and SHA-256 for every artifact except itself |

## 8. Required live regressions

The closeout reruns all of the following at the closeout revision; inherited
artifacts are not reused as execution evidence:

| Command | Frozen S3.8 verdict | Normalized S3.8 artifact |
| --- | --- | --- |
| `make live-isaac-sim-audio` | real headless Isaac capture passes its assertions | `live_isaac_sim_audio_regression.json` |
| `make live-isaac-occlusion` | live clear/blocked/material observations and teardown pass | `live_isaac_occlusion_regression.json` |
| `make live-isaac-lab-audio-gpu` | exact effects-off fixture; CUDA synchronized p95 `<=20.0 ms` | `live_isaac_lab_gpu_off_state_regression.json` |
| effects-on Lab timing companion | measure and report path, mean/p50/p95/p99/max; no budget verdict | `live_isaac_lab_effects_on_report.json` |
| `make live-reliability` | all planted failure scenarios and teardown-safe artifacts pass | `live_reliability_regression.json` |

Each normalized record includes command, start/end time, return code, parsed
assertions, source artifact paths and SHA-256 values, entry and closeout
revisions, and `Passed`/`Failed`/`Blocked`. Full logs are stored under
`regression_logs/`. `live_regression_verdicts.json` rolls up the five rows.
A target unavailable on the acceptance host is `Blocked`; it is never
“available therefore passed.”

## 9. Verification and evidence map

Evidence style is **execute everything**. A row passes only after its actual
assertions execute. Availability checks, collection-only tests, optional
dependency detection, pre-existing artifacts, or expected-error descriptions
cannot substitute for execution.

| Verification row | Required execution | Required evidence below `outputs/isaac_audio_sensors/S3/S3.8/` |
| --- | --- | --- |
| Matrix capability audit | instantiate every S cell and execute every U cell | `matrix_capabilities.json` |
| Velocity and Doppler | `P01`, `P02`, authored precedence, Lab negative | `velocity_stress.json` |
| Multi-source overlap | `P03`, `P04`, `P05`, saturation and silence | `multi_source_stress.json` |
| Reverb and all effects | `P06`, `P10`, real room dependency | `l2_effects_stress.json` |
| Occluder/mount/current state | `P07`, `P08` with S3.7 reasons | `dynamic_state_stress.json` |
| Identity/churn/ambiguity | `P09`, two-mic subcases, duplicate-id failure | `identity_ambiguity_stress.json` |
| Long-run resources | `P11`, raw RSS samples and OLS fit | `resource_stress.json`, `resource_rss.csv` |
| Gap preservation | `P12`, both preservation modes and exact marker/sample placement | `gap_preservation_stress.json` |
| Determinism | fresh-process `P13`, canonical payload hashes | `determinism_replay.json`, `determinism_sha256.json` |
| Edge and explicit errors | all §5 cases and exact exception assertions | `edge_failures.json` |
| New live stress | `make live-s3-stress` | all §7.2 artifacts |
| Live regressions | every §8 command/companion | all §8 normalized records and `live_regression_verdicts.json` |
| Aggregate verdict | parse and validate every preceding artifact | `stress_matrix_gate.json` |

`stress_matrix_gate.json` is the sole aggregate S3.8 verdict. It contains one
record for every S, U, and N/A matrix cell; one record for every pure/live
scenario and invariant; the exact resource bounds and observations; artifact
hashes; all blocked reasons; and a final `Passed`, `Failed`, or `Blocked`.
`Passed` requires every supported and negative-test row to have executed and
passed, every N/A row to carry its frozen rationale, and no blocked row.

The closeout report cites exact commands and artifacts, records unsupported
cases separately from supported claims, and states any deviation from this
specification. A changed bound, fixture, cell, exception class, or exclusion
requires a prospective design revision before evidence is collected.

## 10. Non-goals

`S3.8` does not include:

- robot control, planning, locomotion, or safety-policy evaluation;
- new propagation, diffraction, path-resolved directivity, transmission, or
  material physics;
- acoustic-result caching;
- performance optimization or a scaled effects-on 20 ms Lab claim—P1 owns
  the 20 ms performance gate at scale;
- a portable absolute L2 CPU/GPU latency promise;
- downstream protobuf, cue, policy, transport, or consumer testing—S5 owns
  those integrations; or
- silently selecting a lower fidelity, different backend, fewer effects,
  fewer sources, or scalar/batched path and describing it as the requested
  case.

## 11. Entry and closeout status contract

At entry, this document is the frozen design only. No matrix cell, scenario,
resource bound, live run, regression, or aggregate verdict is claimed passed
by this document.

At closeout, the required report must state:

1. the closeout revision and dirty-tree state;
2. the final supported/unsupported/N/A matrix and any approved design
   revision that changed it;
3. the Lab velocity disposition and proof that batched derivation fails
   explicitly while authored scalar velocity still works;
4. exact pure, live, and regression commands with counts and verdicts;
5. finite-value, identity, ambiguity, current-state, determinism, RSS slope,
   RSS peak/settled, and latency observations against frozen bounds;
6. every required artifact path and SHA-256;
7. every blocked or unsupported case, excluded from claims; and
8. limitations, open questions, and deviations.

The frozen design has no unresolved decision question. Implementation must
still prove that the live adapter forwards the complete effects configuration
and that the new Lab fail-closed checks occur before output; those are
acceptance work, not permission to reinterpret the matrix.

## References

- `docs/final_sensor_development_plan.md` §6.6, `S3.8`
- `docs/development/specs/s0_squadbot_readiness_acceptance.md`, `S3.8`
- `docs/development/specs/s3_acoustic_state_invalidation.md`
- all closeouts under `docs/development/closeouts/S3/`
- `src/isaac_audio_sensors/core/backends/`
- `src/isaac_audio_sensors/core/plugins/registry.py`
- `src/isaac_audio_sensors/core/effects/`
- `src/isaac_audio_sensors/core/motion/`
- `src/isaac_audio_sensors/lab/audio_array_sensor.py`
- `src/isaac_audio_sensors/lab/batched_backend.py`
- `src/isaac_audio_sensors/isaac/extension.py`
- `scripts/live_reliability_gate.py`
- `scripts/run_s3_2_live_time_gaps.py`
- `scripts/live_endurance_capture_gate.py`
- `Makefile`
