# Public Contracts and Recording

## MicrophoneSignalBlock

`MicrophoneSignalBlock` is the simulator-independent runtime output of a propagation or capture producer. It is public from both `isaac_audio_sensors.core` and `isaac_audio_sensors.core.types` without making either import NumPy eagerly.

Every block contains a copied, C-contiguous, read-only `float32` matrix shaped `[microphone, sample]`; ordered, non-empty, unique `microphone_ids`; matching finite array-local `microphone_positions_m` in canonical meters; `array_id`; positive `sample_rate_hz`; an `AudioTimeWindow`; a named `clock_domain`; explicit Boolean `discontinuity`; Boolean `channel_validity` and Boolean-or-null `channel_clipping` per microphone; `producer_id`; provenance; and concise operational diagnostics. The sample axis must equal `max(1, round((end_time_s - start_time_s) * sample_rate_hz))`, and every sample must be finite. The analytic producer follows `MicrophoneArraySpec` order and marks all simulated channels valid.

The block is the final observed microphone mixture after propagation, directivity, occlusion, gain, and enabled effects. It has no source axis and contains no world/source geometry, pose, source identity, detections, stems, waveform paths, or serialized-schema representation. Source signals and stems may exist only inside a producer's private render.

Sample amplitude uses a digital reference of 1.0. Values beyond +/-1 remain unchanged; unit-reference dBFS is not measured dB SPL. `channel_clipping` reports known saturation anywhere in production of the returned samples: true means known clipping, false means known absence, and null means unknown. Final amplitude alone cannot establish earlier clipping. Analytic electronics checks saturation and quantizer limiting only within the returned window, excluding the private render tail; disabled electronics reports false.

`clock_domain` identifies the sample timeline, including its origin, independently of delivery time. The sample rate is nominal; producers report measured drift, buffer latency, nominal gains, calibration evidence, and applied corrections in producer-owned `diagnostics.acquisition`. Null acquisition means unknown, not zero drift, unity gain, or calibrated hardware. Analytic acquisition metadata labels drift as configured, exposes nominal microphone gains and applied channel corrections separately, and declares no measured calibration or delivery latency. This metadata never drives perception or applies corrections automatically. A producer must signal discontinuity for a restart or fault hidden by otherwise contiguous timestamps.

## AudioSensorFrame

`AudioSensorFrame` is the package-native sensor and trace contract with schema version `ias.audio_sensor_frame.v3`, independent from the Python package version.

Every frame identifies its producer, array, required time window, selected-array sample rate, ordered channel validity by microphone identifier, frame index, coordinate convention, units, provenance, output observation bound, observations, aggregate microphone RMS values, waveform paths, and diagnostics. Its serialized `timestamp_ms` is not an independent input: the model derives it exclusively as `int(round(start_time_s * 1000.0))`. `waveform_paths` contains references managed by recording services; perception itself writes no files and initializes the field empty.

Allowed provenance values remain `synthetic/core`, `room_acoustics`, `isaac_live`, and `replay/trace`. `room_acoustics` is historical serialized provenance, not a selectable runtime backend.

The coordinate convention is `x_forward_y_right_z_up_clockwise_bearing`: local `+X` is array forward, local `+Y` is right, local `+Z` is up, positions use meters, orientations use XYZW quaternions, and bearing is clockwise degrees from array forward.

`AudioObservation` contains exactly `observation_id`, `origin`, `detector_id`, optional finite `detection_score`, optional `doa`, and non-privileged diagnostics. `ObservationOrigin` has only `signal_derived` and `external_system`. Observations contain no source identity, class, source pose, oracle geometry, asset reference, occlusion truth, or per-source delay/RMS. A missing DOA means localization was not run; a present unresolved `DoaEstimate` records that localization ran without a unique valid direction.

`ActivityDecision` is the non-serialized result of one detector update. It requires an exact Boolean `active`, accepts optional `activity_probability` only in `[0, 1]`, and copies its diagnostics. For pipeline-produced signal-derived observations, that probability is the sole `detection_score` meaning; detectors without a justified probability return `None` and report energy, threshold, or margin values only as diagnostics. The Boolean has no “not ready” interpretation, so a detector must not report `active=False` merely because calibration is incomplete.

