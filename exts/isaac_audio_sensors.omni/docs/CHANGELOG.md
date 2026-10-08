# Extension Changelog

## 3.0.0 - Unreleased

- Added shared Geometry scene/sensor ownership, prepared-scene controls, saved native settings and separate actionable diagnostics.
- Migrated all sensor consumers to frame v4 observations; integrated Auditok with an explicit activity threshold and default-off causal DOA. Missing estimates and valid silent PCM remain explicit.
- Breaking: binding v7 requires activity, direction and environment settings; older bindings, legacy backends, implicit rooms, and effects-owned directivity are removed.
- Added multievent instruments, guided workflows, source/microphone directivity controls, native OmniSound/OmniListener authoring, finite/infinite playback loops, and qualitative Kit mix capture separate from sensor audio.
- Fixed captured channel order in guided recording and dispatch ordering in Replicator Start/Stop.
- Configuration parses fully before closing the session or applying state. Scalar fields share one import/export definition; USD operations use standard methods.
- Split the live smoke into coherent scenarios with one aggregate result; packaged dependency origins, recording, rendering, and lifecycle remain verified.

## 2.0.0 - 2026-08-21

- Consolidated the maintained Kit workflow and runtime services.
- Standardized the standalone Linux archive for the NVIDIA Community Registry.
- Bundled the room-acoustics and FLAC runtime dependencies without shadowing Kit's NumPy.
