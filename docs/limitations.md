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
- Isaac Sim stage extraction supports live per-step USD world-pose reads,
  nested transform stacks, robot/base-mounted arrays, moving sources and
  arrays, microphone child prim offsets, explicit USD time codes, and
  import-safe fallback attrs. Semantic discovery uses configurable metadata,
  type, name, and child-prim signals; it does not infer arbitrary robot
  articulation semantics or add a custom USD schema.
- Real Isaac Lab `SensorBase` inheritance requires Isaac Lab/Kit
  initialization. If fallback classes were imported too early,
  `ensure_isaac_lab_sensor_classes()` provides the supported recovery path or
  raises a hard import-order error.
- Isaac Lab stage auto-binding supports cloned env namespaces, USD world
  transforms through `UsdGeom.Xformable`, simple fake-stage transform stacks,
  array/source discovery, and child microphone metadata. Arbitrary USD variant
  semantics remain future work.
- Isaac Lab entity binding supports common root/body tensor fields and
  body/link-name lookup through duck typing. It does not require exact Isaac Lab
  classes at import time, but unusual task-specific state layouts still need a
  small adapter or custom `bind_provider(...)`.
- Entity positions are treated as world-frame by default. Env-origin addition
  is opt-in through `state_position_frame="env"` and must not be enabled for
  normal Isaac Lab `*_w` world-frame tensors.
- Replicator writer integration and production acoustic realism remain future
  work.
- This package is independent and is not an official NVIDIA extension.
- Isaac debug draw is best-effort. When the Isaac debug draw API is unavailable,
  the package still emits structured debug primitives for tests and export.
- Replicator annotator/writer registration is not included yet. Use
  `AudioFrameJsonlWriter` for frame recording.
- Generated showcase artifacts are linked through the showcase site; they are
  not tracked source files in this repository.
