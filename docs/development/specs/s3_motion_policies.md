# S3 motion policies

## Status and scope

| Field | Frozen value |
| --- | --- |
| State | Frozen prospective `S3.1` and `S3.2` designs, protocols, fixtures, and tolerances |
| Design date | 2026-07-18 |
| Entry revision | `839fe906ac3f65ed24e60a4ddca9b5c999923eb3` (`839fe90`) |
| S3.2 design revision | 2026-07-18 at `8bc7955e526e227b14d5e452ad774cd72d87f6ce` (`8bc7955`); the original S3.1 entry above remains authoritative for S3.1 |
| Governing gates | `S3.1` pose-derived velocity; `S3.2` time gaps and intra-window motion |
| Governing acceptance | `docs/development/specs/s0_squadbot_readiness_acceptance.md` §S3 |
| Evidence roots | `outputs/isaac_audio_sensors/S3/S3.1/` and `outputs/isaac_audio_sensors/S3/S3.2/` |

This specification freezes the complete `S3.1` pose-derived linear-velocity
contract, policy order, defaults, fixtures, numerical tolerances, and evidence
map. Its dated `8bc7955` revision also freezes the complete `S3.2` session-gap
and piecewise intra-window-motion protocol, tolerances, fixtures, and evidence
map prospectively, before `S3.2` implementation or acceptance evidence.

The design preserves the existing optional
`AudioSourceSpec.velocity_world_mps` and
`MicrophoneArraySpec.velocity_world_mps` fields. Pose derivation fills those
snapshot fields; it does not add velocity to the public frame schema or alter
the existing Doppler equations and `[1/8, 8]` factor clamp.

## 1. Problem definition and responsibility boundary

Live Isaac snapshots currently resolve source and array world poses on every
captured update, while the Doppler paths consume only velocities already
present on the core specs. `S3.1` connects those boundaries by deriving a
world-frame linear velocity from timestamped resolved poses.

Responsibilities are fixed as follows:

1. the pure core motion module owns pose history, finite differences,
   smoothing, and explicit result reasons;
2. the Isaac extension owns the history instance and its lifecycle;
3. live stage snapshot assembly applies authored-versus-derived precedence and
   writes the selected velocity into immutable source and array specs;
4. existing TDOA and room backends consume the selected snapshot field through
   their existing Doppler helpers; and
5. the extension adds one bounded, additive frame diagnostic describing where
   each selected velocity came from.

The authoritative derivation time is simulation time in seconds returned by
`IsaacAudioArraySensor._resolve_update_time`, before conversion to integer
`timestamp_ms`. USD time codes select the pose evaluated at that simulation
instant; integer frame timestamps are not differenced to estimate velocity.
All positions and velocities are in the existing right-handed Z-up world
frame and use metres and metres per second.

## 2. Pure pose-history contract

### 2.1 Module and public behavior

Implementation adds the import-safe module
`src/isaac_audio_sensors/core/motion/pose_history.py`. It may depend on the
standard library and pure core math/types only. It must not import NumPy,
Isaac, Omniverse, `pxr`, a propagation backend, or an effects stage.

`PoseHistory` is keyed by the exact entity id supplied by the caller: a
source's `source_id` or an array's `array_id`. Each entity owns a two-entry ring
buffer of samples:

```text
(time_s, position_world_m, orientation_world_xyzw)
```

`orientation_world_xyzw` may be `None`; it is retained for pose provenance but
is not used in the `S3.1` estimator. The ring capacity is exactly two because
the frozen estimator is a latest-pair backward difference. Smoothing state and
the last returned tagged result are retained separately per entity so they can
survive ring rotation and be replayed for a duplicate timestamp.

The conceptual interface is:

```text
PoseHistory(
    teleport_speed_threshold_mps=50.0,
    stale_time_s=0.5,
    smoothing_alpha=None,
)

observe(
    entity_id,
    time_s,
    position_world_m,
    orientation_world_xyzw=None,
) -> VelocityDerivation(velocity_world_mps, reason)

reset(entity_id=None) -> None
remove(entity_id) -> None
```

The exact concrete dataclass and type-alias names may follow repository style,
but the returned values and state transitions in this specification are
mandatory. `reset()` with no id clears all entity state; entity-scoped reset
and `remove()` clear the named entity only.

### 2.2 Exact estimator

For the latest valid pair with strictly increasing times
`P_(k-1) = (t_(k-1), p_(k-1), q_(k-1))` and
`P_k = (t_k, p_k, q_k)`, define:

```text
dt_k       = t_k - t_(k-1)
v_raw_k[i] = (p_k[i] - p_(k-1)[i]) / dt_k,  i in {x, y, z}
speed_k    = sqrt(sum_i(v_raw_k[i] ** 2))
```

Teleport detection always uses `speed_k` from the unsmoothed backward
difference. When `smoothing_alpha is None`, the returned velocity is exactly
`v_raw_k`.

When `smoothing_alpha = alpha`, smoothing is component-wise and is initialized
to the exact zero vector at the beginning of each entity session:

```text
v_smooth_0 = (0.0, 0.0, 0.0)
v_smooth_n = alpha * v_raw_n + (1.0 - alpha) * v_smooth_(n-1)
```

Here `n` counts accepted, strictly later, non-stale, non-teleport pairs since
the most recent first sample, reset, stale sample, or teleport. Only a
`reason="derived"` observation advances `v_smooth`. A duplicate timestamp,
invalid sample, stale gap, teleport, or time reset does not advance it. For a
constant true velocity `v`, exact arithmetic therefore gives
`v_smooth_n = (1 - (1-alpha)^n) * v` and component error
`abs(v_smooth_n[i] - v[i]) = (1-alpha)^n * abs(v[i])`.

### 2.3 Frozen policy order and tags

Derivation never substitutes an untagged zero velocity. Every successful
`observe` returns one of the following states:

| Condition | State mutation | Returned velocity | Exact reason |
| --- | --- | --- | --- |
| No prior sample for the entity | Store the sample as the sole ring entry; initialize smoothing to zero | `None` | `first_sample` |
| `time_s < latest.time_s` | Clear the entity, then store the current sample as the first sample of a new monotonic session | `None` | `time_reset` |
| `time_s == latest.time_s` | Do not append or mutate smoothing; replay the entity's preceding returned velocity and reason | unchanged | unchanged |
| `dt > stale_time_s` | Clear the entity and smoothing, then store the current sample as the new anchor | `None` | `stale_pose` |
| `speed_k > teleport_speed_threshold_mps` | Clear the entity and smoothing, then store the current sample as the new anchor | `None` | `teleport` |
| Otherwise | Append the sample, compute raw or smoothed velocity, and advance smoothing when configured | selected estimator value | `derived` |

Strict decrease has precedence over duplicate handling. Thus the requested
`dt <= 0` duplicate rule means `dt == 0` after the strictly-decreasing reset
case has been excluded. Stale handling precedes the finite-difference speed
test, so a large gap cannot be reclassified as a teleport. The teleport
comparison is strict: a speed exactly equal to the threshold is derived;
only a greater speed teleports.

Treating the current reset/stale/teleport pose as the new anchor means the
first new derived velocity is available on the second sample of the new
monotonic session. The first sample never yields `(0, 0, 0)` merely because a
previous pose is unavailable.

## 3. Selection, precedence, and diagnostics

### 3.1 Authored velocity always wins

For every source and array in a live snapshot:

