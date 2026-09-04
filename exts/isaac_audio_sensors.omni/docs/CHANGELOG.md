# Extension Changelog

## 3.0.0 - Unreleased

- Integrate Auditok into the standard extension sensor with an explicit finite `Activity dBFS` field, signal-derived observations after causal warm-up, and reset on stream-defining array-layout changes.
- Breaking: import and export `ias.omni_extension_binding.v6` with required exact `activity_detection.detector_id="auditok"` and `activity_detection.energy_threshold_dbfs`; reject v5 and older inputs without compatibility parsing.
- Preserve signal-derived observations through frame export, JSONL, guided recording, Replicator, OmniGraph, headless summaries, presets, and configuration round trips without inventing score, DOA, source identity, class, or occlusion events.
- Bundle and runtime-check Auditok 0.5.2 as the qualified fixed-threshold activity detector; consumer integration is completed by Plan 03.3.
- Breaking: migrate sensor state, configuration, Replicator, OmniGraph, export, instruments, and recording summaries from detections/backend naming to frame-v3 observations/producer naming.
- Show valid waveform and RMS output during inactive, warm-up, and post-reset empty-observation states; do not derive compass, timeline, source identity, or occlusion events from USD source truth.
- Breaking: remove sensor-side DOA ambiguity policy state and introduce `ias.omni_extension_binding.v5`; v4 and saved `lifecycle.ambiguity_policy` inputs were rejected, and Plan 03.3 later superseded v5 with v6.
- Breaking: require explicit environment resolution before validation or sensor start, with `unconfigured`, `manual_free_field`, `anchor`, and `auto` modes and no implicit array-centered shoebox.
- Export and import the analytic backend, solver options, environment mode, anchor, tolerance, resolved result, and provenance without any contextual direction prior.
- Breaking: removed all four legacy backend choices and renamed room-specific UI/configuration fields to their analytic equivalents.
- Breaking: replaced free-form source directivity with the shared four-value `DirectivityPattern` selector and removed the obsolete effects-owned directivity configuration without compatibility aliases.
- Validate source directivity, orientation, nominal gain, saved configuration, sound profiles, and child-microphone `ias:directivity` metadata before authoring mutations.
- Use the shared fail-closed amplitude-gain conversion for native Kit Audio and microphone-rig gains; `gain_db = 0` remains unity and file-backed WAV amplitude is not normalized.

## 2.0.0 - 2026-08-21

- Post-release, unreleased: added compatible array-child listener reuse with a session-layer fallback plus manual qualitative Kit mix capture with verified WAV metadata, safe active-listener restoration, and lifecycle cleanup; Sensor WAV playback and microphone-array observations remain separate.
- Post-release, unreleased: completed native finite/infinite `loopCount` authoring and discovery, excluded non-spatial sounds from strict physical-sensor scans unless explicitly selected, and exposed source loop count in the Kit UI/configuration.
- Post-release, unreleased: author current `OmniSound` prims with schema-native timing, gain, spatial, and loop attributes; generated SDK assets no longer author Kit Audio `filePath` values.
- Post-release, unreleased: refined guided indicators, frame freshness, dBFS meters, adaptive detection rows, operational footer priority, field-specific recovery, and transient field styling without changing public or serialized contracts.
- Post-release, unreleased: redesigned the native Kit window around Guided Workflow, Live Monitor, and Advanced Tools, with persistent expert-mode collapse state and a fixed status strip.
- Consolidated the maintained Kit workflow and runtime services.
- Standardized the standalone Linux archive for the NVIDIA Community Registry.
- Bundled the room-acoustics and FLAC runtime dependencies without shadowing Kit's NumPy.
