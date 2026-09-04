# Changelog

## 3.0.0 - Unreleased

- Breaking (Plan 02): changed `PropagationBackend` from scene-to-frame `simulate()` to scene-to-signal `propagate()`, replaced frame v2 detections with the exact frame v3 observation contract, and removed the temporary bridge and source-conditioned assembly without aliases. Dataset-manifest and calibration-profile wrappers remain v1.
- Added immutable `MicrophoneSignalBlock`, observed-only `AudioObservation` and `AudioPerceptionPipeline` contracts, and `simulate_frame()` as the single propagation-to-perception path shared by waveform, recording, Isaac, Lab, Kit, Replicator, OmniGraph, and downstream adapters.
- Added the stateful `ActivityDetector`/`ActivityDecision` contract and one maintained `AuditokActivityDetector` with causal bounded context, multichannel `any` semantics, deterministic reset, exact float32/dBFS adaptation, and an explicit application-owned threshold. No score, DOA, source identity, class, or source count is invented.
- Corrected Subphase 04.2 to qualify estimator roles independently over the complete 128-case synthetic primary matrix and explicitly scoped the real results as take-level validation within one campaign. PyRoom SRP is the primary planar estimator at a 250 ms causal context and `0.06` reliability threshold; least-squares retains the generic two-microphone ambiguity role; robustness remains failed and optional 3D remains blocked as a product claim without invalidating the planar result.
- Added default-off standard DOA across Core, CLI, Isaac Sim, Isaac Lab reference, and Kit. The consumer owns exact trailing 250 ms context, geometry-only role selection, and fail-closed reversal confirmation; custom pipelines remain caller-owned. Removed the internal SRP module, adapter, export, registry ID, constant, and tests.
- Breaking (Plan 04): Kit configuration is exact `ias.omni_extension_binding.v7` with required `direction_estimation.enabled`; binding v6 has no compatibility parser. Core TOML, `DoaEstimate`, and frame schema v3 are unchanged.
- Fixed energetic identical two-channel least-squares input so zero TDOA preserves both physical candidate bearings without inventing a selected bearing, sector, or confidence; silence remains `low_information`.
- Breaking (Plan 03): standard scalar runtimes now require `energy_threshold_dbfs`; Plan 03 introduced exact Kit binding v6 with required `activity_detection`, later superseded by Plan 04 binding v7. Isaac Lab reference binding owns one detector per environment and keeps all six public tensors zero-filled until Phase 07.
- Added Auditok 0.5.2 as a Core dependency and the sixth hash-locked Kit distribution. Removed superseded calibration-only coverage and unconsumed private render-tail and waveform diagnostic duplicates without changing schemas or maintained outputs.
- Breaking (R9.1.2): removed every Core, backend, plugin, Isaac, Lab, Kit, and TOML ambiguity-policy input. Two-microphone least-squares now returns all physically compatible azimuth candidates with no unique estimate or confidence, except at a deduplicated physical endpoint; contextual selection belongs to downstream consumers.
- Breaking (R9.1.2): least-squares arrays with three or more microphones and all SRP-PHAT arrays now require at least three microphones with rank-2 XY geometry. That subphase introduced Kit binding v5 without a v4 parser; Plan 03.3 supersedes it with v6.
- Breaking (R9.1.1): reduced `AudioTimeWindow` to required start, end, and frame-index fields; removed independent timestamps from scene snapshots, time windows, and detections; and made frame timestamps derived exclusively from frame start time.
- Breaking (R9.1.1): made each `MicrophoneArraySpec.sample_rate_hz` the sole runtime rate authority, removed the parallel Core and `[audio]` rate inputs, and projected the selected array rate into `AudioSensorFrame`.
- Breaking (R9.1.1, superseded by Plan 02.2): removed `max_events` and pre-render source truncation. All active sources still contribute to waveform and aggregate RMS; `max_observations` now limits only the deterministic observed output after perception.
- Added public `AnalyticAcoustics`/`analytic_acoustics` with environment-only routing to Core free-field and half-space solvers or lazy PyRoom shoebox and polygon-prism solvers, including per-surface materials, fail-closed containment, and solver diagnostics on signal blocks and frames.
- Breaking: consolidated runtime propagation on `analytic_acoustics` and removed `geometry_only`, `tdoa_synthetic`, `room_acoustics`, `room_acoustics_srp`, their public classes, modules, registry declarations, and compatibility aliases. Recorded backend identifiers remain provenance only and are not selectable at runtime.
- Preserved the six fixed-shape Isaac Lab tensors and CUDA-native lifecycle while removing source-conditioned tensor assembly. Plan 03.3 runs Auditok only in the scalar reference path; both bindings retain zero-filled tensors until Phase 07.
- Added phase-coherent direct/indirect stem decomposition for Core and PyRoom propagation, including segmented motion, custom sound speed, broadband or banded per-microphone attenuation, and exact `a * D + R` recombination without exposing stems in the public waveform contract.
- Integrated `analytic_acoustics` occlusion with Isaac lifecycle raycasts. `surface_set` remains deferred to the future `GeometryAcoustics` backend.
- Breaking: replaced aggregate `SourceOcclusion` fields with required `array_id`, `source_id`, `per_mic_blocked`, `per_mic_attenuation_db`, and `occlusion_model` state plus optional aligned spectral attenuation, per-microphone hit paths, and material provenance. Aggregate attenuation and hit-path aliases were removed.
- Breaking: replaced `RoomAcousticsSpec` and `AudioSceneSnapshot.room` with `AcousticSurfaceSpec`, `AcousticEnvironmentSpec`, and `AudioSceneSnapshot.environment`; no alias, parallel field, or legacy `[room]` parser remains.
- Breaking: made `AudioSceneSnapshot.environment` and the TOML `[environment]` table mandatory for every backend; all Python, CLI, Isaac, Kit, example, smoke, and active downstream fixtures now provide or resolve one explicit `AcousticEnvironmentSpec`.
- Added fail-closed `free_field`, `half_space`, `shoebox`, `polygon_prism`, and `surface_set` builders, complete world/environment quaternion transforms, and one `[environment]` TOML surface. Shoebox sources and microphones outside the environment always fail instead of clamping.
- Moved `max_order`, `air_absorption`, and `ray_tracing` to `[audio.analytic_acoustics]`; the former room table is rejected. Maintained PyRoom code now lives under analytic backend internals, and public room diagnostics and hashes use `environment_*` names.
- Added fail-closed Isaac `manual`, `anchor`, and `auto` resolution with full-array containment, 1 mm default tolerance, marked shoebox/floor discovery, priority/volume ambiguity rules, and cache refresh on relevant array or USD changes.
- Removed the implicit Kit shoebox, added `unconfigured`, `manual_free_field`, `anchor`, and `auto` modes, made safe presets explicitly free-field, and introduced breaking `ias.omni_extension_binding.v4` configuration with no v2/v3 parser.
- Breaking: made `AudioSourceSpec.directivity` and `MicrophoneSpec.directivity` the only runtime authorities, backed by public `DirectivityPattern` values `omni`, `cardioid`, `supercardioid`, and `figure_eight` and one canonical coefficient table.
- Breaking: removed `audio.effects.directivity`, all pattern-set and frequency-point records, and `EntityBindingCfg.microphone_relative_offsets_m` without aliases or compatibility runtime paths. Lab custom microphones now use `EntityBindingCfg.microphones` with `MicrophoneSpec` values.
- Breaking (R9.1.1): changed the former backend `simulate()` call to `(scene, array_id, time_window)` and Isaac Lab reference binding to `(snapshots, array_ids)`. `AudioSceneSnapshot` became the sole array-state authority; no sensor-object or `array_specs` compatibility path remains.
- Added fail-closed directivity and orientation validation across Core TOML, USD discovery/authoring, Kit configuration and sound profiles, and Isaac Lab bindings. Child microphones use `ias:directivity`; the Kit source field is an enum-backed selector.
- Standardized nominal `gain_db` as amplitude gain `10 ** (gain_db / 20)`. Source gain is applied once to generated or original-amplitude WAV assets before propagation; microphone gain is applied once after propagation in every frame and Lab path.
- Preserved L0/L1 analytical `1/d` with the existing distance floor and L2 PyRoom RIR distance/reflection behavior without a second manual `1/d`. L2 waveform directivity remains signed while RMS uses magnitude.
- Retained channel-response gain, TDOA gain mismatch, and occlusion as separately ordered and diagnosed deltas. Calibration-profile gain remains data-only and is never applied automatically.
- Preserved `ias.audio_dataset_manifest.v1` and `ias.audio_calibration_profile.v1`; the frame contract is now `ias.audio_sensor_frame.v3`.