```text
if spec.velocity_world_mps is not None:
    selected_velocity = spec.velocity_world_mps
    velocity_source = "authored"
elif derive_velocity_from_poses:
    result = pose_history.observe(...)
    selected_velocity = result.velocity_world_mps
    velocity_source = (
        "derived" if result.velocity_world_mps is not None
        else f"none:{result.reason}"
    )
else:
    selected_velocity = None
    emit no motion diagnostic
```

An authored tuple is copied into the output snapshot without arithmetic,
normalization, smoothing, thresholding, or conversion through a zero default.
The IEEE-754 bits of all three components must be preserved. Pose history is
still observed while an authored value wins when derivation is enabled; this
keeps policy state current if authorship is removed on a later update, but its
derived result is not selected or reported for that authored frame.

“Authored” means a non-`None` value already present on the source or array spec
before the motion-enrichment step, whether the spec came from validated config,
a direct core caller, or a future stage-authored mapping. `S3.1` does not
silently reinterpret an absent authored value as a zero vector.

### 3.2 Additive frame diagnostic

Only when `derive_velocity_from_poses=true`, every emitted frame contains:

```text
frame.diagnostics["motion"]["velocity_source"][entity_id]
```

The value is exactly one of:

```text
"authored"
"derived"
"none:first_sample"
"none:teleport"
"none:stale_pose"
"none:time_reset"
```

Duplicate timestamps retain the previous value because their result and
reason are unchanged. The mapping contains every source and the selected
array resolved for that frame, in deterministic source order followed by the
array. `entity_id` is the exact `source_id` or `array_id`. Because the flat
mapping cannot represent a cross-kind collision, derivation-enabled snapshot
validation fails before simulation if a source id equals the selected array
id; it never overwrites a diagnostic entry.

Motion diagnostics are separate from
`frame.diagnostics["effects"]`: velocity is snapshot motion metadata consumed
by propagation, not a post-synthesis channel operation. No `motion` key is
emitted when derivation is disabled, including for authored-velocity scenes.

### 3.3 Absent velocity and Doppler

An absent derived velocity on a first, reset, stale, or teleport frame means
“no trustworthy velocity estimate,” not an estimated zero. The existing
Doppler scalar treats an absent source/listener velocity as no radial term, so
the physical factor for a fixture in which both selected velocities are absent
is exactly `1.0`.

When derivation is enabled, the TDOA and room paths must record an explicit
`doppler_factor: 1.0` on a policy-absent active-source detection and must not
invoke waveform resampling for that source. TDOA per-microphone Doppler factors
are also exactly `1.0`. This explicit factor makes the no-spike assertion
observable without fabricating a zero velocity in the snapshot. Existing
derivation-disabled, velocity-free scenes retain their entry behavior and omit
Doppler diagnostics as they do at `839fe90`.

## 4. Configuration contract

### 4.1 `[audio.effects.motion]` fields and defaults

`MotionEffectsConfig` replaces the reserved `enabled/settings` placeholder
with the following exact `S3.1` fields. The derivation boolean is the motion
activation bit used by `EffectsConfig.all_disabled`.

| Field | Type | Frozen default | Valid range |
| --- | --- | --- | --- |
| `derive_velocity_from_poses` | exact `bool` | `false` | `false` or `true` |
| `teleport_speed_threshold_mps` | finite float, m/s | `50.0` | `0.0 < value <= 100.0` |
| `stale_time_s` | finite float, seconds | `0.5` | `0.0 < value <= 60.0` |
| `smoothing_alpha` | optional finite float | `None` (TOML field absent) | `None` or `0.0 < value <= 1.0` |

Example:

```toml
[audio.effects.motion]
derive_velocity_from_poses = true
teleport_speed_threshold_mps = 50.0
stale_time_s = 0.5
smoothing_alpha = 0.5
```

The `50.0 m/s` teleport default is 2.5 times the approximately `20 m/s`
upper end of physical source motion in the scoped scenarios and is above the
repository's existing `20-30 m/s` analytical Doppler fixtures. At the default
`343 m/s` speed of sound, a `50 m/s` radial source produces factors of only
about `1.171` closing and `0.873` receding, far from the `[1/8, 8]` safety
clamp. The threshold therefore rejects pose discontinuities before the clamp
can hide them while preserving all plausible scoped motion. It remains
configurable for a deliberately different scenario.

The `0.5 s` stale default permits ten missed nominal `0.05 s` extension
updates before refusing a cross-gap difference. That tolerates ordinary update
jitter but prevents a pause or throttled capture from becoming a false burst
of motion. Rendering the actual missing session time belongs to `S3.2`.

### 4.2 Fail-closed validation and hard off-state

Unknown motion keys, a non-boolean derivation flag, booleans supplied as
numbers, non-finite numbers, values outside the table ranges, malformed pose
vectors/quaternions, and non-empty id collisions fail before a partial frame,
waveform, diagnostic, or history mutation is emitted. Configuration errors use
the repository's `ConfigValidationError` and name
`audio.effects.motion.<field>`, the offending value, and the accepted range.
Runtime pose errors name the entity id, sample field, and value.

With `derive_velocity_from_poses=false`, no `PoseHistory` is allocated or
updated, no snapshot spec is replaced, no `motion` diagnostic is added, and no
new floating-point operation is applied to a pose, velocity, detection, or
waveform. For identical inputs, including existing explicitly authored
velocities, serialized frames and waveform assets are byte-identical to the
entry-revision path. This is the motion equivalent of the channel-chain hard
off-state.

Configuration-only/offline snapshots do not provide a live pose-time stream.
Their authored velocities continue to work, but enabling pose derivation for a
non-live sensor fails with `UnsupportedEffectError` before capture rather than
reusing a static pose or frame timestamp as a fake history.

## 5. Isaac wiring and lifecycle

### 5.1 Live update and snapshot assembly

Each `IsaacAudioArraySensor` owns at most one `PoseHistory`, created from its
validated motion configuration. On every captured live update, after
`StageAudioCache`/`IsaacStagePoseResolver` resolves current source and array
poses and before backend simulation:

1. snapshot assembly presents each resolved `(entity_id, time_s, pose)` to the
   owned history;
2. authored-versus-derived precedence from §3.1 is applied with immutable
   `dataclasses.replace`-style spec replacement only when the selected field
   differs;
3. the enriched `AudioSceneSnapshot` and selected array are passed to the
   unchanged backend Doppler equations; and
4. the bounded velocity-source map is attached to the returned frame.

The stage-snapshot API gains an internal motion-enrichment seam so integration
tests can supply a `PoseHistory` and explicit simulation `time_s` while using
fake `pxr`/`omni` stages. `StagePose.time_code` is provenance, not the numeric
velocity time base. A direct forced live capture must likewise supply a finite
simulation time; it may not derive from call count.

### 5.2 Reset, cache invalidation, and removal

The lifecycle rules are frozen:

| Event | Pose-history action |
| --- | --- |
| `IsaacAudioArraySensor.reset()` | `PoseHistory.reset()` after capture state is reset |
| Isaac timeline STOP or RESET event | `PoseHistory.reset()`; the first later sample is `first_sample` |
| Observed strictly decreasing simulation time without a prior event | Per-entity `time_reset` policy from §2.3 |
| Sensor close or stage replacement | Clear all history and release timeline subscription |
| Pose-only USD change (`xformOp:*`) | Keep history; the new pose is exactly the intended next input |
| Structural `StageAudioCache` invalidation | Do not clear history merely because discovery reruns |
| Confirmed entity removal, invalid prim, id-to-prim-path replacement, or disappearance after rediscovery | Remove only that entity's history before accepting a later entity with the id |

