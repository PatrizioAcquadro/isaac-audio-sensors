# Isaac Audio Sensors Extension

`isaac_audio_sensors.omni` is the reference Isaac Sim/Kit interface for the `isaac-audio-sensors` package.

It provides a guided `Setup -> Validate -> Run -> Inspect -> Record -> Export` workflow plus expert controls for stage discovery, array/source authoring, sensor lifecycle, room configuration, instruments, audio preview, optional Replicator recording, and JSON/JSONL/config export.

Open the window from `Window -> Isaac Audio Sensors`; the action ID is `isaac_audio_sensors.omni::toggle_window` and the default shortcut is `Ctrl+Alt+A` when the optional hotkey service is available.

The extension resolves Kit, USD, OmniGraph, Replicator, CUDA, and simulator APIs lazily, so importing its Python module does not require those services outside Isaac Sim.

The optional OmniGraph node is `isaac_audio_sensors.omni.IsaacAudioSensorFrame` version 1 and publishes the latest frame without changing the package frame contract.

The installed archive is self-contained and vendors the maintained `isaac_audio_sensors` package under `_vendor` with source revision and tree-hash metadata.

Canonical technical documentation lives in the repository wiki: <https://github.com/PatrizioAcquadro/isaac-audio-sensors/tree/main/knowledge/wiki>.

Source repository: <https://github.com/PatrizioAcquadro/isaac-audio-sensors>