`DoaEstimate.candidate_bearing_deg`, `ambiguity_class`, and `ambiguity_reason` preserve physically compatible direction evidence for downstream use. A two-microphone result may carry both azimuth candidates, no selected bearing or sector, and zero confidence. This includes energetic identical channels: zero TDOA yields the two physical bearings at 0 and 180 degrees, while true silence remains unresolved `low_information`. `bearing_confidence` is an estimator-local reliability ordering in `[0, 1]`, not a probability or a value comparable across estimators without calibration. Core configuration and APIs expose no ambiguity policy or contextual prior.

`AudioTimeWindow` contains only required `start_time_s`, `end_time_s`, and `frame_index`. `MicrophoneArraySpec.sample_rate_hz`, defaulting to 48 kHz, is the sole runtime sample-rate authority. `AudioSensorFrame.sample_rate_hz` is the output projection of the selected array value; neither `AudioTimeWindow`, `AudioSensorConfig`, nor `[audio]` carries another sample-rate field.

`AudioPerceptionPipeline.process()` accepts a `MicrophoneSignalBlock`, its exact `MicrophoneArraySpec`, frame identity, and optional typed external observations. It validates array ID, sample rate, microphone order, and geometry; passes only valid channels to the injected `ActivityDetector.detect()` in their original order; and skips perception when no channel is valid. The detector object supplies its own stable identifier and returns `ActivityDecision`; there is no parallel `detector_id` pipeline argument. Inactive output emits no observation. Active output emits one `signal_derived` observation and runs optional DOA only when at least two channels remain valid. Aggregate RMS always comes from the observed block, never scene/source truth.

The optional `DoaEstimator` has exactly `estimate(samples, microphone_positions_m, sample_rate_hz) -> (DoaEstimate, diagnostics)`. Its samples are the read-only valid rows of the final combined block, and its matching XYZ geometry is array-local. The call has no scene, source count, source identity or position, schedule, private stem, or producer diagnostic. The registry contains only `tdoa_least_squares` and lazy optional `pyroomacoustics_srp`; internal `srp_phat` is removed. The explicit maintained selector assigns least-squares only to exactly two microphones and PyRoom only to at least three horizontal non-collinear XY microphones, with no fallback. Rank-3 selection remains available only through caller injection.

Standard DOA consumers retain exactly the latest 250 ms of causal valid mixture, including inactive Auditok ticks, and estimate only on active ticks. Before the context is complete they emit unresolved `insufficient_context`. A resolved circular jump of at least 150 degrees abstains as `temporal_instability`; the new lobe requires a next-active-tick confirmation within 30 degrees. Inactivity clears stable and pending bearings but retains audio context. Explicit reset, layout/rate changes, stream identity changes, and non-contiguous windows clear all DOA state. Diagnostics expose one canonical causal context plus role, estimator, raw reliability, jump, pending/confirmed state, and abstention reason.

`AudioPerceptionPipeline.reset()` forwards reset to each injected stateful detector or estimator object exactly once by identity. Lifecycle owners still reset at episode and replay boundaries. The maintained rolling DOA consumer also clears its local state when it observes a changed layout, sample rate, stream identity, or non-contiguous time window. Processing copies the signal block diagnostics into the frame and adds the `perception` namespace; it performs no IO.

Signal-derived output precedes external observations in deterministic order. Observation IDs must be unique before `max_observations` is applied, and the cap never compares producer-specific scores. `None` is unlimited and zero preserves waveform and aggregate RMS, still advances stateful detection, and emits no observations. Subphase 03.3 injects the registered Auditok detector into maintained scalar consumers only when they own an explicit threshold. Direct callers of `simulate_frame()` and `AudioPerceptionPipeline`, including downstream detectorless compositions, remain fully explicit.

`SourceOcclusion` is the simulator-independent direct-path attenuation input. It requires array/source identity and exact blocked and broadband-attenuation maps for every microphone; optional spectral rows align with positive ordered band centers. Invalid identifiers, microphone coverage, non-finite or negative attenuation, inconsistent unblocked state, or row lengths fail closed. Per-record model, hit-path, and material fields have no aliases. Occlusion affects the rendered signal and aggregate RMS but is not copied into an observation as oracle truth.

## Versioned Schemas

The shipped schemas are `ias.audio_sensor_frame.v3`, `ias.audio_dataset_manifest.v4`, and `ias.audio_calibration_profile.v1` under `src/isaac_audio_sensors/schemas/`. Dataset frame records are v2 and embed unchanged frame v3; calibration remains v1. Manifest v2 removes episode-owned source truth, which now belongs exclusively beside each frame.

The three Python generators are authoritative. Checked package resources and exports from `write_json_schema` must remain byte-identical deterministic JSON; schema export never reads documentation files.