The extension subscribes to timeline lifecycle events alongside its existing
update subscription and releases both subscriptions on stop/close. Cache
invalidation and motion reset remain independent: resyncing a surviving prim,
changing discovery metadata, or explicitly calling `rediscover()` must not
erase valid motion history. Entity presence/prim-path comparison after a
successful rediscovery supplies the removal signal.

### 5.3 Isaac Lab limitation

The scalar and especially the batched Isaac Lab capture paths own independent
timestamp and tensor-pose lifecycles and do not pass through the extension's
single-stage `PoseHistory`. Lab batched pose-derived velocity is explicitly out
of `S3.1` scope. `S3.8` must either add and stress a per-environment batched
derivation contract or declare the combination unsupported. Until that
decision, requesting derivation on the Lab batched path fails explicitly; it
must not fall back to zero, silently switch compute paths, or report authored
motion.

## 6. S3.1 frozen defaults, fixtures, and tolerances

### 6.1 Frozen acceptance numbers

All errors are maximum absolute errors, never means or percentiles. A single
entity, component, sample, backend, or policy result outside its bound fails
`S3.1`.

| Criterion | Frozen pass threshold | Brief basis |
| --- | --- | --- |
| Raw constant-velocity recovery | For every derived sample and component, `abs(v_observed[i] - v_true[i]) <= 1e-9 m/s` | Backward difference of an exact linear trajectory is exact in real arithmetic; `1e-9 m/s` is tight float64 arithmetic headroom, not estimator slack |
| Smoothed constant-velocity recovery | With `alpha=0.5`, after exactly 40 derived updates, every component has absolute error `<= 1e-9 m/s` and remains within the bound | For scoped components `<= 20 m/s`, the analytical initialization residual is at most `20 * 2^-40 = 1.8189894e-11 m/s`, leaving over 50x float margin |
| Teleport classification boundary | `speed == 50.0 m/s` is `derived`; the next representable/tested value above it is `teleport` | The policy comparison is strictly greater-than and must be stable at the configured boundary |
| Teleport no-spike, TDOA | On the teleport frame, central and every per-microphone `doppler_factor == 1.0` using exact equality; waveform-rendered flag is false | Absent velocity removes both radial terms and must not be obscured by an approximate comparison |
| Teleport no-spike, room backend | On the teleport frame, detection `doppler_factor == 1.0` exactly, `doppler_waveform_rendered is False`, and the source is not passed through `_doppler_resampled_signal` | Proves the policy reaches the waveform path without a pitch spike or a synthetic zero velocity |
| Time reset | Reset frame returns `None/time_reset`; first new-session sample has no derived velocity, and the first derived value appears only when two monotonic-session samples exist | A backward difference requires two ordered samples; the reset pose is the first anchor |
| Authored precedence | `struct.pack(">ddd", *snapshot_velocity)` is byte-for-byte equal to the authored tuple's packed bytes for source and array fixtures | Proves no derivation, smoothing, normalization, or signed-zero loss touches authored values |
| Motion off-state | Frame JSON bytes, waveform bytes, Doppler diagnostics, and hashes are byte-identical to the `839fe90` goldens; no `motion` key | Disabled derivation must be the literal entry code path |

### 6.2 Frozen analytical fixtures

| Fixture | Frozen protocol |
| --- | --- |
| Raw linear source and array | float64-equivalent Python inputs; `t_k = 0.05*k s` for `k=0..40`; source `p_0=(1,-2,0.5) m`, `v=(20,-7.5,0.125) m/s`; array `p_0=(-3,4,1) m`, `v=(-2,1.25,0) m/s`; smoothing absent; assert first sample and every later component |
| Smoothed linear motion | Same source trajectory extended through 40 derived updates, `alpha=0.5`, smoothing zero-initialization from §2.2; assert the exact step count and analytical error envelope |
| Policy matrix | Independent entity cases for first sample, duplicate after first, duplicate after derived, strict decrease, gap exactly `0.5 s`, gap greater than `0.5 s`, speed exactly `50.0 m/s`, speed greater than `50.0 m/s`, and post-policy recovery |
| Teleport backends | Static quad array and one active source; establish samples at `1.00 s` and `1.05 s`, then move source `3.0 m` at `1.10 s` (`60 m/s` implied); run TDOA and room backends from the teleport snapshot with all other effects disabled |
| Authored precedence | Source and array authored tuples include ordinary finite values and `-0.0`; simultaneous pose deltas imply different derived values; compare packed IEEE-754 bytes in the enriched snapshot |
| Orientation only | Fixed position with changing valid quaternions; no smoothing gives exact `(0.0, 0.0, 0.0)` with reason `derived`; no angular velocity field or diagnostic appears |
| Off-state golden | Entry-revision live fake-stage, authored-velocity, TDOA, and room fixtures run with the motion table absent and with explicit default values; compare serialized frame/waveform bytes and SHA-256 values |

For a time reset, the decreasing-time observation is stored as sample one of
the new monotonic session. One subsequent strictly later observation is sample
two and may produce the first derived velocity. For an explicit timeline reset
that occurs before observation, the first post-event observation is
`first_sample` and the second may derive.

## 7. S3.1 verification map and evidence

Implementation is expected to add pure policy/estimator tests in
`tests/test_pose_history.py`, fake-stage snapshot/config integration tests in
`tests/test_motion_stage_snapshot.py`, and backend assertions in
`tests/test_motion_doppler_integration.py`. Exact function names may follow
repository style, but every row is mandatory.

| Acceptance criterion | Proof type and key assertion | Required evidence below `outputs/isaac_audio_sensors/S3/S3.1/` |
| --- | --- | --- |
| Raw recovery | Pure parameterized unit test for source/array trajectories; maximum component error `<= 1e-9 m/s` | `constant_velocity_results.json`, `constant_velocity_trace.csv` |
| Smoothing | Pure unit test against the closed-form recurrence at every step and the 40-step bound | `smoothing_settling_results.json`, `smoothing_settling_trace.csv` |
| Policy order and boundaries | Pure unit matrix; exact velocity/reason/state preservation, including duplicate and recovery cases | `pose_policy_matrix.json` |
| Invalid input/config | Pure config and history tests; typed failure before state or output mutation | `invalid_motion_config_matrix.json`, `invalid_pose_matrix.json` |
| Snapshot precedence | Integration through `stage_snapshot`/discovery with fake `pxr`/`omni`; packed authored bytes identical and derived values fill only `None` fields | `stage_snapshot_velocity_results.json`, `authored_precedence_bits.json` |
| Cache/lifecycle | Fake-stage cache and extension integration; pose-only edits preserve history, structural rediscovery preserves survivors, removals purge one id, reset events clear all | `pose_history_lifecycle.json`, `stage_cache_motion_trace.json` |
| TDOA teleport | End-to-end core backend test; exact central/per-mic unity factors and exact policy diagnostic | `tdoa_teleport_no_spike.json` |
| Room teleport | Optional-backend end-to-end test; exact unity factor, no resampling call, no rendered shift | `room_teleport_no_spike.json`, `room_teleport_waveform_sha256.json` |
| Hard off-state | Fake live-stage and backend golden regressions; exact bytes/hashes and no motion diagnostic | `motion_off_state_golden_sha256.json`, `motion_off_state_frame.json` |
| Live Isaac teleport | Running-stage source-prim teleport scenario from §7.1; exact unity factor on the teleport frame and next-frame recovery | `live_isaac_teleport_summary.json`, `live_isaac_teleport_frames.jsonl`, `live_isaac_teleport.log`, `live_isaac_teleport_stage.usda`, `live_isaac_environment.json` |

