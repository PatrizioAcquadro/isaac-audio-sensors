# CLI Examples

Validate config:

```bash
isaac-audio-sensors validate-config examples/configs/isaac_audio_sensors_demo.toml
```

Simulate a geometry-only frame and save its trace:

```bash
isaac-audio-sensors simulate \
  examples/configs/isaac_audio_sensors_demo.toml \
  --backend geometry_only \
  --array-id rig_front \
  --out outputs/geometry_trace.json
```
