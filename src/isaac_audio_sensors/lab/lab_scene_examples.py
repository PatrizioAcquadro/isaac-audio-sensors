"""Minimal Isaac Lab scene snippet strings for documentation and tests."""

from __future__ import annotations


def audio_array_sensor_cfg_snippet() -> str:
    """Return a snippet showing how a Lab user attaches the sensor config."""

    return (
        "AudioArraySensorCfg("
        "prim_path='{ENV_REGEX_NS}/Robot/audio_array', "
        "update_period=0.05, backend='tdoa_synthetic', "
        "microphone_layout='quad_front', debug_vis=True)"
    )
