"""Observed-only Lab bindings and finite, masked policy inputs.

The consumer uses fixed angle scaling only. Keep statistical normalization
and observation modifiers disabled for these terms in downstream learners;
masks and truncation counts must reach the policy unchanged.
"""

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
            max_observations=1,
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
    *,
    energy_threshold_dbfs: float,
    doa_enabled: bool = False,
):
    """Create the scalar debug/reference sensor after AppLauncher starts."""

    from isaac_audio_sensors.lab import AudioArraySensor, AudioArraySensorCfg

    sensor = AudioArraySensor(
        AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="analytic_acoustics",
            max_observations=1,
            energy_threshold_dbfs=energy_threshold_dbfs,
            doa_enabled=doa_enabled,
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
    return policy_inputs(data)


def policy_inputs(data: Any) -> dict[str, Any]:
    """Scale angles to [-1, 1], masking absent values without batch statistics.

    Scores retain their producer semantics. Boolean masks and integer counts
    are unmodified; degree suffixes are replaced by ``_scaled`` after scaling.
    """

    import torch

    result = {}
    for name in data.__dataclass_fields__:
        value = getattr(data, name)
        if name.endswith("_deg"):
            mask = getattr(data, name + "_mask")
            scale = 90.0 if "elevation" in name else 180.0
            value = torch.where(mask, value / scale, 0.0)
        policy_name = name.replace("_deg", "_scaled")
        result["audio/" + policy_name] = value
    return result
