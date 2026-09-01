# System Architecture

## Product Shape

`isaac-audio-sensors` converts audio-scene and microphone-array state into standardized sensor frames, waveform-derived features, recordings, replays, and fixed-shape Isaac Lab observations.

The design keeps simulator-independent contracts below optional simulator adapters so the same frame and recording semantics work in pure Python, Isaac Sim, Isaac Lab, and Kit.

## Core Layer

`isaac_audio_sensors.core` owns typed scene, source, pose, array, acoustic-surface/environment, time-window, detection, DOA, occlusion, and frame models; canonical directivity and gain utilities; configuration; microphone geometry; deterministic DSP and effects; acoustic backends; plugins; calibration; trace IO; and waveform helpers. Its package root exports the fundamental models plus `DirectivityPattern`; environment builders and transforms are public from `core.acoustics`.

All propagation backends implement `simulate(scene, array_id, time_window) -> AudioSensorFrame`. `AudioSceneSnapshot` owns the complete canonical state of every microphone array and its mandatory `environment`; `array_id` only selects which array observes that scene. Each backend resolves it through `scene.array_by_id(array_id)` and fails if it is absent. Plugin declarations own backend inventory and capability metadata. `AudioSourceSpec` and `MicrophoneSpec` are the directivity and nominal-gain authorities; `core.directivity` owns the one enum/coefficient model and `core.gain` owns fail-closed scalar dB conversion. Effects keep their immutable records at `core.effects.config`, while domain modules own channel-response, noise, electronics, and motion parsing and validation.

`AnalyticAcoustics` is the only registered runtime propagation backend. It routes from the environment kind to Core direct or half-space propagation, or to lazy PyRoom shoebox or polygon-prism construction. Direct and indirect pair stems remain internal, `SourceOcclusion` applies only to the direct stem, and the public waveform is the recombined multichannel result. Analytic internals own scheduling, rendering, effects, detection, diagnostics, and frame assembly. Removed geometry, synthetic-TDOA, and room backend behavior survives only as internal logic or historical v1 replay data, never as runtime aliases.

Motion owns Doppler and pose/window state; acoustics owns environment builders and transforms, materials, and occlusion interpretation; DOA owns the numerical least-squares solver as well as GCC-PHAT, SRP-PHAT, ambiguity, and sector mapping. Fundamental data contracts remain centralized in `core.types`.

This layer imports no other package subsystem. Importing the core package root loads no NumPy, recording, concrete backend/effect, Isaac, Omniverse, Isaac Lab, Kit, CUDA, Torch, or downstream module.

## Recording Layer

`isaac_audio_sensors.recording` owns the generic session layout, manifests, shard lifecycle, atomic writes, audio codecs, loading, validation, statistics, deterministic splits, and read-only replay.

Recording consumes `AudioSensorFrame` values and emits versioned generic dataset artifacts; it does not own a task-specific acquisition campaign or scientific acceptance policy.

Dataset-manifest constants, models, and canonical JSON serializers are recording APIs rather than core APIs.

`SessionDataset` is the lifecycle and streaming-read authority shared by validation, replay, FLAC, and recovery. `SessionRecorder` composes internal shard/audio writing, recovery state, and pure manifest construction. Record serialization, shard planning/completion, time-gap accounting, and durable file replacement remain focused internal components rather than public user workflow.

## Schema Layer

`isaac_audio_sensors.schemas` owns deterministic generation. `schemas.generate` is the public facade over one private module per contract and shared schema fragments; its three Python generators are authoritative, and packaged JSON schemas are byte-identical generated release artifacts. Generation depends only on core and recording contracts.

## Isaac Sim Layer

`isaac_audio_sensors.isaac` owns lazy stage discovery, metadata authoring, pose resolution, stage snapshots, live sensor lifecycle, occlusion queries, frame publication, Replicator integration, and visualization records.