The focused pure/integration command is expected to be:

```text
python -m pytest -q \
  tests/test_pose_history.py \
  tests/test_motion_stage_snapshot.py \
  tests/test_motion_doppler_integration.py
```

The live scenario runs through a dedicated
`scripts/run_s3_1_live_pose_velocity.py` entry inside the selected Isaac Sim
runtime. A missing Isaac runtime, display/GPU prerequisite, or room-backend
dependency is `Blocked` under the S0 rules, not a skipped pass. The live test
is isolated from the pure suite and records the exact Isaac, Kit, Python,
driver, GPU, extension, and package revisions in `live_isaac_environment.json`.

`pose_velocity_gate.json` is the machine-readable roll-up. It records the
entry revision, package/runtime versions, normalized motion config, fixture
hashes, sample counts, every frozen default and tolerance, measured maxima,
exact-equality results, per-row pass/fail/blocked status, commands, live
environment identity, and SHA-256 for every artifact. The closeout is
`docs/development/closeouts/S3/s3_1_pose_velocity.md`.

### 7.1 Live Isaac scenario

Start a running stage with one static microphone array and one continuously
active source prim. Enable derivation with the frozen defaults, collect two
strictly monotonic `0.05 s`-spaced poses, then translate the source by exactly
`3.0 m` before the next update. Retain the pre-teleport, teleport, and two
recovery frames.

The teleport frame must report the source as `none:teleport`, leave its
snapshot velocity absent, report exact `doppler_factor == 1.0`, and render no
Doppler shift. The first later update supplies the second monotonic-session
sample relative to the teleport anchor and may report `derived`; no frame may
contain NaN, an extreme clamp factor, or a hidden zero fallback. The saved USD,
JSONL frames, log, environment record, and summary all land in the `S3.1`
evidence directory named in the verification table.

## 8. Edge cases and failure behavior

The mandatory boundary/invalid matrix includes empty ids; source/array id
collision; missing position components; malformed quaternion length;
non-numeric or non-finite time, position, orientation, thresholds, stale time,
or alpha; a first sample at zero or negative finite time; exact duplicate
timestamps; strictly decreasing time; exact and just-over stale/teleport
boundaries; entity removal and same-id/new-prim replacement; an empty scene;
and a frame with no active source.

Pose validation completes before any entity state changes. A NaN or infinity
in time, position, or a present orientation fails the update and preserves the
prior ring, smoothing state, last result, frame index, writer state, and output
artifacts. It does not become `first_sample`, `stale_pose`, `teleport`, a zero
velocity, or a partial diagnostic.

Orientation-only changes never create linear motion because only position is
differenced. With smoothing enabled, a zero positional raw sample legitimately
decays a prior smoothed estimate through the frozen recurrence; it still does
not represent angular velocity. Quaternion sign-equivalent poses (`q` and
`-q`) have no special velocity effect in `S3.1`.

An exactly zero positional difference over positive `dt` is a valid derived
zero velocity and is tagged `derived`; it is distinct from an absent velocity.
A duplicate after such a sample replays that derived zero and reason. An entity
that is removed cannot retain a smoothed tail if its id is later reused.

## 9. S3.2 frozen time-gap and intra-window-motion protocol

This section completes the architecture reserved by the original S3.1 design.
`S3.2` has two separately activated responsibilities:

1. the dataset/session recorder preserves missing absolute simulation time in
   continuous session audio; and
2. the live waveform backend may approximate motion inside one bounded capture
   window with ordered piecewise segments.

Neither responsibility changes an `ias.dataset_frame_record.v1` required
field, a shard-completion required field, the frame-v1 schema, the S3.1
estimator, or the default rendering path.

### 9.1 Ownership and configuration

Gap preservation is a recorder/session concern, not an acoustic effect. Its
single configuration field is an optional top-level field in the canonical
dataset session configuration:

| Field | Type | Frozen default | Valid values |
| --- | --- | --- | --- |
| `preserve_time_gaps` | exact `bool` | `false` when absent | `false` or `true` |

The field does **not** live under `[audio.effects.motion]`: a backend still
produces one bounded window, while only the dataset layer owns the continuous
audio cursor, shard rotation, cancellation, resume, and authoritative sample
ranges. With the field absent, the recorder executes the literal `8bc7955`
append path and does not allocate, compare, serialize, or checkpoint gap state.
Explicit `false` has the same runtime behavior, although its presence naturally
changes `session_config.json` bytes and the configuration hash.

Piecewise motion remains a propagation setting and adds this exact field to
`[audio.effects.motion]`:

| Field | Type | Frozen default | Valid range |
| --- | --- | --- | --- |
| `segments_per_window` | exact integer, not `bool` | `1` | `1 <= value <= 64`, and at runtime `value <= window_sample_count` |

`segments_per_window > 1` requires
`derive_velocity_from_poses=true`, a live pose-time stream, runtime profile
`waveform_fidelity`, and backend `room_acoustics` or
`room_acoustics_srp`. Other combinations fail before backend output with
`UnsupportedEffectError`. The upper bound prevents configuration-controlled
unbounded pose, RIR, and diagnostic work; the sample-count bound prevents empty
segments. `segments_per_window=1` selects the exact existing branch before any
new interpolation or allocation.

### 9.2 Absolute placement and exact gap decision

When `preserve_time_gaps=true`, every candidate frame must contain finite
`start_time_s` and `end_time_s`, and the recorder validates all of the
following before changing a frame index, writer, carry, checkpoint, or file:

- `timestamp_ms` is a non-negative integer and equals
  `round_half_even(1000 * start_time_s)` exactly;
- `round_half_even((end_time_s - start_time_s) * R) == W`, where `R` is the
  session sample rate and `W` is `window_sample_count`;
- the audio block is finite `float32` with exact shape `(channels, W)`; and
- `4 * channels <= 1_048_576`, so one float32 sample row fits the frozen
  insertion-allocation cap; and
- producer timestamp and placement ordering pass the rules below.

The exact round operation for every `S3.2` time-to-sample conversion is IEEE
round-to-nearest, ties-to-even: values with fractional part below `0.5` round
down, above `0.5` round up, and exact `n + 0.5` rounds to the even integer.
Python's integer result from `round(x)` for finite non-negative `x` is the
reference. No truncation, floor, round-half-away, or accumulated fractional
remainder is permitted.

The first accepted frame anchors episode time at `O = frame.start_time_s` and
receives no leading gap. The recorder's session cursor is the pair `(E_k,A_k)`:
the expected next start on the episode-relative integer sample lattice and the
total committed session-audio samples before candidate window `k`. Let
`H = hop_sample_count` and `S_k = frame.start_time_s`. For every candidate,
compute placement once with the frozen rounding rule:

```text
P_k_samples     = round_half_even((S_k - O) * R)
D_k_samples     = P_k_samples - E_k
Q_samples       = 0.1 * H
```

For the anchor, `P_k=E_k=0`. `D_k_samples` is therefore an exact integer;
placement rounding occurs once before the tolerance decision and is never
repeated on a delta. `Q_samples` is the frozen inclusive drift tolerance,
exactly one tenth of a hop. The decision is:

