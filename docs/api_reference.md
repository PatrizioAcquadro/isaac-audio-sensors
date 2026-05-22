# API Reference

The initial stable API is defined in [API Freeze 0.1](api_freeze_0_1.md).

Primary imports are available from `isaac_audio_sensors` for common model and
backend classes. More specific helpers live under:

- `isaac_audio_sensors.core`
- `isaac_audio_sensors.core.backends`
- `isaac_audio_sensors.core.doa`
- `isaac_audio_sensors.isaac`
- `isaac_audio_sensors.lab`

The CLI entry point is:

```bash
isaac-audio-sensors --help
```

## AudioSensorFrame V1

`AudioSensorFrame` is the public frame contract for trace files and downstream
adapters. New frames include:

- `schema_version`: currently `ias.audio_sensor_frame.v1`;
- `frame_id` and `frame_name`: deterministic machine and display identifiers;
- `timestamp_ms`, `start_time_s`, `end_time_s`, `sample_rate_hz`, and
  `frame_index`;
- `array_pose`: `Pose3D` for the array at frame time;
- per-detection `source_pose` when the source pose is known, otherwise `null`;
- `coordinate_convention` and explicit `units`;
- `provenance`: `synthetic/core`, `room_acoustics`, `isaac_live`, or
  `replay/trace`;
- `max_events`: deterministic detection limit used for the frame.

The JSON Schema is stored at:

```text
docs/schemas/audio_sensor_frame.v1.schema.json
```

Example traces are stored at:

```text
examples/traces/minimal_frame.v1.json
examples/traces/multi_detection_frame.v1.json
```

Export the schema from code:

```bash
isaac-audio-sensors export-schema --out /tmp/audio_sensor_frame.v1.schema.json
```

## Live Isaac Sensor

`IsaacAudioArraySensor.from_stage(...)` binds a stage and array prim path. The
sensor supports `start()`, `stop()`, `reset()`, `update()`,
`get_latest_frame()`, `configure_writer()`, and `close()`.

Each `update()` rebuilds a stage snapshot, follows moved array/source metadata,
applies active sound windows, respects `max_events`, stores the latest frame,
and can append JSONL frames through `AudioFrameJsonlWriter`.

Debug visualization uses structured primitives that are available without
Isaac. When `omni.isaac.debug_draw` is available, `IsaacDebugDrawer` draws
microphones, sources, bearing rays, and sector wedges.
