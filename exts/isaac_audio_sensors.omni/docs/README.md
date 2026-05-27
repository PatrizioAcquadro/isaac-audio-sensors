# Isaac Audio Sensors

Reference Omniverse extension UX for `isaac-audio-sensors`.

This extension opens a Kit window for authoring `ias:*` microphone-array and
sound-source metadata, discovering audio prims in the current USD stage,
starting the live Isaac audio-array sensor, inspecting the latest
`AudioSensorFrame`, and exporting JSON/JSONL records. Replicator recording is
available as an optional extension-only workflow.

Use `Window -> Isaac Audio Sensors` to show or reopen the window after closing
it with X. The same action is registered as
`isaac_audio_sensors.omni::toggle_window` and is bound by default to
`Ctrl+Alt+A` when `omni.kit.hotkeys.core` is available. The shortcut can be
changed through `/exts/isaac_audio_sensors.omni/shortcut`.

The pure Python package remains import-safe outside Isaac Sim. Importing the
extension module does not require `omni`, `pxr`, GUI, CUDA, Torch, Replicator,
or Isaac Lab modules; those APIs are loaded lazily only inside the live Kit
runtime.

Source repository:
https://github.com/PatrizioAcquadro/isaac-audio-sensors
