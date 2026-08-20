# CLI Examples

Validate config:

```bash
isaac-audio-sensors validate-config examples/configs/isaac_audio_sensors_demo.toml
```

Simulate a geometry-only frame:

```bash
isaac-audio-sensors simulate \
  examples/configs/isaac_audio_sensors_demo.toml \
  --backend geometry_only \
  --array-id rig_front
```

Export a synthetic TDOA trace:

```bash
isaac-audio-sensors export-trace \
  examples/configs/isaac_audio_sensors_demo.toml \
  --backend tdoa_synthetic \
  --array-id rig_front \
  --out outputs/tdoa_trace.json
```
