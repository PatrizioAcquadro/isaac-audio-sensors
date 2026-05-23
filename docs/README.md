# Documentation

This documentation describes the standalone `isaac-audio-sensors` package for
public users.

- [Installation](installation.md)
- [Quickstart](quickstart.md)
- [Isaac Sim](isaac_sim.md)
- [Omniverse Extension UX](isaac_sim.md#reference-extension-ux)
- [Isaac Lab](isaac_lab.md)
- [Acoustic Fidelity Ladder](acoustic_fidelity.md)
- [Backends](backends.md)
- [Room Acoustics](room_acoustics.md)
- [TDOA And DOA](tdoa_doa.md)
- [API Freeze 0.1](api_freeze_0_1.md)
- [AudioSensorFrame Schema](schemas/audio_sensor_frame.v1.schema.json)
- [Validation](validation.md)
- [Limitations](limitations.md)
- [Versioning](versioning.md)
- [Roadmap](roadmap.md)
- [Showcase](showcase.md)
- [Open Source Release Checklist](open_source_release_checklist.md)

## Isaac Sim Reference UX

The source distribution includes `exts/isaac_audio_sensors.omni`, a reference
Kit extension for authoring microphone arrays and sound sources directly in
Isaac Sim. The documented workflow covers selected-prim binding, array/source
metadata authoring, discovery, backend selection, start/update/stop lifecycle,
debug overlay primitives, package JSON/JSONL export, config import/export, and
Omniverse Replicator recording.

Validation artifacts from the live extension smoke are written under ignored
`outputs/isaac_audio_sensors/`, including:

- `omniverse_extension_live_ux.json`
- `omniverse_extension_live_ux.frames.jsonl`
- `omniverse_extension_live_ux.config.json`
- `omniverse_extension_live_ux.replicator/`

Screenshots are saved as
`outputs/isaac_audio_sensors/omniverse_extension_live_ux.viewport.png` when the
active Kit viewport exposes a capture API; otherwise the evidence JSON records
the exact capture blocker and still includes serialized overlay primitives.
