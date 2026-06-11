# Limitations

- The package is simulation tooling, not a safety-certified perception system.
- [V1 Public Scope](v1_scope.md) is the canonical promise boundary. V1 does not
  promise SquadBot as a v1 release gate, Alex as a v1 release gate, mandatory
  ROS 2 or downstream adapters, sim-real calibration, real hardware
  benchmarks, complete L3/L4 acoustic fidelity, realistic occlusions or
  material acoustics, or Alex/SquadBot validation before releasing the sensor
  package.
- `geometry_only` is deterministic geometry, not acoustic propagation.
- `tdoa_synthetic` models direct-path delay from known geometry and optional
  deterministic stress controls; it does not model multipath or microphone
  frequency response, and applies occlusion only as producer-supplied
  per-microphone broadband raycast/transmission attenuation.
- `room_acoustics` is an optional approximate shoebox simulation and depends on
  `pyroomacoustics`. It generates RIRs and true microphone mixtures, then
  derives TDOA through GCC-PHAT, but it does not provide realistic occlusion,
  material behavior, source directivity, calibrated microphone response,
  production beamforming, mixed-source separation of unknown signals, or
  sim-real transfer.
- `room_acoustics` file-backed `audio_asset_path` loading is intentionally
  narrow: paths must be relative public files under the checkout. Mismatched
  sample rates are resampled with `scipy.signal.resample_poly`.
- Doppler from per-tick source motion is not modeled by the continuous
  session renderer; it is deferred to the Block 8 roadmap item together with
  source velocity tracking.
- The continuous session WAV is the concatenation of captured windows;
  sim-time gaps between throttled update ticks are not rendered as silence.
- The 2026-05-24 local-time final `1.0.0` live Isaac Sim validation
  (`2026-05-25T03:34Z` Kit log timestamp) skipped `room_acoustics` because
  `pyroomacoustics` was absent from the Isaac runtime. The live proof covered
  `geometry_only` and `tdoa_synthetic`; room/RIR diagnostics are live-validated
  only when the optional dependency is installed and the smoke reports that
  backend as passed.
- L3 advanced realism is a provisional API direction; its first shipped
  capability is opt-in Isaac raycast occlusion, since `1.4.0` a
  material-aware, frequency-dependent ray/transmission model (multi-hit,
  per-microphone, octave-band presets and USD attribute overrides). It is
  not a wave-acoustic propagation solver: diffraction, edge effects, and
  thickness-dependent transmission are not modeled, and the preset
  transmission-loss table is illustrative, not measured truth. Richer
  wave/RIR, directivity, noise, and estimator realism remain future work,
  and L3 still is not a complete v1 runtime backend.
- L4 sim-real calibration is experimental/tooling direction for future
  calibration artifacts and sim-vs-real comparisons; it is not a stable v1
  runtime backend or automatic hardware calibration pipeline.
- Two-microphone arrays have front/back ambiguity. The package exposes that
  ambiguity instead of hiding it.
- Four or more non-collinear microphones are recommended for robust DOA demos.
- L1 `noise_std_s`, `clock_jitter_s`, and `gain_mismatch_db` are deterministic
  stress knobs (seeded Gaussian draws, repeatable per seed/frame/microphone),
  not calibrated hardware noise. They perturb delay/RMS and
  confidence diagnostics but do not model stochastic sensor drift, electronics
  noise spectra, clipping, automatic gain control, or hardware clock recovery.
- L1 `air_absorption_db_per_m` is a single broadband coefficient, not a
  frequency-dependent atmospheric absorption model. `self_noise_db` and source
  `directivity` are modeled first-order at L0/L1 and are metadata-only at L2.
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
- Replicator recording is implemented for the reference Omniverse extension,
  not for pure Python imports. It requires `omni.replicator.core` inside
  Isaac Sim/Kit, registers a Python writer, and records recoverable
  `AudioSensorFrame` v1 payloads plus metadata. Kit versions with no compatible
  writer registry, writer lookup, or flush API report a readable blocker and
  should still use the package JSON/JSONL recording path.
- This package is independent and is not an official NVIDIA extension.
- Isaac debug draw is best-effort. When the Isaac debug draw API is unavailable,
  the package still emits structured debug primitives for tests and export.
- Replicator annotator registration is best-effort because public Kit Python
  APIs vary by Isaac version. The writer path is the supported v1 recording
  path; annotator registration status is captured in config/live evidence.
- Generated showcase artifacts are linked through the showcase site; they are
  not tracked source files in this repository.
- The local live-evidence report and PDF are generated under ignored
  `outputs/isaac_audio_sensors/` by `scripts/generate_live_evidence_report.py`.
  They may contain machine-local absolute Python runtime paths from evidence
  fields such as `python_executable`; those paths are evidence facts, not
  portable install instructions or release-archive content.
