# Isaac Audio Sensors

Reference Omniverse extension UX for `isaac-audio-sensors`.

## Overview

This extension opens a Kit window for the real Isaac Audio Sensors workflow in
an Isaac Sim stage:

- bind the selected USD prim as the microphone array, sound source, or robot
  base;
- author `ias:*` microphone-array and sound-source metadata on stage prims;
- discover authored arrays and sources from configurable USD roots;
- start, update, and stop the live `IsaacAudioArraySensor`;
- inspect latest-frame status and debug overlay primitive counts;
- export the latest frame as JSON and stream frames as JSONL;
- export and import reusable extension/stage-binding config JSON;
- optionally record extension frames through Omniverse Replicator when the Kit
  runtime exposes compatible Replicator APIs.

Use `Window -> Isaac Audio Sensors` to show or reopen the window after closing
it with X. The same action is registered as
`isaac_audio_sensors.omni::toggle_window` and is bound by default to
`Ctrl+Alt+A` when `omni.kit.hotkeys.core` is available. The shortcut can be
changed through `/exts/isaac_audio_sensors.omni/shortcut`.

## Runtime And Dependencies

Using the extension requires an Isaac Sim/Kit runtime. The extension manifest
declares the Kit/UI/USD dependencies it loads directly:

- `omni.kit.actions.core`
- `omni.kit.menu.utils`
- `omni.ui`
- `omni.usd`
- optional `omni.kit.hotkeys.core`
- optional `omni.replicator.core` for extension-only Replicator recording

The pure Python package remains import-safe outside Isaac Sim. Importing the
extension module does not require `omni`, `pxr`, GUI, CUDA, Torch,
pyroomacoustics, Replicator, or Isaac Lab modules; those APIs are loaded lazily
only inside the live Kit/runtime paths that use them.

## Packages

The extension exposes one extension Python module:

- `isaac_audio_sensors_omni`

It does not register additional extension packages. The reusable Python package
is distributed separately from `src/isaac_audio_sensors`.

## OmniGraph

The extension registers one runtime Python OmniGraph node when
`omni.graph.core` is available: `isaac_audio_sensors.omni.IsaacAudioSensorFrame`.
It reads the newest published frame (optionally filtered by the
`inputs:arrayKey` token, an array prim path) and exposes `frameId`,
`timestampMs`, `detectionCount`, `bearingDeg`, `sector`, `micIds`, `micRms`,
`occluded`, and a `frameJson` token so audio wires into Action Graphs like
cameras and lidars. Registration uses `og.register_node_type` (no `.ogn`
codegen); when OmniGraph is unavailable or registration fails, the extension
keeps working and reports the exact status in the Sensor section and the live
gate evidence. The same data is reachable from Script Nodes through
`isaac_audio_sensors.isaac.frame_registry.get_latest_frame()`.

Source repository:
https://github.com/PatrizioAcquadro/isaac-audio-sensors
