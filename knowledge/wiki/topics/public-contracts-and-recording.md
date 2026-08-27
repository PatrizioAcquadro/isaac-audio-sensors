# Public Contracts and Recording

## AudioSensorFrame

`AudioSensorFrame` is the package-native sensor and trace contract with schema version `ias.audio_sensor_frame.v1`, independent from the Python package version.

Every frame identifies its backend, array, time window, sample rate, frame index, coordinate convention, units, provenance, event bound, detections, aggregate microphone RMS values, waveform paths, and diagnostics.

Allowed provenance values are `synthetic/core`, `room_acoustics`, `isaac_live`, and `replay/trace`.

The coordinate convention is `x_forward_y_right_z_up_clockwise_bearing`: local `+X` is array forward, local `+Y` is right, local `+Z` is up, positions use meters, orientations use XYZW quaternions, and bearing is clockwise degrees from array forward.

Detections keep source identity and class, timing, known source pose and oracle geometry when available, DOA estimates, ambiguity, per-microphone delay/RMS, audio asset reference, occlusion state, and diagnostics distinct.

## Versioned Schemas

The shipped schemas are `ias.audio_sensor_frame.v1`, `ias.audio_dataset_manifest.v1`, and `ias.audio_calibration_profile.v1` under `src/isaac_audio_sensors/schemas/`.

The three Python generators are authoritative. Checked package resources and exports from `write_json_schema` must remain byte-identical deterministic JSON; schema export never reads documentation files.

Generators are public under `isaac_audio_sensors.schemas.generate`; dataset manifests and their canonical `manifest_from_dict`, `manifest_to_dict`, `read_dataset_manifest`, and `write_dataset_manifest` services are public under `isaac_audio_sensors.recording`.

Package upgrades may preserve an existing schema version when serialized meaning is compatible; an incompatible field shape or semantic change requires a new schema version.

## Configuration and Runtime Profiles

`AudioSensorConfig` validates simulator-independent scene, audio, source, array, room, backend, runtime-profile, and effects settings from TOML before simulation. It validates meters and Z-up without storing fixed-value convention fields. Isaac Lab configuration belongs to `isaac_audio_sensors.lab.AudioArraySensorCfg`.

Sources and microphones own their directivity. TOML accepts only `omni`, `cardioid`, `supercardioid`, and `figure_eight`; non-omni sources require world orientation and non-omni microphones require relative orientation. `[audio.effects.directivity]` is an unknown key in v3 rather than a deprecated alias.

`waveform_fidelity` is the default runtime profile and permits waveform-producing behavior; `training_features` is a constrained feature-oriented profile and rejects incompatible waveform export.

Unknown backends, profiles, coordinate conventions, invalid time windows, invalid array geometry, and unsupported combinations fail closed.

## Plugins and Capabilities

Import-safe protocols define propagation backends, DOA estimators, and audio feature extractors.

Capability declarations record identifiers, profiles, device support, `PluginDeclaration.output_contract`, determinism, dependencies, and provider provenance. `get_backend()` is the sole public propagation-backend resolver, while `registered_backend_ids()` is the authoritative built-in inventory.

Registry resolution rejects duplicate declarations, unknown identifiers, unavailable dependencies, unsupported devices/profiles, factory results that do not satisfy `PropagationBackend`, and mismatched `backend_id` values. Dependency and capability checks occur before backend construction.

`discover_capabilities()` reports each maintained level and optional feature as `bundled`, `external`, or `absent`. Standard Python resolves room and FLAC dependencies from the `room` extra; the packaged Kit extension resolves them from its internal `_bundled` directory.

## Trace IO

JSON frame files and JSONL streams use deterministic serialization and round-trip through the public frame model.

Readers accept documented absent optional v1 fields and restore their canonical defaults; writers emit the current complete compatible v1 shape. In particular, legacy frames may omit the additive `units.elevation` entry.

Tracked examples under `examples/traces/` cover minimal, multi-detection, ambiguity, and diagnostic/provenance-rich records.

## Dataset Sessions

The recording subsystem writes a finalized session with a root manifest, canonical session configuration, deterministic shard directories, frame records, audio payloads when enabled, and completion markers that bind promoted shard content.

The public recording surface contains the manifest/provenance models, `AppendFrameResult`, `LoadedFrame`, `ReplayEvent`, split/statistics/validation reports, `SessionRecorder`, `SessionDataset`, replay, validation, FLAC export, manifest IO, and split-plan services. `DatasetLayoutError`, `DatasetSplitError`, and `SessionRecorderError` are the public failures; writer, checkpoint, carry, marker, planner, and filesystem details are internal.

`SessionRecorder.append_frame()` accepts one `AudioSensorFrame` and its audio block, uses the frame timestamp for automatic time-gap diagnostics, and accepts `is_reset` only as a keyword. `cancel()` finalizes an incomplete session; class methods own resume and finalization recovery.

Durable staging and atomic promotion prevent a partial write from appearing as a completed shard. Manifest and split-plan writes are atomic, and manifest input must already match the canonical v1 representation rather than relying on type coercion.

`SessionDataset` verifies lifecycle, manifest/configuration agreement, completion markers, record order, audio joins, and optional checksums before exposing records. Corrupt or incomplete shards are not silently treated as valid data, and layout failures carry stable code, location, and detail fields.

Validation checks manifest/schema consistency, shard tiling and lifecycle, frame records, split-group isolation, waveform finiteness when requested, and preserved time-gap accounting.

Deterministic split planning keeps one split group together, statistics stream verified records, FLAC export is optional, and replay is ordered and read-only.

## Calibration Profiles

The calibration contract stores versioned, unit-explicit array and microphone corrections with provenance and validation rather than asserting unmeasured physical truth. Calibration gain remains data-only and is not injected automatically into runtime amplitude.

Applying relative geometry, gain, delay, polarity, response, confidence, or timing information requires values supported by the profile; absolute physical calibration and sim-to-real validity require external measurements and evidence.

## Audio Asset References

Generated identifiers support deterministic examples; file-backed sources are loaded and resampled when the selected waveform backend requires audio; external corpora remain outside the repository and are referenced through user-owned paths. The generated or file sample amplitude is part of the asset. Nominal source `gain_db = 0` is unity, and WAV loading performs no automatic peak or RMS normalization.

Exported waveforms and recordings are runtime outputs, not tracked product source or embedded schema content.

## Compatibility

Package `3.0.0` is a breaking directivity and gain consistency release. Import sensor contracts from `core`, dataset contracts from `recording`, and schema generators from `schemas.generate`.

Migrate source directivity to `AudioSourceSpec.directivity`, microphone directivity to `MicrophoneSpec.directivity`, and Isaac Lab custom microphone geometry to `EntityBindingCfg.microphones`. Remove `[audio.effects.directivity]` rather than translating it. Former directivity `frequency_points` have no automatic migration; move a still-required microphone response manually to `audio.effects.channel_response.<mic>.frequency_response`.

The frame, dataset-manifest, and calibration-profile schemas remain v1 because their serialized meanings did not change. The v3 package does not retain v2 aliases or parallel runtime paths for the removed Python/configuration surfaces.

Stable serialized v1 fields, units, provenance, coordinate meaning, ambiguity representation, backend identifiers, sector mapping, and named diagnostic namespaces cannot be removed or redefined in a compatible release.

Additive optional fields, diagnostics, capabilities, and bug fixes are compatible when older readers can ignore them and current readers preserve older records.
