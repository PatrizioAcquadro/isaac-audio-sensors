# Isaac Lab

The `isaac_audio_sensors.lab` layer provides a lightweight wrapper around the
core sensor frame model for Isaac Lab-style observation workflows.

Supported compatibility target:

- Isaac Lab 5.1: live smoke supported when the user's Isaac Lab Python runtime
  is available.
- Pure Python import: supported without Isaac Lab installed.

The wrapper is intentionally small. It accepts an `AudioSceneSnapshot`, a
`MicrophoneArraySpec`, and an `AudioArraySensorCfg`, then returns
`AudioArraySensorData` tuples suitable for observation plumbing.

Live smoke:

```bash
PYTHONPATH=src "$ISAAC_LAB_PYTHON" scripts/live_isaac_lab_audio_smoke.py
```

The smoke script checks that an Isaac Lab module imports in the selected
runtime, builds a generic scene snapshot, updates the sensor once, and writes
optional JSON evidence under ignored `outputs/`.

Isaac Lab remains optional. The core package does not depend on it for install,
import, unit tests, or CLI simulation.
