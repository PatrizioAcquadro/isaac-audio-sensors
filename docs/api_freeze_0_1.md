# API Freeze 0.1

This document defines the initial public API for `isaac-audio-sensors` 0.1.x.

## Stable For 0.1.x

Package import and version:

- `import isaac_audio_sensors`
- `isaac_audio_sensors.__version__`

Core data models:

- `AudioSourceSpec`
- `AudioTimeWindow`
- `MicrophoneSpec`
- `MicrophoneArraySpec`
- `RoomAcousticsSpec`
- `AudioSceneSnapshot`
- `AudioSensorFrame`
- `AudioDetection`
- `DoaEstimate`
- `Pose3D`

Microphone array helpers:

- `create_microphone_array`
- `arbitrary_microphone_array`
- `microphone_layout`
- `microphone_world_positions`

Backend selection and configuration:

- `AudioSimulationBackend`
- `GeometryBackend`
- `TdoaSyntheticBackend`
- `RoomAcousticsBackend`
- `get_backend`
- `load_audio_config`
- `validate_audio_config`
- `build_scene_snapshot`

Isaac Sim helper entry points:

- `IsaacAudioArraySensor`
  - `from_stage`
  - `from_config`
  - `start`
  - `stop`
  - `reset`
  - `update`
  - `capture`
  - `get_latest_frame`
  - `configure_writer`
  - `close`
- `create_sound_prim`
- `create_listener_prim`
- `attach_microphone_array_attrs`
- `attach_microphone_attrs`
- `attach_sound_source_attrs`
- `build_stage_snapshot`
- `discover_sound_sources`
- `discover_listeners`
- `discover_microphone_arrays`

Isaac Lab wrapper entry points:

- `AudioArraySensorCfg`
- `AudioArraySensorData`
- `AudioArraySensor`

CLI commands:

- `isaac-audio-sensors validate-config`
- `isaac-audio-sensors simulate`
- `isaac-audio-sensors export-trace`
- `isaac-audio-sensors export-schema`

Schema and trace helpers:

- `frame_to_trace_dict`
- `frame_from_trace_dict`
- `write_frame_trace`
- `read_frame_trace`
- `append_frame_jsonl`
- `AudioFrameJsonlWriter`
- `audio_sensor_frame_json_schema`
- `write_audio_sensor_frame_json_schema`

The stable frame schema version is `ias.audio_sensor_frame.v1`. It is distinct
from the package version and is exported as
`docs/schemas/audio_sensor_frame.v1.schema.json`.

## Experimental

- `isaac_audio_sensors.isaac.viz`
- `isaac_audio_sensors.examples`
- Omniverse extension metadata under `exts/`
- Diagnostic scripts under `scripts/`

## Internal

Names starting with `_` are private. Test-only fake stages and local script
implementation details are not public API.

## Deprecation Policy

For `0.1.x`, stable APIs should not be removed or renamed. If a stable API must
change, add a replacement first, document the deprecation in `CHANGELOG.md`, and
keep the old path working until the next minor release.

Semantic versioning expectation:

- patch release: bug fixes and docs that keep the API compatible;
- minor release: new public APIs or documented experimental API promotion;
- major release: incompatible public API changes.
