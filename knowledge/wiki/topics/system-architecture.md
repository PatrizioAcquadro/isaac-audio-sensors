# System Architecture

## Product Shape

`isaac-audio-sensors` converts audio-scene and microphone-array state into standardized sensor frames, waveform-derived features, recordings, replays, and fixed-shape Isaac Lab observations.

The design keeps simulator-independent contracts below optional simulator adapters so the same frame and recording semantics work in pure Python, Isaac Sim, Isaac Lab, and Kit.

## Core Layer

`isaac_audio_sensors.core` owns typed scene, source, pose, array, room, time-window, detection, DOA, occlusion, and frame models; configuration; microphone geometry; deterministic DSP and effects; acoustic backends; plugins; calibration; trace IO; and waveform helpers. Its package root exports only the eleven fundamental models; the other APIs remain public from their canonical modules.

All propagation backends implement the same scene, array, and time-window to sensor-frame contract. Plugin declarations own backend inventory and capability metadata; effects separate immutable configuration, parsing, and validation; room acoustics separates orchestration, signal preparation, rendering, and diagnostics.

This layer imports no other package subsystem. Importing the core package root loads no NumPy, recording, concrete backend/effect, Isaac, Omniverse, Isaac Lab, Kit, CUDA, Torch, or downstream module.

## Recording Layer

`isaac_audio_sensors.recording` owns the generic session layout, manifests, shard lifecycle, atomic writes, audio codecs, loading, validation, statistics, deterministic splits, and read-only replay.

Recording consumes `AudioSensorFrame` values and emits versioned generic dataset artifacts; it does not own a task-specific acquisition campaign or scientific acceptance policy.

Dataset-manifest constants, models, and canonical JSON serializers are recording APIs rather than core APIs.

## Schema Layer

`isaac_audio_sensors.schemas` owns deterministic generation through `schemas.generate`; its three Python generators are authoritative and packaged JSON schemas are generated release artifacts. Generation depends only on core and recording contracts.

## Isaac Sim Layer

`isaac_audio_sensors.isaac` owns lazy stage discovery, metadata authoring, pose resolution, stage snapshots, live sensor lifecycle, occlusion queries, frame publication, Replicator integration, validation, and visualization records.

The layer turns live USD state into pure core dataclasses before backend computation and raises explicit optional-runtime errors when required Isaac APIs are unavailable.

## Isaac Lab Layer

`isaac_audio_sensors.lab` adapts core behavior to Isaac Lab `SensorBaseCfg` and `SensorBase`, fixed-shape Torch buffers, cloned-stage binding, scene/entity tensor binding, selected-environment update/reset, and scalar or batched computation.

Fallback classes keep imports testable outside Lab, while `ensure_isaac_lab_sensor_classes()` recovers the real classes after `AppLauncher` initializes the runtime.

## Kit and Extension Layers

`isaac_audio_sensors.kit` contains the import-safe state, controller, workflow, view-model, instruments, audio preview, validation, and UI-section logic.

The guided headless service is a Kit application service and receives an `ExtensionController` explicitly. Isaac validation returns dependency-free findings; Kit converts its first error finding into the extension error type.

`exts/isaac_audio_sensors.omni` is the thin Omniverse extension entry point and package metadata; it registers the window, menu/action/hotkey integration, and optional OmniGraph node while delegating reusable behavior to the Python package.

## Data Flow

Configuration or live stage/entity state defines sources, arrays, motion, room, and effects; a selected backend emits `AudioSensorFrame`; optional writers serialize traces or session shards; Isaac Lab converts the same semantic output into bounded observation tensors; downstream projects adapt those outputs outside this repository.

Privileged source pose, geometry, isolated-signal, or simulator state must remain distinguishable from observed waveform and estimator outputs so training supervision does not become an unlabelled runtime dependency.

## Dependency Boundary

The enforced internal imports are `recording -> core`, `isaac -> core`, `lab -> core + isaac`, `kit -> core + recording + isaac`, and `schemas -> core + recording`. The CLI composes public services; lower components do not import Kit, UI, or CLI.

The package root exports only `__version__`. Public types and services are imported from their semantic subsystem.

Core runtime dependencies are NumPy and TOML support for Python versions that need it. JSON Schema validation is development-only.

The `room` extra provides `pyroomacoustics`, SciPy, and SoundFile; Isaac, Kit, CUDA, Torch, and Replicator remain environment capabilities resolved lazily.

Optional absence is a supported state for pure functionality, but a requested optional capability must fail with a precise error rather than degrade silently.

## Downstream Boundary

Robot-specific mounts, assets, policies, task orchestration, acceptance criteria, research campaigns, and consumer adapters belong to downstream repositories.

See [[decisions/product-boundary-and-compatibility|Product Boundary and Compatibility]] for the maintained promises and exclusions.
