# S3 motion policies

## Status and scope

| Field | Frozen value |
| --- | --- |
| State | Frozen prospective `S3.1` design and tolerances; `S3.2` architecture reserved with tolerances deferred |
| Design date | 2026-07-18 |
| Entry revision | `839fe906ac3f65ed24e60a4ddca9b5c999923eb3` (`839fe90`) |
| Governing gates | `S3.1` pose-derived velocity; reserved `S3.2` time gaps and intra-window motion |
| Governing acceptance | `docs/development/specs/s0_squadbot_readiness_acceptance.md` §S3 |
| Evidence roots | `outputs/isaac_audio_sensors/S3/S3.1/` and, later, `outputs/isaac_audio_sensors/S3/S3.2/` |

This specification freezes the complete `S3.1` pose-derived linear-velocity
contract, policy order, defaults, fixtures, numerical tolerances, and evidence
map before implementation or acceptance evidence exists. It also fixes where
`S3.2` session gaps and piecewise intra-window motion will live, but does not
set `S3.2` numerical tolerances.

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

## 9. S3.2 time gaps and intra-window motion — architecture reserve

`S3.2` will preserve absolute simulation-time gaps at the continuous session
recorder boundary. Backends continue to produce one bounded capture window;
the recorder compares that window's absolute simulation placement with its
session cursor and inserts/advances the missing interval rather than
concatenating non-adjacent windows. Overlap or non-monotonic placement fails
before an append. The dataset/session writer remains responsible for atomicity,
bounded memory, sample accounting, and final gap metadata under the `S2.2`
contract; a propagation backend must not invent recorder silence.

The motion table's reserved `S3.2` field is:

| Field | Architectural default | Placement |
| --- | --- | --- |
| `segments_per_window` | `1` | Positive integer controlling piecewise pose/Doppler evaluation inside a capture window |

`segments_per_window=1` is a literal selection of the existing single-snapshot,
single-Doppler-factor room/TDOA code path, including the current
`_doppler_resampled_signal` call shape. Values greater than one will divide a
window into ordered subwindows and evaluate piecewise motion before mixture,
estimation, diagnostics, and export are finalized. `S3.2` owns interpolation,
segment-boundary assembly, gap sample rounding, and non-monotonic trajectory
rules. Until `S3.2` is implemented, a non-default explicit value is unsupported
and fails before output.

> **TOLERANCES DEFERRED:** gap sample-count/silence, pause/throttle,
> interpolation, segment-boundary continuity, and non-monotonic-time
> tolerances will be frozen in a dated revision of this specification before
> any `S3.2` acceptance evidence is generated or viewed. They may not be
> selected or adjusted from final `S3.2` results.

## 10. Non-goals and limitations

- No angular-velocity Doppler or angular-velocity field is introduced.
- No acceleration model or higher-order finite difference is introduced.
- No trajectory extrapolation predicts a pose beyond the latest resolved
  sample.
- No Isaac Lab batched derivation is claimed in `S3.1`; its `S3.8` disposition
  is explicit in §5.3.
- No intra-window pose interpolation, piecewise Doppler, or session-gap
  rendering is implemented or accepted by `S3.1`; those belong to `S3.2`.
- The existing one-factor-per-source room Doppler approximation and `[1/8, 8]`
  safety clamp remain unchanged for valid authored or derived velocities.
- Pose-derived velocity is simulation truth, not a calibrated real-world
  motion estimate and not evidence of sim-to-real fidelity.

## 11. Entry, closeout, and verification status

Implementation may begin only from the frozen `S3.1` policy, fixture,
measurement, and tolerance contract above. Changing an `S3.1` default,
formula, policy order, fixture, measurement method, or threshold after
acceptance evidence exists invalidates that evidence and requires a reviewed
dated design revision plus a complete rerun.

`S3.2` implementation may use the reserved placement in §9, but acceptance
evidence may not begin until its deferred tolerances are frozen prospectively.

This change is documentation only. No implementation, unit, integration,
Isaac, GPU, or hardware verification was run or is claimed by this
specification.

## References

- `docs/final_sensor_development_plan.md`, §§6.2 and 6.6 (`S3.1`, `S3.2`).
- `docs/development/specs/s0_squadbot_readiness_acceptance.md`, §S3 (`S3.1`, `S3.2`).
- `docs/development/specs/s3_channel_effects_chain.md`, especially §§2.4, 3.1, 3.4, and 13.
- `docs/development/specs/s2_atomic_writers.md`.
- `docs/development/closeouts/S3/s3_3_channel_response.md`, S3.1 input contract.
- `docs/room_acoustics.md`.
- `docs/roadmap.md`.
- `src/isaac_audio_sensors/core/types.py`.
- `src/isaac_audio_sensors/core/doppler.py`.
- `src/isaac_audio_sensors/core/backends/tdoa.py`.
- `src/isaac_audio_sensors/core/backends/room_acoustics.py`.
- `src/isaac_audio_sensors/core/config.py`.
- `src/isaac_audio_sensors/core/effects/config.py`.
- `src/isaac_audio_sensors/core/io/waveforms.py`.
- `src/isaac_audio_sensors/isaac/pose_resolver.py`.
- `src/isaac_audio_sensors/isaac/stage_snapshot.py`.
- `src/isaac_audio_sensors/isaac/stage_cache.py`.
- `src/isaac_audio_sensors/isaac/extension.py`.
- `src/isaac_audio_sensors/lab/audio_array_sensor.py`.
