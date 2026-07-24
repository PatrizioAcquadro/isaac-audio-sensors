# S4.6 profile and configuration application closeout

## Final status

**PASS.** S4.6 resolves the authoritative S4.5 active pointer, handoff, and v2
profile as one fail-closed bundle; validates the complete runtime identity and
application context; computes the complete seven-component plan; and only then
returns an adjusted immutable runtime configuration. No S4.5 parameter was
refit or reinterpreted.

The implementation is integrated through the normal TOML configuration loader
and the existing waveform-effects and microphone-array configuration owners.
The standalone `scripts/apply_s4_6_profile.py` entry point exposes the same
application path and its deterministic report.

## Applied fields and runtime ownership

The exact authorized components are:

| Field | Applied value | Runtime owner |
| --- | ---: | --- |
| `channels.ch1.gain_db` | `-1.6020864972841506 dB` | `EffectsConfig.channel_response` |
| `channels.ch2.gain_db` | `-1.2795753710282032 dB` | `EffectsConfig.channel_response` |
| `channels.ch3.gain_db` | `-1.2135862725210074 dB` | `EffectsConfig.channel_response` |
| `channels.ch1.polarity` | `+1` | `EffectsConfig.channel_response` |
| `channels.ch2.polarity` | `+1` | `EffectsConfig.channel_response` |
| `channels.ch3.polarity` | `+1` | `EffectsConfig.channel_response` |
| fitted functional channel-position association | `ch0=(-0.033,-0.033,0)`, `ch1=(-0.033,+0.033,0)`, `ch2=(+0.033,+0.033,0)`, `ch3=(+0.033,-0.033,0)` in `F_project` | `MicrophoneSpec.relative_position_m` |

Gain uses the existing additive-dB convention, with waveform scale
`10 ** (gain_db / 20)`. Polarity `+1` preserves the waveform. The
`MicrophoneSpec.gain_db` values remain unchanged, preventing double
application.

The position mapping is a fitted functional association. Its coordinate
values remain nominal and unmeasured. It is not measured microphone geometry,
physically traced wiring, a scalar bearing correction, or a mirrored
`F_project`.

## Skipped and rejected fields

Reference-channel `ch0` gain, delay, and polarity and the nominal microphone
positions are reported as nominal rather than applied corrections. Relative
delay for `ch1`-`ch3`, geometry uncertainty, and temperature are reported as
unmeasured.

The following remain unsupported and are never applied: relative delay,
scalar bearing correction, confidence calibration, relative audio-video
timing, functional noise/self-noise, frequency-dependent channel response,
playback-level linearity, AGC/compression, sector thresholds or confusion
matrices, abstention thresholds, absolute SPL, absolute microphone
sensitivity, and precision optical/acoustic extrinsics. Unknown, partial,
omitted, or status-incompatible values fail before plan application.

## Atomic, disabled, and repeated application behavior

Enabled application validates the fixed configuration hash and schema,
pointer, handoff, profile, identities, statuses, paths, hashes, retained-count
semantics, supported fields, and the complete independently declared runtime
context before computing the plan. Configuration replacement happens only
after all checks pass.

Disabled mode returns the same input configuration object, resolves no bundle,
applies zero fields, and reports one skipped profile-application field. The
canonical equivalence report records `configuration_equal=true`,
`same_object_returned=true`, and `off_state_drift=false`.

A second application is rejected before mutation when channel response is
already active. Active S4.6 response correction is restricted to the scalar
`waveform_fidelity` runtime; Isaac Lab batched mode rejects it explicitly.

## Fail-closed coverage

The canonical matrix contains 34 executed cases. It accepts only the valid
authoritative bundle and rejects swapped order, wrong count, wrong device,
wrong array, wrong rate, wrong frames, wrong coordinate convention, wrong
fixture or geometry identity, wrong environment, historical v1 selection,
inactive or stale identity, altered content, rechecksummed tampering,
malformed content, unsafe paths, missing members, hash mismatch, partial or
unsupported fields, unknown fitted parameters, retained-count misuse, runtime
identity bypass, unsupported batched use, and double application.