| Condition | Result |
| --- | --- |
| producer `timestamp_ms` is less than the preceding accepted timestamp | Reject as non-monotonic even if placement drift would be within tolerance |
| `D_k_samples < -Q_samples` | Reject as overlapping/backward window placement |
| `abs(D_k_samples) <= Q_samples` | Accept with zero inserted samples; signed drift is absorbed |
| `D_k_samples > Q_samples` | Exactly `G_k = D_k_samples` zero-input samples are due |

After an accepted candidate, the next expectation is phase-locked to that
candidate, `E_(k+1) = P_k + H`; absorbed drift therefore does not accumulate
until it becomes a fabricated pause. The corresponding expected absolute time
is `O + E_(k+1)/R`. The continuous audio cursor separately advances by exactly
`G_k + H` committed samples. At 48 kHz and a 0.05 s hop, `H=2400` and the
inclusive tolerance is exactly 240 samples or 5 ms. The 10% choice absorbs
timestamp quantization and ordinary scheduler jitter but remains well below
one missed capture hop.

### 9.3 Silence streaming and overlap/reverb carry

The recorder inserts the `G_k` samples immediately before window `k` through
the same staged WAV append and `CarryState` path used by ordinary frame audio.
No dataset-frame record is fabricated for the gap. Consequently the resumed
frame's authoritative `audio_start_sample` follows the inserted interval and
the gap remains unattributed, as already permitted by S2.1 §4.1.

"Silence" means zero new acoustic input, not forced-zero output. For every gap
sample, pending overlap/reverb carry is advanced by one sample and added to the
zero input. If the gap is shorter than the pending tail, the unconsumed tail
continues into the resumed frame; if the gap is longer, the tail decays into
the beginning of the gap and the remainder is exact zero. The tail is never
dropped, flushed instantaneously, or carried across elapsed time unchanged.
This is the physically honest rule: reverberation continues while sources are
silent.

Insertion is streaming. Each temporary zero-input/output block contains at
most

```text
min(65_536, max(1, floor(1_048_576 / (4 * channels)))) samples per channel
```

so each float32 silence array is at most 1 MiB regardless of gap duration or
channel count. The cancellation token is checked before every block and before
the resumed frame append. Implementations may use smaller blocks but may never
allocate an array proportional to the whole gap. The S2.2 `128 MiB` RSS,
session-growth, and file-descriptor gates remain unchanged and mandatory.

In aligned-shard mode, the disk-backed episode buffer stores the scalar gap
plan beside the existing frame metadata; it does not materialize or duplicate
the silence interval. Later assembly replays each plan in frame order and
streams its gap immediately before its audio block. Unaligned mode streams the
same plan immediately. Both modes therefore produce identical concatenated
audio and bounded memory for the same accepted frame stream.

### 9.4 Additive diagnostics without schema drift

`DatasetFrameRecord` parsing in `core/dataset/layout.py` requires exactly the
six frozen top-level fields, and shard markers likewise reject unknown fields.
Therefore `S3.2` adds no record, marker, manifest, or root-layout field. Gap
metadata lands only in the existing free-form frame diagnostic surface,
preserved inside the record's unmodified `frame` object:

```text
frame.diagnostics["recording"]["time_gap"] = {
  "placement_sequence": <next dataset_frame_index>,
  "placement_source": "frame.start_time_s",
  "expected_start_time_s": <float or null for the episode anchor>,
  "incoming_start_time_s": <float>,
  "placement_sample": <int>,
  "delta_samples": <int>,
  "tolerance_samples": <float>,
  "inserted_silence_samples": <int>,
  "absorbed_drift_samples": <int>,
  "session_audio_start_sample": <int>
}
```

The dataset layer must still obey S2.1's no-rewrite rule. A pure recorder-owned
placement planner computes a single-use plan against the current cursor; the
producer/controller attaches the exact mapping to a copied frame before
`append_frame`. `append_frame` recomputes and validates the plan and its
`placement_sequence` before mutation. A missing, stale, overwritten, or
disagreeing mapping is rejected rather than repaired. Existing unrelated
`recording` diagnostic keys are preserved; a conflicting `time_gap` key fails.
This handshake keeps placement authority in the recorder while storing the
producer-supplied frame byte-identically.

The recorder also maintains bounded scalar counters
`gap_event_count`, `inserted_silence_samples`, `absorbed_drift_count`, and
`absorbed_drift_samples_signed`. They are exposed by the recorder summary API,
persisted in internal staging/checkpoint state for resume, and copied into
`time_motion_gate.json`; they are not new published dataset-contract fields.
The canonical validator recomputes the placement sequence from frame times and
configuration, reconciles diagnostics and concatenated shard sample offsets,
and uses exact finding codes `time_gap_metadata_mismatch`,
`unexpected_audio_gap`, and `non_monotonic_window_placement`.

### 9.5 Failure, shard, resume, and episode behavior

The existing append error surface is retained. Recorder-side invalid placement
is a rejected producer frame: `AppendFrameResult(False, None, reason)` is
returned, drop accounting advances, and no dataset frame index or audio state
advances. Reasons contain `non-monotonic timestamp`,
`overlapping window placement`, or `time-gap diagnostic mismatch` so the
validator mapping remains stable.

The Isaac extension rejects invalid time earlier. Before throttle reuse or
`AudioTimeWindow` construction, a non-finite time, a strict decrease from the
last captured simulation time, or a forced duplicate/overlapping placement
raises `ValueError` and produces no backend call, frame, diagnostic, or writer
mutation. Ordinary strictly later sub-period ticks remain throttle drops and
return the latest frame; they are not candidate placements and create no gap.
An `end_time_s <= start_time_s` continues to fail in `AudioTimeWindow`.

At a pending mid-episode shard boundary, rotation occurs first, transfers the
existing `CarryState`, and then streams the gap at the beginning of the shard
containing the resumed frame. A first record may therefore have a positive
`audio_start_sample`. Carry checkpoint metadata additively includes the time
cursor and four summary counters. A completion marker is written only after
the entire gap and resumed frame are consistent.

Cancellation during gap insertion abandons the open, unmarked shard under the
S2.2 rules. Resume restores the last published carry/time checkpoint, requires
the producer to replay the uncommitted frame, and deterministically regenerates
the whole gap; a partial gap is never treated as committed. Ending or resetting
an episode flushes its tail under S2.1 and clears the placement cursor for the
next episode anchor, while the four session summary counters remain cumulative.
No gap crosses the reset and no silence is inferred between episodes.

### 9.6 Segment division and pose endpoint sourcing

Let `P = segments_per_window` and `W = window_sample_count`. Compute
`q, r = divmod(W, P)`. Segment `j`, zero-based, has `q + 1` samples when
`j < r` and `q` samples otherwise; the longer segments come first. Boundaries
are cumulative integers `b_0=0`, `b_P=W`, and segment times are derived only
from samples:

```text
t_j = window.start_time_s + b_j / sample_rate_hz
```

No independent floating division may choose a different boundary. Every
sample belongs to exactly one ordered half-open segment.

Piecewise live capture uses a bounded trailing window. Starting the sensor
primes `PoseHistory` at the current simulation time without emitting a frame.
At a later captured update `t_k`, the rendered window is exactly
`[t_k - W/R, t_k)`. The latest two-sample PoseHistory pair must bracket that
interval. Normal throttle capture supplies the nominal pair; after a tolerable
pause, the start endpoint is interpolated inside the older/current pair. A
forced update whose pair cannot bracket the trailing window fails before
output. A S3.1 policy-absent pair (`first_sample`, `time_reset`, `stale_pose`,
or `teleport`) uses the exact current position for all segments and exact
unity Doppler, preserving the S3.1 no-spike rule rather than extrapolating.

