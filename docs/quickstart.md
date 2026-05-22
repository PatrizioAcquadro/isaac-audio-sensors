# Quickstart

Validate the bundled example config:

```bash
isaac-audio-sensors validate-config configs/isaac_audio_sensors_phase55.toml
```

Run a deterministic geometry-only frame:

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

Run examples from the repository root:

```bash
python examples/core/single_source_bearing.py
python examples/core/multi_mic_tdoa.py
python examples/core/two_mic_ambiguity.py
python examples/core/room_acoustics_demo.py
```

The examples use `generated://` audio asset identifiers. They do not require
private recordings or generated media.
