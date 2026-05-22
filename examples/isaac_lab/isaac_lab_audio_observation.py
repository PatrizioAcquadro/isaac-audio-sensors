"""Isaac Lab observation config snippet."""

from __future__ import annotations

from isaac_audio_sensors.lab import AudioArraySensorCfg

audio_array = AudioArraySensorCfg(
    prim_path="{ENV_REGEX_NS}/Robot/audio_array",
    update_period=0.05,
    backend="tdoa_synthetic",
    microphone_layout="quad_front",
    debug_vis=True,
)
