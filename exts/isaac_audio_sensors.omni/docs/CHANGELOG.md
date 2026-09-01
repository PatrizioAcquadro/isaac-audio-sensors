# Extension Changelog

## 3.0.0 - Unreleased

- Breaking: require explicit environment resolution before validation or sensor start, with `unconfigured`, `manual_free_field`, `anchor`, and `auto` modes and no implicit array-centered shoebox.
- Export and import `ias.omni_extension_binding.v3` with environment mode, anchor, tolerance, resolved result, and provenance; v2 has no compatibility parser.
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
