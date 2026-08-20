# Examples

Run examples from the repository root after installing the package in editable
mode:

```bash
python -m pip install -e ".[dev]"
python examples/core/single_source_bearing.py
python examples/core/multi_mic_tdoa.py
python examples/core/two_mic_ambiguity.py
python examples/core/room_acoustics_demo.py
```

Isaac runtime examples:

```bash
PYTHONPATH=src ~/isaacsim/python.sh tools/smoke/live_isaac_sim_audio_smoke.py
PYTHONPATH=src ~/IsaacLab/isaaclab.sh -p tools/smoke/live_isaac_lab_audio_smoke.py
```

Frame trace examples are tracked under `examples/traces/` and match
`src/isaac_audio_sensors/schemas/audio_sensor_frame.v1.schema.json`. They intentionally cover the
stable v1 trace shape: an empty minimal frame, multiple detections, explicit
two-microphone ambiguity, stable provenance namespaces, fixed units, and the
corrected bearing-sector semantics.

The examples are generic and do not depend on downstream project contracts.
