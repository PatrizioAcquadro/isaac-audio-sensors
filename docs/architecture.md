# Architecture

`isaac-audio-sensors` is split into four layers.

## Pure Core

`isaac_audio_sensors.core` contains dataclasses, microphone-array geometry,
backend protocols, config loading, trace IO, and DOA helpers. It must import in
a normal Python environment without Isaac Sim, Isaac Lab, Omniverse, ROS 2,
protobuf, or downstream project modules.

## Isaac Sim

`isaac_audio_sensors.isaac` contains lazy Isaac Sim helpers for authoring and
discovering sound sources, listeners, and microphone arrays on a USD-like stage.
Tests use duck-typed fake stages so the core behavior remains testable without
NVIDIA runtimes.

## Isaac Lab

`isaac_audio_sensors.lab` wraps core frames as observation-style sensor data.
The wrapper can bind a scene snapshot and reuse its update buffer according to
`AudioArraySensorCfg.update_period`.

## Optional Project Adapters

Downstream projects can adapt `AudioSensorFrame` records into their own message
or graph contracts outside the core package. Those adapters should remain
optional and should not become install or import dependencies for this package.
