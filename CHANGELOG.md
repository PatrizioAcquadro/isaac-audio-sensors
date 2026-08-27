# Changelog

## 3.0.0 - Unreleased

- Breaking: made `AudioSourceSpec.directivity` and `MicrophoneSpec.directivity` the only runtime authorities, backed by public `DirectivityPattern` values `omni`, `cardioid`, `supercardioid`, and `figure_eight` and one canonical coefficient table.
- Breaking: removed `audio.effects.directivity`, all pattern-set and frequency-point records, and `EntityBindingCfg.microphone_relative_offsets_m` without aliases or compatibility runtime paths. Lab custom microphones now use `EntityBindingCfg.microphones` with `MicrophoneSpec` values.
- Added fail-closed directivity and orientation validation across Core TOML, USD discovery/authoring, Kit configuration and sound profiles, and Isaac Lab bindings. Child microphones use `ias:directivity`; the Kit source field is an enum-backed selector.
- Standardized nominal `gain_db` as amplitude gain `10 ** (gain_db / 20)`. Source gain is applied once to generated or original-amplitude WAV assets before propagation; microphone gain is applied once after propagation in every frame and Lab path.
- Preserved L0/L1 analytical `1/d` with the existing distance floor and L2 PyRoom RIR distance/reflection behavior without a second manual `1/d`. L2 waveform directivity remains signed while RMS uses magnitude.
- Retained channel-response gain, TDOA gain mismatch, and occlusion as separately ordered and diagnosed deltas. Calibration-profile gain remains data-only and is never applied automatically.
- Preserved `ias.audio_sensor_frame.v1`, `ias.audio_dataset_manifest.v1`, and `ias.audio_calibration_profile.v1` serialized schemas.

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
