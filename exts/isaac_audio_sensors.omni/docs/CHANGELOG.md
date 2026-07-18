# Changelog

## 1.10.0 - Unreleased

- Version aligned with package release `1.10.0` (Stage 1 dynamic acoustics
  line). No packaged extension behavior change yet in this line.

## 1.9.0 - Unreleased

- Version aligned with package release `1.9.0` (Stage 1 recording, replay,
  diagnostics, and operational GUI line). No packaged extension behavior
  change yet in this line.

## 1.8.0 - Unreleased

- Version aligned with package release `1.8.0` (Stage 1 stable installable
  foundation). Packaged self-contained extension build lands in this line.
- Packaged archives import the canonical core package only from `_vendor`, with
  version and provenance validation; source checkouts retain explicit tracked
  developer mode and the existing `src/` fallback.
- Added deterministic Kit archive build and audit gates, including tree-drift,
  sentinel ambiguity, and conflicting-installed-package negative coverage.

## 1.7.0 - 2026-06-12

- The backend selector adds `room_acoustics_srp` (the L2 room pipeline with
  SRP-PHAT as the DOA estimator).
- The array layout selector adds the rank-3 `tetrahedral` preset, enabling
  elevation estimation in core frames.
- Inherited from core: additive optional elevation fields on DOA estimates,
  optional `velocity_world_mps` source/array velocities, and Doppler-shifted
  L2 waveforms when velocities are set.

## 1.6.0 - 2026-06-12

- Added the `Room` section for the `room_acoustics` backend: anchor the room to
  a stage prim's world bounding box or leave it centered on the array, and
  choose `error` or `clamp` for out-of-bounds sources/microphones.
- The active room readout reports dimensions, origin, absorption provenance,
  and anchor path.
- Debug overlays and USD debug geometry now draw room outlines.
- Breaking behavior inherited from core: room-acoustics scenes no longer
  auto-refit the shoebox around every frame's source/microphone positions.

## 1.5.0 - 2026-06-11

- GUI instruments release: the window gains an `Instruments` section (polar
  bearing compass, per-mic RMS meters, detection timeline) and an
  `Audio Output` section (waveform/spectrogram preview and audition of
  exported WAVs).
- Viewport-first interaction: `Follow Selection` routes clicked prims by
  discovery class; `Live Sync Pose` mirrors manipulator-driven array/source
  transforms into the numeric fields.
- Persistent USD debug geometry: the `USD Debug` toggle authors overlay
  primitives as session-layer Spheres/BasisCurves under a configurable root.
- OmniGraph: registers the runtime node
  `isaac_audio_sensors.omni.IsaacAudioSensorFrame` when `omni.graph.core`
  is present, exposing the latest frame to Action Graphs.
- The backing `extension_ui` module became a package with the same import
  path; the extension config schema stays `ias.omni_extension_binding.v1`
  with additive keys.

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