For each entity and each `t_j`, position is the component-wise linear
interpolation of the bracketing PoseHistory positions. Segment propagation
uses the position at its sample midpoint
`t_mid = start_time_s + (b_j + (length_j - 1)/2) / R`. Authored velocity still
wins unchanged; otherwise the tagged S3.1 derived velocity for the bracket is
used. Orientation is held at the current window-end orientation for all
segments: angular interpolation and angular-velocity Doppler remain out of
scope. The read-only interpolation seam does not change PoseHistory's exact
two-entry ring, estimator recurrence, policy order, or mutation rules.

### 9.7 Piecewise Doppler, scheduling, and room assembly

For each source and segment, the backend computes the existing central
source/array Doppler scalar from the segment-midpoint positions and selected
velocities, including the existing `[1/8, 8]` clamp. It then performs these
steps in deterministic source and segment order:

1. `_scheduled_window_signal` creates one sample-accurate source-relative
   signal for the full window, preserving absolute source phase, start, end,
   and leading scheduling silence.
2. A cumulative source-sample cursor starts at zero and is never reset at a
   segment boundary. For output sample `n` in segment `j`, it advances by that
   segment's Doppler factor. The sample value is deterministic float64 linear
   interpolation between `floor(cursor)` and the next scheduled input sample;
   out-of-range samples are zero. Exactly `length_j` output samples are
   produced, so concatenation is exactly `W` samples.
3. Room geometry and RIR are evaluated at each segment midpoint. Each
   segment's source/microphone response begins at `b_j`; its RIR remainder is
   overlap-added into later segments and the ordinary recorder carry. Tails
   therefore cross both segment boundaries and inserted zero-input gaps.
4. The assembled full-window premix feeds the existing effects chain,
   full-window estimator, detection construction, diagnostics, and waveform
   export once. No segment becomes a separate frame or detection.

The phase-cursor operation is the piecewise-only generalization adjacent to
`_doppler_resampled_signal`; it does not replace that helper. For `P=1`, the
branch calls the existing `_scheduled_window_signal`, one-factor
`_doppler_resampled_signal`, room simulation, and estimator with the exact
`8bc7955` call shapes and operation order.

At every internal boundary, the excess jump relative to the analytical
phase-continuous piecewise reference is measured as

```text
abs((y[b_j] - y[b_j - 1]) - (y_ref[b_j] - y_ref[b_j - 1]))
```

after peak-normalizing the compared non-silent fixture to full scale. The
maximum over sources, microphones, and boundaries must be `<= 2e-6` full
scale. This is a click-residual bound, not a ban on natural waveform slope or
a demand that adjacent audio samples be equal.

### 9.8 Analytical motion-error contract

The piecewise room solver holds geometry at one midpoint per segment. Let
`T=W/R`, `Delta_max=ceil(W/P)/R`, `v_max` be the maximum true entity speed in
the window, `a_max` a declared bound on acceleration magnitude, and `B` the
PoseHistory bracket duration. Linear interpolation of two bracket endpoints
has the standard constant-acceleration position bound

```text
epsilon_pose <= a_max * B^2 / 8.
```

Midpoint-held segment geometry adds at most

```text
epsilon_segment <= v_max * Delta_max / 2
                   + a_max * Delta_max^2 / 8.
```

The frozen acceptance inequality for every entity and tested sample is

```text
max_position_error <= epsilon_pose + epsilon_segment + 1e-9 m.
```

For the nominal bracket `B=T` and an exactly divisible window, this becomes

```text
max_position_error <= v_max*T/(2*P)
                      + a_max*T^2*(1 + 1/P^2)/8
                      + 1e-9 m.
```

The speed term is the honest error from holding moving geometry at a segment
midpoint; the second-order terms are the linear-interpolation and
constant-acceleration remainders. For exact constant velocity,
`epsilon_pose=0`; increasing `P` reduces the remaining bound linearly.

### 9.9 L0/L1 semantics, diagnostics, and determinism

`geometry_only` and `tdoa_synthetic` can expose one frame pose and one
window-effective Doppler metadata value, but cannot represent per-segment
waveform geometry or assemble segment RIR tails. They therefore reject
`segments_per_window>1` explicitly; they do not average positions, factors,
or velocities and do not claim piecewise motion. Their `P=1` behavior is
unchanged.

Supported waveform frames add to the existing S3.1 motion diagnostic:

```text
frame.diagnostics["motion"]["segments_per_window"]
frame.diagnostics["motion"]["segments"]
```

The ordered `segments` array contains `index`, `start_sample`, `end_sample`,
`start_time_s`, `end_time_s`, and, under exact entity ids, the start/end/mid
`position_world_m`, selected `velocity_world_mps` or `null`, and
`velocity_source`. It also contains `doppler_factor_by_source`. The bounded
`P<=64` array is diagnostic metadata inside frame v1; it adds no public frame
field. The full-window detection remains the result of the assembled waveform
and is never mislabeled as a per-segment detection.

Fixed inputs, source order, pose history, configuration, dependency versions,
and platform produce byte-identical frames and waveform bytes. Segment
iteration, entity mappings, remainder allocation, summation order, and
float64-to-float32 conversion order are fixed as stated above. Default
`P=1` leaves registry declarations and self-tests unchanged, and a repeated
`P>1` registry self-test fixture must also reproduce hashes.

## 10. Non-goals and limitations

- No angular-velocity Doppler or angular-velocity field is introduced.
- No acceleration model or higher-order finite difference is introduced.
- No trajectory extrapolation predicts a pose beyond the latest resolved
  sample.
- No Isaac Lab batched derivation is claimed in `S3.1`; its `S3.8` disposition
  is explicit in §5.3.
- S3.1 by itself still makes no intra-window or session-gap claim; those
  behaviors require the independently enabled S3.2 paths in §9.
- No angular pose interpolation or continuously moving RIR solver is claimed.
- The existing one-factor-per-source room Doppler approximation remains the
  exact `segments_per_window=1` path; piecewise mode uses one central factor
  per segment. The `[1/8, 8]` clamp is unchanged in both paths.
- Pose-derived velocity is simulation truth, not a calibrated real-world
  motion estimate and not evidence of sim-to-real fidelity.

## 11. S3.2 frozen fixtures and acceptance numbers

All sample counts and span endpoints are exact integers. All floating errors
are maximum absolute errors, never means or percentiles. One out-of-bound gap,
entity, segment, boundary, channel, sample, backend, or replay fails S3.2.

### 11.1 Frozen acceptance table

