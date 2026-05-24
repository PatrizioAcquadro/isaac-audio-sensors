# Changelog

## 1.0.0rc1 - 2026-05-24

This is a release candidate for the v1 package line, not the final `1.0.0`
release.

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