## 2.0.0 - 2026-08-21

- Post-release, unreleased: reorganized current core sources by effect domain, room-pipeline stage, and semantic motion/acoustics/DOA ownership while preserving public exports, schemas, diagnostics, error behavior, and numerical output.
- Post-release, unreleased: completed finite/infinite `OmniSound.loopCount` conversion, excluded non-spatial stage sounds from physical-sensor discovery without failing strict scans unless explicitly selected, and made file-backed room sources repeat within the authoritative playback window.
- Post-release, unreleased: added compatible array-child listener reuse with a temporary session-layer fallback and manual Kit device-mix capture for qualitative audition, explicitly isolated from microphone-array frames, recordings, datasets, and Isaac Lab observations.
- Post-release, unreleased: migrated Isaac/Kit authoring to NVIDIA's current `OmniSound` and `OmniListener` schemas, corrected native audio units and attributes, and retained read compatibility for deprecated `Sound` and `Listener` prims.
- Established subsystem-owned v2 APIs, lazy optional runtimes, focused tests, and concise examples without compatibility shims; existing frame, manifest, and calibration schema v1 contracts remain supported.
- Consolidated backends, effects, recording, Isaac Sim, Isaac Lab, Kit, and CLI around their maintained runtime responsibilities while removing duplicate, private, and test-only surfaces.
- Added dataset-manifest and calibration-profile contracts, runtime profiles, plugin protocols, version synchronization, and deterministic release audits.
- Added generic sharded recording, verified session lifecycle, deterministic splits, validation, replay, and guided Kit workflows without changing existing frame or manifest schemas.
- Consolidated product documentation in the canonical wiki and cleaned root guidance, generated workspaces, and validation output under R6.1.
- Added an audited Python source distribution and one universal wheel built from it, with isolated installed-artifact validation.
- Standardized the self-contained Kit extension as a minimal Linux x86_64 Community Registry archive for Kit 110.1 and Python 3.12.
- Removed the custom acoustics-pack workflow and bundled the locked room-acoustics and FLAC dependencies directly in the Kit archive without duplicating Kit's NumPy.
- Reduced the local workflow to safe clean, deterministic check, and clean-source release commands that leave exactly the audited sdist, wheel, and Kit ZIP.
- Added Python 3.10–3.12 CI and tokenless TestPyPI/PyPI publication through GitHub Actions with environment approval and attestations.
- Closed local R6 validation with exact source-derived artifact inventories, offline installed-wheel validation, and packaged RTX runtime and consumer gates.

