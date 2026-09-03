# Public Contracts and Recording

## MicrophoneSignalBlock

`MicrophoneSignalBlock` is the simulator-independent runtime output of a propagation or capture producer. It is public from both `isaac_audio_sensors.core` and `isaac_audio_sensors.core.types` without making either import NumPy eagerly.

Every block contains a copied, C-contiguous, read-only `float32` matrix shaped `[microphone, sample]`; ordered, non-empty, unique `microphone_ids`; `array_id`; positive `sample_rate_hz`; an `AudioTimeWindow`; a Boolean `channel_validity` value for each microphone; `producer_id`; provenance; and concise operational diagnostics. The sample axis must equal `max(1, round((end_time_s - start_time_s) * sample_rate_hz))`, and every sample must be finite. The analytic producer follows `MicrophoneArraySpec` order and marks all simulated channels valid.

The block is the final observed microphone mixture after propagation, directivity, occlusion, gain, and enabled effects. It has no source axis and contains no geometry, pose, source identity, detections, stems, waveform paths, or serialized-schema representation. Source signals and stems may exist only inside a producer's private render.

## AudioSensorFrame

`AudioSensorFrame` is the package-native sensor and trace contract with schema version `ias.audio_sensor_frame.v3`, independent from the Python package version.

Every frame identifies its producer, array, required time window, selected-array sample rate, ordered channel validity by microphone identifier, frame index, coordinate convention, units, provenance, output observation bound, observations, aggregate microphone RMS values, waveform paths, and diagnostics. Its serialized `timestamp_ms` is not an independent input: the model derives it exclusively as `int(round(start_time_s * 1000.0))`. `waveform_paths` contains references managed by recording services; perception itself writes no files and initializes the field empty.

Allowed provenance values remain `synthetic/core`, `room_acoustics`, `isaac_live`, and `replay/trace`. `room_acoustics` is historical serialized provenance, not a selectable runtime backend.

The coordinate convention is `x_forward_y_right_z_up_clockwise_bearing`: local `+X` is array forward, local `+Y` is right, local `+Z` is up, positions use meters, orientations use XYZW quaternions, and bearing is clockwise degrees from array forward.

`AudioObservation` contains exactly `observation_id`, `origin`, `detector_id`, optional finite `detection_score`, optional `doa`, and non-privileged diagnostics. `ObservationOrigin` has only `signal_derived` and `external_system`. Observations contain no source identity, class, source pose, oracle geometry, asset reference, occlusion truth, or per-source delay/RMS. A missing DOA means localization was not run; a present unresolved `DoaEstimate` records that localization ran without a unique valid direction.

`DoaEstimate.candidate_bearing_deg`, `ambiguity_class`, and `ambiguity_reason` preserve physically compatible direction evidence for downstream use. A two-microphone result may carry both azimuth candidates, no selected bearing or sector, and zero confidence. Core configuration and APIs expose no ambiguity policy or contextual prior.

`AudioTimeWindow` contains only required `start_time_s`, `end_time_s`, and `frame_index`. `MicrophoneArraySpec.sample_rate_hz`, defaulting to 48 kHz, is the sole runtime sample-rate authority. `AudioSensorFrame.sample_rate_hz` is the output projection of the selected array value; neither `AudioTimeWindow`, `AudioSensorConfig`, nor `[audio]` carries another sample-rate field.

`AudioPerceptionPipeline.process()` accepts a `MicrophoneSignalBlock`, its exact `MicrophoneArraySpec`, frame identity, and optional typed external observations. It validates array ID, sample rate, microphone order, and geometry; passes only valid channels to the injected activity detector in their original order; and skips perception when no channel is valid. Inactive output emits no observation. Active output emits one `signal_derived` observation and runs optional DOA only when at least two channels remain valid. Aggregate RMS always comes from the observed block, never scene/source truth.

`AudioPerceptionPipeline.reset()` forwards reset to each injected stateful detector or estimator object exactly once by identity. Processing copies the signal block diagnostics into the frame and adds the `perception` namespace; it performs no IO.

Signal-derived output precedes external observations in deterministic order. Observation IDs must be unique before `max_observations` is applied, and the cap never compares producer-specific scores. `None` is unlimited and zero preserves waveform and aggregate RMS while emitting no observations. Until Phase 03 introduces a concrete detector, maintained default consumers intentionally emit zero observations.

