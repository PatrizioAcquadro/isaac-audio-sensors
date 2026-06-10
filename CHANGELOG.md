# Changelog

## 1.1.0 - 2026-06-10

Physics coherence release for the v1 line. Every shared quantity now means
the same thing at L0, L1, and L2, and no observable output leaks ground
truth. The frame schema version is unchanged at `ias.audio_sensor_frame.v1`;
all value changes are documented physics bug fixes plus additive optional
APIs and diagnostics.

Documented physics corrections (bug fixes preserving the v1 frame shape):

- L0/L1 synthetic RMS now follows the pressure law `1/distance` instead of
  `1/distance^2`. The reference convention is documented: `gain_db` is the
  source level re 1 m, so RMS at 1 m equals `10 ** (gain_db / 20)`.
- `AudioSourceSpec.gain_db` is now applied at L0 and L1, matching the
  existing L2 behavior.
- `aggregate_per_mic_rms` is now an incoherent power sum `sqrt(sum(rms^2))`
  across sources in all three backends instead of a linear sum.
- Bearing confidence no longer uses the ground-truth bearing: it derives only
  from the least-squares residual, array geometry, and stress settings. The
  ground-truth comparison moved to the additive detection diagnostic
  `oracle_bearing_error_deg`, and confidence is invariant to ground-truth
  changes by test. `estimate_doa_from_delays` keeps its
  `ground_truth_bearing_deg` parameter for compatibility but ignores it.
- The L1 stress controls replace the alternating-sign bias with real Gaussian
  draws: delay noise and clock jitter are deterministic per
  `(seed, frame_id, mic_id)`, and gain mismatch is a static per-mic draw per
  `(seed, mic_id)`. Zero-noise outputs are bit-identical to before.

Additive APIs, diagnostics, and tooling:

- `TdoaSyntheticBackend(seed=...)` selects the deterministic noise stream;
  the default (`seed=None`) remains fully deterministic.
- `TdoaSyntheticBackend(air_absorption_db_per_m=...)` adds optional broadband
  air-absorption attenuation to L1 RMS (default 0.0 is a no-op).
- `MicrophoneSpec.self_noise_db` is now modeled at L0/L1 as a per-mic noise
  floor in `aggregate_per_mic_rms`; `AudioSourceSpec.directivity` is now
  modeled at L0/L1 with a first-order omni/cardioid factor. Unknown
  directivity values and cardioid sources without orientation behave as omni
  and are reported via the `directivity_applied` diagnostic. Both remain
  metadata-only at L2.
- New detection diagnostics: `source_gain_db`, `directivity`,
  `directivity_applied`, `oracle_bearing_error_deg`, `noise_seed`,
  `air_absorption_db_per_m`.
- The live Kit update-stream subscription now respects `update_period_s`
  instead of forcing a capture every tick.
- GCC-PHAT pairwise estimation caches per-channel rFFTs and mirrors the
  symmetric half of the pair matrix; outputs are unchanged.
- New `make regenerate-traces` target and
  `scripts/regenerate_example_traces.py` regenerate the backend-generated
  JSON example traces, which are refreshed for the corrected physics.
- `docs/api_freeze_0_1.md` gains an explicit "V1 Frame Schema Evolution
  Policy" section defining what compatible v1 releases may add to a frame.

## 1.0.0 - 2026-05-24

This is the final v1 package release promoted from `1.0.0rc1`.

- Freezes the `AudioSensorFrame` v1 API/data contract for the v1 line except
  for compatible additive changes and bug fixes.
- Keeps the frame schema version separate from the package version at
  `ias.audio_sensor_frame.v1`.
- Reviewed the `1.0.0rc1` feedback window and promoted early with explicit
  maintainer approval on 2026-05-24.
- Confirmed the changes after `v1.0.0rc1` were non-breaking docs and evidence
  updates before the final version bump; no frame fields, schema semantics,
  stable backend ids, units, timestamps, provenance values, bearing sectors,
  public APIs, or core dependency boundaries were broken.
- Promotes the same v1 scope validated by the RC: stable L0 `geometry_only`,
  stable L1 `tdoa_synthetic`, supported optional L2 `room_acoustics`, Isaac
  Sim, Isaac Lab, Omniverse reference UX, stable JSON/JSONL export, and
  optional extension-only Replicator support.
