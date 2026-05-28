# Changelog

## 1.0.0 - 2026-05-24

- Final v1 package release promoted from `1.0.0rc1`.
- Freezes the `AudioSensorFrame` v1 API/data contract for the v1 line except
  for compatible additive changes and bug fixes.
- Keeps the frame schema version separate from the package version at
  `ias.audio_sensor_frame.v1`.
- Includes the Omniverse extension as the reference UX for selected-prim
  binding, array/source metadata authoring, semantic discovery, live sensor
  start/update/stop, overlay inspection, stable JSON/JSONL export, config
  import/export, and optional extension-only Replicator recording.
- Keeps Replicator optional and extension-only; core import, `AudioSensorFrame`,
  package JSON/JSONL export, Isaac Sim sensor control, and Isaac Lab sensor
  APIs do not require Replicator.

## 1.0.0rc1 - 2026-05-24

- Added reference Omniverse extension UX coverage for selected-prim binding,
  array/source metadata authoring, semantic discovery, live overlay state,
  config import/export, JSON/JSONL export, and optional Replicator writer
  recording.
- Expanded the Omniverse extension wrapper with configure/start/stop/update and
  latest-frame export entry points.