`SourceOcclusion` is the simulator-independent direct-path attenuation input. It requires array/source identity and exact blocked and broadband-attenuation maps for every microphone; optional spectral rows align with positive ordered band centers. Invalid identifiers, microphone coverage, non-finite or negative attenuation, inconsistent unblocked state, or row lengths fail closed. Per-record model, hit-path, and material fields have no aliases. Occlusion affects the rendered signal and aggregate RMS but is not copied into an observation as oracle truth.

## Versioned Schemas

The shipped schemas are `ias.audio_sensor_frame.v3`, `ias.audio_dataset_manifest.v1`, and `ias.audio_calibration_profile.v1` under `src/isaac_audio_sensors/schemas/`. Dataset records embed frame v3; the dataset and calibration wrapper meanings remain v1.

The three Python generators are authoritative. Checked package resources and exports from `write_json_schema` must remain byte-identical deterministic JSON; schema export never reads documentation files.

Generators are public under `isaac_audio_sensors.schemas.generate`; dataset manifests and their canonical `manifest_from_dict`, `manifest_to_dict`, `read_dataset_manifest`, and `write_dataset_manifest` services are public under `isaac_audio_sensors.recording`.

Package upgrades may preserve an existing schema version when serialized meaning is compatible; an incompatible field shape or semantic change requires a new schema version.

## Configuration and Runtime Profiles

`AudioSensorConfig` validates simulator-independent scene, audio, source, array, environment, backend, runtime-profile, analytic-solver, and effects settings from TOML before simulation. Each `arrays.*.sample_rate_hz` value is a positive integer, defaults to 48 kHz, and effects are validated for every configured array rate. `[audio].sample_rate_hz` is rejected. `[audio.analytic_acoustics]` owns `max_order`, `air_absorption`, and `ray_tracing`; the removed `[audio.room_acoustics]` table has no parser. It validates meters and Z-up without storing fixed-value convention fields. Isaac Lab configuration belongs to `isaac_audio_sensors.lab.AudioArraySensorCfg`.

Sources and microphones own their directivity. TOML accepts only `omni`, `cardioid`, `supercardioid`, and `figure_eight`; non-omni sources require world orientation and non-omni microphones require relative orientation. `[audio.effects.directivity]` is an unknown key in v3 rather than a deprecated alias.

`waveform_fidelity` is the default runtime profile and permits waveform-producing behavior; `training_features` is a constrained feature-oriented profile and rejects incompatible waveform export. Core TOML no longer selects `doa_estimator`; an optional existing `DoaEstimator` is injected into `AudioPerceptionPipeline` with its detector.

Unknown backends, profiles, coordinate conventions, removed `tdoa_ambiguity_policy` or `doa_estimator` configuration, invalid time windows, invalid array geometry, and unsupported combinations fail closed. Signal propagation supports mono arrays because it performs no localization. Perception skips DOA below two valid channels; individual estimators retain their own geometry requirements.

## Plugins and Capabilities

Import-safe protocols define propagation backends, DOA estimators, and audio feature extractors.

Every propagation backend implements `propagate(scene, array_id, time_window) -> MicrophoneSignalBlock`. The snapshot is the only array-state authority for simulated propagation; the identifier is a selector, and missing identifiers raise the clear `AudioSceneSnapshot.array_by_id()` error before rendering.

`core.simulation.simulate_frame()` is the public module-level composition boundary above the plugin protocol. It calls `propagate()` once, resolves the exact snapshot array, runs perception with deterministic frame identity, optionally passes the same block to a waveform sink, and returns the frame and block. It is not re-exported from the package root. `propagate()` itself performs no frame construction or persistence, and `AnalyticAcoustics` has no `simulate()` compatibility method.

Capability declarations record identifiers, profiles, device support, `PluginDeclaration.output_contract`, determinism, dependencies, and provider provenance. `get_backend()` is the sole public propagation-backend resolver, while `registered_backend_ids()` is the authoritative built-in inventory.

Registry resolution rejects duplicate declarations, unknown identifiers, unavailable dependencies, unsupported devices/profiles, factory results that do not satisfy `PropagationBackend`, and mismatched `backend_id` values. Dependency and capability checks occur before backend construction.