The layer turns live USD state into pure core dataclasses before backend computation. `IsaacEnvironmentResolutionCfg` keeps simulator inputs separate from `AcousticEnvironmentSpec` and resolves manual environments, explicit anchors, or marked USD shoebox/half-space candidates before snapshot construction. The cache re-resolves on array motion or relevant marker, bounds, pose, and material changes. The sensor uses `analytic_acoustics`, forwards analytic solver options, and supplies per-pair raycast occlusion through the live lifecycle. It has no offline config path or application persistence: consumers inject an optional core waveform sink, and required Isaac APIs resolve lazily with explicit errors.

## Isaac Lab Layer

`isaac_audio_sensors.lab` is import-safe at its package root and resolves direct Isaac Lab `SensorBaseCfg` and `SensorBase` subclasses only after `AppLauncher` initialization.

Its entity path converts official scene root/body pose tensors directly into batched fixed-shape `analytic_acoustics` observations. It requires explicit free field, at least three microphones, TDOA least-squares, compatible analytic options, and identity effects; pose, delay, relative amplitude, confidence, scheduling, and compaction remain on the sensor device without per-environment loops. The separate reference path converts pure Core snapshots through scalar `AnalyticAcoustics`, accepts one array identifier per snapshot, and retains all supported analytic topologies, two-microphone ambiguity, SRP-PHAT, PyRoom, and effects. USD discovery, stage poses, and environment anchoring remain in the Isaac Sim layer; Lab owns no stage adapter or device fallback.

## Kit and Extension Layers

`isaac_audio_sensors.kit` exports only `ExtensionController`; profiles, validation, state, workflow, instruments, presentation adapters, and internal application services remain in their canonical Kit modules.

`ExtensionController` composes those services, owns the flat `ExtensionUiState`, reports status/errors, and exposes the maintained GUI/headless actions. `window.py` and `sections.py` only render state and invoke actions. Pure validation checks remain dependency-free; the stateful validation controller owns capability discovery, backend/device facts, calibration reads, and fail-closed environment-mode checks. The registry-derived backend choice is `analytic_acoustics`. Kit configuration uses `ias.omni_extension_binding.v4`; v3 is rejected, `unconfigured` cannot validate or start, and maintained presets select explicit free field.

The guided headless service receives an `ExtensionController` explicitly. `exts/isaac_audio_sensors.omni` only constructs that controller and runs startup, shutdown, and optional OmniGraph registration; Kit lifecycle service owns window, menu, action, hotkey, and subscriptions.

## Data Flow

Configuration or live stage/entity state produces an authoritative `AudioSceneSnapshot`; an array identifier selects the observer and a backend emits `AudioSensorFrame`; optional writers serialize traces or session shards; Isaac Lab converts the same semantic output into bounded observation tensors; downstream projects adapt those outputs outside this repository.

Privileged source pose, geometry, isolated-signal, or simulator state must remain distinguishable from observed waveform and estimator outputs so training supervision does not become an unlabelled runtime dependency.

## Dependency Boundary

The enforced internal imports are `recording -> core`, `isaac -> core`, `lab -> core`, `kit -> core + recording + isaac`, and `schemas -> core + recording`. `cli.py` owns the entrypoint and parser topology; private `_cli` modules adapt standard, dataset, and guided commands and import owning public services only after a leaf command is selected. Lower components do not import Kit, UI, or CLI.

The package root exports only `__version__`. Public types and services are imported from their semantic subsystem.

Core runtime dependencies are NumPy and TOML support for Python versions that need it. JSON Schema validation is development-only.

The `room` extra provides `pyroomacoustics`, SciPy, and SoundFile; Isaac, Kit, CUDA, Torch, and Replicator remain environment capabilities resolved lazily.

The Kit archive build extracts locked `pyroomacoustics`, SciPy, SoundFile, CFFI, and pycparser wheels into `isaac_audio_sensors/_bundled`. The extension uses that tree without downloading packages and leaves NumPy and `typing_extensions` owned by Kit. The universal Python wheel never contains `_bundled`.

Optional absence is a supported state for pure functionality, but a requested optional capability must fail with a precise error rather than degrade silently.

## Downstream Boundary

Robot-specific mounts, assets, policies, task orchestration, acceptance criteria, research campaigns, and consumer adapters belong to downstream repositories.

See [[decisions/product-boundary-and-compatibility|Product Boundary and Compatibility]] for the maintained promises and exclusions.
