# S1.2 Stage 1 public contracts closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S1.2` - Stage 1 public contracts |
| Closeout date | 2026-07-17 |
| Entry revision | `8ef3d89` |
| Predecessor input | `docs/development/closeouts/S1/s1_1_architecture_lock.md` (approved ADR) |
| Governing gate | `docs/development/specs/s0_squadbot_readiness_acceptance.md`, S1.2 row |
| Design note | `docs/development/specs/s1_stage1_public_contracts.md` |
| Result | **Pass** |

## Scope

Implements the two independent Stage 1 contracts and the runtime-profile
vocabulary locked by the S1.1 ADR (Decision 3):

- `ias.audio_dataset_manifest.v1`: `src/isaac_audio_sensors/core/dataset_manifest.py`,
  `core/io/manifests.py`, `docs/schemas/audio_dataset_manifest.v1.schema.json`,
  fixtures under `examples/manifests/` (2 valid, 15 invalid).
- `ias.audio_calibration_profile.v1`: `core/calibration_profile.py` with
  fail-closed `check_profile_compatibility`, `core/io/calibration.py`,
  `docs/schemas/audio_calibration_profile.v1.schema.json`, fixtures under
  `examples/calibration/` (1 nominal-not-measured valid, 10 invalid).
- Runtime profiles: `RUNTIME_PROFILES = ("training_features",
  "waveform_fidelity")`, default `waveform_fidelity` preserving current
  behavior; unknown profiles and `training_features` +
  `write_waveforms=true` fail closed in `validate_audio_config`.
- CLI `export-schema` extended backward-compatibly to all three schemas;
  Makefile `export-schema` and new `regenerate-manifests` targets;
  distribution inventory and MANIFEST coverage.

`ias.audio_sensor_frame.v1` schema, trace fixtures, and frame types are
byte-untouched. Dataset layout semantics remain S2.1 scope.

## Execution record

Implemented by two bounded Codex CLI runs (`codex` 0.144.4, `gpt-5.6-sol`,
reasoning `high`, `--ignore-user-config`, `workspace-write`), orchestrated
and diff-reviewed by Claude. The first run implemented the contracts and
stopped correctly at its write boundary; a second authorized micro-run added
the new required entries to the synthetic archives in
`tests/test_distribution_audit.py` only.

## Gate results (evidence: `outputs/isaac_audio_sensors/S1/S1.2/`)

| Gate | Result | Evidence |
| --- | --- | --- |
| `make test` | 431 passed, 67 skipped | `gate_test.log` |
| `make lint` | clean | `gate_lint.log` |
| `make validate-config` (existing demo config unchanged behavior) | pass | `gate_validate_config.log` |
| Schema parity (`make export-schema` then clean `git diff docs/schemas/`) | clean | `gate_schema_parity.log` |
| Manifest/calibration fixture regeneration determinism (sha256 re-check) | deterministic | `gate_manifest_parity.log` |
| Frame trace fixture parity (`make regenerate-traces`) | clean | `gate_trace_parity.log` |
| `make build` + distribution audit | OK (sdist 256 files, wheel 90 files, 1.8.0) | `gate_build_audit.log` |
| Fixture/schema hash inventory | recorded | `fixture_inventory_sha256.txt` |

Acceptance mapping (S1.2 row): generated and checked schemas match (parity
gate); valid fixtures round-trip (contract tests); malformed ids, units,
frames, timestamps, channel order, checksums, and incompatible profiles fail
before partial use (25 invalid fixtures each asserted); unknown runtime
profiles fail (test_runtime_profiles.py); existing configurations retain
documented behavior (demo-config regression + default profile test).

## Limitations and next input contract

- Contracts are frozen surfaces only; no dataset writer/loader (S2) and no
  profile-fitting workflow (S4) exists yet.
- Next subphase input (S1.3): approved ADR, these contracts and runtime
  profiles, plan Section 4.6.

## Post-review remediation (2026-07-17)

`ManifestPose.orientation_xyzw` now uses the shared quaternion validator:
zero, near-zero, NaN, and infinite values reject, while finite non-unit
quaternions normalize to unit length before serialization. Direct
construction, JSON loading, normalized serialization, and valid-fixture
parity are covered. Schema, trace, manifest, and calibration regeneration
was repeated over 37 files with zero byte drift after the intended schema
description update. The final pure battery passed 518 tests with 67
documented optional-dependency skips.