The built-in propagation registry contains only `analytic_acoustics`; legacy identifiers are unknown at resolution time and have no aliases. `discover_capabilities()` reports each maintained level and optional feature as `bundled`, `external`, or `absent`. Standard Python resolves room and FLAC dependencies from the `room` extra; the packaged Kit extension resolves them from its internal `_bundled` directory.

## Trace IO

JSON frame files and JSONL streams use deterministic serialization and round-trip through the public frame model.

Readers require the exact v3 frame shape; writers emit that same deterministic shape. A reader reconstructs the frame from `start_time_s` and rejects any serialized `timestamp_ms` that does not equal the derived value. Frame v1/v2 resources and compatibility parsing are absent from the current package. Recorded producer identifiers describe provenance but do not become runtime selectors.

Tracked v3 examples under `examples/traces/` cover a minimal zero-observation frame, one resolved observation, and external/unresolved observation records.

## Dataset Sessions

The recording subsystem writes a finalized session with a root manifest, canonical session configuration, deterministic shard directories, frame records, audio payloads when enabled, and completion markers that bind promoted shard content.

The public recording surface contains the manifest/provenance models, `AppendFrameResult`, `LoadedFrame`, `ReplayEvent`, split/statistics/validation reports, `SessionRecorder`, `SessionDataset`, replay, validation, FLAC export, manifest IO, and split-plan services. `DatasetLayoutError`, `DatasetSplitError`, and `SessionRecorderError` are the public failures; writer, checkpoint, carry, marker, planner, and filesystem details are internal.

`SessionRecorder.append_frame()` accepts one `AudioSensorFrame` and a `MicrophoneSignalBlock | None`, uses the frame timestamp for automatic time-gap diagnostics, and accepts `is_reset` only as a keyword. The recorder verifies array, producer, sample rate, window, frame index, microphone order, channel validity, and session configuration before consuming the immutable samples. It does not require equal frame/block provenance because an Isaac-owned `isaac_live` frame may derive from an analytic producer block. `None` remains valid for metadata-only sessions, and hop/overlap carry remains recorder-owned. `cancel()` finalizes an incomplete session; class methods own resume and finalization recovery.

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

Package `3.0.0` is a breaking directivity, gain-consistency, signal-producer, and observed-frame release. Import sensor contracts from `core`, dataset contracts from `recording`, and schema generators from `schemas.generate`.

Migrate source directivity to `AudioSourceSpec.directivity`, microphone directivity to `MicrophoneSpec.directivity`, and Isaac Lab custom microphone geometry to `EntityBindingCfg.microphones`. Construct `SourceOcclusion` from its required per-microphone maps and optional band rows; removed aggregate, model, hit-path, and material fields have no aliases. Rename Isaac fallback configuration to `unknown_material_loss_db` and remove any total-loss cap argument. Propagation plugins implement `propagate(scene, array_id, time_window)` and return `MicrophoneSignalBlock`; scene-to-frame consumers compose `core.simulation.simulate_frame()` with an explicit perception pipeline. Waveform sinks implement `write_signal_block(*, frame_id, block)`, and dataset recorders receive the block directly. Bind Lab reference mode with `array_ids` instead of `array_specs`. Replace legacy backend choices with `analytic_acoustics`, move solver options to `[audio.analytic_acoustics]`, and choose the estimator separately. Remove `[audio.effects.directivity]` rather than translating it. Former directivity `frequency_points` have no automatic migration; move a still-required microphone response manually to `audio.effects.channel_response.<mic>.frequency_response`.

The frame schema is v3 because Plan 02.2 intentionally replaced backend-owned detections with perception-owned observations and channel validity. Dataset-manifest and calibration-profile schemas remain v1 because their wrapper contracts did not change; dataset records embed the current v3 frame. The package does not retain aliases or parallel runtime paths for `AudioDetection`, detection fields, frame v1/v2, removed Python/configuration surfaces, four legacy propagation backends, the backend sensor-object argument, or Lab `array_specs` reference binding.

Stable serialized v3 frame fields, units, provenance, coordinate meaning, ambiguity representation, producer identifiers, sector mapping, and named diagnostic namespaces cannot be removed or redefined in a compatible release. This serialized compatibility does not require preserving an old identifier as a runtime selection surface.

The frame v3 top-level and observation shapes are exact; changing them requires another explicit schema decision. Additive entries inside documented diagnostic maps, capability reporting, and bug fixes remain compatible when their existing meanings are preserved.