Generators are public under `isaac_audio_sensors.schemas.generate`; dataset manifests and their canonical `manifest_from_dict`, `manifest_to_dict`, `read_dataset_manifest`, and `write_dataset_manifest` services are public under `isaac_audio_sensors.recording`.

Package upgrades may preserve an existing schema version when serialized meaning is compatible; an incompatible field shape or semantic change requires a new schema version. Subphase 04.2 preserves frame v3 field shape and range while clarifying in the generated schema that bearing confidence is estimator-local reliability.

## Configuration and Runtime Profiles

`AudioSensorConfig` validates simulator-independent scene, audio, source, array, environment, backend, runtime-profile, analytic-solver, and effects settings from TOML before simulation. Each `arrays.*.sample_rate_hz` value is a positive integer, defaults to 48 kHz, and effects are validated for every configured array rate. `[audio].sample_rate_hz` is rejected. `[audio.analytic_acoustics]` owns `max_order`, `air_absorption`, and `ray_tracing`; the removed `[audio.room_acoustics]` table has no parser. It validates meters and Z-up without storing fixed-value convention fields. Isaac Lab configuration belongs to `isaac_audio_sensors.lab.AudioArraySensorCfg`.

Sources and microphones own their directivity. TOML accepts only `omni`, `cardioid`, `supercardioid`, and `figure_eight`; non-omni sources require world orientation and non-omni microphones require relative orientation. `[audio.effects.directivity]` is an unknown key in v3 rather than a deprecated alias.

`waveform_fidelity` is the default runtime profile and permits waveform-producing behavior; `training_features` is a constrained feature-oriented profile and rejects incompatible waveform export. Core TOML no longer selects `doa_estimator`; an optional existing `DoaEstimator` is injected into `AudioPerceptionPipeline` with its detector.

Unknown backends, profiles, coordinate conventions, removed `tdoa_ambiguity_policy` or `doa_estimator` configuration, invalid time windows, invalid array geometry, and unsupported combinations fail closed. Signal propagation supports mono arrays because it performs no localization. Perception skips DOA below two valid channels; individual estimators retain their own geometry requirements.

## Plugins and Capabilities

Import-safe protocols define propagation backends, activity detectors, DOA estimators, and audio feature extractors. `ActivityDetector` requires `detector_id`, `detect(samples, sample_rate_hz) -> ActivityDecision`, and `reset()`; detector state owns temporal smoothing and event boundaries.

`AuditokActivityDetector` is public from `core.plugins` and requires `energy_threshold_dbfs`; its initial temporal defaults are 50 ms analysis, 100 ms minimum activity, and 100 ms maximum silence. It feeds Auditok 0.5.2 native-endian IEEE-754 float32 frames in sample-major/channel-interleaved order, not integer PCM. Auditok scales those samples by 32768, so IAS converts thresholds and energies by `20 log10(32768)` while keeping all public diagnostics in dBFS. The `any`-channel policy takes the maximum per-channel energy and avoids cross-channel cancellation.

The adapter reconstructs Auditok tokenization from bounded, analysis-window-aligned past context plus the current block. A decision is active only when a token overlaps that block; `reset()` makes subsequent behavior equivalent to a fresh instance. Sample rate or channel-count changes fail until reset. Initial calibration is a separate pre-stream experiment, not a runtime detector mode; a resulting numeric threshold may construct the fixed detector, but the candidate percentile, margin, floor, and duration are not public defaults.

Every propagation backend implements `propagate(scene, array_id, time_window) -> MicrophoneSignalBlock`. The snapshot is the only array-state authority for simulated propagation; the identifier is a selector, and missing identifiers raise the clear `AudioSceneSnapshot.array_by_id()` error before rendering.

`core.simulation.simulate_frame()` is the public module-level composition boundary above the plugin protocol. It calls `propagate()` once, resolves the exact snapshot array, runs perception with deterministic frame identity, optionally passes the same block to a waveform sink, and returns the frame and block. It is not re-exported from the package root. `propagate()` itself performs no frame construction or persistence, and `AnalyticAcoustics` has no `simulate()` compatibility method.

`core.simulation.simulate_from_config()` is the higher-level maintained scalar entry point. It requires keyword-only `energy_threshold_dbfs`, accepts `doa_enabled=False`, resolves the standard pipeline internally, and returns the frame while leaving `AudioSensorConfig`, TOML, and the low-level composition contracts unchanged.

