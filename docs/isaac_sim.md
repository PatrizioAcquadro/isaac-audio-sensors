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
- binds `IsaacAudioArraySensor` to `/World/Rig/AudioArray`;
- calls `start()`, repeated `update(...)`, `get_latest_frame()`, and `close()`;
- moves the source and array between ticks and verifies changed frame output;
- evaluates the inactive sound window after the authored duration;
- builds debug primitives and uses Isaac debug draw when available;
- writes JSON evidence and JSONL frame traces under ignored `outputs/`.

Programmatic lifecycle:

```python
from isaac_audio_sensors.isaac import IsaacAudioArraySensor

sensor = IsaacAudioArraySensor.from_stage(
    stage=stage,
    array_prim_path="/World/Rig/AudioArray",
    backend="tdoa_synthetic",
    update_period_s=0.05,
    max_events=4,
    debug_draw=True,
    writer_path="outputs/isaac_audio_sensors/frames.jsonl",
)
sensor.start()
frame = sensor.update(sim_time_s=0.0)
latest = sensor.get_latest_frame()
sensor.stop()
sensor.close()
```

`update()` rebuilds the stage snapshot every time. For authored metadata, active
sources are selected by half-open windows `[start_time_s, end_time_s)`. A source
with `ias:start_time_s = 0.1` and `ias:duration_s = 0.2` is active for windows
that overlap `[0.1, 0.3)`.

Native USD/Isaac sound attributes are read on a best-effort basis where the
stage exposes them through ordinary attributes such as `filePath`, `startTime`,
`duration`, and `gain`. Package metadata under `ias:*` is the documented path.

This package is not an official NVIDIA extension. The extension metadata under
`exts/` is included for developers who want a lightweight Kit workflow with
start/stop/update/export controls. Replicator annotator/writer registration is
not implemented yet; use the package JSONL writer for frame recording.