- Documents that SquadBot, Alex, ROS 2, and downstream project adapters are not
  final v1 package release gates.
- Leaves phases 9, 10, and 11 as post-v1 planned work, not prerequisites for
  this release.

## 1.0.0rc1 - 2026-05-24

This is a release candidate for the v1 package line, not the final `1.0.0`
release.

- `AudioSensorFrame` v1 API is frozen except for bug fixes and additive
  compatible diagnostics or fields.
- The RC feedback window is open from 2026-05-24 through 2026-06-07 before
  final `1.0.0` consideration.
- This RC is not final `1.0.0`; final release still depends on RC feedback and
  review of real downstream usage.
- SquadBot is not included in the `v1.0.0rc1` release gate.
- Phases 9, 10, and 11 are planned after the RC and are not prerequisites for
  this tag.
- Strengthened `AudioSensorFrame` as the public v1 frame contract with
  `schema_version`, `frame_name`, `Pose3D` array/source poses, explicit units,
  provenance, time-window fields, and deterministic `max_events` semantics.
- Added JSON Schema export, tracked schema and trace examples, trace
  round-trip helpers, and JSONL frame writer support.
- Added checked-in schema parity tests, deterministic JSON and NDJSON trace
  corpus coverage, coordinate/unit/provenance/timestamp contract tests, and
  stable diagnostics namespace documentation for `AudioSensorFrame` v1.
- Added a public acoustic fidelity ladder with stable L0/L1 backends,
  supported optional L2 room acoustics, and future-compatible L3/L4 metadata
  boundaries.
- Hardened L2 `room_acoustics` as a supported optional v1 backend with
  pyroomacoustics RIR/waveform generation, waveform-derived GCC-PHAT TDOA,
  deterministic multi-source scheduling, and stable room/RIR/waveform
  diagnostics.
- Added lifecycle-capable `IsaacAudioArraySensor` updates for repeated stage
  snapshots, moving source/array metadata, active sound windows, latest-frame
  access, structured debug primitives, and package writer integration.
- Expanded the Omniverse extension wrapper with configure/start/stop/update
  and latest-frame export entry points.
- Added reference Omniverse extension UX coverage for selected-prim binding,
  array/source metadata authoring, live overlay state, config import/export,
  and optional Replicator writer recording.
- Fixed floating-point sector-boundary classification so L0/L1 bearing sectors
  stay consistent at exact 45-degree boundary cases.
- Renamed the bundled config and Isaac Sim example away from legacy project
  phase naming.
- Documented the public API freeze with stable, provisional, experimental, and
  internal/private surfaces after the Isaac-native Sim/Lab upgrades.
- Added public release-candidate docs for versioning, archive auditing,
  completed roadmap items, live Isaac validation expectations, and API-change
  deprecation policy.
- Added a distribution audit script and `make audit-dist`; `make build` now
  checks the built source distribution and wheel for required public files,
  forbidden generated/private paths, and public-package leak tokens.
- Added a canonical v1 public scope page plus guardrails for v1 promises,
  non-promises, downstream non-gates, and optional extension-only Replicator
  wording.
- Set the package version to `1.0.0rc1` while keeping the frame contract
  version separate at `ias.audio_sensor_frame.v1`.
- Closed the release-candidate scope around the stable frame contract, stable
  L0 `geometry_only`, stable L1 `tdoa_synthetic`, supported optional L2
  `room_acoustics`, Isaac Sim, Isaac Lab, Omniverse reference UX, stable
  JSON/JSONL export, and optional extension-only Replicator support.

## 0.1.0 - 2026-05-21

- Added the standalone `isaac-audio-sensors` package with pure core models,
  geometry-only simulation, synthetic TDOA simulation, optional room-acoustics
  simulation, CLI trace export, lazy Isaac Sim helpers, lazy Isaac Lab wrappers,
  generic examples, public documentation, and validation tests.
- Documented the initial 0.1.x public API freeze and semantic versioning policy.
- Excluded project-specific adapters, generated media, private recordings, and
  local environment artifacts from the public package boundary.