Capability declarations record identifiers, profiles, device support, `PluginDeclaration.output_contract`, determinism, dependencies, and provider provenance. Activity declarations require scalar `ActivityDecision` output and registry resolution rejects a detector whose instance identifier differs from its declaration. `get_backend()` is the sole public propagation-backend resolver, while `registered_backend_ids()` is the authoritative built-in backend inventory.

Registry resolution rejects duplicate declarations, unknown identifiers, unavailable dependencies, unsupported devices/profiles, factory results that do not satisfy `PropagationBackend`, and mismatched `backend_id` values. Dependency and capability checks occur before backend construction.

The built-in propagation registry contains only `analytic_acoustics`, and the built-in activity-detector registry contains only `auditok`; resolution requires `factory_kwargs={"energy_threshold_dbfs": ...}`. The DOA registry contains only `tdoa_least_squares` and optional `pyroomacoustics_srp`; removed IDs are unknown and have no aliases. `discover_capabilities()` reports each maintained level and optional feature as `bundled`, `external`, or `absent`. Standard Python installs Auditok with Core and resolves room and FLAC dependencies from the `room` extra; the packaged Kit extension resolves all six third-party distributions from its internal `_bundled` directory.

## Trace IO

JSON frame files and JSONL streams use deterministic serialization and round-trip through the public frame model.

Readers require the exact v3 frame shape; writers emit that same deterministic shape. A reader reconstructs the frame from `start_time_s` and rejects any serialized `timestamp_ms` that does not equal the derived value. Frame v1/v2 resources and compatibility parsing are absent from the current package. Recorded producer identifiers describe provenance but do not become runtime selectors.

Tracked v3 examples under `examples/traces/` cover a minimal zero-observation frame, one resolved observation, and external/unresolved observation records.

## Dataset Supervision

Subphase 05.1 provides `recording.FrameTruth`, `TruthEvent`, `AnnotationRecord`, and `simulate_dataset_frame()`. The dataset-owned simulation function returns observed frame, immutable signal block, and separate truth from one analytic render. Per-source identity, authored class, snapshot geometry, emission, received evidence, occlusion, and asset references never enter `AudioObservation`, signal blocks, or perception inputs.

Truth distinguishes missing supervision from a known empty scene. Observation and truth cardinalities are independent. Annotation provenance and explicit references belong beside the frame. Received RMS describes linear source stems before mixture effects; mixture residual RMS includes noise, electronics, and float32 conversion and is not a pure-noise or SNR estimate. No automatic audibility decision or matching is provided. Truth window fields match the frame exactly; received and residual maps cover the same microphone IDs. Scalar energy values are finite and nonnegative. Snapshot positions use world meters and XYZW orientation; bearing/elevation use the frame coordinate convention. Exact semantics and implementation status are owned by [[implementation_phases/05-ground-truth-and-learning-datasets|Plan 05]].

## Dataset Sessions

Manifest v4 preserves the stable acquisition `session_id` introduced in v3, defaulted from the initial `dataset_id` by the recorder and preserved by FLAC export. Optional episode `trajectory_id` and `source_asset_ids` are caller-declared global identities for learning splits; null assets mean unknown inventory, while an empty list means known empty. These fields survive recorder state v2 recovery. Frame-record v2 and frame v3 remain unchanged.

Manifest v4 removes episode `array_poses`, `labels`, and `visual_sync_asset_ids`, `ManifestPose`, and the `visual_sync` asset kind. Per-frame observations, truth, and annotations remain separate. Statistics no longer expose `label_counts`, `visual_sync_count`, JSON `labels`, or `modalities.visual_sync_count`; no replacement counters or label conversion are added.

The recording subsystem writes a finalized session with a root manifest, canonical session configuration, deterministic shard directories, frame records, audio payloads when enabled, and completion markers that bind promoted shard content.

The public recording surface contains the learning sample/dataset/collation APIs, manifest/provenance models, `AppendFrameResult`, `LoadedFrame`, `ReplayEvent`, split/statistics/validation reports, `SessionRecorder`, `SessionDataset`, replay, validation, FLAC export, manifest IO, and split-plan services. `DatasetLayoutError`, `DatasetSplitError`, and `SessionRecorderError` are the public failures; writer, checkpoint, carry, marker, planner, and filesystem details are internal.