## 1.7.0 - 2026-06-12

- Added optional 3D elevation, tetrahedral arrays, SRP-PHAT, and Doppler-aware diagnostics/rendering while keeping earlier v1 traces readable.
- Preserved the `ias.audio_sensor_frame.v1` schema with additive fields only.

## 1.6.0 - 2026-06-12

- Made room acoustics use explicit world-space bounds with fixed or stage-anchored placement, material discovery, and visible room diagnostics.
- Replaced automatic room refitting with fail-closed bounds validation or explicit clamping.

## 1.5.0 - 2026-06-11

- Split the Omniverse UI monolith into maintainable components and added live instruments, waveform/spectrogram preview, viewport workflows, persistent debug geometry, and OmniGraph output.
- Kept the frame schema unchanged and evolved extension configuration additively.

## 1.4.0 - 2026-06-11

- Added explicit discovery-cache semantics and material-aware, frequency-dependent, per-microphone multi-hit occlusion.
- Kept diffraction, edge effects, and thickness-dependent transmission outside the claimed model.

## 1.3.0 - 2026-06-10

- Added Isaac PhysX raycast occlusion for each source/microphone pair and cached live-stage discovery.
- Preserved the v1 frame contract through additive occlusion diagnostics.

## 1.2.0 - 2026-06-10

- Added sample-accurate multi-source room rendering and multichannel WAV export.
- Derived room diagnostics from the rendered microphone mixtures without changing the frame schema.

## 1.1.0 - 2026-06-10

- Corrected cross-backend pressure, gain, TDOA, bearing, and observable-only semantics while preserving the v1 frame shape.
- Added compatible diagnostics and deterministic physics validation.

## 1.0.0 - 2026-05-24

- Promoted the reviewed release candidate and froze the `AudioSensorFrame` v1 contract for compatible additions and bug fixes.
- Kept package and serialized schema versions independent.

## 1.0.0rc1 - 2026-05-24

- Published the v1 release candidate with stable L0/L1 backends, optional L2 room acoustics, lazy Isaac integrations, and the frozen frame API.
- Excluded downstream task behavior and later phases from the release gate.

## 0.1.0 - 2026-05-21

- Added the standalone package with pure sensor models, geometry/TDOA backends, optional room acoustics, CLI export, lazy Isaac integrations, examples, and tests.
- Defined the initial public boundary and excluded project-specific adapters, private data, and local artifacts.
