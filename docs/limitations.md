# Limitations

- The package is simulation tooling, not a safety-certified perception system.
- `geometry_only` is deterministic geometry, not acoustic propagation.
- `tdoa_synthetic` models direct-path delay from known geometry and optional
  synthetic noise; it does not model occlusion, multipath, or microphone
  frequency response.
- `room_acoustics` is an optional approximate shoebox simulation and depends on
  `pyroomacoustics`.
- Two-microphone arrays have front/back ambiguity. The package exposes that
  ambiguity instead of hiding it.
- Four or more non-collinear microphones are recommended for robust DOA demos.
- Isaac Sim and Isaac Lab integrations require a user-managed NVIDIA runtime.
- This package is independent and is not an official NVIDIA extension.
- Isaac debug draw is best-effort. When the Isaac debug draw API is unavailable,
  the package still emits structured debug primitives for tests and export.
- Replicator annotator/writer registration is not included yet. Use
  `AudioFrameJsonlWriter` for frame recording.
- Generated showcase artifacts are linked through the showcase site; they are
  not tracked source files in this repository.