`SessionRecorder.append_frame()` accepts one `AudioSensorFrame` and a `MicrophoneSignalBlock | None`, uses the frame timestamp for automatic time-gap diagnostics, and accepts keyword-only `is_reset=False`, `truth=None`, and `annotations=()`. Truth and annotation references are validated before frame state advances; invalid inputs follow existing drop accounting. The recorder verifies array, producer, sample rate, window, frame index, microphone order, channel validity, and session configuration before consuming the immutable samples. It does not require equal frame/block provenance because an Isaac-owned `isaac_live` frame may derive from an analytic producer block. `None` remains valid for metadata-only sessions, and hop/overlap carry remains recorder-owned. `cancel()` finalizes an incomplete session; class methods own resume and finalization recovery.

Every canonical `ias.dataset_frame_record.v2` row contains its dataset/episode identity, audio sample bounds, `frame`, nullable `truth`, and an `annotations` array. Truth contains a `truth_events` array independently of `frame.observations`. A known empty scene has a non-null truth record with no events; unavailable truth is null. `LoadedFrame` exposes `frame`, `truth`, and `annotations` separately. Replay preserves these fields and FLAC copies the JSONL rows unchanged. No per-source waveform is stored.

Durable staging and atomic promotion prevent a partial write from appearing as a completed shard. Manifest and split-plan writes are atomic, and manifest input must already match the canonical v4 representation rather than relying on type coercion.

`SessionDataset` verifies lifecycle, manifest/configuration agreement, completion markers, record order, audio joins, frame sample rate/channel IDs, exact reset alignment, and optional checksums before exposing records. The recorder also rejects channel-ID mismatches in metadata-only captures before advancing accepted frame state. Loader and validation call the same canonical frame-record parser directly. Replay uses the checked episode stream for timestamp, reset, and count guarantees. Corrupt or incomplete shards are not silently treated as valid data, and layout failures carry stable code, location, and detail fields.

Validation checks manifest/schema consistency, shard tiling and lifecycle, frame records, split-group isolation, waveform finiteness when requested, and preserved time-gap accounting.

Deterministic split planning keeps one split group together, statistics stream verified records, FLAC export is optional, and replay is ordered and read-only.

## Learning Samples

Open complete artifact roots with `LearningDataset.open([root_a, root_b])`. Input paths and artifact `dataset_id` values must be unique; transformed artifacts may share acquisition `session_id`. Iteration preserves supplied artifact order and frame order. `iter_samples(with_audio=True, with_supervision=False, split=None)` yields `LearningSample(policy_inputs, frame, truth, annotations, context)`. Supervision is opt-in and never changes policy inputs. Frame metadata, IDs, poses, provenance, and free-form diagnostics stay outside the policy projection.

Policy arrays use float32 numerical values and boolean masks. Let C be channels, T the referenced audio length, O observations, and K the maximum candidate count for the corresponding angle axis within the sample:

| Fields | Sample shape | Meaning |
| --- | --- | --- |
| `waveform`, `audio_mask` | `(C, T)`, `(T,)` | Full-scale audio and stored-sample presence; waveform is `None` when absent or disabled. |
| `channel_validity` | `(C,)` | Recorded microphone validity, independent of padding. |
| `rms`, `rms_mask` | `(C,)` | Observed RMS and value availability in manifest channel order. |
| `observation_mask` | `(O,)` | Real observations rather than batch padding. |
| `detection_score`, `bearing_deg`, `elevation_deg`, `bearing_confidence`, and each corresponding `_mask` | `(O,)` | Observed estimates; unavailable scalars use zero with a false mask. |
| `candidate_bearing_deg`, `candidate_elevation_deg`, and each corresponding `_mask` | `(O, K)` | Candidate angles with separate bearing/elevation axes; no candidate pairing is invented. |

`context` carries `dataset_id`, `session_id`, `episode_id`, `dataset_frame_index`, `audio_reference=(shard_id, start_sample, end_sample)`, `sample_rate_hz`, `channel_order`, `episode_start`, and `is_reset`. A reset may occur inside an episode; these flags are not interchangeable. The authoritative half-open audio range can be shorter than the nominal frame window at a shard boundary. Missing audio has zero audio-mask length and is distinct from recorded silence. PCM16 and left-aligned PCM24 are converted to float32 full-scale amplitude; WAV amplitude is unchanged.

`collate_learning_samples(samples)` adds a leading batch dimension and pads variable axes with zero/false, without truncation. It rejects empty batches and mismatched sample rates/channel orders. With no audio in any sample, batch waveform remains `None`; otherwise absent audio rows are masked padding. It returns `policy_inputs` separately from ordered `frames`, `truth`, `annotations`, and `context` tuples. Ground truth remains ragged and independent of observation counts. Policy arrays and mappings are read-only; no additional waveform is serialized.