| Criterion | Frozen pass threshold | Brief basis |
| --- | --- | --- |
| Pause sample count | At 48 kHz, `W=H=2400`, starts `0.00, 0.05, 0.45 s` produce exactly `16,800` inserted samples, a final stream length of exactly `24,000`, and the zero-tail gap span `[4,800, 21,600)` | The third expected start is `0.10 s`; `(0.45-0.10)*48000=16800` exactly |
| Throttle sample count | Kit ticks every `0.01 s` from `0.00` through `0.10 s`, with a `0.05 s` capture period, produce captured starts `0.00, 0.05, 0.10`, zero inserted samples, and exactly `7,200` output samples | Sub-period ticks are throttle reuse, not dropped candidate windows |
| Gap tolerance | With `H=2400`, a `+240` or `-240` sample placement delta is accepted with zero insertion; `+241` inserts exactly `241`; `-241` rejects before append | Placement is rounded once to the integer lattice before the inclusive `0.1H` comparison |
| One-sample/subsample gap | At the same hop, `+1`, `+0.5`, and any positive gap below one sample are absorbed with zero insertion and no zero-length write | Such drift is far inside the frozen 240-sample tolerance |
| Round-half-even | In a fixture with `H=10` (`Q=1`), positive gaps of `2.5` and `3.5` samples insert exactly `2` and `4` samples | Freezes tie behavior independently of binary time representation by constructing exact decimal/rational inputs |
| Reverb through gap | For a known carry vector and gap length `G`, the first `min(G, carry_length)` output samples equal the carry advanced sample-for-sample; remaining due samples are exact zero, and any unconsumed carry is bit-identical at resume | Proves elapsed silence neither drops nor freezes a tail |
| Silence memory | Every gap allocation obeys the 1 MiB and 65,536-sample block caps; S2.2 W1/W2 memory and growth limits still pass | Gap duration must not control memory use |
| Constant-velocity interpolation | `v=20 m/s`, `T=0.05 s`, `P=8`, `a=0`: endpoint interpolation error `<=1e-9 m`; midpoint-held maximum error `<=0.062500001 m` | `20*0.05/(2*8)=0.0625 m` plus numerical headroom |
| Constant-acceleration interpolation | 1-D `p(t)=12t+4t^2 m`, `T=B=0.05 s`, `P=8`: interpolation-only error `<=0.002500001 m`; total midpoint-held error `<=0.0412890635 m` | `v_max=12.4 m/s`, `a=8 m/s^2`; evaluates the frozen first- and second-order terms |
| Circular speed-dependent bound | Constant-speed circle, `v=20 m/s`, radius `10 m`, `T=B=0.05 s`, `P=8`: maximum position error `<=0.0751953135 m` | `a=v^2/r=40 m/s^2`; explicitly ties the acceleration term to speed |
| Segment continuity | Maximum normalized boundary jump residual `<=2e-6` full scale for every source and microphone | Approximately -114 dBFS; below a click-sized discontinuity while retaining natural slope |
| Segment sample accounting | Segment lengths are exactly `q+1` for the first `r` and `q` thereafter; sum exactly `W`; every assembled source and frame mixture is exactly `W` samples before RIR tail | Prevents loss, duplication, or time drift at remainders |
| Unsupported L0/L1 | `segments_per_window=2` fails with `UnsupportedEffectError` before output on `geometry_only` and `tdoa_synthetic` | Their contracts cannot encode piecewise waveform motion honestly |
| Non-monotonic/overlap | Decreasing timestamp, placement at `-(Q+1)` samples, forced duplicate captured time, and `end<=start` each fail before append/backend mutation | Preserves existing monotonicity and makes placement overlap explicit |
| Gap off-state | With `preserve_time_gaps` absent, pinned `8bc7955` frame JSON, WAV, record, marker, manifest, and SHA-256 bytes are identical | Absent default must be the literal entry path |
| One-segment identity | With `segments_per_window=1`, backend frame JSON and waveform bytes are identical to the equivalent field-absent `8bc7955` result; no segment diagnostic is emitted | Proves literal selection of the current room/TDOA call path |
| Determinism | Two runs of every pure/integration fixture have identical frame, WAV, JSON/CSV, and gate hashes under pinned versions | Required for replay and registry claims |

### 11.2 Frozen fixture and measurement protocols

**Pause and throttle.** Use four float32 channels at 48 kHz, `W=H=2400`,
carry-free deterministic blocks, and capture starts from the first two table
rows. The first and last 32 samples of each non-gap block contain a nonzero
known-answer marker; all due gap input is zero. Decode the final WAV, locate
the markers, assert exact length/span/sample values, reconcile every record
range and time-gap diagnostic, and hash the WAV. A second variant supplies a
known finite carry `[1, 1/2, 1/4, ...]` independently per channel and compares
every gap/carry output bit.

**Tolerance and rounding.** Construct placement deltas as exact rational
sample counts divided by `R`, not by inspecting a produced float and choosing
a nearby threshold. Cover zero, `+/-Q`, `+/- (Q+1)`, one sample, half a sample,
`2.5`, and `3.5` sample cases. Record raw `D_k_samples`, rounded `G_k`, decision,
cursor before/after, and error surface in `gap_rounding_matrix.json`.

**Piecewise motion.** Use `R=48000`, `W=2400`, `P=8`, a static quad array, and
one continuously active deterministic two-tone source. Evaluate these exact
trajectories over `[0, 0.05] s`:

- linear: `p(t)=(1+20t, -2, 0.5) m`;
- constant acceleration: `p(t)=(12t+4t^2, 0, 0) m`; and
- circular: `p(t)=(10*cos(2t), 10*sin(2t), 0) m`, whose speed is exactly
  `20 m/s` and acceleration magnitude exactly `40 m/s^2`.

Sample the analytical trajectory at every segment endpoint, midpoint, and at
least 1,001 evenly spaced evaluation times. Compare PoseHistory interpolation
and midpoint-held geometry separately to the closed forms, then apply the
inequalities in §11.1. The test may report tighter observed error but may not
replace the frozen bounds.

**Continuity.** Use the same 2,400-sample two-tone window with eight segments
and factors `(0.95, 0.97, 0.99, 1.00, 1.01, 1.03, 1.04, 1.05)`. Generate the
analytical phase-cursor reference in float64, peak-normalize non-silent source
and microphone outputs, and evaluate only the seven exact sample boundaries
with the §9.7 residual. Also scan the full output for NaN, infinity, lost or
duplicated samples, and an impulse exceeding the reference residual bound.

### 11.3 Mandatory edge and failure cases

- A first frame anchors its episode and never creates leading silence.
- A zero-length gap, a gap rounding to zero, and a gap smaller than one sample
  perform no write; their diagnostics remain explicit and counters unchanged.
- Drift exactly at either tolerance boundary is absorbed; only a more-negative
  placement is overlap and only a more-positive placement creates silence.
- A gap at a pending frame-count shard cut rotates first. Carry and time cursor
  checkpoints transfer, the complete marker for the preceding shard remains
  valid, and concatenated audio matches an unsharded run bit-for-bit.
- Cancellation at the first, middle, and final silence block publishes no
  partial-gap marker. Resume replays the frame and regenerates the complete gap
  and diagnostics byte-for-byte.
- Interruption after all gap samples but before the frame record is still an
  uncommitted gap and is regenerated on resume.
- Episode end/reset flushes carry, clears placement state, and makes the next
  frame a fresh anchor. A pause never spans or creates an episode reset.
- Missing frame window endpoints, timestamp/start mismatch, wrong block shape,
  non-finite placement, decreasing timestamp, excessive negative placement,
  stale placement plan, and conflicting diagnostic key all reject before
  state mutation.
- `P>W`, `P>64`, `P=0`, negative, boolean, non-integer, unsupported backend,
  offline/static pose stream, and unbracketed forced live capture all fail
  before output. Uneven `W/P` and `P=W` cover remainder and one-sample segments.
- A S3.1 absent/teleport/stale segment fixture has static current positions,
  exact factor `1.0`, no resampler invocation, and no spike.

## 12. S3.2 verification map and evidence

Implementation is expected to add focused tests in
`tests/test_dataset_time_gaps.py`, `tests/test_intra_window_motion.py`, and
`tests/test_time_motion_integration.py`. Exact test function names may follow
repository style, but every row is mandatory.

