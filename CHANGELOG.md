# Changelog

## 2.0.0 - Unreleased

- Established subsystem-owned v2 APIs, lazy optional runtimes, focused tests, and concise examples without compatibility shims; existing frame, manifest, and calibration schema v1 contracts remain supported.
- Consolidated backends, effects, recording, Isaac Sim, Isaac Lab, Kit, and CLI around their maintained runtime responsibilities while removing duplicate, private, and test-only surfaces.
- Consolidated product documentation in the canonical wiki and cleaned root guidance, generated workspaces, and validation output under R6.1.
- Replaced the temporary wheel/source workflow with one audited universal Python wheel installed in an isolated environment.
- Standardized the self-contained Kit extension as a minimal Linux x86_64 Community Registry archive for Kit 110.1 and Python 3.12.
- Removed the custom acoustics-pack workflow and bundled the locked room-acoustics and FLAC dependencies directly in the Kit archive without duplicating Kit's NumPy.
- Reduced the local release workflow to safe clean, deterministic check, and clean-source release commands that leave only the audited wheel and Kit ZIP.

## 1.9.0 - Unreleased

- Added generic sharded recording, verified session lifecycle, deterministic splits, validation, replay, and the reference dataset fixture without changing existing frame or manifest schemas.
- Added guided Kit recording, recovery, validation, split, and export workflows.

## 1.8.0 - Unreleased

- Added dataset-manifest and calibration-profile contracts, runtime profiles, plugin protocols, version synchronization, and deterministic release audits.
- Added self-contained Kit and optional acoustics-pack workflows plus official Isaac Sim 6.0.1 and Isaac Lab 3.0.0-beta2 launcher support.

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
