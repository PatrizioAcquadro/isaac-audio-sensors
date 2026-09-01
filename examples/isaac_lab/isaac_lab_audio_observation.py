"""Two maintained Isaac Lab audio binding paths."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.types import AudioSceneSnapshot


def bind_entities(scene: object):
    """Create the batched training sensor after AppLauncher starts."""

    from isaac_audio_sensors.lab import (
        AudioArraySensor,
        AudioArraySensorCfg,
        EntityBindingCfg,
        SourceEntityCfg,
    )

    sensor = AudioArraySensor(
        AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="analytic_acoustics",
            max_detections=2,
        )
    )
    return sensor.bind_entities(
        scene,
        EntityBindingCfg(
            environment=free_field_environment(environment_id="lab_training"),
            robot_entity_name="robot",
            array_mount_body_name="head",
            microphone_layout="quad_front",
            source_entities=(SourceEntityCfg(entity_name="speaker"),),
        ),
    )


def bind_reference(
    snapshots: Sequence[AudioSceneSnapshot],
    array_ids: Sequence[str],
):
    """Create the scalar debug/reference sensor after AppLauncher starts."""

    from isaac_audio_sensors.lab import AudioArraySensor, AudioArraySensorCfg

    sensor = AudioArraySensor(
        AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="analytic_acoustics",
            max_detections=2,
        )
    )
    return sensor.bind_reference(snapshots, array_ids)


def audio_observation(
    sensor: Any,
    *,
    dt: float,
    reset_env_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    if reset_env_ids is not None:
        sensor.reset(reset_env_ids)
    sensor.update(dt, force_recompute=True)
    data = sensor.data
    return {
        "audio/event_presence": data.event_presence,
        "audio/bearing_deg": data.bearing_deg,
        "audio/confidence": data.confidence,
        "audio/sector_onehot": data.sector_onehot,
        "audio/per_mic_rms": data.per_mic_rms,
        "audio/ambiguity_mask": data.ambiguity_mask,
    }