| Acceptance criterion | Proof type and key assertion | Required evidence below `outputs/isaac_audio_sensors/S3/S3.2/` |
| --- | --- | --- |
| Pause/throttle accounting | Pure recorder integration; exact captured starts, gap span, sample count, ranges, counters, and WAV samples | `pause_sample_accounting.json`, `pause_frames.jsonl`, `pause_audio.wav`, `throttle_trace.jsonl` |
| Tolerance/rounding | Pure parameterized placement planner and recorder boundary tests; exact decisions at every frozen rational case | `gap_rounding_matrix.json`, `gap_cursor_trace.csv` |
| Carry and bounded streaming | Recorder/WAV integration with known carry, long gap, allocation spy, and cancellation per block | `gap_carry_results.json`, `gap_carry_trace.csv`, `gap_memory_telemetry.json` |
| Additive schema/validator | Layout round-trip keeps six exact record fields; diagnostics reconcile; each planted mismatch emits its exact finding code | `gap_metadata_results.json`, `gap_validator_findings.json` |
| Shard/cancel/resume | Single-vs-multishard and uninterrupted-vs-resumed byte comparison, including interruption mid-gap | `gap_shard_resume_results.json`, `gap_shard_hashes.txt`, `gap_cancellation_matrix.json` |
| Segment partition/endpoints | Pure known-answer division and PoseHistory interpolation tests; exact boundaries, endpoint source, policy-absent behavior | `segment_partition_results.json`, `segment_pose_trace.csv` |
| Analytical motion bounds | Pure analytical fixtures; every sampled error obeys the declared interpolation and total inequalities | `interpolation_error_results.json`, `interpolation_error_trace.csv` |
| Doppler/RIR assembly | Room-backend integration; per-segment factors/geometry, exact `W`, tail carry, full-window estimator, finite output | `piecewise_room_results.json`, `piecewise_doppler_trace.csv`, `piecewise_waveform_sha256.json` |
| Boundary continuity | Analytical phase reference at every boundary; maximum residual `<=2e-6` | `segment_continuity_results.json`, `segment_continuity_trace.csv` |
| L0/L1 rejection | Backend matrix; exact pre-output `UnsupportedEffectError`, no files or diagnostics | `unsupported_segment_backend_matrix.json` |
| Off-state and `P=1` | Pinned `8bc7955` golden regressions and call-spy proof of literal branches | `time_gap_off_state_sha256.json`, `segments_one_golden_sha256.json`, `registry_self_test.json` |
| Live throttled capture | Running Kit scenario below; exact 16,800-sample gap and clean resume | `live_throttled_capture_summary.json`, `live_throttled_capture_frames.jsonl`, `live_throttled_capture_audio.wav`, `live_throttled_capture.log`, `live_throttled_capture_stage.usda`, `live_time_motion_environment.json` |
| S2 reliability regression | Rerun the complete recorder reliability target after implementation | `live_reliability_rerun.log`, `live_reliability_rerun_summary.json` |

The focused pure/integration command is expected to be:

```text
python -m pytest -q \
  tests/test_dataset_time_gaps.py \
  tests/test_intra_window_motion.py \
  tests/test_time_motion_integration.py
```

Because S3.2 touches `SessionRecorder`, `CarryState` checkpoint use, shard
rotation, cancellation, and resume, `make live-reliability` must be rerun after
implementation. A shortened or substituted command does not close that row.

`time_motion_gate.json` is the mandatory machine-readable roll-up. It records
the S3.2 design revision, package/runtime/dependency versions, normalized
configuration, all frozen constants and formulas, fixture hashes, sample and
segment counts, cursor/counter reconciliations, measured maxima, exact-equality
results, validator finding codes, per-row pass/fail/blocked status, commands,
live environment identity, and SHA-256 for every artifact. A missing Isaac,
GPU/display, or room dependency is `Blocked` under S0, never a skipped pass.

### 12.1 Live Kit pause/resume scenario

Run Kit with one static four-microphone array and one continuously active
source, 48 kHz, a 0.05 s capture period, `W=H=2400`, room waveform output, and
`preserve_time_gaps=true`. Capture windows starting at `0.00` and `0.05 s`,
pause the sensor's capture subscription while the Kit timeline continues, and
resume capture at `0.45 s`. Do not pause simulation time: the purpose is to
exercise the same dropped sub-period/capture interval that occurs under live
throttling.

The output must contain exactly 16,800 zero-input elapsed samples before the
resumed window, exact total/sample-range accounting from §11.1, a decaying RIR
tail rather than an instantaneous cut, no duplicate frame, and validator-clean
published shards. Then enable `P=8` in a separate continuously moving-source
phase, retain the primed and rendered windows, and prove finite per-segment
poses/factors plus the continuity bound. Save the USD, frame trace, WAV, log,
environment, and summary under the names in the verification table before Kit
teardown.

## 13. Entry, closeout, and verification status

Implementation may begin only from the frozen S3.1 and dated S3.2 policy,
fixture, measurement, and tolerance contracts above. Changing an S3.1 or S3.2
default, formula, policy order, rounding rule, fixture, measurement method, or
threshold after acceptance evidence exists invalidates the affected evidence
and requires a reviewed dated design revision plus complete affected and
regression reruns.

S3.2 closeout is
`docs/development/closeouts/S3/s3_2_time_motion.md`. It must reconcile every
row in §12 with `time_motion_gate.json`, retain blocked rows honestly, and
carry the exact supported-backend and fidelity limits into S3.7/S3.8.

This change is documentation only. No implementation, unit, integration,
Isaac, GPU, or hardware verification was run or is claimed by this
specification.

## References

- `docs/final_sensor_development_plan.md`, §§6.2 and 6.6 (`S3.1`, `S3.2`).
- `docs/development/specs/s0_squadbot_readiness_acceptance.md`, §S3 (`S3.1`, `S3.2`).
- `docs/development/specs/s3_channel_effects_chain.md`, especially §§2.4, 3.1, 3.4, and 13.
- `docs/development/specs/s2_atomic_writers.md`.
- `docs/development/specs/s2_session_shard_layout.md`.
- `docs/development/closeouts/S3/s3_3_channel_response.md`, S3.1 input contract.
- `docs/room_acoustics.md`.
- `docs/roadmap.md`.
- `src/isaac_audio_sensors/core/types.py`.
- `src/isaac_audio_sensors/core/doppler.py`.
- `src/isaac_audio_sensors/core/backends/tdoa.py`.
- `src/isaac_audio_sensors/core/backends/room_acoustics.py`.
- `src/isaac_audio_sensors/core/config.py`.
- `src/isaac_audio_sensors/core/effects/config.py`.
- `src/isaac_audio_sensors/core/motion/pose_history.py`.
- `src/isaac_audio_sensors/core/dataset/layout.py`.
- `src/isaac_audio_sensors/core/dataset/recorder.py`.
- `src/isaac_audio_sensors/core/dataset/validate.py`.
- `src/isaac_audio_sensors/core/io/waveforms.py`.
- `src/isaac_audio_sensors/isaac/pose_resolver.py`.
- `src/isaac_audio_sensors/isaac/stage_snapshot.py`.
- `src/isaac_audio_sensors/isaac/stage_cache.py`.
- `src/isaac_audio_sensors/isaac/extension.py`.
- `src/isaac_audio_sensors/lab/audio_array_sensor.py`.
