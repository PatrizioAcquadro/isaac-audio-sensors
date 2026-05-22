# Architecture

`isaac-audio-sensors` is split into four layers.

## Pure Core

`isaac_audio_sensors.core` contains dataclasses, microphone-array geometry,
backend protocols, config loading, JSON Schema export, trace IO, and DOA
helpers. It must import in a normal Python environment without Isaac Sim, Isaac
Lab, Omniverse, ROS 2, protobuf, or downstream project modules.

The core frame boundary is `AudioSensorFrame` schema
`ias.audio_sensor_frame.v1`. It carries deterministic IDs/names, array and
source poses, explicit units, provenance, time-window fields, and `max_events`
semantics for downstream consumers.

## Isaac Sim

`isaac_audio_sensors.isaac` contains lazy Isaac Sim helpers for authoring and
discovering sound sources, listeners, and microphone arrays on a USD-like stage.
`IsaacAudioArraySensor` can bind a stage and array prim path, subscribe to Kit
updates when Isaac is available, or step deterministically in tests with
`update()`. Each update rebuilds the stage snapshot, so moved source/array
metadata and active sound windows are reflected in the emitted frame.

Debug visualization is split into pure structured primitives and a lazy Isaac
debug-draw renderer. The structured path is always available for tests,
fallback export, and future USD geometry authoring.

## Isaac Lab

`isaac_audio_sensors.lab` wraps core frames as observation-style sensor data.
The wrapper can bind a scene snapshot and reuse its update buffer according to
`AudioArraySensorCfg.update_period`.

## Extension And Writer

The `exts/isaac_audio_sensors.omni` wrapper provides a developer Kit extension
entry point. It can configure/start/stop/update a live sensor and export the
latest frame when loaded in Isaac. A full Replicator annotator/writer
registration is not implemented in this iteration; the supported writer path is
the package JSONL writer, `AudioFrameJsonlWriter`.

## Optional Project Adapters

Downstream projects can adapt `AudioSensorFrame` records into their own message
or graph contracts outside the core package. Those adapters should remain
optional and should not become install or import dependencies for this package.
