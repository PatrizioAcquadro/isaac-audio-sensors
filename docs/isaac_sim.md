# Isaac Sim

The `isaac_audio_sensors.isaac` layer provides optional helpers for Isaac Sim
and Omniverse USD stages.

Supported compatibility target:

- Isaac Sim 5.1: live smoke supported when the user's Isaac Python runtime is
  available.
- Pure Python import: supported without Isaac installed.

The helpers use lazy imports. Calling code can import the package normally in a
non-Isaac environment, and Isaac-specific failures are raised only when a live
Isaac helper actually needs `pxr`, `omni`, or `isaacsim`.

Live smoke:

```bash
PYTHONPATH=src "$ISAAC_SIM_PYTHON" scripts/live_isaac_sim_audio_smoke.py
```

The smoke script:

- creates an in-memory USD stage;
- authors sound source, listener, and microphone-array metadata;
- discovers the authored stage objects;
- captures a synthetic TDOA `AudioSensorFrame`;
- writes optional JSON evidence under ignored `outputs/`.

This package is not an official NVIDIA extension. The thin extension metadata
under `exts/` is included for developers who want to experiment with an
Omniverse extension wrapper.
