# Extension Changelog

## 2.0.0 - 2026-08-21

- Post-release, unreleased: added compatible array-child listener reuse with a session-layer fallback plus manual qualitative Kit mix capture with verified WAV metadata, safe active-listener restoration, and lifecycle cleanup; Sensor WAV playback and microphone-array observations remain separate.
- Post-release, unreleased: completed native finite/infinite `loopCount` authoring and discovery, excluded non-spatial sounds from strict physical-sensor scans unless explicitly selected, and exposed source loop count in the Kit UI/configuration.
- Post-release, unreleased: author current `OmniSound` prims with schema-native timing, gain, spatial, and loop attributes; generated SDK assets no longer author Kit Audio `filePath` values.
- Post-release, unreleased: refined guided indicators, frame freshness, dBFS meters, adaptive detection rows, operational footer priority, field-specific recovery, and transient field styling without changing public or serialized contracts.
- Post-release, unreleased: redesigned the native Kit window around Guided Workflow, Live Monitor, and Advanced Tools, with persistent expert-mode collapse state and a fixed status strip.
- Consolidated the maintained Kit workflow and runtime services.
- Standardized the standalone Linux archive for the NVIDIA Community Registry.
- Bundled the room-acoustics and FLAC runtime dependencies without shadowing Kit's NumPy.
