# System Architecture

## Product Shape

`isaac-audio-sensors` converts audio-scene and microphone-array state into standardized sensor frames, waveform-derived features, recordings, replays, and fixed-shape Isaac Lab observations.

The design keeps simulator-independent contracts below optional simulator adapters so the same frame and recording semantics work in pure Python, Isaac Sim, Isaac Lab, and Kit.

## Core Layer

`isaac_audio_sensors.core` owns typed scene, source, pose, array, room, time-window, detection, DOA, occlusion, and frame models; configuration; schema generation; microphone geometry; deterministic DSP and effects; acoustic backends; plugins; calibration; trace IO; and waveform helpers.

This layer must not import Isaac, Omniverse, Isaac Lab, ROS 2, CUDA, Torch, or downstream project modules during normal import.

## Recording Layer

`isaac_audio_sensors.recording` owns the generic session layout, manifests, shard lifecycle, atomic writes, audio codecs, loading, validation, statistics, deterministic splits, and read-only replay.

Recording consumes `AudioSensorFrame` values and emits versioned generic dataset artifacts; it does not own a task-specific acquisition campaign or scientific acceptance policy.

## Isaac Sim Layer

`isaac_audio_sensors.isaac` owns lazy stage discovery, metadata authoring, pose resolution, stage snapshots, live sensor lifecycle, occlusion queries, frame publication, Replicator integration, validation, and visualization records.

The layer turns live USD state into pure core dataclasses before backend computation and raises explicit optional-runtime errors when required Isaac APIs are unavailable.

## Isaac Lab Layer

`isaac_audio_sensors.lab` adapts core behavior to Isaac Lab `SensorBaseCfg` and `SensorBase`, fixed-shape Torch buffers, cloned-stage binding, scene/entity tensor binding, selected-environment update/reset, and scalar or batched computation.

Fallback classes keep imports testable outside Lab, while `ensure_isaac_lab_sensor_classes()` recovers the real classes after `AppLauncher` initializes the runtime.

## Kit and Extension Layers

`isaac_audio_sensors.kit` contains the import-safe state, controller, workflow, view-model, instruments, audio preview, validation, and UI-section logic.

`exts/isaac_audio_sensors.omni` is the thin Omniverse extension entry point and package metadata; it registers the window, menu/action/hotkey integration, and optional OmniGraph node while delegating reusable behavior to the Python package.

## Data Flow

Configuration or live stage/entity state defines sources, arrays, motion, room, and effects; a selected backend emits `AudioSensorFrame`; optional writers serialize traces or session shards; Isaac Lab converts the same semantic output into bounded observation tensors; downstream projects adapt those outputs outside this repository.

Privileged source pose, geometry, isolated-signal, or simulator state must remain distinguishable from observed waveform and estimator outputs so training supervision does not become an unlabelled runtime dependency.

## Dependency Boundary

Core dependencies are NumPy, JSON Schema validation, and TOML support for Python versions that need it.

The `room` extra provides `pyroomacoustics`, SciPy, and SoundFile; Isaac, Kit, CUDA, Torch, and Replicator remain environment capabilities resolved lazily.

Optional absence is a supported state for pure functionality, but a requested optional capability must fail with a precise error rather than degrade silently.

## Downstream Boundary

Robot-specific mounts, assets, policies, task orchestration, acceptance criteria, research campaigns, and consumer adapters belong to downstream repositories.

See [[decisions/product-boundary-and-compatibility|Product Boundary and Compatibility]] for the maintained promises and exclusions.