`build_split(ratios=..., seed=..., isolate_by=("scene", "trajectory", "asset"), kind="train_validation_test")` returns read-only artifact-ID assignments and installs them for `iter_samples(split=...)`. `fit_holdout` uses the existing fit/holdout partition convention. Sessions are always indivisible, including multiple exports of one acquisition. Shared selected identities connect sessions transitively. Missing selected identities and impossible partitions fail; ratios are frame-weighted targets and may not be exactly attainable. A failed split request clears any earlier assignment. These corpus assignments do not modify existing per-session manifest splits or create another stored split format. Identity semantics and scope are owned by [[implementation_phases/05-ground-truth-and-learning-datasets|Plan 05]].

The maintained `examples/core/learning_samples.py` example records generated signals in temporary sessions, splits the corpus, and collates a supervised batch. Only `batch["policy_inputs"]` is intended for the policy.

## Calibration Profiles

The calibration contract stores versioned, unit-explicit array and microphone corrections with provenance and validation rather than asserting unmeasured physical truth. Calibration gain remains data-only and is not injected automatically into runtime amplitude.

Applying relative geometry, gain, delay, polarity, response, confidence, or timing information requires values supported by the profile; absolute physical calibration and sim-to-real validity require external measurements and evidence.

## Audio Asset References

Generated identifiers support deterministic examples; file-backed sources are loaded and resampled when the selected waveform backend requires audio; external corpora remain outside the repository and are referenced through user-owned paths. The generated or file sample amplitude is part of the asset. Nominal source `gain_db = 0` is unity, and WAV loading performs no automatic peak or RMS normalization.

Exported waveforms and recordings are runtime outputs, not tracked product source or embedded schema content.

## Compatibility

Package `3.0.0` is a breaking directivity, gain-consistency, signal-producer, and observed-frame release. Import sensor contracts from `core`, dataset contracts from `recording`, and schema generators from `schemas.generate`.

Migrate source directivity to `AudioSourceSpec.directivity`, microphone directivity to `MicrophoneSpec.directivity`, and Isaac Lab custom microphone geometry to `EntityBindingCfg.microphones`. Construct `SourceOcclusion` from its required per-microphone maps and optional band rows; removed aggregate, model, hit-path, and material fields have no aliases. Rename Isaac fallback configuration to `unknown_material_loss_db` and remove any total-loss cap argument. Propagation plugins implement `propagate(scene, array_id, time_window)` and return `MicrophoneSignalBlock`; scene-to-frame consumers compose `core.simulation.simulate_frame()` with an explicit perception pipeline. Waveform sinks implement `write_signal_block(*, frame_id, block)`, and dataset recorders receive the block directly. Bind Lab reference mode with `array_ids` instead of `array_specs`. Replace legacy backend choices with `analytic_acoustics`, move solver options to `[audio.analytic_acoustics]`, and choose the estimator separately. Remove `[audio.effects.directivity]` rather than translating it. Former directivity `frequency_points` have no automatic migration; move a still-required microphone response manually to `audio.effects.channel_response.<mic>.frequency_response`.

The frame schema is v3 because Plan 02.2 intentionally replaced backend-owned detections with perception-owned observations and channel validity. Subphase 05.1 introduced dataset-manifest and dataset-frame-record schemas v2, replacing `SourceTruth` and `EpisodeRecord.source_truth` with per-frame supervision. Subphase 05.2 advances the manifest to v3 for learning identities while keeping frame-record v2. Subphase 05.3 advances the manifest to v4 by removing unused pose, episode-label, and visual-sync metadata and their supporting APIs. Earlier manifest versions and removed fields are rejected without compatibility readers. Calibration remains v1 and dataset records embed the current v3 frame. The package does not retain aliases or parallel runtime paths for `AudioDetection`, detection fields, frame v1/v2, removed Python/configuration surfaces, four legacy propagation backends, the backend sensor-object argument, or Lab `array_specs` reference binding.

Stable serialized v3 frame fields, units, provenance, coordinate meaning, ambiguity representation, producer identifiers, sector mapping, and named diagnostic namespaces cannot be removed or redefined in a compatible release. This serialized compatibility does not require preserving an old identifier as a runtime selection surface.

The frame v3 top-level and observation shapes are exact; changing them requires another explicit schema decision. Additive entries inside documented diagnostic maps, capability reporting, and bug fixes remain compatible when their existing meanings are preserved.
