# Quickstart

Validate the bundled example config:

```bash
isaac-audio-sensors validate-config examples/configs/isaac_audio_sensors_demo.toml
```

Run a deterministic geometry-only frame:

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

Export the public frame JSON Schema:

```bash
isaac-audio-sensors export-schema \
  --out outputs/audio_sensor_frame.v1.schema.json
```

Tracked example traces are available under `examples/traces/`.

Run examples from the repository root:

```bash
python examples/core/single_source_bearing.py
python examples/core/multi_mic_tdoa.py
python examples/core/two_mic_ambiguity.py
python examples/core/room_acoustics_demo.py
```

The examples use `generated://` audio asset identifiers. They do not require
private recordings or generated media.