Separate executed probes prove that partial application, off-state drift, and
nondeterministic output are absent.

## Evidence and deterministic replay

The canonical package is
`outputs/isaac_audio_sensors/S4/S4.6/`. Its 13 files include the complete
application plan, applied values, field statuses, functional association,
compatibility/fail-closed matrix, off-state equivalence, determinism,
preservation and phase-boundary report, provenance, reproduction command,
final validation, evidence index, and `SHA256SUMS`.

The package is bound to implementation source commit
`559d1a028408d1e3d3460880e28583316d151897`. The recorded replay command is:

```text
python3 scripts/replay_s4_6.py --canonical outputs/isaac_audio_sensors/S4/S4.6
```

Replay checked out the bound source into a clean temporary archive, regenerated
all 13 records, and proved byte-for-byte equality. Validation reported zero
issues, zero holdout observations, and no later-phase artifacts.

## Preservation and phase boundary

The authoritative S4.5 active-handoff validator was executed from a detached
clean checkout of entry revision
`c92ebddcf0eef9254954b96388943fb167150b9d` with
`--require-tracked --require-committed`. It passed with semantic regeneration,
zero issues, and zero holdout observations.

Preservation remained exact:

- S4.4 tracked-tree SHA-256:
  `b079f2441f8c1a9c66d7d6fa9180b01a34ceb7a1be750c47db165afd2dc06caa`;
- S4.5 tracked-tree SHA-256:
  `165c49b2f483a4ba9d258f86f368323ffbbee8389553b57b5cbe993f3b70b234`;
- public profile-schema SHA-256:
  `fb56c9024bfa16ce25a999ed8e2552ab19189459f44801f33edd9f0d75d1ff46`.

Historical S4.5 pass and replay assertions use a test-only pre-S4.6 snapshot,
matching the repository's existing cross-phase preservation pattern. Frozen
S4.4/S4.5 evidence, contracts, active pointer, handoff, and profiles were not
changed.

No held-out scientific result was opened. No S4.8 access grant was created.
No S4.7-S4.9, S5, or S6 artifact was created. `dataset/` remains untracked, no
new raw media was tracked, and nothing was pushed.

## Validation results

```text
.venv/bin/python -m pytest -q tests/test_s4_6_contract.py tests/test_s4_6_profile_application.py tests/test_s4_6_evidence.py
PASS: 56 passed

make test
PASS: 1529 passed, 80 skipped

make lint
PASS: All checks passed

make check-version
PASS: version-sync 1.10.0

make check-release-source
PASS: release-source 559d1a028408d1e3d3460880e28583316d151897

make build
PASS: sdist and wheel built; distribution audit passed

.venv/bin/python scripts/validate_s4_6.py
PASS: 13 files, zero issues

.venv/bin/python scripts/replay_s4_6.py --canonical outputs/isaac_audio_sensors/S4/S4.6
PASS: 13 files byte-identical

git diff --check
PASS
```

The 80 skips are existing optional dependency, Isaac/Lab, hardware, and
retained-fixture skips. No S4.6 test was skipped.

## Local source commits

The verified local source history is:

- `26b4eaf8969a92c4091c428ba03dd627d321f933` — freeze the S4.6 contract;
- `a10e05faf9785f60084ab2a30e5271f7ce747512` — implement atomic application;
- `bd4d28512d7906036c46dae07fce3d1ad2383e41` — require independent runtime identity and executed evidence probes;
- `a78d5bffc7d081947c2c8a37ee1f6e33f53672cf` — preserve historical S4.5 test gates;
- `2bc8ed6e62dfac690d90a2c88972211b7291d25d` — isolate entry-revision validation;
- `559d1a028408d1e3d3460880e28583316d151897` — snapshot the historical S4.5 replay assertion.

The canonical evidence and this closeout are committed together after
finalization; their commit hash is intentionally reported outside this
self-referential document.

S4.6 is complete. S4 as a whole is not complete because S4.7-S4.9 remain
future, separately gated work.
