# CLI Examples

Validate config:

```bash
isaac-audio-sensors validate-config configs/isaac_audio_sensors_phase55.toml
```

Simulate a geometry-only frame:

```bash
isaac-audio-sensors simulate \
  configs/isaac_audio_sensors_phase55.toml \
  --backend geometry_only \
  --array-id rig_front
```

Export a synthetic TDOA trace:

```bash
isaac-audio-sensors export-trace \
  configs/isaac_audio_sensors_phase55.toml \
  --backend tdoa_synthetic \
  --array-id rig_front \
  --out outputs/tdoa_trace.json
```
