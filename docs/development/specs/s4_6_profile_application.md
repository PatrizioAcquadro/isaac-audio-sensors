# S4.6 profile and configuration application

## Status and authority

This specification freezes the S4.6 application contract. It is additive and
does not change `ias.audio_calibration_profile.v1`, any S4.4/S4.5 evidence, or
the scientific decisions in the authoritative S4.5 amendment.

The only authorized input is the bundle reached through:

`outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json`

The pointer must resolve the exact active S4.5 handoff and v2 profile declared
there. Direct profile paths, the historical v1 profile, and alternate pointers
are never application inputs.

## Atomic resolution and application

An enabled application performs these stages in order:

1. parse and validate the versioned S4.6 configuration contract;
2. safely resolve the fixed active pointer inside the repository;
3. verify pointer schema, active status, count, v2 identity, paths, and hashes;
4. safely resolve and verify the bound handoff and profile;
5. validate the public profile schema and import-safe profile dataclasses;
6. validate every identity, status, field declaration, retained-count
   semantic, functional-association, fixture, geometry, and environment guard;
7. validate the complete unadjusted runtime context;
8. compute the complete immutable application plan and field-status report;
9. create the adjusted configuration only after every prior stage passes.

No validation stage mutates the input configuration. Any failure rejects the
whole operation. No supported field may be used before the complete plan is
valid.

Repository-relative paths must use normalized POSIX syntax, remain beneath the
repository root, and refer to regular files. Absolute paths, Windows drives,
backslashes, parent traversal, symlink escapes, missing members, and alternate
active-pointer locations are rejected.

## Exact compatibility context

The application context must match all values in
`configs/s4_6_profile_application.v1.json`, including:

- active profile identity, version, path, and SHA-256;
- active handoff identity, path, and SHA-256;
- active pointer identity, count, status, and routing policy;
- device and model identity;
- array identity;
- sample rate, channel count, and channel order;
- array frame, source frame, and coordinate convention;
- temporary mount/fixture identity;
- functional association identity, frame, mapping digest, and nominal geometry
  status;
- the complete ordered environment-tag tuple;
- supported-field and unsupported-field declarations;
- corrected retained-count semantics; and
- frozen/active/inactive bundle statuses.

The temporary mount identity is `S4_TEMP_DESKTOP_FIXTURE_REV0`. Geometry
identity is guarded by the exact active profile and handoff hashes, array frame,
functional association id, ordered mapping digest, and
`nominal_not_measured` status.

Staleness is identity based, never age based. A bundle is stale if the fixed
pointer no longer resolves the exact active v2 profile and handoff frozen by
the S4.6 contract, or if any bound identity, version, status, path, hash,
routing, or declaration differs. Wall-clock age is not a staleness criterion.

## Authorized application plan

Exactly seven scientific components are authorized:

1. `channels.ch1.gain_db = -1.6020864972841506 dB`;
2. `channels.ch2.gain_db = -1.2795753710282032 dB`;
3. `channels.ch3.gain_db = -1.2135862725210074 dB`;
4. `channels.ch1.polarity = +1`;
5. `channels.ch2.polarity = +1`;
6. `channels.ch3.polarity = +1`; and
7. the fitted functional channel-to-position association in `F_project`.

Gain values are direct additive dB corrections. Existing S3.3 channel-response
runtime semantics apply them as `10 ** (gain_db / 20)`. Polarity uses the
existing multiplier convention: `-1` inverts and `+1` preserves.

The functional association is:

| Raw channel | Functional position in `F_project` (m) |
| --- | --- |
| `ch0` | `[-0.033, -0.033, 0.0]` |
| `ch1` | `[-0.033, +0.033, 0.0]` |
| `ch2` | `[+0.033, +0.033, 0.0]` |
| `ch3` | `[+0.033, -0.033, 0.0]` |

It is a fitted functional raw-channel association selected on Fit A and
validated unchanged on Fit B. The coordinate values remain nominal acoustic
centers. This application does not turn them into measured geometry, physically
traced wiring, a scalar bearing correction, or a mirrored project frame.

The application owns runtime channel response through
`EffectsConfig.channel_response` and owns functional positions through the
target array's ordered `MicrophoneSpec.relative_position_m` values. It must not
also add the fitted gains to `MicrophoneSpec.gain_db`, which would double them.

## Field status and retained counts

The field-status report has one deterministic record per considered field with
one of: `applied`, `skipped`, `rejected`, `nominal`, `unmeasured`, or
`unsupported`, plus a reason.

The ch0 gain and polarity values are nominal reference conventions, not fitted
corrections. Profile microphone positions are nominal/unmeasured geometry;
only the separate functional association is applied.

The following remain skipped as unmeasured, unsupported, or omitted:

- relative delay and scalar bearing correction;
- confidence calibration and relative audio-video timing;
- functional noise/self-noise and frequency-dependent response;
- playback linearity and AGC/compression;
- sector/confusion and abstention thresholds;
- absolute SPL and absolute microphone sensitivity; and
- precision optical/acoustic extrinsics.

Counts are interpreted exactly as six scalar profile parameters plus one
non-scalar association. The legacy profile metric
`retained_parameter_count=7` is superseded as an application count and must
never authorize seven scalar applications.

## Disabled and repeated application

Mode `off` performs no bundle I/O, returns the unadjusted configuration
unchanged, and reports zero applied fields. The off result must be byte/value
equivalent to the existing no-profile path.

Enabled application requires an unadjusted channel-response stage. If the
stage is already enabled or contains microphone corrections, the operation
fails before constructing an adjusted configuration. This makes repeated
application and ambiguous merging explicit failures rather than allowing a
second correction.

## Evidence and phase boundary

The canonical package is generated under
`outputs/isaac_audio_sensors/S4/S4.6/` from the exact implementation commit.
It records the full plan, applied values, field statuses, compatible and
fail-closed fixture matrix, off-state equivalence, determinism, functional
association semantics, preservation and phase boundaries, provenance,
reproduction command, final validation, evidence index, and SHA-256 manifest.

A clean checkout of the bound implementation commit must reproduce the package
byte-for-byte in a temporary directory. S4.6 does not open holdout data,
preregister S4.7, grant or run S4.8, package S4.9, or start S5/S6. S4 remains
incomplete until S4.8 and S4.9 pass.
