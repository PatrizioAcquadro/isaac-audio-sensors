"""Minimal Isaac Lab audio observation helper."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.lab import (
    LabAudioEntityBindingCfg,
    LabAudioSourceEntityCfg,
    LabAudioStageBindingCfg,
    ensure_isaac_lab_sensor_classes,
    get_audio_array_sensor_classes,
)

AUDIO_OBSERVATION_KEYS = (
    "audio/event_presence",
    "audio/bearing_deg",
    "audio/confidence",
    "audio/sector_onehot",
    "audio/per_mic_rms",
    "audio/ambiguity_mask",
)
AUDIO_OBSERVATION_FIELDS = tuple(
    key.removeprefix("audio/") for key in AUDIO_OBSERVATION_KEYS
)

_classes = get_audio_array_sensor_classes(require_real=False)

audio_array = _classes.cfg(
    prim_path="{ENV_REGEX_NS}/Robot/audio_array",
    update_period=0.05,
    backend="tdoa_synthetic",
    microphone_layout="quad_front",
    max_events=2,
    debug_vis=True,
)

explicit_stage_binding = LabAudioStageBindingCfg(
    num_envs=2,
    env_namespace_pattern="/World/envs/env_{env_id}",
    array_prim_path="Robot/audio_array",
    source_prim_paths=("Sources/speaker",),
    microphone_layout="quad_front",
)

discovered_scene_binding = LabAudioStageBindingCfg(
    discover_arrays=True,
    array_discovery_root_path="Robot",
    preferred_array="audio_array",
    discover_sources=True,
    source_discovery_root_path="Sources",
    microphone_layout="quad_front",
)

entity_tensor_binding = LabAudioEntityBindingCfg(
    num_envs=2,
    robot_entity_name="robot",
    array_mount_body_name=None,
    array_relative_position_m=(0.08, 0.0, 0.0),
    microphone_layout="quad_front",
    source_entities=(
        LabAudioSourceEntityCfg(
            entity_name="speaker",
            source_id="speaker",
            class_label="Speech",
            duration_s=1.0,
        ),
    ),
)


def bind_from_stage(stage: object):
    """Create the live Lab sensor after AppLauncher/SimulationApp starts."""

    classes = ensure_isaac_lab_sensor_classes()
    cfg = classes.cfg(
        prim_path="{ENV_REGEX_NS}/Robot/audio_array",
        update_period=0.05,
        backend="tdoa_synthetic",
        microphone_layout="quad_front",
        max_events=2,
    )
    return classes.sensor(cfg).bind_lab_stage(
        stage=stage,
        binding_cfg=explicit_stage_binding,
    )


def bind_from_scene(scene: object):
    """Bind from a scene/env wrapper that exposes stage and num_envs."""

    classes = ensure_isaac_lab_sensor_classes()
    cfg = classes.cfg(
        prim_path="{ENV_REGEX_NS}/Robot/audio_array",
        update_period=0.05,
        backend="tdoa_synthetic",
        microphone_layout="quad_front",
        max_events=2,
    )
    return classes.sensor(cfg).bind_lab_scene(
        scene=scene,
        binding_cfg=discovered_scene_binding,
    )


def bind_from_scene_entities(scene: object):
    """Bind from a scene wrapper that exposes Lab entity tensor state."""

    classes = ensure_isaac_lab_sensor_classes()
    cfg = classes.cfg(
        prim_path="{ENV_REGEX_NS}/Robot/root/audio_array",
        update_period=0.05,
        backend="tdoa_synthetic",
        microphone_layout="quad_front",
        max_events=2,
    )
    return classes.sensor(cfg).bind_lab_entities(
        scene=scene,
        binding_cfg=entity_tensor_binding,
    )


def audio_observation(
    sensor: object,
    *,
    dt: float,
    update_env_ids: list[int] | tuple[int, ...] | None = None,
    reset_env_ids: list[int] | tuple[int, ...] | None = None,
    force_recompute: bool = True,
) -> dict[str, Any]:
    """Return stable RL observation tensors from an AudioArraySensor."""

    if reset_env_ids is not None:
        sensor.reset(env_ids=reset_env_ids)
    if update_env_ids is None:
        sensor.update(dt=dt, force_recompute=force_recompute)
    else:
        sensor.update(
            dt=dt,
            force_recompute=force_recompute,
            env_ids=update_env_ids,
        )
    data = sensor.data
    return {
        "audio/event_presence": data.event_presence,
        "audio/bearing_deg": data.bearing_deg,
        "audio/confidence": data.confidence,
        "audio/sector_onehot": data.sector_onehot,
        "audio/per_mic_rms": data.per_mic_rms,
        "audio/ambiguity_mask": data.ambiguity_mask,
    }


def ambiguity_observation(observation: dict[str, Any]) -> dict[str, Any]:
    """Split valid detections into ambiguous and unambiguous masks."""

    event_presence = observation["audio/event_presence"]
    ambiguity_mask = observation["audio/ambiguity_mask"]
    return {
        "audio/ambiguous_event_presence": event_presence & ambiguity_mask,
        "audio/unambiguous_event_presence": event_presence & ~ambiguity_mask,
    }


def observation_spec(observation: dict[str, Any]) -> dict[str, dict[str, object]]:
    """Summarize keys, shapes, dtypes, and devices for observation managers."""

    return {
        key: {
            "shape": tuple(value.shape),
            "dtype": str(value.dtype),
            "device": str(value.device),
        }
        for key, value in observation.items()
    }
