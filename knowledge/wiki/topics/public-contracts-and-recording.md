# Public Contracts and Recording

## AudioSensorFrame

`AudioSensorFrame` is the package-native sensor and trace contract with schema version `ias.audio_sensor_frame.v1`, independent from the Python package version.

Every frame identifies its backend, array, time window, sample rate, frame index, coordinate convention, units, provenance, event bound, detections, aggregate microphone RMS values, waveform paths, and diagnostics.

Allowed provenance values are `synthetic/core`, `room_acoustics`, `isaac_live`, and `replay/trace`.

The coordinate convention is `x_forward_y_right_z_up_clockwise_bearing`: local `+X` is array forward, local `+Y` is right, local `+Z` is up, positions use meters, orientations use XYZW quaternions, and bearing is clockwise degrees from array forward.

Detections keep source identity and class, timing, known source pose and oracle geometry when available, DOA estimates, ambiguity, per-microphone delay/RMS, audio asset reference, occlusion state, and diagnostics distinct.

## Versioned Schemas

The shipped schemas are `ias.audio_sensor_frame.v1`, `ias.audio_dataset_manifest.v1`, and `ias.audio_calibration_profile.v1` under `src/isaac_audio_sensors/schemas/`.

Code generation and checked package resources must remain identical; schema export never reads documentation files.

Package upgrades may preserve an existing schema version when serialized meaning is compatible; an incompatible field shape or semantic change requires a new schema version.

## Configuration and Runtime Profiles

`AudioSensorConfig` validates scene, audio, source, array, room, Lab, backend, runtime-profile, and effects settings from TOML before simulation.

`waveform_fidelity` is the default runtime profile and permits waveform-producing behavior; `training_features` is a constrained feature-oriented profile and rejects incompatible waveform export.

Unknown backends, profiles, coordinate conventions, invalid time windows, invalid array geometry, and unsupported combinations fail closed.

## Plugins and Capabilities

Import-safe protocols define propagation backends, DOA estimators, and audio feature extractors.

Capability declarations record identifiers, profiles, device support, output contracts, determinism, dependencies, and provider provenance; registry resolution rejects duplicate declarations, unavailable dependencies, unsupported devices/profiles, and mismatched output claims.

The built-in capability set includes the maintained acoustic backends and DOA estimators, while optional packs can add capabilities without changing core imports.

## Trace IO

JSON frame files and JSONL streams use deterministic serialization and round-trip through the public frame model.

Readers accept documented absent optional v1 fields and restore their canonical defaults; writers emit the current complete compatible v1 shape.

Tracked examples under `examples/traces/` cover minimal, multi-detection, ambiguity, and diagnostic/provenance-rich records.

## Dataset Sessions

The recording subsystem writes a finalized session with a root manifest, canonical session configuration, deterministic shard directories, frame records, audio payloads when enabled, and completion markers that bind promoted shard content.

Atomic staging, retry, cancellation, filesystem seams, and promotion prevent a partial write from appearing as a completed shard.

The loader verifies layout and completion markers before exposing records; corrupt or incomplete shards are not silently treated as valid data.

Validation checks manifest/schema consistency, shard tiling and lifecycle, frame records, split-group isolation, waveform finiteness when requested, and preserved time-gap accounting.

Deterministic split planning keeps one split group together, statistics stream verified records, FLAC export is optional, and replay is ordered and read-only.

## Calibration Profiles

The calibration contract stores versioned, unit-explicit array and microphone corrections with provenance and validation rather than asserting unmeasured physical truth.

Applying relative geometry, gain, delay, polarity, response, confidence, or timing information requires values supported by the profile; absolute physical calibration and sim-to-real validity require external measurements and evidence.

## Audio Asset References

Generated identifiers support deterministic examples; file-backed sources are loaded and resampled when the selected waveform backend requires audio; external corpora remain outside the repository and are referenced through user-owned paths.

Exported waveforms and recordings are runtime outputs, not tracked product source or embedded schema content.

## Compatibility

Stable v1 fields, units, provenance, coordinate meaning, ambiguity representation, backend identifiers, sector mapping, and named diagnostic namespaces cannot be removed or redefined in a compatible release.

Additive optional fields, diagnostics, capabilities, and bug fixes are compatible when older readers can ignore them and current readers preserve older records.
